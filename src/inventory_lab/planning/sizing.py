"""Lot sizing: EOQ plus packaging decorators (the 'full pallet' advantage of (s,Q))."""

from __future__ import annotations

from math import ceil, sqrt

from inventory_lab.core.registry import BuildContext, ComponentRegistry
from inventory_lab.domain.base import NonNegativeFloat, PositiveInt, ValueObject
from inventory_lab.domain.errors import ConfigurationError
from inventory_lab.domain.supply import ComponentSpec
from inventory_lab.ports.planning import LotSizingStrategy

sizing_registry: ComponentRegistry[LotSizingStrategy] = ComponentRegistry("lot_sizing")


class FixedLotSize(LotSizingStrategy):
    def __init__(self, quantity: float) -> None:
        if quantity <= 0:
            raise ConfigurationError("fixed lot size must be positive")
        self._quantity = quantity

    def quantity(self, mean_daily_demand: float) -> float:
        return self._quantity


class EconomicOrderQuantity(LotSizingStrategy):
    """EOQ = sqrt(2·D·K / h) with D in units/day and h in cost/unit/day."""

    def __init__(
        self, fixed_order_cost: float, holding_cost_per_unit_day: float
    ) -> None:
        if fixed_order_cost <= 0 or holding_cost_per_unit_day <= 0:
            raise ConfigurationError("EOQ requires positive ordering and holding costs")
        self._k, self._h = fixed_order_cost, holding_cost_per_unit_day

    def quantity(self, mean_daily_demand: float) -> float:
        if mean_daily_demand <= 0:
            return 0.0
        return sqrt(2.0 * mean_daily_demand * self._k / self._h)


class RoundedLotSize(LotSizingStrategy):
    """Decorator: round any inner lot size up to a packaging multiple and/or MOQ."""

    def __init__(
        self, inner: LotSizingStrategy, multiple: int = 1, minimum: float = 0.0
    ) -> None:
        self._inner, self._multiple, self._minimum = inner, max(1, multiple), minimum

    def quantity(self, mean_daily_demand: float) -> float:
        raw = max(self._inner.quantity(mean_daily_demand), self._minimum)
        if raw <= 0:
            return 0.0
        return ceil(raw / self._multiple) * self._multiple


class FixedLotConfig(ValueObject):
    quantity: NonNegativeFloat


class EOQConfig(ValueObject):
    fixed_order_cost: NonNegativeFloat | None = None  # None -> take lane's cost
    holding_cost_per_unit_day: NonNegativeFloat | None = None  # None -> take cost model


class RoundedConfig(ValueObject):
    inner: ComponentSpec
    multiple: PositiveInt = 1
    minimum: NonNegativeFloat = 0.0


@sizing_registry.register("fixed", FixedLotConfig)
def _build_fixed(config: FixedLotConfig, ctx: BuildContext) -> LotSizingStrategy:
    return FixedLotSize(config.quantity)


@sizing_registry.register("eoq", EOQConfig)
def _build_eoq(config: EOQConfig, ctx: BuildContext) -> LotSizingStrategy:
    return EconomicOrderQuantity(
        config.fixed_order_cost
        if config.fixed_order_cost is not None
        else ctx.default_order_cost,
        config.holding_cost_per_unit_day
        if config.holding_cost_per_unit_day is not None
        else ctx.cost_model.holding_cost_per_unit_day,
    )


@sizing_registry.register("rounded", RoundedConfig)
def _build_rounded(config: RoundedConfig, ctx: BuildContext) -> LotSizingStrategy:
    return RoundedLotSize(
        sizing_registry.create(config.inner, ctx), config.multiple, config.minimum
    )
