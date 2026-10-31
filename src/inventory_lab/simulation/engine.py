"""Discrete-event simulation: heap-ordered events, deterministic tie-breaking."""

from __future__ import annotations

import heapq
from collections.abc import Mapping, Sequence
from itertools import count
from math import ceil, floor
from random import Random

from inventory_lab.domain.base import PositiveInt, ValueObject
from inventory_lab.domain.errors import OrderRejectedError, SimulationError
from inventory_lab.domain.events import (
    DemandEvent,
    ExpiryEvent,
    ReceiptEvent,
    ReviewEvent,
    SimEvent,
    SnapshotEvent,
)
from inventory_lab.domain.inventory import PurchaseOrder, ShortageMode
from inventory_lab.domain.planning import PolicyContext
from inventory_lab.ports.clock import Clock
from inventory_lab.ports.demand import DemandObserver
from inventory_lab.ports.order_interceptor import OrderInterceptor
from inventory_lab.ports.policy import InventoryPolicy
from inventory_lab.ports.reporting import TraceRecord, TraceSink
from inventory_lab.simulation.costs import CostModel
from inventory_lab.simulation.kpi import KpiAccumulator
from inventory_lab.simulation.ledger import InventoryLedger
from inventory_lab.simulation.result import OrderRecord, SimulationResult
from inventory_lab.sourcing.runtime import LaneRuntime


class EngineConfig(ValueObject):
    horizon_days: PositiveInt = 365
    warmup_days: int = 0
    shortage_mode: ShortageMode = ShortageMode.BACKORDER
    max_orders_per_event: PositiveInt = 8
    """Circuit breaker: a pathological parameterisation must fail loudly, not hang."""
    collect_trace: bool = False
    shelf_life_days: float = 9_999.0
    """Default shelf life for all received batches. Override per-lane in future."""
    collect_order_log: bool = False
    """When True the engine appends every placed order to SimulationResult.order_log."""


class SimulationEngine:
    """Orchestrates time, state and policies. Contains NO inventory-policy logic.

    Event priority at equal timestamps: RECEIPT < DEMAND < REVIEW < SNAPSHOT.
    Continuous policies are re-evaluated after every state change; periodic ones
    are woken by their calendar. Both can coexist inside one composite policy.
    """

    def __init__(
        self,
        *,
        config: EngineConfig,
        clock: Clock,
        ledger: InventoryLedger,
        lanes: Mapping[str, LaneRuntime],
        policies: Sequence[InventoryPolicy],
        demand_events: Sequence[DemandEvent],
        cost_model: CostModel,
        rng: Random,
        candidate: str,
        policy_code: str,
        seed: int,
        replication: int = 0,
        forecast_observer: DemandObserver | None = None,
        tracer: TraceSink | None = None,
        order_interceptor: OrderInterceptor | None = None,
    ) -> None:
        self._config = config
        self._clock = clock
        self._ledger = ledger
        self._lanes = lanes
        self._policies = tuple(policies)
        self._demand_events = tuple(demand_events)
        self._rng = rng
        self._forecast_observer = forecast_observer
        self._tracer = tracer
        self._interceptor = order_interceptor
        self._candidate, self._policy_code = candidate, policy_code
        self._seed, self._replication = seed, replication
        self._kpi = KpiAccumulator(cost_model)
        self._queue: list[tuple[float, int, int, SimEvent]] = []
        self._seq = count()
        self._order_ids = count(1)
        self._trace: list[TraceRecord] = []
        self._order_log: list[OrderRecord] = []
        self._orders_this_event = 0
        self._prepared = False
        self._warmup_done = self._config.warmup_days <= 0
        # When True, _on_snapshot skips the flush_pending call because
        # PortfolioEngine drives placement directly in the lockstep protocol.
        self._lockstep_mode = False

    # ---- event plumbing -------------------------------------------------
    def _push(self, event: SimEvent) -> None:
        heapq.heappush(
            self._queue, (event.time, int(event.kind), next(self._seq), event)
        )

    def prepare(self) -> None:
        """Seed the event queue and KPI accumulator without running any events.

        Must be called once before ``step_until`` when driving the engine
        externally (e.g. from ``PortfolioEngine`` in lockstep mode).
        Calling ``run()`` internally calls ``prepare()`` automatically.
        """
        if self._prepared:
            return
        self._prepared = True
        horizon = float(self._config.horizon_days)
        for event in self._demand_events:
            if event.time <= horizon:
                self._push(event)
        for policy in self._policies:
            if policy.schedule.reviews_on_schedule:
                first = policy.schedule.next_after(0.0)
                if first is not None and first <= horizon:
                    self._push(ReviewEvent(time=first, policy_id=policy.code))
            else:
                self._push(ReviewEvent(time=0.0, policy_id=policy.code))
        for day in range(1, self._config.horizon_days + 1):
            self._push(SnapshotEvent(time=float(day)))
        self._kpi.begin(0.0, self._ledger.snapshot())

    def step_until(self, stop_time: float) -> bool:
        """Process all queued events with ``time < stop_time``.

        Stops *before* consuming any event at exactly ``stop_time`` so the
        caller can inject work (e.g. flush consolidated orders) before the
        snapshot event fires.

        Returns ``True`` if there are more events to process, ``False`` if the
        queue is exhausted (simulation is done).
        """
        horizon = float(self._config.horizon_days)
        while self._queue:
            time, _, _, event = self._queue[0]  # peek
            if time >= stop_time:
                break
            heapq.heappop(self._queue)
            if time > horizon:
                break
            self._kpi.accrue(time)
            self._orders_this_event = 0

            if not self._warmup_done and time >= self._config.warmup_days:
                self._kpi.reset_at_warmup(time, self._ledger.snapshot())
                self._warmup_done = True

            match event:
                case ReceiptEvent():
                    self._on_receipt(event, time)
                case DemandEvent():
                    self._on_demand(event, time)
                case ReviewEvent():
                    self._on_scheduled_review(event, time)
                case SnapshotEvent():
                    self._on_snapshot(event, time)
                case ExpiryEvent():
                    self._on_expiry(event, time)
                case _:  # pragma: no cover
                    raise SimulationError(f"unhandled event {event!r}")

            self._kpi.sync(self._ledger.snapshot())

        return bool(self._queue)

    def process_snapshot(self, t: float) -> None:
        """Consume the single SnapshotEvent at exactly ``t`` (if present).

        Called by ``PortfolioEngine`` *after* placing consolidated orders into
        this engine's ledger.  The interceptor hook is intentionally skipped
        here — ``PortfolioEngine`` has already handled order placement via
        ``_place_deferred``; firing it again would cause duplicate registration.
        """
        horizon = float(self._config.horizon_days)
        while self._queue:
            time, _, _, event = self._queue[0]
            if time > t:
                break
            if time < t:
                # Defensive: drain any stragglers before the snapshot.
                heapq.heappop(self._queue)
                if time > horizon:
                    break
                self._kpi.accrue(time)
                self._orders_this_event = 0
                if not self._warmup_done and time >= self._config.warmup_days:
                    self._kpi.reset_at_warmup(time, self._ledger.snapshot())
                    self._warmup_done = True
                match event:
                    case ReceiptEvent():
                        self._on_receipt(event, time)
                    case DemandEvent():
                        self._on_demand(event, time)
                    case ReviewEvent():
                        self._on_scheduled_review(event, time)
                    case SnapshotEvent():
                        # Skip interceptor — placement already done externally.
                        pass
                    case ExpiryEvent():
                        self._on_expiry(event, time)
                self._kpi.sync(self._ledger.snapshot())
                continue
            # time == t: consume the snapshot
            heapq.heappop(self._queue)
            if isinstance(event, SnapshotEvent):
                self._kpi.accrue(time)
                self._orders_this_event = 0
                if not self._warmup_done and time >= self._config.warmup_days:
                    self._kpi.reset_at_warmup(time, self._ledger.snapshot())
                    self._warmup_done = True
                # Do NOT call _on_snapshot — PortfolioEngine already placed orders.
                self._kpi.sync(self._ledger.snapshot())
            break

    def finalise(self) -> SimulationResult:
        """Drain any remaining events and return the ``SimulationResult``.

        Call after the last ``step_until`` / ``process_snapshot`` pair.
        """
        horizon = float(self._config.horizon_days)
        while self._queue:
            time, _, _, event = heapq.heappop(self._queue)
            if time > horizon:
                break
            self._kpi.accrue(time)
            self._orders_this_event = 0
            if not self._warmup_done and time >= self._config.warmup_days:
                self._kpi.reset_at_warmup(time, self._ledger.snapshot())
                self._warmup_done = True
            match event:
                case ReceiptEvent():
                    self._on_receipt(event, time)
                case DemandEvent():
                    self._on_demand(event, time)
                case ReviewEvent():
                    self._on_scheduled_review(event, time)
                case SnapshotEvent():
                    self._on_snapshot(event, time)
                case ExpiryEvent():
                    self._on_expiry(event, time)
                case _:  # pragma: no cover
                    raise SimulationError(f"unhandled event {event!r}")
            self._kpi.sync(self._ledger.snapshot())

        result_kpis = self._kpi.snapshot(horizon, self._ledger.snapshot())
        return SimulationResult(
            candidate=self._candidate,
            policy_code=self._policy_code,
            seed=self._seed,
            replication=self._replication,
            kpis=result_kpis,
            trace=tuple(self._trace),
            order_log=tuple(self._order_log) if self._config.collect_order_log else (),
        )

    def run(self) -> SimulationResult:
        self.prepare()

        while self._queue:
            time, _, _, event = heapq.heappop(self._queue)
            if time > float(self._config.horizon_days):
                break
            self._kpi.accrue(time)  # integrate with the PRE-event state
            self._orders_this_event = 0

            if not self._warmup_done and time >= self._config.warmup_days:
                self._kpi.reset_at_warmup(time, self._ledger.snapshot())
                self._warmup_done = True

            match event:
                case ReceiptEvent():
                    self._on_receipt(event, time)
                case DemandEvent():
                    self._on_demand(event, time)
                case ReviewEvent():
                    self._on_scheduled_review(event, time)
                case SnapshotEvent():
                    self._on_snapshot(event, time)
                case ExpiryEvent():
                    self._on_expiry(event, time)
                case _:  # pragma: no cover - discriminated union is exhaustive
                    raise SimulationError(f"unhandled event {event!r}")

            self._kpi.sync(self._ledger.snapshot())

        horizon = float(self._config.horizon_days)
        result_kpis = self._kpi.snapshot(horizon, self._ledger.snapshot())
        return SimulationResult(
            candidate=self._candidate,
            policy_code=self._policy_code,
            seed=self._seed,
            replication=self._replication,
            kpis=result_kpis,
            trace=tuple(self._trace),
            order_log=tuple(self._order_log) if self._config.collect_order_log else (),
        )

    # ---- handlers -------------------------------------------------------
    def _on_receipt(self, event: ReceiptEvent, now: float) -> None:
        order = self._ledger.pop_order(event.order_id)
        receipt = self._ledger.receive(
            order.quantity,
            order.unit_cost,
            self._config.shelf_life_days,
            now,
        )
        self._kpi.record_receipt(receipt)
        # Schedule an expiry event for this batch if it falls within the horizon.
        if (
            receipt.batch_id is not None
            and receipt.expires_at is not None
            and receipt.expires_at <= self._config.horizon_days
        ):
            self._push(ExpiryEvent(time=receipt.expires_at, batch_id=receipt.batch_id))
        self._review_continuous(now)

    def _on_demand(self, event: DemandEvent, now: float) -> None:
        consumption = self._ledger.consume(event.quantity, now)
        self._kpi.record_demand(consumption)
        if self._forecast_observer is not None:
            self._forecast_observer.observe(self._clock.day_index(now), event.quantity)
        self._review_continuous(now)

    def _on_scheduled_review(self, event: ReviewEvent, now: float) -> None:
        policy = next((p for p in self._policies if p.code == event.policy_id), None)
        if policy is None:
            raise SimulationError(
                f"review event for unknown policy {event.policy_id!r}"
            )
        self._evaluate(policy, now)
        nxt = policy.schedule.next_after(now)
        if nxt is not None and nxt <= self._config.horizon_days:
            self._push(ReviewEvent(time=nxt, policy_id=policy.code))

    def _on_expiry(self, event: ExpiryEvent, now: float) -> None:
        """Remove the batch from stock and record the waste in KPIs."""
        wasted = self._ledger.expire_batch(event.batch_id)
        if wasted > 0:
            self._kpi.record_expiry(wasted)
            self._kpi.sync(self._ledger.snapshot())

    def _on_snapshot(self, event: SnapshotEvent, now: float) -> None:
        """Day-boundary hook: flush any deferred consolidated orders.

        In lockstep mode this is a no-op — PortfolioEngine drives placement
        directly via coordinator.flush() + engine._place_deferred().
        """
        if self._interceptor is None or self._lockstep_mode:
            return
        for order in self._interceptor.flush_pending(now, owner=self._candidate):
            self._place_deferred(order)

    def _review_continuous(self, now: float) -> None:
        for policy in self._policies:
            if policy.schedule.reviews_on_change:
                self._evaluate(policy, now)

    def _evaluate(self, policy: InventoryPolicy, now: float) -> None:
        ctx = PolicyContext(
            now=now, state=self._ledger.snapshot(), open_orders=self._ledger.open_orders
        )
        decision = policy.decide(ctx)
        ordered = 0
        for intent in decision.orders:
            order = self._issue(intent.lane_id, intent.quantity, now)
            if order is not None:
                ordered += order.quantity
        if self._config.collect_trace and decision.reviewed:
            params = decision.parameters
            record = TraceRecord(
                time=now,
                policy_code=decision.policy_code,
                net_inventory=decision.net_inventory
                if decision.net_inventory is not None
                else 0,
                safety_stock=params.safety_stock if params else 0.0,
                reorder_point=params.reorder_point if params else None,
                order_up_to_level=params.order_up_to_level if params else None,
                order_quantity=params.order_quantity if params else None,
                ordered=ordered,
                lane_id=decision.orders[0].lane_id if decision.orders else None,
                rationale=decision.rationale,
            )
            self._trace.append(record)
            if self._tracer is not None:
                self._tracer.record(record)

    def _issue(self, lane_id: str, requested: int, now: float) -> PurchaseOrder | None:
        """Normalise to lane constraints, then place. Single place where money is committed."""
        runtime = self._lanes.get(lane_id)
        if runtime is None:
            raise OrderRejectedError(f"unknown lane {lane_id!r}")
        spec = runtime.spec
        qty = requested
        if spec.order_multiple > 1:
            qty = ceil(qty / spec.order_multiple) * spec.order_multiple
        qty = max(qty, spec.min_order_quantity)
        if spec.max_order_quantity:
            qty = min(qty, spec.max_order_quantity)
            if spec.order_multiple > 1:
                qty = floor(qty / spec.order_multiple) * spec.order_multiple
        if qty <= 0:
            return None

        self._orders_this_event += 1
        if self._orders_this_event > self._config.max_orders_per_event:
            raise SimulationError(
                "order loop detected: more than "
                f"{self._config.max_orders_per_event} orders at t={now}. "
                "Check Q vs. reorder point parameterisation."
            )

        lead = runtime.lead_time.sample(self._rng)
        order = PurchaseOrder(
            order_id=f"PO-{next(self._order_ids)}",
            lane_id=lane_id,
            quantity=qty,
            placed_at=now,
            due_at=now + lead,
            unit_cost=spec.unit_cost,
            fixed_cost=spec.fixed_order_cost,
            is_emergency=spec.kind.is_emergency
            if hasattr(spec.kind, "is_emergency")
            else spec.kind.value == "emergency",
        )

        # Intercept before committing: the interceptor may suppress (return None)
        # or modify the order (e.g. adjust fixed cost for consolidation).
        if self._interceptor is not None:
            intercepted = self._interceptor.intercept(order, now, owner=self._candidate)
            if intercepted is None:
                return None  # suppressed — interceptor will re-emit via flush_pending
            order = intercepted

        self._ledger.register_order(order)
        self._kpi.record_order(order)
        self._push(ReceiptEvent(time=order.due_at, order_id=order.order_id))
        if self._config.collect_order_log:
            self._order_log.append(
                OrderRecord(
                    order_id=order.order_id,
                    lane_id=order.lane_id,
                    quantity=order.quantity,
                    placed_at=order.placed_at,
                    due_at=order.due_at,
                    unit_cost=order.unit_cost,
                    fixed_cost=order.fixed_cost,
                )
            )
        return order

    def _place_deferred(self, order: PurchaseOrder) -> None:
        """Register a consolidated order released by the interceptor.

        This bypasses the normal ``_issue`` path (quantity normalisation, circuit
        breaker) because the order was already validated when originally proposed.
        """
        self._ledger.register_order(order)
        self._kpi.record_order(order)
        self._push(ReceiptEvent(time=order.due_at, order_id=order.order_id))
        if self._config.collect_order_log:
            self._order_log.append(
                OrderRecord(
                    order_id=order.order_id,
                    lane_id=order.lane_id,
                    quantity=order.quantity,
                    placed_at=order.placed_at,
                    due_at=order.due_at,
                    unit_cost=order.unit_cost,
                    fixed_cost=order.fixed_cost,
                )
            )
        self._kpi.sync(self._ledger.snapshot())
