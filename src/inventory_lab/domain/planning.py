"""Planning vocabulary. Every ambiguous 'target' is given exactly one explicit name."""

from __future__ import annotations

from typing import Self

from pydantic import Field, model_validator

from inventory_lab.domain.base import NonNegativeFloat, Probability, ValueObject
from inventory_lab.domain.errors import MissingParameterError
from inventory_lab.domain.inventory import InventoryState, PurchaseOrder


class SafetyStockContext(ValueObject):
    """Inputs to a safety-stock calculation, independent of any policy."""

    mean_daily_demand: NonNegativeFloat
    daily_demand_std: NonNegativeFloat
    lead_time_mean_days: NonNegativeFloat
    lead_time_std_days: NonNegativeFloat = 0.0
    review_period_days: NonNegativeFloat = Field(
        default=0.0, description="R: 0 for continuous review, > 0 for periodic review"
    )
    cycle_service_level: Probability = 0.95

    @property
    def protection_period_days(self) -> float:
        """Risk period: L for (s,Q); R + L for (R,S) and (R,s,Q). Chapter 4."""
        return self.review_period_days + self.lead_time_mean_days


class SafetyStockResult(ValueObject):
    """Explainable output — never a bare number, so audits can reconstruct it."""

    units: NonNegativeFloat
    method: str
    z_score: NonNegativeFloat | None = None
    protection_period_days: NonNegativeFloat
    protection_demand_std: NonNegativeFloat
    expected_protection_demand: NonNegativeFloat
    notes: str = ""


class ReplenishmentParameters(ValueObject):
    """The four textbook parameters, unambiguously named."""

    reorder_point: float | None = Field(
        default=None, description="s: a MINIMUM threshold"
    )
    order_up_to_level: float | None = Field(
        default=None, description="S: a MAXIMUM target"
    )
    order_quantity: float | None = Field(
        default=None, description="Q: a fixed lot size"
    )
    safety_stock: NonNegativeFloat = 0.0
    protection_period_days: NonNegativeFloat = 0.0
    expected_protection_demand: NonNegativeFloat = 0.0

    @model_validator(mode="after")
    def _at_least_one_control_parameter(self) -> Self:
        if all(
            v is None
            for v in (self.reorder_point, self.order_up_to_level, self.order_quantity)
        ):
            raise ValueError(
                "at least one of reorder_point / order_up_to_level / order_quantity"
            )
        return self

    def require_reorder_point(self) -> float:
        if self.reorder_point is None:
            raise MissingParameterError(
                "policy requires reorder_point (s) but provider gave None"
            )
        return self.reorder_point

    def require_order_up_to(self) -> float:
        if self.order_up_to_level is None:
            raise MissingParameterError(
                "policy requires order_up_to_level (S) but got None"
            )
        return self.order_up_to_level

    def require_order_quantity(self) -> float:
        if self.order_quantity is None or self.order_quantity <= 0:
            raise MissingParameterError("policy requires a positive order_quantity (Q)")
        return self.order_quantity


class PolicyContext(ValueObject):
    """Read-only, minimal view handed to a policy.

    ISP: a policy sees the inventory position and its own open pipeline — never the
    ledger, the engine, the RNG, or the cost model. It cannot mutate the world.
    """

    now: NonNegativeFloat
    state: InventoryState
    open_orders: tuple[PurchaseOrder, ...] = ()

    def open_quantity_on(self, lane_id: str) -> int:
        return sum(o.quantity for o in self.open_orders if o.lane_id == lane_id)

    def earliest_arrival(self, lane_id: str | None = None) -> float | None:
        candidates = [
            o.due_at
            for o in self.open_orders
            if lane_id is None or o.lane_id == lane_id
        ]
        return min(candidates) if candidates else None
