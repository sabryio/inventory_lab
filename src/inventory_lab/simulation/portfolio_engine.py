"""Portfolio simulation engine: multiple SKUs, one supplier, optional consolidation.

Design
------
Each SKU gets its own SimulationEngine, InventoryLedger, KpiAccumulator, and
independent demand stream.

When consolidation_enabled=False
---------------------------------
All engines run sequentially via engine.run(). Post-processing with the order
log computes exact savings for reporting.

When consolidation_enabled=True
--------------------------------
Engines run in lockstep so a shared ConsolidationCoordinator can see all orders
from all SKUs before any snapshot fires. For each day t=1..horizon:

1. Every engine steps through all events with time < t (demand, reviews, receipts
   from prior consolidated orders). Any order the engine wants to place is
   intercepted by the coordinator (suppressed, stored with owner tag).

2. After all engines have stepped, the coordinator flushes: it groups pending
   orders by (lane_id, due_at) and splits the lane's fixed cost proportionally
   by quantity.

3. Each engine receives its own consolidated orders via _place_deferred, which
   registers them in the ledger and schedules receipt events. The engine then
   processes its snapshot event (day-boundary KPI anchor).

This eliminates the sequential-engine timing problem: by the time any snapshot
fires, every SKU has already had a chance to place its orders for that day.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from math import floor
from random import Random

from inventory_lab.application.factory import SimulationClock
from inventory_lab.application.portfolio_specs import PortfolioSpec, SkuSpec
from inventory_lab.core.registry import BuildContext
from inventory_lab.domain.order import ConsolidatedPurchaseOrder, OrderLineItem
from inventory_lab.domain.supply import SupplyLane
from inventory_lab.forecasting.forecast import forecast_registry
from inventory_lab.infrastructure.consolidation import ConsolidationCoordinator
from inventory_lab.infrastructure.tracing import InMemoryTraceSink
from inventory_lab.policies import factories as _policy_factories  # noqa: F401
from inventory_lab.policies.factories import policy_registry
from inventory_lab.ports.demand import DemandObserver
from inventory_lab.safety_stock import composite as _ss_composite  # noqa: F401
from inventory_lab.safety_stock import empirical as _ss_empirical  # noqa: F401
from inventory_lab.safety_stock import fixed as _ss_fixed  # noqa: F401
from inventory_lab.simulation import demand as _demand_components  # noqa: F401
from inventory_lab.simulation.demand import demand_registry
from inventory_lab.simulation.engine import EngineConfig, SimulationEngine
from inventory_lab.simulation.ledger import InventoryLedger
from inventory_lab.simulation.result import OrderRecord, SimulationResult
from inventory_lab.sourcing.lead_time import lead_time_registry
from inventory_lab.sourcing.runtime import LaneRuntime


@dataclass
class _SkuBundle:
    sku_id: str
    engine: SimulationEngine


@dataclass
class PortfolioRunResult:
    """Outcomes of a single portfolio replication."""

    sku_results: dict[str, SimulationResult]

    # Zero when consolidation_enabled=False
    consolidated_orders: list[ConsolidatedPurchaseOrder] = field(default_factory=list)
    total_fixed_cost_saved: float = 0.0


class PortfolioEngine:
    """Runs a multi-SKU portfolio for one replication."""

    def __init__(
        self,
        spec: PortfolioSpec,
        seed: int,
        replication: int = 0,
    ) -> None:
        self._spec = spec
        self._seed = seed
        self._replication = replication

        self._clock = SimulationClock(start_date=spec.start_date)

        rng0 = Random(seed ^ 0xBEEF)
        base_ctx = BuildContext(
            clock=self._clock,
            forecast=None,
            rng=rng0,
            cost_model=spec.cost_model,
        )
        self._lanes: dict[str, LaneRuntime] = {
            lane.lane_id: LaneRuntime(
                spec=lane,
                lead_time=lead_time_registry.create(lane.lead_time, base_ctx),
            )
            for lane in spec.lanes
        }

        # Build the shared coordinator when consolidation is active.
        self._coordinator: ConsolidationCoordinator | None = (
            ConsolidationCoordinator(self._lanes)
            if spec.consolidation_enabled
            else None
        )

        self._bundles: list[_SkuBundle] = [
            self._build_sku(sku, seed, replication) for sku in spec.skus
        ]

    # ------------------------------------------------------------------

    def _build_sku(self, sku: SkuSpec, seed: int, replication: int) -> _SkuBundle:
        rng = Random(seed ^ hash(sku.sku_id) & 0xFFFF_FFFF)
        base_ctx = BuildContext(
            clock=self._clock,
            forecast=None,
            rng=rng,
            cost_model=self._spec.cost_model,
        )
        forecast = forecast_registry.create(sku.forecast, base_ctx)
        ctx = BuildContext(
            clock=self._clock,
            forecast=forecast,
            rng=rng,
            cost_model=self._spec.cost_model,
            lanes=self._lanes,
            service_level=self._spec.target_service_level,
        )
        policy = policy_registry.create(sku.policy, ctx)
        generator = demand_registry.create(sku.demand, ctx)
        events = list(generator.generate(self._spec.horizon_days, rng, self._clock))

        engine = SimulationEngine(
            config=EngineConfig(
                horizon_days=self._spec.horizon_days,
                warmup_days=self._spec.warmup_days,
                shortage_mode=self._spec.shortage_mode,
                collect_trace=self._spec.collect_trace,
                shelf_life_days=sku.shelf_life_days,
                # Order log for post-processing savings summary in independent mode.
                collect_order_log=self._spec.consolidation_enabled,
            ),
            clock=self._clock,
            ledger=InventoryLedger(sku.initial_on_hand, self._spec.shortage_mode),
            lanes=self._lanes,
            policies=[policy],
            demand_events=events,
            cost_model=self._spec.cost_model,
            rng=rng,
            candidate=sku.sku_id,
            policy_code=policy.code,
            seed=seed,
            replication=replication,
            forecast_observer=forecast
            if isinstance(forecast, DemandObserver)
            else None,
            tracer=InMemoryTraceSink() if self._spec.collect_trace else None,
            # Inject the shared coordinator only when consolidation is active.
            order_interceptor=self._coordinator,
        )
        # In lockstep mode the portfolio engine drives flush/place directly;
        # suppress the engine-level _on_snapshot hook to prevent premature flushes.
        if self._spec.consolidation_enabled:
            engine._lockstep_mode = True
        return _SkuBundle(sku_id=sku.sku_id, engine=engine)

    # ------------------------------------------------------------------

    def run(self) -> PortfolioRunResult:
        if self._spec.consolidation_enabled:
            return self._run_lockstep()
        # Fast path: no consolidation — run each engine independently.
        sku_results = {b.sku_id: b.engine.run() for b in self._bundles}
        return PortfolioRunResult(sku_results=sku_results)

    # ------------------------------------------------------------------
    # Lockstep execution (consolidation enabled)
    # ------------------------------------------------------------------

    def _run_lockstep(self) -> PortfolioRunResult:
        """Drive all SKU engines day-by-day in lockstep.

        For each day boundary t the protocol is:
          1. step_until(t) on every engine  -- intra-day events
          2. coordinator.flush(t)           -- group + cost-split
          3. _place_deferred per engine     -- inject consolidated orders
          4. process_snapshot(t) per engine -- day-boundary KPI
        """
        assert self._coordinator is not None
        coordinator = self._coordinator

        # Seed all event queues.
        for bundle in self._bundles:
            bundle.engine.prepare()

        horizon = self._spec.horizon_days

        for day in range(1, horizon + 1):
            t = float(day)

            # Step 1: advance all engines to just before the snapshot.
            for bundle in self._bundles:
                bundle.engine.step_until(t)

            # Step 2: flush — all SKUs have now placed their orders for this day.
            coordinator.flush(t)

            # Step 3 + 4: inject consolidated orders, then fire the snapshot.
            for bundle in self._bundles:
                for order in coordinator.get_pending(bundle.sku_id):
                    bundle.engine._place_deferred(order)
                bundle.engine.process_snapshot(t)

        # Collect final results (drains any residual events beyond last snapshot).
        sku_results = {b.sku_id: b.engine.finalise() for b in self._bundles}

        # Derive the savings summary from the order logs recorded by each engine.
        consolidated, saved = self._summarise_consolidation(sku_results)
        return PortfolioRunResult(
            sku_results=sku_results,
            consolidated_orders=consolidated,
            total_fixed_cost_saved=saved,
        )

    # ------------------------------------------------------------------
    # Consolidation savings summary (exact, from order logs)
    # ------------------------------------------------------------------

    def _summarise_consolidation(
        self, results: dict[str, SimulationResult]
    ) -> tuple[list[ConsolidatedPurchaseOrder], float]:
        """Group per-SKU order logs by (lane_id, day_bucket) to compute savings.

        The actual fixed cost was already split in the coordinator; here we
        compute the total saved for reporting: (n_skus_in_group - 1) * fixed.
        """
        lane_by_id: dict[str, SupplyLane] = {
            lane.lane_id: lane for lane in self._spec.lanes
        }

        # (lane_id, day_bucket) -> [(sku_id, OrderRecord)]
        groups: dict[tuple[str, int], list[tuple[str, OrderRecord]]] = defaultdict(list)
        for sku_id, result in results.items():
            for rec in result.order_log:
                key = (rec.lane_id, floor(rec.placed_at))
                groups[key].append((sku_id, rec))

        consolidated: list[ConsolidatedPurchaseOrder] = []
        total_saved = 0.0
        group_counter = 0

        for (lane_id, _day), entries in groups.items():
            unique_skus = {sid for sid, _ in entries}
            if len(unique_skus) <= 1:
                continue

            lane = lane_by_id[lane_id]
            fixed = lane.fixed_order_cost
            saved = (len(unique_skus) - 1) * fixed
            total_saved += saved

            group_counter += 1
            _, first_rec = entries[0]
            consolidated.append(
                ConsolidatedPurchaseOrder(
                    order_id=f"CON-{group_counter}",
                    lane_id=lane_id,
                    line_items=tuple(
                        OrderLineItem(
                            sku_id=sid,
                            quantity=rec.quantity,
                            unit_cost=rec.unit_cost,
                        )
                        for sid, rec in entries
                    ),
                    placed_at=first_rec.placed_at,
                    due_at=first_rec.due_at,
                    fixed_cost=fixed,
                )
            )

        return consolidated, total_saved
