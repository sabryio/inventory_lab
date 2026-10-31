"""Lead-time distributions. Variance here is what drives (and costs) safety stock."""

from __future__ import annotations

from random import Random
from statistics import mean, pstdev

from inventory_lab.core.registry import BuildContext, ComponentRegistry
from inventory_lab.domain.base import NonNegativeFloat, ValueObject
from inventory_lab.domain.errors import ConfigurationError
from inventory_lab.ports.supply import LeadTimeModel

lead_time_registry: ComponentRegistry[LeadTimeModel] = ComponentRegistry("lead_time")


class DeterministicLeadTime(LeadTimeModel):
    def __init__(self, days: float) -> None:
        self._days = days

    @property
    def mean_days(self) -> float:
        return self._days

    @property
    def std_days(self) -> float:
        return 0.0

    def sample(self, rng: Random) -> float:
        return self._days


class NormalLeadTime(LeadTimeModel):
    """Truncated normal: physically plausible, statistically convenient."""

    def __init__(
        self, mean_days: float, std_days: float, minimum_days: float = 0.1
    ) -> None:
        if std_days < 0:
            raise ConfigurationError("lead-time std must be non-negative")
        self._mean, self._std, self._min = mean_days, std_days, max(minimum_days, 0.01)

    @property
    def mean_days(self) -> float:
        return self._mean

    @property
    def std_days(self) -> float:
        return self._std

    def sample(self, rng: Random) -> float:
        if self._std == 0:
            return max(self._mean, self._min)
        return max(self._min, rng.gauss(self._mean, self._std))


class EmpiricalLeadTime(LeadTimeModel):
    """Bootstrap realised receipt lead times — no distributional assumption."""

    def __init__(self, samples_days: tuple[float, ...]) -> None:
        if not samples_days:
            raise ConfigurationError("empirical lead time needs at least one sample")
        self._samples = samples_days

    @property
    def mean_days(self) -> float:
        return mean(self._samples)

    @property
    def std_days(self) -> float:
        return pstdev(self._samples) if len(self._samples) > 1 else 0.0

    def sample(self, rng: Random) -> float:
        return rng.choice(self._samples)


class FixedConfig(ValueObject):
    days: NonNegativeFloat


class NormalConfig(ValueObject):
    mean_days: NonNegativeFloat
    std_days: NonNegativeFloat = 0.0
    minimum_days: NonNegativeFloat = 0.1


class EmpiricalConfig(ValueObject):
    samples_days: tuple[NonNegativeFloat, ...]


@lead_time_registry.register("fixed", FixedConfig)
def _build_fixed(config: FixedConfig, ctx: BuildContext) -> LeadTimeModel:
    return DeterministicLeadTime(config.days)


@lead_time_registry.register("normal", NormalConfig)
def _build_normal(config: NormalConfig, ctx: BuildContext) -> LeadTimeModel:
    return NormalLeadTime(config.mean_days, config.std_days, config.minimum_days)


@lead_time_registry.register("empirical", EmpiricalConfig)
def _build_empirical(config: EmpiricalConfig, ctx: BuildContext) -> LeadTimeModel:
    return EmpiricalLeadTime(config.samples_days)
