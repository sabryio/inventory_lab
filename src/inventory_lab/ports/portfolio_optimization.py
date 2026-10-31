"""DIP hinge for portfolio-level optimization.

The application layer depends only on these abstractions; the concrete SciPy
(or Optuna, or BoTorch) implementation lives entirely in infrastructure/.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from inventory_lab.domain.base import NonNegativeFloat, PositiveInt, ValueObject


class PortfolioOptimizationBounds(ValueObject):
    """Search-space boundaries for portfolio-level parameters."""

    review_period_min: PositiveInt = 1   # days
    review_period_max: PositiveInt = 30
    safety_factor_min: NonNegativeFloat = 0.5
    safety_factor_max: NonNegativeFloat = 3.0


class PortfolioOptimizationResult(ValueObject):
    """Outcome of a completed portfolio optimization run."""

    best_review_period: PositiveInt
    best_safety_factor: NonNegativeFloat
    best_total_cost: NonNegativeFloat
    achieved_fill_rate: NonNegativeFloat
    total_fixed_cost_savings: NonNegativeFloat
    evaluations: PositiveInt
    replications_per_eval: PositiveInt
    success: bool


class PortfolioOptimizer(ABC):
    """Optimises shared review-period and safety-factor for a SKU portfolio.

    Implementations drive repeated ``PortfolioEngine`` runs and are responsible
    for handling stochasticity (multiple replications, penalty functions).  The
    application layer is agnostic of the underlying algorithm.
    """

    @abstractmethod
    def optimize(
        self,
        spec: object,  # PortfolioSpec — typed as object to avoid circular import
        bounds: PortfolioOptimizationBounds,
        replications_per_eval: int = 5,
        max_evaluations: int = 50,
    ) -> PortfolioOptimizationResult: ...
