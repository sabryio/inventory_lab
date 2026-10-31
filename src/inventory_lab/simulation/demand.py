"""Demand streams: synthetic, seasonal, or historical replay."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from math import exp
from random import Random

from inventory_lab.core.registry import BuildContext, ComponentRegistry
from inventory_lab.domain.base import NonNegativeFloat, ValueObject
from inventory_lab.domain.errors import ConfigurationError
from inventory_lab.domain.events import DemandEvent
from inventory_lab.ports.clock import Clock
from inventory_lab.ports.demand import DemandGenerator

demand_registry: ComponentRegistry[DemandGenerator] = ComponentRegistry("demand")

_DEMAND_OFFSET = (
    0.5  # demand lands mid-day; reviews at day boundaries see yesterday's stock
)


def _poisson(rng: Random, lam: float) -> int:
    """Knuth's algorithm — adequate for the small daily lambdas of a pharmacy."""
    if lam <= 0:
        return 0
    if lam > 500:  # normal approximation for large means
        return max(0, round(rng.gauss(lam, lam**0.5)))
    threshold, k, p = exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= threshold:
            return k
        k += 1


class PoissonDemand(DemandGenerator):
    def __init__(
        self, mean_daily: float, weekday_factors: Sequence[float] | None = None
    ) -> None:
        if mean_daily < 0:
            raise ConfigurationError("mean_daily must be non-negative")
        if weekday_factors is not None and len(weekday_factors) != 7:
            raise ConfigurationError(
                "weekday_factors must have exactly 7 entries (Mon..Sun)"
            )
        self._mean = mean_daily
        self._factors = tuple(weekday_factors) if weekday_factors else None

    def generate(
        self, horizon_days: int, rng: Random, clock: Clock
    ) -> Iterator[DemandEvent]:
        for day in range(horizon_days):
            factor = 1.0
            if self._factors:
                factor = self._factors[clock.to_datetime(day).weekday()]
            qty = _poisson(rng, self._mean * factor)
            if qty > 0:
                yield DemandEvent(time=day + _DEMAND_OFFSET, quantity=qty)

    def describe(self) -> str:
        seasonal = " seasonal" if self._factors else ""
        return f"Poisson{seasonal}(mean={self._mean:g}/day)"


class NormalDemand(DemandGenerator):
    def __init__(self, mean_daily: float, std_daily: float) -> None:
        self._mean, self._std = mean_daily, std_daily

    def generate(
        self, horizon_days: int, rng: Random, clock: Clock
    ) -> Iterator[DemandEvent]:
        for day in range(horizon_days):
            qty = max(0, round(rng.gauss(self._mean, self._std)))
            if qty > 0:
                yield DemandEvent(time=day + _DEMAND_OFFSET, quantity=qty)

    def describe(self) -> str:
        return f"Normal(mean={self._mean:g}, std={self._std:g})"


class EmpiricalDemand(DemandGenerator):
    """Replay history, optionally bootstrapping to generate fresh replications."""

    def __init__(self, history: Sequence[int], bootstrap: bool = False) -> None:
        if not history:
            raise ConfigurationError("empirical demand needs a non-empty history")
        self._history = tuple(history)
        self._bootstrap = bootstrap

    def generate(
        self, horizon_days: int, rng: Random, clock: Clock
    ) -> Iterator[DemandEvent]:
        for day in range(horizon_days):
            qty = (
                rng.choice(self._history)
                if self._bootstrap
                else self._history[day % len(self._history)]
            )
            if qty > 0:
                yield DemandEvent(time=day + _DEMAND_OFFSET, quantity=int(qty))

    def describe(self) -> str:
        mode = "bootstrap" if self._bootstrap else "replay"
        return f"Empirical({mode}, n={len(self._history)})"


class PoissonConfig(ValueObject):
    mean_daily: NonNegativeFloat
    weekday_factors: tuple[NonNegativeFloat, ...] | None = None


class NormalConfig(ValueObject):
    mean_daily: NonNegativeFloat
    std_daily: NonNegativeFloat


class EmpiricalConfig(ValueObject):
    history: tuple[int, ...]
    bootstrap: bool = False


@demand_registry.register("poisson", PoissonConfig)
def _build_poisson(config: PoissonConfig, ctx: BuildContext) -> DemandGenerator:
    return PoissonDemand(config.mean_daily, config.weekday_factors)


@demand_registry.register("normal", NormalConfig)
def _build_normal(config: NormalConfig, ctx: BuildContext) -> DemandGenerator:
    return NormalDemand(config.mean_daily, config.std_daily)


@demand_registry.register("empirical", EmpiricalConfig)
def _build_empirical(config: EmpiricalConfig, ctx: BuildContext) -> DemandGenerator:
    return EmpiricalDemand(config.history, config.bootstrap)
