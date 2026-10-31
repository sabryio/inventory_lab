"""Discrete events. Priority order at equal timestamps is explicit and deterministic."""

from __future__ import annotations

from enum import IntEnum
from typing import Annotated, Literal

from pydantic import Field

from inventory_lab.domain.base import NonNegativeFloat, PositiveInt, ValueObject


class EventKind(IntEnum):
    RECEIPT = 0  # goods arrive first (available for today's demand)
    DEMAND = 1  # then patients arrive
    REVIEW = 2  # then we review and order
    SNAPSHOT = 3  # then we book the day


class ReceiptEvent(ValueObject):
    time: NonNegativeFloat
    kind: Literal[EventKind.RECEIPT] = EventKind.RECEIPT
    order_id: str


class DemandEvent(ValueObject):
    time: NonNegativeFloat
    kind: Literal[EventKind.DEMAND] = EventKind.DEMAND
    quantity: PositiveInt


class ReviewEvent(ValueObject):
    time: NonNegativeFloat
    kind: Literal[EventKind.REVIEW] = EventKind.REVIEW
    policy_id: str


class SnapshotEvent(ValueObject):
    time: NonNegativeFloat
    kind: Literal[EventKind.SNAPSHOT] = EventKind.SNAPSHOT


SimEvent = Annotated[
    ReceiptEvent | DemandEvent | ReviewEvent | SnapshotEvent,
    Field(discriminator="kind"),
]
