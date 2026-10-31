"""Batch-level inventory with expiration dates — critical for pharmaceuticals."""

from __future__ import annotations

from typing import Self

from pydantic import model_validator

from inventory_lab.domain.base import (
    NonNegativeFloat,
    NonNegativeInt,
    PositiveInt,
    ValueObject,
)


class Batch(ValueObject):
    """A single production batch with a known expiration date."""

    batch_id: str
    quantity: PositiveInt
    received_at: NonNegativeFloat  # simulation time (days)
    expires_at: NonNegativeFloat   # simulation time (days)
    unit_cost: NonNegativeFloat

    @model_validator(mode="after")
    def _expiry_after_receipt(self) -> Self:
        if self.expires_at <= self.received_at:
            raise ValueError("batch must expire after it is received")
        return self

    @property
    def shelf_life_days(self) -> float:
        return self.expires_at - self.received_at

    def is_expired(self, now: float) -> bool:
        return now >= self.expires_at

    def remaining_shelf_life(self, now: float) -> float:
        return max(0.0, self.expires_at - now)


class BatchAllocation(ValueObject):
    """Result of FEFO issuance: which batches were consumed and how much."""

    consumed_from_batches: tuple[tuple[str, int], ...]  # (batch_id, quantity)
    total_consumed: NonNegativeInt
    wasted_units: NonNegativeInt = 0  # units discarded due to expiry during this allocation
