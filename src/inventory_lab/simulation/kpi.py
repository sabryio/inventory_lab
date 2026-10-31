"""Time-weighted KPI accounting. Integrals, not end-of-day snapshots."""

from __future__ import annotations

from inventory_lab.domain.inventory import (
    Consumption,
    InventoryState,
    PurchaseOrder,
    Receipt,
)
from inventory_lab.simulation.costs import CostBreakdown, CostModel
from inventory_lab.simulation.result import KpiSnapshot


class KpiAccumulator:
    """Integrates on-hand and backlog over time so averages are duration-correct.

    `accrue` must be called with the PRE-mutation state before every state change;
    the engine guarantees this by accruing at event-pop time.
    """

    def __init__(self, cost_model: CostModel) -> None:
        self._cost = cost_model
        self._reset_counters()
        self._last_t = 0.0
        self._start_t = 0.0
        self._prev = InventoryState(on_hand=0)

    def _reset_counters(self) -> None:
        self._on_hand_integral = 0.0
        self._backorder_integral = 0.0
        self._stockout_time = 0.0
        self._demanded = self._filled_now = self._filled_late = self._lost = 0
        self._wasted = 0
        self._received = self._orders = self._emergency_orders = 0
        self._ordered = self._ordered_emergency = 0
        self._ordering_cost = self._purchasing_cost = 0.0
        self._demand_events = self._demand_events_full = 0

    def begin(self, now: float, state: InventoryState) -> None:
        self._last_t = self._start_t = now
        self._prev = state

    def reset_at_warmup(self, now: float, state: InventoryState) -> None:
        """Discard the transient: keep stock, forget the statistics."""
        self._reset_counters()
        self.begin(now, state)

    def accrue(self, now: float) -> None:
        dt = now - self._last_t
        if dt < 0:
            raise ValueError("time went backwards in KPI accumulator")
        self._on_hand_integral += self._prev.on_hand * dt
        self._backorder_integral += self._prev.backorders * dt
        if self._prev.on_hand == 0:
            self._stockout_time += dt
        self._last_t = now

    def sync(self, state: InventoryState) -> None:
        self._prev = state

    # ---- event recording ----------------------------------------------
    def record_demand(self, consumption: Consumption) -> None:
        self._demanded += consumption.requested
        self._filled_now += consumption.filled_now
        self._lost += consumption.lost
        self._wasted += consumption.wasted_units
        self._demand_events += 1
        if consumption.filled_now == consumption.requested:
            self._demand_events_full += 1

    def record_receipt(self, receipt: Receipt) -> None:
        self._received += receipt.received
        self._filled_late += receipt.backlog_cleared

    def record_expiry(self, wasted: int) -> None:
        """Record units scrapped directly by an ExpiryEvent (not via demand)."""
        self._wasted += wasted

    def record_order(self, order: PurchaseOrder) -> None:
        self._orders += 1
        self._ordered += order.quantity
        self._ordering_cost += order.fixed_cost
        self._purchasing_cost += order.unit_cost * order.quantity
        if order.is_emergency:
            self._emergency_orders += 1
            self._ordered_emergency += order.quantity

    # ---- output --------------------------------------------------------
    def snapshot(self, now: float, final_state: InventoryState) -> KpiSnapshot:
        self.accrue(now)
        self.sync(final_state)
        duration = max(now - self._start_t, 1e-9)
        avg_on_hand = self._on_hand_integral / duration
        costs = CostBreakdown(
            holding=self._cost.holding_cost_per_unit_day * self._on_hand_integral,
            ordering=self._ordering_cost,
            purchasing=self._purchasing_cost,
            backorder_penalty=self._cost.backorder_penalty_per_unit_day
            * self._backorder_integral,
            lost_sales_penalty=self._cost.lost_sale_penalty_per_unit * self._lost,
            waste_penalty=self._cost.waste_penalty_per_unit * self._wasted,
        )
        served = self._filled_now + self._filled_late
        return KpiSnapshot(
            measured_days=duration,
            units_demanded=self._demanded,
            units_filled_immediately=self._filled_now,
            units_filled_late=self._filled_late,
            units_lost=self._lost,
            units_wasted=self._wasted,
            units_received=self._received,
            units_ordered=self._ordered,
            units_ordered_emergency=self._ordered_emergency,
            orders_placed=self._orders,
            emergency_orders_placed=self._emergency_orders,
            fill_rate=self._filled_now / self._demanded if self._demanded else 1.0,
            event_fill_rate=self._demand_events_full / self._demand_events
            if self._demand_events
            else 1.0,
            ready_rate=1.0 - self._stockout_time / duration,
            stockout_days=self._stockout_time,
            avg_on_hand=avg_on_hand,
            avg_backorders=self._backorder_integral / duration,
            inventory_turns=served / avg_on_hand if avg_on_hand > 0 else 0.0,
            costs=costs,
            total_cost=costs.total,
            final_state=final_state,
        )
