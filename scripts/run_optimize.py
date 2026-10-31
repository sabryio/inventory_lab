"""Optimize (s, Q) — daily ordering preset. All values in EGP."""

import json
import math
import time

from inventory_lab.application.factory import SimulationFactory
from inventory_lab.application.optimize import OptimizePolicy
from inventory_lab.infrastructure.optimization import (
    ScipyDifferentialEvolutionOptimizer,
)
from inventory_lab.infrastructure.presets import pharmacy_daily_experiment
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

print("── Salary breakdown ──────────────────────────────────")
print(f"Monthly salary   : EGP {monthly_salary:>12,.0f}")
print(f"Hourly rate      : EGP {hourly_rate:>12,.2f}/hr")
print(f"Per-order cost   : EGP {fixed_order_cost:>12,.2f}")
print()

# ── patch the daily preset's lane with salary-derived FOC ────────────────
spec = pharmacy_daily_experiment()
patched_lane = spec.lanes[0].model_copy(update={"fixed_order_cost": fixed_order_cost})
spec = spec.model_copy(update={"lanes": (patched_lane,)})

# ── EOQ preview ───────────────────────────────────────────────────────────
annual_demand = 12 * 365
holding_annual = spec.cost_model.holding_cost_per_unit_day * 365
eoq = math.sqrt(2 * annual_demand * fixed_order_cost / holding_annual)

print("── EOQ preview ───────────────────────────────────────")
print(f"EOQ              : {eoq:.1f} units  (~{eoq / 12:.1f} days of supply)")
print(f"Order cadence    : every {eoq / 12:.1f} days")
print()

# ── bounds centred on EOQ ─────────────────────────────────────────────────
bounds = OptimizationBounds(
    s_min=1,
    s_max=50,
    Q_min=1,
    Q_max=max(24, int(eoq * 4)),
)

# ── run ───────────────────────────────────────────────────────────────────
t0 = time.perf_counter()

result = OptimizePolicy(
    SimulationFactory(spec),
    ScipyDifferentialEvolutionOptimizer(),
).execute(
    spec=spec,
    policy_kind="s_Q",
    bounds=bounds,
    replications_per_eval=5,
    max_evaluations=150,
)

elapsed = time.perf_counter() - t0

print("── Result ────────────────────────────────────────────")
print(f"Best parameters  : {result.best_parameters}")
print(f"Total cost       : EGP {result.best_total_cost:>12,.0f}")
print(
    f"Fill rate        : {result.achieved_fill_rate:.2%}  (target ≥ {spec.target_service_level:.0%})"
)
print(f"Ready rate       : {result.achieved_ready_rate:.2%}")
print(f"Evaluations      : {result.evaluations}")
print(f"Converged        : {result.success}")
print(f"Wall time        : {elapsed:.1f} s")
print()
print(json.dumps(result.model_dump(mode="json"), indent=2))
