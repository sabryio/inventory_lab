"""King's formula, extended for periodic review and variable lead time."""

from __future__ import annotations

from math import sqrt
from statistics import NormalDist

from inventory_lab.core.registry import BuildContext, ComponentRegistry
from inventory_lab.domain.base import ValueObject
from inventory_lab.domain.planning import SafetyStockContext, SafetyStockResult
from inventory_lab.ports.planning import SafetyStockStrategy

safety_stock_registry: ComponentRegistry[SafetyStockStrategy] = ComponentRegistry(
    "safety_stock"
)


class NormalSafetyStockConfig(ValueObject):
    """No parameters: everything comes from the SafetyStockContext."""


class NormalSafetyStock(SafetyStockStrategy):
    """SS = z(csl) · sqrt( (R + L)·σd² + d̄²·σL² ).

    Rationale: the protection period is R+L for periodic policies
    and L for continuous ones. Lead-time variance is
    scaled by mean demand squared, which is why unreliable suppliers are expensive.
    """

    def compute(self, ctx: SafetyStockContext) -> SafetyStockResult:
        z = NormalDist().inv_cdf(ctx.cycle_service_level)
        period = ctx.protection_period_days
        demand_variance = period * ctx.daily_demand_std**2
        lead_time_variance = (ctx.mean_daily_demand**2) * (ctx.lead_time_std_days**2)
        sigma = sqrt(max(demand_variance + lead_time_variance, 0.0))
        return SafetyStockResult(
            units=max(0.0, z * sigma),
            method="normal_king",
            z_score=max(0.0, z),
            protection_period_days=period,
            protection_demand_std=sigma,
            expected_protection_demand=ctx.mean_daily_demand * period,
            notes=f"demand_var={demand_variance:.2f}, lead_time_var={lead_time_variance:.2f}",
        )


@safety_stock_registry.register("normal", NormalSafetyStockConfig)
def _build_normal(
    config: NormalSafetyStockConfig, ctx: BuildContext
) -> SafetyStockStrategy:
    return NormalSafetyStock()
