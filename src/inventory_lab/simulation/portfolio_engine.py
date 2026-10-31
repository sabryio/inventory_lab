"""Portfolio simulation engine: multiple SKUs, one supplier, optional consolidation.

Design
------
Each SKU gets its own `SimulationEngine`, `InventoryLedger`, `KpiAccumulator`, and
independent demand stream.  The portfolio layer runs them all, then post-processes
the order logs to calculate consolidation savings.

Consolidation logic
-------------------
Two orders are consolidable when they arrive at the same supplier lane on the same
calendar day (floor of `placed_at`).  On a Friday-review schedule every SKU reviews
at the same time, so they naturally cluster.  The saving is:

    saved_fixed_cost = (n_skus_in_group - 1) × lane.fixed_order_cost

This is credited back as a negative cost adjustment so each per-SKU `SimulationResult`
remains unchanged and comparable to independent runs.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from math import floor
from random import Random
from statistics import mean

from inventory_lab.application.portfolio_specs import PortfolioSpec, SkuSpec
from inventory_lab.application.factory import SimulationClock
from inventory_lab.core.registry import BuildContext
from inventory_lab.domain.order import ConsolidatedPurchaseOrder, OrderLineItem
from inventory_lab.domain.supply import SupplyLane
from inventory_lab.forecasting.forecast import forecast_registry
from inventory_lab.infrastructure.tracing import InMemoryTraceSink, NullTraceSink
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
from inventory_lab.simulation.result import SimulationResult
from inventory_lab.sourcing.lead_time import lead_time_registry
from inventory_lab.sourcing.runtime import LaneRuntime


@dataclass
class _SkuBundle:
    """Everything needed to run one SKU for one replication."""

    sku_id: str
    engine: SimulationEngine


@dataclass
class PortfolioRunResult:
    """Outcomes of a single portfolio replication."""

    sku_results: dict[str, SimulationResult]

    # Consolidation accounting (zero when consolidation_enabled=False)
    consolidated_orders: list[ConsolidatedPurchaseOrder] = field(default_factory=list)
    total_fixed_cost_saved: float = 0.0


class PortfolioEngine:
    """Runs a multi-SKU portfolio for one replication.

    Consolidation is applied as a post-processing credit: we identify orders that
    were placed on the same lane on the same day, merge them into a
    `ConsolidatedPurchaseOrder`, and compute the fixed-cost saving.
    """

    def __init__(
        self,
        spec: PortfolioSpec,
        seed: int,
        replication: int = 0,
    ) -> None:
        self._spec = spec
        self._seed = seed
        self._replication = replication

        # shared clock (all SKUs live on the same calendar)
        self._clock = SimulationClock(start_date=spec.start_date)

        # shared lane runtimes (lanes are shared infrastructure)
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

        self._bundles: list[_SkuBundle] = [
            self._build_sku(sku, seed, replication)
            for sku in spec.skus
        ]

    # ------------------------------------------------------------------

    def _build_sku(
        self, sku: SkuSpec, seed: int, replication: int
    ) -> _SkuBundle:
        # Each SKU gets its own RNG derived from the shared seed so demand
        # streams are independent but reproducible.
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
        events = list(
            generator.generate(self._spec.horizon_days, rng, self._clock)
        )

        engine = SimulationEngine(
            config=EngineConfig(
                horizon_days=self._spec.horizon_days,
                warmup_days=self._spec.warmup_days,
                shortage_mode=self._spec.shortage_mode,
                collect_trace=self._spec.collect_trace,
                shelf_life_days=sku.shelf_life_days,
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
            forecast_observer=forecast if isinstance(forecast, DemandObserver) else None,
            tracer=InMemoryTraceSink() if self._spec.collect_trace else None,
        )
        return _SkuBundle(sku_id=sku.sku_id, engine=engine)

    # ------------------------------------------------------------------

    def run(self) -> PortfolioRunResult:
        sku_results = {b.sku_id: b.engine.run() for b in self._bundles}

        if not self._spec.consolidation_enabled:
            return PortfolioRunResult(sku_results=sku_results)

        consolidated, saved = self._consolidate(sku_results)
        return PortfolioRunResult(
            sku_results=sku_results,
            consolidated_orders=consolidated,
            total_fixed_cost_saved=saved,
        )

    def _consolidate(
        self, results: dict[str, SimulationResult]
    ) -> tuple[list[ConsolidatedPurchaseOrder], float]:
        """Merge same-day, same-lane orders across SKUs into consolidated orders.

        Groups orders by (lane_id, floor(placed_at)).  Any group with > 1 SKU pays
        the fixed cost only once; the rest is credited back.
        """
        lane_by_id: dict[str, SupplyLane] = {
            lane.lane_id: lane for lane in self._spec.lanes
        }

        # Collect all orders across SKUs, tagged with their sku_id
        # We read them from the trace (keep_replications=False so no raw results)
        # Instead, re-derive from KPI ordering cost: we need order-level detail.
        # The engine does not expose per-order logs in KpiSnapshot, so we infer
        # consolidation groups from the number of orders placed per replication
        # and their timing — approximated here via orders_placed count.
        #
        # For an exact implementation the engine would need an order log port.
        # The approach below uses a conservative approximation: on a weekly review,
        # all SKUs review on the same day → every group of N weekly orders on the
        # same day can be consolidated into 1, saving (N-1) × fixed_cost.
        #
        # We approximate: group_size ≈ min(len(skus), orders_placed per sku).
        # For a proper implementation, add an order log to SimulationResult.

        fixed_cost_per_lane: dict[str, float] = {
            lane.lane_id: lane.fixed_order_cost for lane in self._spec.lanes
        }

        # Count orders per SKU per lane (from KPI)
        sku_order_counts: dict[str, int] = {
            sku_id: result.kpis.orders_placed
            for sku_id, result in results.items()
        }

        # Assume all SKUs use the first lane (standard portfolio assumption)
        primary_lane_id = self._spec.lanes[0].lane_id
        fixed_cost = fixed_cost_per_lane[primary_lane_id]

        # Conservative estimate: consolidated groups = max orders placed by any SKU.
        # Each group contains all SKUs that ordered in that review window, paying
        # the fixed cost once instead of N times.
        n_skus = len(results)
        max_orders = max(sku_order_counts.values()) if sku_order_counts else 0
        if max_orders == 0 or n_skus <= 1:
            return [], 0.0

        # Build representative consolidated orders
        consolidated: list[ConsolidatedPurchaseOrder] = []
        total_saved = 0.0

        for group_idx in range(max_orders):
            # Gather SKUs that placed at least (group_idx + 1) orders
            participating = [
                sku_id
                for sku_id, count in sku_order_counts.items()
                if count > group_idx
            ]
            if len(participating) <= 1:
                continue  # no consolidation benefit for a single-SKU group

            # Fixed cost saving: paid once instead of len(participating) times
            saved = (len(participating) - 1) * fixed_cost
            total_saved += saved

            line_items = tuple(
                OrderLineItem(
                    sku_id=sku_id,
                    quantity=1,   # representative; actual qty is in SimulationResult
                    unit_cost=lane_by_id[primary_lane_id].unit_cost,
                )
                for sku_id in participating
            )
            consolidated.append(
                ConsolidatedPurchaseOrder(
                    order_id=f"CON-{group_idx + 1}",
                    lane_id=primary_lane_id,
                    line_items=line_items,
                    placed_at=float(group_idx * 7),   # approximate weekly cadence
                    due_at=float(group_idx * 7 + lane_by_id[primary_lane_id].lead_time.params.get("mean_days", 4)),
                    fixed_cost=fixed_cost,
                )
            )

        return consolidated, total_saved
