"""Turn forecasts + uncertainty into s, S, Q. This is where safety stock is injected."""

from __future__ import annotations

from inventory_lab.core.registry import BuildContext, ComponentRegistry
from inventory_lab.domain.base import NonNegativeFloat, Probability, ValueObject
from inventory_lab.domain.planning import (
    PolicyContext,
    ReplenishmentParameters,
    SafetyStockContext,
)
from inventory_lab.domain.supply import ComponentSpec
from inventory_lab.ports.demand import ForecastReader
from inventory_lab.ports.planning import (
    LotSizingStrategy,
    ParameterProvider,
    SafetyStockStrategy,
)
from inventory_lab.ports.supply import LeadTimeModel

parameter_registry: ComponentRegistry[ParameterProvider] = ComponentRegistry(
    "parameters"
)


class StaticParameters(ParameterProvider):
    """Textbook mode: hand-set s/S/Q, never recomputed."""

    def __init__(self, parameters: ReplenishmentParameters) -> None:
        self._parameters = parameters

    def parameters_for(self, ctx: PolicyContext) -> ReplenishmentParameters:
        return self._parameters


class StatisticalParameters(ParameterProvider):
    """Dynamic mode: recompute the buffer at every review from the live forecast.

    s = d̄·(R+L) + SS      (reorder point — a MINIMUM)
    S = d̄·(R+L) + SS      (order-up-to level — a MAXIMUM)
    Q = lot sizing strategy (EOQ / fixed / pallet-rounded)

    Note both s and S are produced; each QuantityRule/TriggerRule consumes only the
    one it needs, so a single provider serves all four policies (DRP + ISP).
    """

    def __init__(
        self,
        forecast: ForecastReader,
        safety: SafetyStockStrategy,
        sizing: LotSizingStrategy,
        lead_time: LeadTimeModel,
        review_period_days: float,
        service_level: float,
    ) -> None:
        self._forecast = forecast
        self._safety = safety
        self._sizing = sizing
        self._lead_time = lead_time
        self._review_period = review_period_days
        self._service_level = service_level

    def parameters_for(self, ctx: PolicyContext) -> ReplenishmentParameters:
        ss_ctx = SafetyStockContext(
            mean_daily_demand=self._forecast.mean_daily,
            daily_demand_std=self._forecast.std_daily,
            lead_time_mean_days=self._lead_time.mean_days,
            lead_time_std_days=self._lead_time.std_days,
            review_period_days=self._review_period,
            cycle_service_level=self._service_level,
        )
        result = self._safety.compute(ss_ctx)
        base = result.expected_protection_demand + result.units
        lot = self._sizing.quantity(ss_ctx.mean_daily_demand)
        return ReplenishmentParameters(
            reorder_point=base,
            order_up_to_level=base,
            order_quantity=lot if lot > 0 else None,
            safety_stock=result.units,
            protection_period_days=result.protection_period_days,
            expected_protection_demand=result.expected_protection_demand,
        )


class StaticParametersConfig(ValueObject):
    reorder_point: float | None = None
    order_up_to_level: float | None = None
    order_quantity: NonNegativeFloat | None = None
    safety_stock: NonNegativeFloat = 0.0


class StatisticalParametersConfig(ValueObject):
    safety: ComponentSpec = ComponentSpec(kind="normal")
    sizing: ComponentSpec = ComponentSpec(kind="fixed", params={"quantity": 100})
    service_level: Probability | None = None


@parameter_registry.register("static", StaticParametersConfig)
def _build_static(
    config: StaticParametersConfig, ctx: BuildContext
) -> ParameterProvider:
    return StaticParameters(
        ReplenishmentParameters(
            reorder_point=config.reorder_point,
            order_up_to_level=config.order_up_to_level,
            order_quantity=config.order_quantity,
            safety_stock=config.safety_stock,
        )
    )


@parameter_registry.register("statistical", StatisticalParametersConfig)
def _build_statistical(
    config: StatisticalParametersConfig, ctx: BuildContext
) -> ParameterProvider:
    from inventory_lab.planning.sizing import sizing_registry
    from inventory_lab.safety_stock.normal import safety_stock_registry

    return StatisticalParameters(
        forecast=ctx.forecast,
        safety=safety_stock_registry.create(config.safety, ctx),
        sizing=sizing_registry.create(config.sizing, ctx),
        lead_time=ctx.lead_time,
        review_period_days=ctx.review_period_days,
        service_level=config.service_level or ctx.service_level,
    )
