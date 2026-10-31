"""Supply lanes: the commercial and physical constraints of a sourcing option."""

from __future__ import annotations

from enum import Enum
from typing import Any, Self

from pydantic import Field, model_validator

from inventory_lab.domain.base import NonNegativeFloat, NonNegativeInt, ValueObject


class LaneKind(str, Enum):
    REGULAR = "regular"
    EMERGENCY = "emergency"


class ComponentSpec(ValueObject):
    """Late-bound reference to a registered component: `kind` + validated `params`.

    This is the OCP seam: new algorithms are registered under a new `kind` without
    editing any spec model, factory signature, or call site.
    """

    kind: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)


class SupplyLane(ValueObject):
    """A supplier lane with packaging, MOQ and cost economics."""

    lane_id: str = Field(min_length=1)
    kind: LaneKind = LaneKind.REGULAR
    lead_time: ComponentSpec
    unit_cost: NonNegativeFloat = 0.0
    fixed_order_cost: NonNegativeFloat = 0.0
    order_multiple: NonNegativeInt = Field(
        default=1, description="Case/pallet multiple (0 = free)"
    )
    min_order_quantity: NonNegativeInt = 0
    max_order_quantity: NonNegativeInt = 0  # 0 = unlimited capacity

    @model_validator(mode="after")
    def _capacity_consistent(self) -> Self:
        if (
            self.max_order_quantity
            and self.max_order_quantity < self.min_order_quantity
        ):
            raise ValueError("max_order_quantity must be >= min_order_quantity")
        if self.max_order_quantity and self.order_multiple > self.max_order_quantity:
            raise ValueError("order_multiple exceeds lane capacity: no feasible order")
        return self
