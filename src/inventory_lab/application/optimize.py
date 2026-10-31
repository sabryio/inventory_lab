"""Use case: optimize a policy kind within an experiment via simulation.

Single responsibility: orchestrate.  Zero knowledge of SciPy, numpy, or Bayesian
methods — those details belong in infrastructure/.
"""

from __future__ import annotations

import logging

from inventory_lab.application.factory import SimulationFactory
from inventory_lab.application.specs import ExperimentSpec
from inventory_lab.domain.errors import ConfigurationError
from inventory_lab.ports.optimization import (
    OptimizationBounds,
    OptimizationResult,
    SimulationOptimizer,
)

logger = logging.getLogger(__name__)

_SUPPORTED = frozenset({"s_Q", "R_s_Q", "R_s_S"})


class OptimizePolicy:
    """Orchestrates the optimization loop.

    Knows *what* to do (validate, delegate, log).  Knows nothing about *how* the
    optimizer searches the parameter space.
    """

    def __init__(
        self,
        factory: SimulationFactory,
        optimizer: SimulationOptimizer,
    ) -> None:
        self._factory = factory
        self._optimizer = optimizer

    def execute(
        self,
        spec: ExperimentSpec,
        policy_kind: str,
        bounds: OptimizationBounds,
        replications_per_eval: int = 5,
        max_evaluations: int = 100,
    ) -> OptimizationResult:
        if policy_kind not in _SUPPORTED:
            raise ConfigurationError(
                f"optimization not supported for policy kind {policy_kind!r}; "
                f"supported: {', '.join(sorted(_SUPPORTED))}"
            )

        logger.info(
            "Starting %s optimization | bounds=%s | reps/eval=%d | max_evals=%d",
            policy_kind,
            bounds.model_dump(),
            replications_per_eval,
            max_evaluations,
        )

        result = self._optimizer.optimize(
            spec=spec,
            policy_kind=policy_kind,
            bounds=bounds,
            replications_per_eval=replications_per_eval,
            max_evaluations=max_evaluations,
        )

        if result.success:
            logger.info(
                "Optimization converged | cost=%.2f | fill=%.2%% | params=%s",
                result.best_total_cost,
                result.achieved_fill_rate,
                result.best_parameters,
            )
        else:
            logger.warning(
                "Optimization did not find a feasible solution within the given bounds."
            )

        return result
