"""DIP hinge for simulation-based optimization.

The application layer depends only on these abstractions; the concrete scipy (or
Optuna, or BoTorch) implementation lives entirely in infrastructure/.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from inventory_lab.domain.base import NonNegativeFloat, PositiveInt, ValueObject


class OptimizationBounds(ValueObject):
    """Search-space boundaries for policy parameters (all bounds inclusive)."""

    s_min: PositiveInt = 1
    s_max: PositiveInt = 500
    Q_min: PositiveInt = 1
    Q_max: PositiveInt = 1000
    R_min: PositiveInt = 1  # review period (days) — ignored for s_Q
    R_max: PositiveInt = 30


class OptimizationResult(ValueObject):
    """Outcome of a completed optimization run."""

    policy_kind: str
    best_parameters: dict[str, float]  # e.g. {"s": 45.0, "Q": 120.0}
    best_total_cost: NonNegativeFloat
    achieved_fill_rate: NonNegativeFloat
    achieved_ready_rate: NonNegativeFloat
    evaluations: PositiveInt
    replications_per_eval: PositiveInt
    success: bool


class SimulationOptimizer(ABC):
    """Optimizes policy parameters via repeated simulation.

    Implementations are responsible for handling the stochastic nature of the
    objective (e.g. running multiple replications, applying penalty functions for
    constraint violations).  The application layer is agnostic of the algorithm.
    """

    @abstractmethod
    def optimize(
        self,
        spec: object,  # ExperimentSpec — typed as object to avoid a circular
        policy_kind: str,  # "s_Q" | "R_s_Q" | "R_s_S"
        bounds: OptimizationBounds,
        replications_per_eval: int = 5,
        max_evaluations: int = 100,
    ) -> OptimizationResult: ...
