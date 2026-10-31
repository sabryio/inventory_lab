"""Optimize (s, Q) with fixed_order_cost derived from Egyptian pharmacist salary.

Salary formula
--------------
    monthly_salary   = monthly_hours * rate_per_monthly_hour
    daily_salary     = monthly_salary / working_days
    hourly_rate      = daily_salary   / hours_per_day
    fixed_order_cost = hourly_rate / 60 * review_minutes

All monetary values are in EGP.
"""

import json
import math
import time

from inventory_lab.application.factory import SimulationFactory
from inventory_lab.application.optimize import OptimizePolicy
from inventory_lab.domain.supply import SupplyLane  # noqa: F401 (used via model_copy)
from inventory_lab.infrastructure.optimization import (
    ScipyDifferentialEvolutionOptimizer,
)
from inventory_lab.infrastructure.presets import pharmacy_daily_experiment
from inventory_lab.ports.optimization import OptimizationBounds
from inventory_lab.simulation.costs import CostModel

# ── salary inputs ──────────────────────────────────────────────────────────
MONTHLY_HOURS = 300  # contractual hours billed per month
RATE_PER_MONTHLY_HOUR = 1_200  # EGP paid per monthly hour
WORKING_DAYS = 26  # working days per month
HOURS_PER_DAY = 12  # working hours per day
REVIEW_MINUTES = 3  # pharmacist review time per order suggestion

# ── derived ordering cost ──────────────────────────────────────────────────
monthly_salary = MONTHLY_HOURS * RATE_PER_MONTHLY_HOUR / WORKING_DAYS  # EGP / month
hourly_rate = monthly_salary / HOURS_PER_DAY  # EGP / hr
fixed_order_cost = hourly_rate / 60 * REVIEW_MINUTES  # EGP / order

print("── Salary breakdown ──────────────────────────────────")
print(
    f"Monthly salary   : EGP {monthly_salary:>12,.0f}  ({MONTHLY_HOURS} hrs × EGP {RATE_PER_MONTHLY_HOUR:,}/hr)"
)
print(f"Hourly rate      : EGP {hourly_rate:>12,.2f}  ÷ {HOURS_PER_DAY} hrs/day")
print(
    f"Per-order cost   : EGP {fixed_order_cost:>12,.2f}  × {REVIEW_MINUTES} min review"
)
print()

# ── unit economics in EGP (1 EUR ≈ 55 EGP) ────────────────────────────────
EUR_TO_EGP = 55.0

UNIT_COST_EGP = 3.20 * EUR_TO_EGP
HOLDING_COST_PER_UNIT_DAY_EGP = 0.015 * EUR_TO_EGP
BACKORDER_PENALTY_EGP = 0.60 * EUR_TO_EGP
LOST_SALE_PENALTY_EGP = 4.00 * EUR_TO_EGP
WASTE_PENALTY_EGP = 3.50 * EUR_TO_EGP

# ── EOQ preview ───────────────────────────────────────────────────────────
annual_demand = 12 * 365
holding_annual = HOLDING_COST_PER_UNIT_DAY_EGP * 365
eoq = math.sqrt(2 * annual_demand * fixed_order_cost / holding_annual)

print("── EOQ preview ───────────────────────────────────────")
print(f"EOQ              : {eoq:.1f} units  (~{eoq / 12:.1f} days of supply)")
print(f"Order cadence    : every {eoq / 12:.1f} days  (~{7 / (eoq / 12):.1f}×/week)")
print()

# ── build spec ────────────────────────────────────────────────────────────
spec = pharmacy_daily_experiment().model_copy(
    update={
        "name": "pharmacy_egy_semi_automated",
        "cost_model": CostModel(
            holding_cost_per_unit_day=HOLDING_COST_PER_UNIT_DAY_EGP,
            backorder_penalty_per_unit_day=BACKORDER_PENALTY_EGP,
            lost_sale_penalty_per_unit=LOST_SALE_PENALTY_EGP,
            waste_penalty_per_unit=WASTE_PENALTY_EGP,
        ),
    }
)
patched_lane = spec.lanes[0].model_copy(
    update={
        "unit_cost": UNIT_COST_EGP,
        "fixed_order_cost": fixed_order_cost,
    }
)
spec = spec.model_copy(update={"lanes": (patched_lane,)})

# ── optimizer bounds centred on EOQ ───────────────────────────────────────
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
