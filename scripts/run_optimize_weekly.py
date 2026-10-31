"""Optimize (R=7, s, Q) — weekly ordering preset. All values in EGP."""

import json
import math
import time

from inventory_lab.application.factory import SimulationFactory
from inventory_lab.application.optimize import OptimizePolicy
from inventory_lab.infrastructure.optimization import (
    ScipyDifferentialEvolutionOptimizer,
)
from inventory_lab.infrastructure.presets import pharmacy_weekly_experiment
from inventory_lab.ports.optimization import OptimizationBounds

# ── salary → fixed_order_cost ─────────────────────────────────────────────
MONTHLY_HOURS = 300
RATE_PER_MONTHLY_HOUR = 1_200  # EGP
WORKING_DAYS = 26
HOURS_PER_DAY = 12
REVIEW_MINUTES = 3

monthly_salary = MONTHLY_HOURS * RATE_PER_MONTHLY_HOUR / WORKING_DAYS
hourly_rate = monthly_salary / (HOURS_PER_DAY * WORKING_DAYS)
fixed_order_cost = hourly_rate / 60 * REVIEW_MINUTES  # EGP / order

# patch preset
spec = pharmacy_weekly_experiment()
patched_lane = spec.lanes[0].model_copy(update={"fixed_order_cost": fixed_order_cost})
spec = spec.model_copy(update={"lanes": (patched_lane,)})

# EOQ preview
annual_demand = 12 * 365
holding_annual = spec.cost_model.holding_cost_per_unit_day * 365
eoq = math.sqrt(2 * annual_demand * fixed_order_cost / holding_annual)

print(f"Per-order cost   : EGP {fixed_order_cost:,.2f}")
print(f"EOQ preview      : {eoq:.1f} units  (~{eoq / 12:.1f} days of supply)")
print()

# Weekly ordering: R fixed at 7 days, lead time ~4 days.
# s covers (R+L) demand = 11 days × 12 units + safety stock.
bounds = OptimizationBounds(
    s_min=20,
    s_max=250,
    Q_min=24,
    Q_max=max(144, int(eoq * 2)),
    R_min=7,
    R_max=7,
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

print(f"Preset           : {spec.name}")
print(f"Best parameters  : {result.best_parameters}")
print(f"Total cost       : EGP {result.best_total_cost:,.0f}")
print(
    f"Fill rate        : {result.achieved_fill_rate:.2%}  (target ≥ {spec.target_service_level:.0%})"
)
print(f"Ready rate       : {result.achieved_ready_rate:.2%}")
print(f"Evaluations      : {result.evaluations}")
print(f"Converged        : {result.success}")
print(f"Wall time        : {elapsed:.1f} s")
print()
print(json.dumps(result.model_dump(mode="json"), indent=2))
