"""Manual buffer — a floor, a legacy value, or a regulatory minimum."""

from __future__ import annotations

from inventory_lab.core.registry import BuildContext
from inventory_lab.domain.base import NonNegativeFloat, ValueObject
from inventory_lab.domain.planning import SafetyStockContext, SafetyStockResult
from inventory_lab.ports.planning import SafetyStockStrategy
from inventory_lab.safety_stock.normal import safety_stock_registry


class FixedSafetyStockConfig(ValueObject):
    units: NonNegativeFloat


class FixedSafetyStock(SafetyStockStrategy):
    def __init__(self, units: float) -> None:
        self._units = units

    def compute(self, ctx: SafetyStockContext) -> SafetyStockResult:
        return SafetyStockResult(
            units=self._units,
            method="fixed",
            protection_period_days=ctx.protection_period_days,
            protection_demand_std=0.0,
            expected_protection_demand=ctx.mean_daily_demand
            * ctx.protection_period_days,
            notes="manually specified buffer",
        )


@safety_stock_registry.register("fixed", FixedSafetyStockConfig)
def _build_fixed(
    config: FixedSafetyStockConfig, ctx: BuildContext
) -> SafetyStockStrategy:
    return FixedSafetyStock(config.units)
