"""Real-time order consolidation coordinator.

Infrastructure detail: only PortfolioEngine imports this.
The engine depends only on the OrderInterceptor port.

Architecture
------------
The coordinator is shared across all SKU engines in a portfolio.
PortfolioEngine drives engines in lockstep (all engines advance to the same day
boundary before anyone's snapshot fires), so:

1. Every engine steps through its intra-day events (demand, reviews, receipts).
   Any order the engine wants to place calls intercept(), which stores the order
   and returns None -- suppressing the original.

2. After all engines have stepped, PortfolioEngine calls coordinator.flush(t).
   This groups all pending orders by (lane_id, due_at), splits the fixed cost
   proportionally by quantity, and caches the per-owner result.

3. PortfolioEngine calls coordinator.get_pending(sku_id) for each engine and
   passes the consolidated orders to engine._place_deferred(), which registers
   the order and schedules the receipt event.

4. Each engine then processes its snapshot event (day boundary KPI anchor).

Fixed-cost allocation
---------------------
Within a (lane_id, due_at) group:

    shared_fixed_i = fixed_cost * (qty_i / total_qty_in_group)

Sum across all members == one fixed cost. Saving == (n-1) * fixed_cost.
"""

from __future__ import annotations

from collections import defaultdict
from itertools import count
from math import floor
from typing import NamedTuple

from inventory_lab.domain.inventory import PurchaseOrder
from inventory_lab.sourcing.runtime import LaneRuntime


class _PendingEntry(NamedTuple):
    owner: str
    order: PurchaseOrder


class ConsolidationCoordinator:
    """Intercept and consolidate orders across multiple SKU engines.

    Lockstep protocol (called by PortfolioEngine each day)
    ------------------------------------------------------
    ::

        # Step 1: all intra-day events for every SKU
        for bundle in bundles:
            bundle.engine.step_until(day_t)

        # Step 2: group + allocate costs
        coordinator.flush(day_t)

        # Step 3: give each engine its consolidated orders, then process snapshot
        for bundle in bundles:
            for order in coordinator.get_pending(bundle.sku_id):
                bundle.engine._place_deferred(order)
            bundle.engine.process_snapshot(day_t)

    The engine's _on_snapshot hook also calls flush_pending() via the
    OrderInterceptor protocol. When PortfolioEngine has already called flush(),
    that call is a no-op (idempotent on the same timestamp).
    """

    def __init__(self, lanes: dict[str, LaneRuntime]) -> None:
        self._fixed_cost: dict[str, float] = {
            lid: rt.spec.fixed_order_cost for lid, rt in lanes.items()
        }
        self._pending: list[_PendingEntry] = []
        self._flushed: dict[str, list[PurchaseOrder]] = {}
        self._order_ids = count(1)
        self._flushed_at: float = -1.0

    # ------------------------------------------------------------------
    # OrderInterceptor protocol
    # ------------------------------------------------------------------

    def intercept(
        self,
        proposed: PurchaseOrder,
        now: float,
        owner: str | None = None,
    ) -> PurchaseOrder | None:
        """Store the proposed order; return None to suppress the original."""
        self._pending.append(_PendingEntry(owner=owner or "", order=proposed))
        return None

    def flush_pending(
        self,
        now: float,
        owner: str | None = None,
    ) -> list[PurchaseOrder]:
        """Protocol shim called by the engine's _on_snapshot hook.

        In lockstep mode PortfolioEngine already called flush() before this
        fires, so the call is a no-op and returns the cached result.
        Works standalone too (single-engine / test scenarios).
        """
        if self._flushed_at != now:
            self.flush(now)
        return self._flushed.get(owner or "", [])

    # ------------------------------------------------------------------
    # Lockstep API
    # ------------------------------------------------------------------

    def flush(self, now: float) -> None:
        """Group all pending orders and compute proportional fixed costs.

        Idempotent: repeated calls for the same now are no-ops.
        """
        if self._flushed_at == now:
            return
        self._flushed_at = now
        self._flushed = self._build_consolidated()
        self._pending.clear()

    def get_pending(self, owner: str) -> list[PurchaseOrder]:
        """Return consolidated orders for owner after flush() has been called."""
        return self._flushed.get(owner, [])

    def reset(self) -> None:
        """Clear all state (call between replications if reusing the instance)."""
        self._pending.clear()
        self._flushed.clear()
        self._flushed_at = -1.0

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_consolidated(self) -> dict[str, list[PurchaseOrder]]:
        if not self._pending:
            return {}

        # Group by (lane_id, floor(placed_at)) — orders placed on the same day
        # travel on the same shipment regardless of stochastic lead time samples.
        # We use the mean due_at within each group as the single arrival time.
        from collections import defaultdict
        from math import floor

        groups: dict[tuple[str, int], list[_PendingEntry]] = defaultdict(list)
        for entry in self._pending:
            key = (entry.order.lane_id, floor(entry.order.placed_at))
            groups[key].append(entry)

        result: dict[str, list[PurchaseOrder]] = defaultdict(list)

        for (lane_id, _day), entries in groups.items():
            fixed = self._fixed_cost.get(lane_id, 0.0)
            total_qty = sum(e.order.quantity for e in entries)
            # Use the mean due_at as the single consolidated arrival time.
            mean_due = sum(e.order.due_at for e in entries) / len(entries)

            for entry in entries:
                share = entry.order.quantity / total_qty if total_qty else 0.0
                result[entry.owner].append(
                    PurchaseOrder(
                        order_id=f"CPO-{next(self._order_ids)}",
                        lane_id=lane_id,
                        quantity=entry.order.quantity,
                        placed_at=entry.order.placed_at,
                        due_at=mean_due,
                        unit_cost=entry.order.unit_cost,
                        fixed_cost=fixed * share,
                        is_emergency=entry.order.is_emergency,
                    )
                )

        return dict(result)
