"""Run the 10-SKU portfolio comparison with salary-derived fixed_order_cost.

All monetary values are natively in EGP — no conversion factors anywhere.
"""

import math

from inventory_lab.application.portfolio_compare import ComparePortfolioStrategies
from inventory_lab.infrastructure.portfolio_presets import pharmacy_portfolio_experiment

# ── salary → fixed_order_cost ─────────────────────────────────────────────
MONTHLY_HOURS = 300
RATE_PER_MONTHLY_HOUR = 1_200  # EGP
WORKING_DAYS = 26
HOURS_PER_DAY = 12
REVIEW_MINUTES = 3

monthly_salary = MONTHLY_HOURS * RATE_PER_MONTHLY_HOUR / WORKING_DAYS
hourly_rate = monthly_salary / (HOURS_PER_DAY * WORKING_DAYS)
fixed_order_cost = hourly_rate / 60 * REVIEW_MINUTES  # EGP / order

print("── Salary breakdown ──────────────────────────────────────────────")
print(
    f"Monthly salary   : EGP {monthly_salary:>12,.0f}  "
    f"({MONTHLY_HOURS} hrs × EGP {RATE_PER_MONTHLY_HOUR:,}/hr)"
)
print(f"Hourly rate      : EGP {hourly_rate:>12,.2f}  ÷ {HOURS_PER_DAY} hrs/day")
print(
    f"Per-order cost   : EGP {fixed_order_cost:>12,.2f}  × {REVIEW_MINUTES} min review"
)
print()

# ── patch preset: replace fixed_order_cost with salary-derived value ──────
base_spec = pharmacy_portfolio_experiment(replications=5, horizon_days=365)

patched_lane = base_spec.lanes[0].model_copy(
    update={"fixed_order_cost": fixed_order_cost}
)
spec = base_spec.model_copy(
    update={
        "name": "pharmacy_portfolio_egy",
        "lanes": (patched_lane,),
    }
)

# ── EOQ preview ───────────────────────────────────────────────────────────
representative_demand = 15.0
annual_demand = representative_demand * 365
holding_annual = spec.cost_model.holding_cost_per_unit_day * 365
eoq = math.sqrt(2 * annual_demand * fixed_order_cost / holding_annual)

print("── EOQ preview (representative SKU, 15 units/day) ────────────────")
print(
    f"EOQ              : {eoq:.1f} units  (~{eoq / representative_demand:.1f} days of supply)"
)
print(f"Order cadence    : every {eoq / representative_demand:.1f} days")
print()

# ── run ───────────────────────────────────────────────────────────────────
result = ComparePortfolioStrategies().execute(spec)

sep = "=" * 68
print(sep)
print(f"Portfolio: {result.experiment}")
print(
    f"SKUs: {result.n_skus}  |  Replications: {result.replications}"
    f"  |  Horizon: {result.horizon_days}d"
)
print(sep)
print()
print(
    f"{'SKU':<12} {'Fill':>7} {'Ready':>7} {'Avg OH':>8}"
    f" {'Orders':>7} {'Cost (EGP)':>12} {'OK':>4}"
)
print("-" * 68)

for s in result.sku_summaries:
    ok = "✓" if s.meets_service_target else "✗"
    print(
        f"{s.sku_id:<12} {s.mean_fill_rate:>7.1%}"
        f" {s.mean_ready_rate:>7.1%}"
        f" {s.mean_avg_on_hand:>8.1f}"
        f" {s.mean_orders_placed:>7.1f}"
        f" {s.mean_total_cost:>12,.0f}"
        f" {ok:>4}"
    )

print("-" * 68)
print()
print(f"Total cost (independent):  EGP {result.total_cost_independent:>12,.0f}")
print(f"Total cost (consolidated): EGP {result.total_cost_consolidated:>12,.0f}")
print(
    f"Fixed-cost saving:         EGP {result.fixed_cost_saved:>12,.0f}"
    f"  ({result.savings_pct:.1f}%)"
)
print()
print(f"Portfolio fill rate  : {result.portfolio_fill_rate:.2%}")
print(f"All SKUs meet target : {'Yes' if result.all_skus_meet_target else 'No'}")
print(sep)
