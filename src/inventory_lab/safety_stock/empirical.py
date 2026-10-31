"""Distribution-free safety stock from observed lead-time demand."""

from __future__ import annotations

from statistics import mean, quantiles

from inventory_lab.core.registry import BuildContext, ComponentRegistry  # noqa: F401
from inventory_lab.domain.base import ValueObject
from inventory_lab.domain.errors import ConfigurationError
from inventory_lab.domain.planning import SafetyStockContext, SafetyStockResult
from inventory_lab.ports.planning import SafetyStockStrategy
from inventory_lab.safety_stock.normal import safety_stock_registry


class EmpiricalSafetyStockConfig(ValueObject):
    lead_time_demand_samples: tuple[float, ...]
    """Observed demand over realised protection periods (R+L), in units."""


class EmpiricalSafetyStock(SafetyStockStrategy):
    """SS = quantile(LTD, csl) − E[LTD].

    Preferred when demand is intermittent or strongly non-normal — common for
    slow-moving or seasonal pharmaceuticals, where a z-score understates the tail.
    """

    def __init__(self, samples: tuple[float, ...]) -> None:
        if len(samples) < 4:
            raise ConfigurationError(
                "empirical safety stock needs >= 4 lead-time-demand samples"
            )
        if any(s < 0 for s in samples):
            raise ConfigurationError("lead-time-demand samples must be non-negative")
        self._samples = tuple(sorted(samples))

    def compute(self, ctx: SafetyStockContext) -> SafetyStockResult:
        n = len(self._samples)
        # Linear-interpolated quantile at p = (n-1)·csl.
        pos = (n - 1) * ctx.cycle_service_level
        lo, hi = int(pos), min(int(pos) + 1, n - 1)
        target = self._samples[lo] + (self._samples[hi] - self._samples[lo]) * (
            pos - lo
        )
        expected = mean(self._samples)
        return SafetyStockResult(
            units=max(0.0, target - expected),
            method="empirical_quantile",
            protection_period_days=ctx.protection_period_days,
            protection_demand_std=(
                quantiles(self._samples, n=4)[2] - quantiles(self._samples, n=4)[0]
            )
            / 1.349,
            expected_protection_demand=expected,
            notes=f"n={n}, quantile_target={target:.2f}",
        )


@safety_stock_registry.register("empirical", EmpiricalSafetyStockConfig)
def _build_empirical(
    config: EmpiricalSafetyStockConfig, ctx: BuildContext
) -> SafetyStockStrategy:
    return EmpiricalSafetyStock(config.lead_time_demand_samples)
