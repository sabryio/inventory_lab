"""The only mutable inventory authority. Invariants are enforced here, once."""

from __future__ import annotations

from inventory_lab.domain.errors import InvariantViolation
from inventory_lab.domain.inventory import (
    Consumption,
    InventoryState,
    PurchaseOrder,
    Receipt,
    ShortageMode,
)


class InventoryLedger:
    """Stateful bookkeeping service (behaviour, not a data transfer object).

    State is exposed exclusively as immutable InventoryState value objects, so no
    collaborator can mutate inventory behind the ledger's back.
    """

    def __init__(self, initial_on_hand: int, shortage_mode: ShortageMode) -> None:
        if initial_on_hand < 0:
            raise InvariantViolation("initial on-hand cannot be negative")
        self._on_hand = initial_on_hand
        self._backorders = 0
        self._mode = shortage_mode
        self._open: dict[str, PurchaseOrder] = {}

    # ---- queries -------------------------------------------------------
    @property
    def open_orders(self) -> tuple[PurchaseOrder, ...]:
        return tuple(self._open.values())

    def snapshot(self) -> InventoryState:
        return InventoryState(
            on_hand=self._on_hand,
            in_transit=sum(o.quantity for o in self._open.values()),
            backorders=self._backorders,
        )

    def pop_order(self, order_id: str) -> PurchaseOrder:
        try:
            return self._open.pop(order_id)
        except KeyError as exc:
            raise InvariantViolation(f"receipt for unknown order {order_id!r}") from exc

    # ---- commands ------------------------------------------------------
    def register_order(self, order: PurchaseOrder) -> None:
        if order.order_id in self._open:
            raise InvariantViolation(f"duplicate order id {order.order_id!r}")
        self._open[order.order_id] = order

    def receive(self, quantity: int) -> Receipt:
        if quantity <= 0:
            raise InvariantViolation("receipt quantity must be positive")
        cleared = min(self._backorders, quantity)
        self._backorders -= cleared
        added = quantity - cleared
        self._on_hand += added
        return Receipt(received=quantity, backlog_cleared=cleared, added_to_stock=added)

    def consume(self, quantity: int) -> Consumption:
        if quantity <= 0:
            raise InvariantViolation("demand quantity must be positive")
        filled = min(self._on_hand, quantity)
        self._on_hand -= filled
        shortfall = quantity - filled
        if shortfall and self._mode is ShortageMode.BACKORDER:
            self._backorders += shortfall
            return Consumption(filled_now=filled, backordered=shortfall, lost=0)
        return Consumption(filled_now=filled, backordered=0, lost=shortfall)
