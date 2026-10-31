"""Optimize (R=7, s, Q) — weekly ordering preset."""

import json
import time

from inventory_lab.application.factory import SimulationFactory
from inventory_lab.application.optimize import OptimizePolicy
from inventory_lab.infrastructure.optimization import ScipyDifferentialEvolutionOptimizer
from inventory_lab.infrastructure.presets import pharmacy_weekly_experiment
from inventory_lab.ports.optimization import OptimizationBounds

spec = pharmacy_weekly_experiment()

# Weekly ordering: R fixed at 7 days, lead time ~4 days.
# s must cover R+L demand (~84-100 units) + safety stock.
# Q is case-pack multiples of 12, typically 2-8 cases (24-96 units).
bounds = OptimizationBounds(
    s_min=20,
    s_max=200,
    Q_min=24,
    Q_max=144,
    R_min=7,
    R_max=7,   # fixed weekly review — optimizer won't move this
)

t0 = time.perf_counter()

result = OptimizePolicy(
    SimulationFactory(spec),
    ScipyDifferentialEvolutionOptimizer(),
).execute(
    spec=spec,
    policy_kind="R_s_Q",
    bounds=bounds,
    replications_per_eval=5,
    max_evaluations=150,
)

elapsed = time.perf_counter() - t0

print(f"Preset          : {spec.name}")
print(f"Best parameters : {result.best_parameters}")
print(f"Total cost      : {result.best_total_cost:,.2f}")
print(f"Fill rate       : {result.achieved_fill_rate:.2%}  (target ≥ {spec.target_service_level:.0%})")
print(f"Ready rate      : {result.achieved_ready_rate:.2%}")
print(f"Evaluations     : {result.evaluations}")
print(f"Converged       : {result.success}")
print(f"Wall time       : {elapsed:.1f} s")
print()
print(json.dumps(result.model_dump(mode="json"), indent=2))
