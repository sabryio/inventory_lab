"""Concrete PortfolioOptimizer using SciPy Differential Evolution.

Infrastructure detail: the application layer never imports this module directly.
Inject ``ScipyPortfolioOptimizer`` at the composition root (cli.py / tests).

What is being optimised
-----------------------
Two shared parameters applied uniformly across all SKUs:

``review_period``  (integer days)
    All SKUs switch from their preset schedule to an ``interval`` schedule with
    this period.  A shared review day maximises consolidation benefit — all SKUs
    review simultaneously so their orders land in the same daily flush window.

``safety_factor``  (continuous ≥ 0)
    Multiplier applied to each SKU's statistical safety stock.  Higher values
    raise service level at the cost of more inventory; lower values do the
    reverse.  The optimiser finds the Pareto-efficient frontier subject to the
    portfolio's ``target_service_level`` constraint enforced via a penalty.

Objective
---------
    minimise  mean_total_cost + PENALTY × max(0, target_fill − achieved_fill)

where ``mean_total_cost`` is the mean consolidated total cost across all
replications and all SKUs.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import Bounds, differential_evolution

from inventory_lab.application.portfolio_specs import PortfolioSpec, SkuSpec
from inventory_lab.domain.supply import ComponentSpec
from inventory_lab.ports.portfolio_optimization import (
    PortfolioOptimizationBounds,
    PortfolioOptimizationResult,
    PortfolioOptimizer,
)
from inventory_lab.simulation.portfolio_engine import PortfolioEngine

_PENALTY_WEIGHT = 100_000.0


def _apply_shared_params(
    spec: PortfolioSpec,
    review_period: int,
    safety_factor: float,
) -> PortfolioSpec:
    """Return a new PortfolioSpec with the shared review period and safety factor
    applied to every SKU's policy.

    Review period
    ~~~~~~~~~~~~~
    The existing schedule (e.g. ``weekly``) is replaced with an ``interval``
    schedule whose ``period_days`` equals ``review_period``.  All SKUs share
    the same cadence so their orders cluster on the same day, maximising the
    consolidation benefit.

    Safety factor
    ~~~~~~~~~~~~~
    ``NormalSafetyStockConfig`` has no fields — it derives everything from
    ``SafetyStockContext``, which is seeded from ``BuildContext.service_level``.
    The cleanest way to scale safety stock without adding a new config field is
    therefore to scale the portfolio's ``target_service_level``:

        effective_sl = clamp( base_sl ** (1 / safety_factor), 0.50, 0.999 )

    A ``safety_factor > 1`` raises effective_sl → higher z-score → more stock.
    A ``safety_factor < 1`` lowers it → leaner stock.
    At ``safety_factor = 1`` the portfolio's own target is used unchanged.

    This is mathematically equivalent to multiplying z by ``safety_factor`` on
    a Normal distribution when the base target is close to 0.95 and the factor
    is near 1, while staying within the valid [0, 1) service-level domain.
    """
    interval_schedule = ComponentSpec(
        kind="interval",
        params={"period_days": float(review_period), "offset_days": 0.0},
    )

    # Scale the service level via the safety factor.
    base_sl: float = float(spec.target_service_level)
    if safety_factor > 0:
        # base_sl^(1/sf): sf>1 → exponent<1 → effective_sl > base_sl
        effective_sl = base_sl ** (1.0 / safety_factor)
    else:
        effective_sl = 0.50
    effective_sl = max(0.50, min(0.999, effective_sl))

    updated_skus: list[SkuSpec] = []
    for sku in spec.skus:
        policy_params: dict = dict(sku.policy.params)

        # Replace schedule with the shared interval.
        policy_params["schedule"] = interval_schedule.model_dump()

        updated_skus.append(
            SkuSpec(
                sku_id=sku.sku_id,
                demand=sku.demand,
                forecast=sku.forecast,
                policy=ComponentSpec(kind=sku.policy.kind, params=policy_params),
                initial_on_hand=sku.initial_on_hand,
                shelf_life_days=sku.shelf_life_days,
            )
        )

    return spec.model_copy(
        update={
            "skus": tuple(updated_skus),
            "target_service_level": effective_sl,
        }
    )


class _PortfolioObjective:
    """Evaluate a single (review_period, safety_factor) point.

    Runs ``replications`` independent ``PortfolioEngine`` simulations and returns
    the mean consolidated total cost plus a penalty for service-level shortfall.
    """

    def __init__(
        self,
        base_spec: PortfolioSpec,
        target_service_level: float,
        replications: int,
    ) -> None:
        self._base_spec = base_spec
        self._target = target_service_level
        self._replications = replications
        self._evaluations = 0

    def __call__(self, x: np.ndarray) -> float:
        self._evaluations += 1
        review_period = round(x[0])
        safety_factor = float(x[1])

        trial_spec = _apply_shared_params(self._base_spec, review_period, safety_factor)
        # Always evaluate with consolidation ON so the optimiser maximises
        # the shared-schedule benefit.
        trial_spec = trial_spec.model_copy(update={"consolidation_enabled": True})

        total_cost = 0.0
        total_fill = 0.0
        n_skus = len(trial_spec.skus)

        for r in range(self._replications):
            seed = self._base_spec.seed + self._evaluations * 997 + r
            run = PortfolioEngine(trial_spec, seed=seed, replication=r).run()
            # Sum consolidated costs across all SKUs for this replication.
            rep_cost = sum(res.kpis.total_cost for res in run.sku_results.values())
            # Subtract the fixed-cost saving already embedded in the KPIs.
            rep_cost -= run.total_fixed_cost_saved
            rep_fill = (
                sum(res.kpis.fill_rate for res in run.sku_results.values()) / n_skus
                if n_skus > 0
                else 0.0
            )
            total_cost += rep_cost
            total_fill += rep_fill

        mean_cost = total_cost / self._replications
        mean_fill = total_fill / self._replications

        shortfall = max(0.0, self._target - mean_fill)
        return mean_cost + _PENALTY_WEIGHT * shortfall

    @property
    def evaluations(self) -> int:
        return self._evaluations


class ScipyPortfolioOptimizer(PortfolioOptimizer):
    """Portfolio optimiser using SciPy Differential Evolution.

    Searches over a mixed integer/continuous space:
    - ``review_period``  — integer (integrality=[True, False])
    - ``safety_factor``  — continuous float

    DE is well-suited here: the objective is stochastic, non-differentiable, and
    has a mixed discrete/continuous domain.
    """

    def optimize(
        self,
        spec: object,
        bounds: PortfolioOptimizationBounds,
        replications_per_eval: int = 5,
        max_evaluations: int = 50,
    ) -> PortfolioOptimizationResult:
        assert isinstance(spec, PortfolioSpec)

        evaluator = _PortfolioObjective(
            base_spec=spec,
            target_service_level=spec.target_service_level,
            replications=replications_per_eval,
        )

        scipy_bounds = Bounds(
            lb=[float(bounds.review_period_min), bounds.safety_factor_min],
            ub=[float(bounds.review_period_max), bounds.safety_factor_max],
            keep_feasible=True,
        )
        integrality = [True, False]

        # popsize × n_params × maxiter ≈ total evaluations
        popsize = 10
        maxiter = max(1, max_evaluations // (popsize * len(integrality)))

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

        best_review_period = round(de_result.x[0])
        best_safety_factor = float(de_result.x[1])

        # ---- High-fidelity final evaluation (20 replications) ---------------
        final_spec = _apply_shared_params(spec, best_review_period, best_safety_factor)
        final_spec = final_spec.model_copy(
            update={"consolidation_enabled": True, "replications": 20}
        )

        total_cost = 0.0
        total_fill = 0.0
        total_saved = 0.0
        n_skus = len(final_spec.skus)

        for r in range(20):
            seed = spec.seed + r
            run = PortfolioEngine(final_spec, seed=seed, replication=r).run()
            rep_cost = sum(res.kpis.total_cost for res in run.sku_results.values())
            rep_cost -= run.total_fixed_cost_saved
            total_cost += rep_cost
            total_fill += (
                sum(res.kpis.fill_rate for res in run.sku_results.values()) / n_skus
                if n_skus > 0
                else 0.0
            )
            total_saved += run.total_fixed_cost_saved

        mean_cost = total_cost / 20
        mean_fill = total_fill / 20
        mean_saved = total_saved / 20

        return PortfolioOptimizationResult(
            best_review_period=best_review_period,
            best_safety_factor=best_safety_factor,
            best_total_cost=mean_cost,
            achieved_fill_rate=mean_fill,
            total_fixed_cost_savings=mean_saved,
            evaluations=evaluator.evaluations,
            replications_per_eval=replications_per_eval,
            success=mean_fill >= spec.target_service_level,
        )
