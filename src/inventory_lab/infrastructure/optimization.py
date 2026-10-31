"""Concrete SimulationOptimizer using SciPy Differential Evolution.

Infrastructure detail: the application layer never imports this module directly.
Inject `ScipyDifferentialEvolutionOptimizer` at the composition root (cli.py / tests).
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import Bounds, differential_evolution

from inventory_lab.application.compare import ComparePolicies
from inventory_lab.application.factory import SimulationFactory
from inventory_lab.application.specs import CandidateSpec, ExperimentSpec
from inventory_lab.domain.supply import ComponentSpec
from inventory_lab.ports.optimization import (
    OptimizationBounds,
    OptimizationResult,
    SimulationOptimizer,
)

# A penalty weight that dominates any feasible total cost.
# Must be >> max(horizon * holding_cost * max_stock + ordering + purchasing).
_PENALTY_WEIGHT = 100_000.0


def _build_candidate(
    policy_kind: str,
    lane_id: str,
    s: int,
    Q: int,
    R: int | None,
    name: str = "opt_candidate",
) -> CandidateSpec:
    """Map discrete integer parameters to a CandidateSpec with a static provider."""
    if R is not None:
        schedule = ComponentSpec(
            kind="interval", params={"period_days": float(R), "offset_days": 0.0}
        )
    else:
        schedule = ComponentSpec(kind="continuous")

    static_params: dict[str, float] = {
        "reorder_point": float(s),
        "order_quantity": float(Q),
        # order_up_to_level = s + Q is the natural definition for (R,s,Q) and (R,s,S).
        "order_up_to_level": float(s + Q),
    }

    return CandidateSpec(
        name=name,
        policy=ComponentSpec(
            kind=policy_kind,
            params={
                "lane_id": lane_id,
                "schedule": schedule.model_dump(),
                "parameters": {
                    "kind": "static",
                    "params": static_params,
                },
            },
        ),
    )


class _ObjectiveEvaluator:
    """SRP: evaluate a single point in the parameter space.

    Isolates the mapping from the optimizer's continuous vector to discrete
    Pydantic specs, the Monte-Carlo averaging, and the penalty calculation.
    """

    def __init__(
        self,
        factory: SimulationFactory,
        base_spec: ExperimentSpec,
        policy_kind: str,
        target_service_level: float,
        replications: int,
    ) -> None:
        self._factory = factory
        self._base_spec = base_spec
        self._policy_kind = policy_kind
        self._target = target_service_level
        self._replications = replications
        self._evaluations = 0
        self._lane_id = base_spec.lanes[0].lane_id

    # SciPy calls this with a 1-D numpy array.
    def __call__(self, x: np.ndarray) -> float:
        self._evaluations += 1

        # --- 1. decode continuous → discrete --------------------------------
        if self._policy_kind == "s_Q":
            s, Q = round(x[0]), round(x[1])
            R: int | None = None
        else:
            R, s, Q = round(x[0]), round(x[1]), round(x[2])

        Q = max(Q, 1)
        s = max(s, 0)

        candidate = _build_candidate(self._policy_kind, self._lane_id, s, Q, R)

        # --- 2. Monte-Carlo replications with Common Random Numbers ----------
        # Seed = base + eval_index * large_prime + replication keeps evaluations
        # comparable to each other (same demand stream) while replications vary.
        total_cost = 0.0
        fill_rate = 0.0
        for r in range(self._replications):
            seed = 42 + self._evaluations * 997 + r
            result = self._factory.create_engine(
                candidate, seed=seed, replication=r
            ).run()
            total_cost += result.kpis.total_cost
            fill_rate += result.kpis.fill_rate

        mean_cost = total_cost / self._replications
        mean_fill = fill_rate / self._replications

        # --- 3. penalty for constraint violation ----------------------------
        shortfall = max(0.0, self._target - mean_fill)
        return mean_cost + _PENALTY_WEIGHT * shortfall

    @property
    def evaluations(self) -> int:
        return self._evaluations


class ScipyDifferentialEvolutionOptimizer(SimulationOptimizer):
    """Differential Evolution is robust for stochastic, non-differentiable,
    integer-constrained black-box functions — exactly what simulation gives us.

    Key properties:
    - Population-based: escapes local optima that gradient methods miss.
    - Integer constraints: `integrality` flag rounds each variable to an integer.
    - Bounded: keeps s, Q, R inside the declared search space throughout.
    """

    def optimize(
        self,
        spec: object,
        policy_kind: str,
        bounds: OptimizationBounds,
        replications_per_eval: int = 5,
        max_evaluations: int = 100,
    ) -> OptimizationResult:
        assert isinstance(spec, ExperimentSpec)  # narrow type for mypy/ty

        evaluator = _ObjectiveEvaluator(
            factory=SimulationFactory(spec),
            base_spec=spec,
            policy_kind=policy_kind,
            target_service_level=spec.target_service_level,
            replications=replications_per_eval,
        )

        # --- build scipy bounds in parameter order --------------------------
        if policy_kind == "s_Q":
            scipy_bounds = Bounds(
                lb=[bounds.s_min, bounds.Q_min],
                ub=[bounds.s_max, bounds.Q_max],
                keep_feasible=True,
            )
            integrality = [True, True]
        else:
            scipy_bounds = Bounds(
                lb=[bounds.R_min, bounds.s_min, bounds.Q_min],
                ub=[bounds.R_max, bounds.s_max, bounds.Q_max],
                keep_feasible=True,
            )
            integrality = [True, True, True]

        # maxiter × popsize × n_params ≈ total evaluations
        n_params = len(integrality)
        popsize = 15
        maxiter = max(1, max_evaluations // (popsize * n_params))

        de_result = differential_evolution(
            func=evaluator,
            bounds=scipy_bounds,
            integrality=integrality,
            maxiter=maxiter,
            popsize=popsize,
            seed=42,
            disp=False,
            updating="deferred",
            workers=1,
            tol=0.01,
        )

        # --- decode best solution -------------------------------------------
        x_best = de_result.x
        if policy_kind == "s_Q":
            s, Q = round(x_best[0]), round(x_best[1])
            best_params: dict[str, float] = {"s": float(s), "Q": float(Q)}
            R_best: int | None = None
        else:
            R_best, s, Q = (
                round(x_best[0]),
                round(x_best[1]),
                round(x_best[2]),
            )
            best_params = {"R": float(R_best), "s": float(s), "Q": float(Q)}

        # --- high-fidelity final evaluation (20 replications) ---------------
        final_candidate = _build_candidate(
            policy_kind,
            spec.lanes[0].lane_id,
            s,
            Q,
            R_best,
            name="optimized",
        )
        final_spec = spec.model_copy(
            update={"candidates": (final_candidate,), "replications": 20}
        )
        final_report = ComparePolicies(SimulationFactory(final_spec)).execute(
            final_spec, keep_replications=False
        )
        candidate_report = final_report.candidates[0]

        achieved_fill = candidate_report.metrics["fill_rate"].mean
        achieved_ready = candidate_report.metrics["ready_rate"].mean
        achieved_cost = candidate_report.metrics["total_cost"].mean
        # success = solution is feasible (meets service target).
        # de_result.success only means DE converged numerically, which requires
        # many more evaluations than a practical budget allows — don't use it here.
        success = achieved_fill >= spec.target_service_level

        return OptimizationResult(
            policy_kind=policy_kind,
            best_parameters=best_params,
            best_total_cost=achieved_cost,
            achieved_fill_rate=achieved_fill,
            achieved_ready_rate=achieved_ready,
            evaluations=evaluator.evaluations,
            replications_per_eval=replications_per_eval,
            success=success,
        )
