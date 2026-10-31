"""Use case: Optimise portfolio-level parameters.

Single responsibility: orchestrate the optimizer and log progress.
No dependency on any concrete infrastructure class.
"""

from __future__ import annotations

import logging

from inventory_lab.ports.portfolio_optimization import (
    PortfolioOptimizationBounds,
    PortfolioOptimizationResult,
    PortfolioOptimizer,
)

logger = logging.getLogger(__name__)


class OptimizePortfolio:
    """Drives portfolio-level parameter search via an injected ``PortfolioOptimizer``.

    Typical usage (composition root wires the concrete optimizer)::

        from inventory_lab.infrastructure.portfolio_optimization import ScipyPortfolioOptimizer
        result = OptimizePortfolio(ScipyPortfolioOptimizer()).execute(spec, bounds)
    """

    def __init__(self, optimizer: PortfolioOptimizer) -> None:
        self._optimizer = optimizer

    def execute(
        self,
        spec: object,  # PortfolioSpec — typed as object to mirror the port
        bounds: PortfolioOptimizationBounds,
        replications_per_eval: int = 5,
        max_evaluations: int = 50,
    ) -> PortfolioOptimizationResult:
        logger.info(
            "starting portfolio optimization  bounds=%s  replications=%d  max_evals=%d",
            bounds.model_dump(),
            replications_per_eval,
            max_evaluations,
        )

        result = self._optimizer.optimize(
            spec=spec,
            bounds=bounds,
            replications_per_eval=replications_per_eval,
            max_evaluations=max_evaluations,
        )

        if result.success:
            logger.info(
                "portfolio optimization converged  review_period=%dd  "
                "safety_factor=%.2f  total_cost=%.2f  fill_rate=%.2%%  "
                "fixed_cost_savings=%.2f  evaluations=%d",
                result.best_review_period,
                result.best_safety_factor,
                result.best_total_cost,
                result.achieved_fill_rate * 100,
                result.total_fixed_cost_savings,
                result.evaluations,
            )
        else:
            logger.warning(
                "portfolio optimization finished without a feasible solution  "
                "best_fill_rate=%.2%%  target=%.2%%",
                result.achieved_fill_rate * 100,
                # spec.target_service_level is unknown here (typed as object),
                # so we note the shortfall indirectly via success=False.
                0.0,
            )

        return result
