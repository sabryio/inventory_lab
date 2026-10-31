"""Cost model: the objective function the comparison is judged on."""

from __future__ import annotations

from inventory_lab.domain.base import NonNegativeFloat, ValueObject


class CostModel(ValueObject):
    holding_cost_per_unit_day: NonNegativeFloat = 0.0025
    backorder_penalty_per_unit_day: NonNegativeFloat = 0.5
    lost_sale_penalty_per_unit: NonNegativeFloat = 4.0
    """Margin + goodwill loss when a patient walks away."""
    waste_penalty_per_unit: NonNegativeFloat = 3.5
    """Cost of expired units: purchase cost recovery + disposal charge."""


class CostBreakdown(ValueObject):
    holding: NonNegativeFloat = 0.0
    ordering: NonNegativeFloat = 0.0
    purchasing: NonNegativeFloat = 0.0
    backorder_penalty: NonNegativeFloat = 0.0
    lost_sales_penalty: NonNegativeFloat = 0.0
    waste_penalty: NonNegativeFloat = 0.0

    @property
    def total(self) -> float:
        return (
            self.holding
            + self.ordering
            + self.purchasing
            + self.backorder_penalty
            + self.lost_sales_penalty
            + self.waste_penalty
        )
