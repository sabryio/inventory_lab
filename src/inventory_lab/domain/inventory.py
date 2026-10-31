"""Inventory truth: on-hand, in-transit, backorders — exactly as the textbook defines."""

from __future__ import annotations

from enum import Enum
from typing import Self

from pydantic import Field, model_validator

from inventory_lab.domain.base import (
    NonNegativeFloat,
    NonNegativeInt,
    PositiveInt,
    ValueObject,
)


class ShortageMode(str, Enum):
    """What happens to unmet demand. Pharmacies mix both, so it is configurable."""

    BACKORDER = "backorder"  # patient waits; backlog accumulates
    LOST_SALES = "lost_sales"  # patient goes elsewhere; sale is gone


class InventoryState(ValueObject):
    """Snapshot of net inventory components."""

    on_hand: NonNegativeInt = Field(description="Physically available to dispense")
    in_transit: NonNegativeInt = Field(
        default=0, description="Ordered, not yet received"
    )
    backorders: NonNegativeInt = Field(
        default=0, description="Open, unfulfilled demand"
    )
    batch_count: NonNegativeInt = Field(
        default=0, description="Number of distinct batches in stock"
    )
    nearest_expiry_days: float | None = Field(
        default=None, description="Simulation-time of the soonest batch expiry"
    )

    @model_validator(mode="after")
    def _no_stock_and_backlog_simultaneously(self) -> Self:
        # The ledger always clears backlog on receipt, so this pair is unreachable.
        if self.on_hand > 0 and self.backorders > 0:
            raise ValueError(
                "on_hand and backorders cannot both be positive: receipts must clear backlog first"
            )
        return self

    @property
    def net_inventory(self) -> int:
        """Net inventory = on-hand + in-transit - backorders. May be negative."""
        return self.on_hand + self.in_transit - self.backorders

    @property
    def inventory_position(self) -> int:
        """Alias kept explicit to defuse the 'confusion curse'."""
        return self.net_inventory


class PurchaseOrder(ValueObject):
    """An open replenishment order (a pipeline element)."""

    order_id: str
    lane_id: str
    quantity: PositiveInt
    placed_at: float
    due_at: float
    unit_cost: NonNegativeFloat
    fixed_cost: NonNegativeFloat
    is_emergency: bool = False

    @model_validator(mode="after")
    def _due_after_placement(self) -> Self:
        if self.due_at < self.placed_at:
            raise ValueError("due_at must be >= placed_at")
        return self


class Consumption(ValueObject):
    """Outcome of a demand arrival."""

    filled_now: NonNegativeInt
    backordered: NonNegativeInt
    lost: NonNegativeInt
    wasted_units: NonNegativeInt = Field(
        default=0,
        description="Units expired and discarded during this consumption event",
    )

    @property
    def requested(self) -> int:
        return self.filled_now + self.backordered + self.lost


class Receipt(ValueObject):
    """Outcome of a receipt: units received and backlog cleared."""

    received: NonNegativeInt
    backlog_cleared: NonNegativeInt
    added_to_stock: NonNegativeInt
    batch_id: str | None = None
    expires_at: float | None = None
