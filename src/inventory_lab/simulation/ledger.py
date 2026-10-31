"""The only mutable inventory authority. Invariants are enforced here, once.

Batches are issued in First-Expired-First-Out (FEFO) order to minimise waste.
"""

from __future__ import annotations

from inventory_lab.domain.batch import Batch
from inventory_lab.domain.errors import InvariantViolation
from inventory_lab.domain.inventory import (
    Consumption,
    InventoryState,
    PurchaseOrder,
    Receipt,
    ShortageMode,
)

# Shelf life assigned to seed stock at t=0 (effectively infinite for simulation purposes).
_SEED_SHELF_LIFE_DAYS = 9_999.0


class InventoryLedger:
    """Stateful bookkeeping service with batch-level FEFO tracking.

    State is exposed exclusively as immutable InventoryState value objects, so no
    collaborator can mutate inventory behind the ledger's back.
    """

    def __init__(self, initial_on_hand: int, shortage_mode: ShortageMode) -> None:
        if initial_on_hand < 0:
            raise InvariantViolation("initial on-hand cannot be negative")
        self._backorders = 0
        self._mode = shortage_mode
        self._open: dict[str, PurchaseOrder] = {}
        self._batches: dict[str, Batch] = {}
        self._batch_counter = 0

        if initial_on_hand > 0:
            self._batch_counter += 1
            seed_id = f"BATCH-{self._batch_counter}"
            self._batches[seed_id] = Batch(
                batch_id=seed_id,
                quantity=initial_on_hand,
                received_at=0.0,
                expires_at=_SEED_SHELF_LIFE_DAYS,
                unit_cost=0.0,  # seed stock has no tracked purchase cost
            )

    # ---- queries -------------------------------------------------------

    @property
    def open_orders(self) -> tuple[PurchaseOrder, ...]:
        return tuple(self._open.values())

    def snapshot(self) -> InventoryState:
        on_hand = sum(b.quantity for b in self._batches.values())
        in_transit = sum(o.quantity for o in self._open.values())
        nearest = (
            min(b.expires_at for b in self._batches.values())
            if self._batches
            else None
        )
        return InventoryState(
            on_hand=on_hand,
            in_transit=in_transit,
            backorders=self._backorders,
            batch_count=len(self._batches),
            nearest_expiry_days=nearest,
        )

    def pop_order(self, order_id: str) -> PurchaseOrder:
        try:
            return self._open.pop(order_id)
        except KeyError as exc:
            raise InvariantViolation(f"receipt for unknown order {order_id!r}") from exc

    def get_batch(self, batch_id: str) -> Batch | None:
        return self._batches.get(batch_id)

    # ---- commands ------------------------------------------------------

    def register_order(self, order: PurchaseOrder) -> None:
        if order.order_id in self._open:
            raise InvariantViolation(f"duplicate order id {order.order_id!r}")
        self._open[order.order_id] = order

    def receive(
        self,
        quantity: int,
        unit_cost: float,
        shelf_life_days: float,
        now: float,
    ) -> Receipt:
        """Receive units as a new batch; clear any open backlog first."""
        if quantity <= 0:
            raise InvariantViolation("receipt quantity must be positive")

        self._batch_counter += 1
        batch_id = f"BATCH-{self._batch_counter}"
        expires_at = now + shelf_life_days

        self._batches[batch_id] = Batch(
            batch_id=batch_id,
            quantity=quantity,
            received_at=now,
            expires_at=expires_at,
            unit_cost=unit_cost,
        )

        # Clear backlog with the newly received stock (FEFO will handle ordering).
        cleared = min(self._backorders, quantity)
        if cleared > 0:
            self._backorders -= cleared
            self._consume_fefo(cleared)

        added = quantity - cleared
        return Receipt(
            received=quantity,
            backlog_cleared=cleared,
            added_to_stock=added,
            batch_id=batch_id,
            expires_at=expires_at,
        )

    def consume(self, quantity: int, now: float) -> Consumption:
        """Consume units using FEFO; expire stale batches before issuing."""
        if quantity <= 0:
            raise InvariantViolation("demand quantity must be positive")

        wasted = self._remove_expired(now)

        filled = self._consume_fefo(quantity)
        shortfall = quantity - filled

        if shortfall and self._mode is ShortageMode.BACKORDER:
            self._backorders += shortfall
            return Consumption(
                filled_now=filled, backordered=shortfall, lost=0, wasted_units=wasted
            )
        return Consumption(
            filled_now=filled, backordered=0, lost=shortfall, wasted_units=wasted
        )

    def expire_batch(self, batch_id: str) -> int:
        """Forcibly expire a specific batch (called by the engine on ExpiryEvent).

        Returns the number of units wasted (0 if the batch was already consumed).
        """
        batch = self._batches.pop(batch_id, None)
        return batch.quantity if batch is not None else 0

    # ---- internals -----------------------------------------------------

    def _consume_fefo(self, quantity: int) -> int:
        """Issue up to `quantity` units from batches in expiry-date order.

        Returns how many units were actually filled.
        """
        sorted_batches = sorted(self._batches.values(), key=lambda b: b.expires_at)
        remaining = quantity
        filled = 0

        for batch in sorted_batches:
            if remaining <= 0:
                break
            take = min(batch.quantity, remaining)
            new_qty = batch.quantity - take
            if new_qty == 0:
                del self._batches[batch.batch_id]
            else:
                # Pydantic ValueObjects are frozen; replace with updated copy.
                self._batches[batch.batch_id] = batch.model_copy(
                    update={"quantity": new_qty}
                )
            filled += take
            remaining -= take

        return filled

    def _remove_expired(self, now: float) -> int:
        """Remove every batch whose expiry time has been reached or passed.

        Returns the total number of wasted units.
        """
        expired = [b for b in self._batches.values() if b.is_expired(now)]
        wasted = sum(b.quantity for b in expired)
        for b in expired:
            del self._batches[b.batch_id]
        return wasted
