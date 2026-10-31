"""Forecasts. RollingWindowForecast makes safety stock genuinely dynamic."""

from __future__ import annotations

from collections import deque
from statistics import mean, pstdev

from inventory_lab.core.registry import BuildContext, ComponentRegistry
from inventory_lab.domain.base import NonNegativeFloat, PositiveInt, ValueObject
from inventory_lab.ports.demand import ForecastReader

forecast_registry: ComponentRegistry[ForecastReader] = ComponentRegistry("forecast")


class StaticForecast:
    """Fixed mean/std. Implements ForecastReader and (as a no-op) DemandObserver."""

    def __init__(self, mean_daily: float, std_daily: float) -> None:
        self._mean, self._std = mean_daily, std_daily

    @property
    def mean_daily(self) -> float:
        return self._mean

    @property
    def std_daily(self) -> float:
        return self._std

    def observe(
        self, day: int, quantity: int
    ) -> None:  # LSP: honours the no-op contract
        return None


class RollingWindowForecast:
    """Bayesian-ish shrinkage: use priors until enough observations accumulate.

    Implements BOTH narrow ports (ForecastReader, DemandObserver) while the engine
    only ever sees the writer and the planner only ever sees the reader (ISP).
    """

    def __init__(
        self,
        prior_mean: float,
        prior_std: float,
        window_days: int = 90,
        min_samples: int = 14,
    ) -> None:
        self._prior_mean, self._prior_std = prior_mean, prior_std
        self._min_samples = min_samples
        self._samples: deque[float] = deque(maxlen=window_days)

    def observe(self, day: int, quantity: int) -> None:
        self._samples.append(float(quantity))

    @property
    def mean_daily(self) -> float:
        if len(self._samples) < self._min_samples:
            return self._prior_mean
        return mean(self._samples)

    @property
    def std_daily(self) -> float:
        if len(self._samples) < self._min_samples:
            return self._prior_std
        # Floors at sqrt(mean) to avoid a zero-variance illusion on flat windows.
        return max(pstdev(self._samples), self.mean_daily**0.5 * 0.25)


class StaticForecastConfig(ValueObject):
    mean_daily: NonNegativeFloat
    std_daily: NonNegativeFloat


class RollingForecastConfig(ValueObject):
    prior_mean: NonNegativeFloat
    prior_std: NonNegativeFloat
    window_days: PositiveInt = 90
    min_samples: PositiveInt = 14


@forecast_registry.register("static", StaticForecastConfig)
def _build_static(config: StaticForecastConfig, ctx: BuildContext) -> ForecastReader:
    return StaticForecast(config.mean_daily, config.std_daily)


@forecast_registry.register("rolling", RollingForecastConfig)
def _build_rolling(config: RollingForecastConfig, ctx: BuildContext) -> ForecastReader:
    return RollingWindowForecast(
        config.prior_mean, config.prior_std, config.window_days, config.min_samples
    )
