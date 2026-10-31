"""Optimize (R=7, s, Q) — all parameters derived from CSV data.

Inputs
------
data/medicines.csv      — per-SKU product master (unit cost, packaging, shelf life, etc.)
data/sales_history.csv  — daily dispensing history
data/purchase_history.csv — purchase orders with timestamps for lead-time calculation

Only pharmacy-level constants remain hardcoded below (salary structure and
capital cost rate). Every per-SKU parameter is read from the data files.

All monetary values are in EGP.
"""

from __future__ import annotations

import csv
import json
import math
import time
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from statistics import mean, median, stdev

from inventory_lab.application.factory import SimulationFactory
from inventory_lab.application.optimize import OptimizePolicy
from inventory_lab.application.specs import CandidateSpec, ExperimentSpec
from inventory_lab.domain.supply import ComponentSpec, LaneKind, SupplyLane
from inventory_lab.infrastructure.optimization import (
    ScipyDifferentialEvolutionOptimizer,
)
from inventory_lab.ports.optimization import OptimizationBounds
from inventory_lab.simulation.costs import CostModel

# ── pharmacy-level constants (not per-SKU) ────────────────────────────────
SALES_CSV = Path(__file__).parent.parent / "data" / "sales_history.csv"
PURCHASE_CSV = Path(__file__).parent.parent / "data" / "purchase_history.csv"
MEDICINES_CSV = Path(__file__).parent.parent / "data" / "medicines.csv"

SKU_ID = "SKU-001"  # ← change to optimise a different medicine

# pharmacist salary (used to derive fixed_order_cost)
MONTHLY_HOURS = 300
RATE_PER_MONTHLY_HOUR = 1_200  # EGP
WORKING_DAYS = 26
HOURS_PER_DAY = 12
REVIEW_MINUTES = 3  # minutes per order review

# capital cost rate (financing + storage + insurance)
CAPITAL_RATE_PER_YEAR = 0.25  # 25 % / year applied to unit_cost

# fallback lead time when purchase history is thin
LEAD_TIME_MEAN_FALLBACK = 4.0
LEAD_TIME_STD_FALLBACK = 1.2
MIN_LEAD_TIME_SAMPLES = 5

# optimizer budget
REPLICATIONS_PER_EVAL = 5
MAX_EVALUATIONS = 150
HORIZON_DAYS = 365
REPLICATIONS = 10

# ── salary → fixed_order_cost ─────────────────────────────────────────────
monthly_salary = MONTHLY_HOURS * RATE_PER_MONTHLY_HOUR / WORKING_DAYS
hourly_rate = monthly_salary / (HOURS_PER_DAY * WORKING_DAYS)
fixed_order_cost = hourly_rate / 60 * REVIEW_MINUTES  # EGP / order


# ── loaders ───────────────────────────────────────────────────────────────


def load_medicine(path: Path, sku_id: str) -> dict[str, str]:
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row["sku_id"].strip() == sku_id:
                return {k.strip(): v.strip() for k, v in row.items()}
    raise ValueError(f"SKU {sku_id!r} not found in {path}")


def load_daily_sales(path: Path, sku_id: str) -> list[int]:
    """Dense daily series with zeros filled for missing days."""
    rows: dict[str, int] = defaultdict(int)
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row["sku_id"].strip() == sku_id:
                rows[row["date"].strip()] += int(row["units_sold"])
    if not rows:
        raise ValueError(f"SKU {sku_id!r} not found in {path}")
    dates = sorted(rows)
    first, last = date.fromisoformat(dates[0]), date.fromisoformat(dates[-1])
    full: list[int] = []
    cur = first
    while cur <= last:
        full.append(rows.get(str(cur), 0))
        cur += timedelta(days=1)
    return full


def load_lead_times(path: Path, sku_id: str) -> list[float]:
    """Fractional-day lead times from order/receipt timestamps.

    Accepts order_datetime/receipt_datetime (with time) or
    order_date/receipt_date (date-only = midnight). Negative values skipped.
    """

    def _parse(s: str) -> datetime:
        s = s.strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(s, fmt).replace(tzinfo=UTC)
            except ValueError:
                continue
        raise ValueError(f"unrecognised datetime: {s!r}")

    lead_times: list[float] = []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        headers = reader.fieldnames or []
        oc = "order_datetime" if "order_datetime" in headers else "order_date"
        rc = "receipt_datetime" if "receipt_datetime" in headers else "receipt_date"
        for row in reader:
            if row["sku_id"].strip() != sku_id:
                continue
            delta = (_parse(row[rc]) - _parse(row[oc])).total_seconds() / 86_400
            if delta >= 0:
                lead_times.append(round(delta, 4))
    return lead_times


# ── load data ─────────────────────────────────────────────────────────────
medicine = load_medicine(MEDICINES_CSV, SKU_ID)
history = load_daily_sales(SALES_CSV, SKU_ID)
lead_times = load_lead_times(PURCHASE_CSV, SKU_ID)

mean_daily = mean(history)
std_daily = stdev(history) if len(history) > 1 else mean_daily * 0.3

# ── derive all per-SKU parameters from medicines.csv ──────────────────────
unit_cost_egp = float(medicine["unit_cost_egp"])
order_multiple = int(medicine["order_multiple"])
min_order_qty = int(medicine["min_order_qty"])
shelf_life_days = float(medicine["shelf_life_days"])
service_level = float(medicine["service_level"])
markup_rate = float(medicine["markup_rate"])
disposal_rate = float(medicine["disposal_rate"])

# holding cost: capital rate applied to what you paid for each unit
holding_cost_per_unit_day = unit_cost_egp * CAPITAL_RATE_PER_YEAR / 365

# backorder penalty: each day a patient waits costs you the daily margin
backorder_penalty_per_unit_day = unit_cost_egp * markup_rate / 365

# lost sale penalty: you lose the full margin when a patient walks out
lost_sale_penalty_per_unit = unit_cost_egp * markup_rate

# waste penalty: you paid for the unit plus disposal overhead
waste_penalty_per_unit = unit_cost_egp * (1.0 + disposal_rate)

# warmup: long enough for the replenishment pipeline to stabilise
lt_mean = (
    mean(lead_times)
    if len(lead_times) >= MIN_LEAD_TIME_SAMPLES
    else LEAD_TIME_MEAN_FALLBACK
)
warmup_days = max(int(lt_mean * 3), 14)

# ── lead time spec ────────────────────────────────────────────────────────
if len(lead_times) >= MIN_LEAD_TIME_SAMPLES:
    lt_mean = mean(lead_times)
    lt_std = stdev(lead_times) if len(lead_times) > 1 else 0.0
    lead_time_spec = ComponentSpec(
        kind="empirical", params={"samples_days": lead_times}
    )
    lt_source = f"empirical ({len(lead_times)} orders)"
else:
    lt_mean = LEAD_TIME_MEAN_FALLBACK
    lt_std = LEAD_TIME_STD_FALLBACK
    lead_time_spec = ComponentSpec(
        kind="normal", params={"mean_days": lt_mean, "std_days": lt_std}
    )
    lt_source = f"fallback (only {len(lead_times)} orders found)"

warmup_days = max(int(lt_mean * 3), 14)

# ── EOQ preview ───────────────────────────────────────────────────────────
holding_annual = holding_cost_per_unit_day * 365
eoq = math.sqrt(2 * mean_daily * 365 * fixed_order_cost / holding_annual)

# ── print summary ─────────────────────────────────────────────────────────
W = 54
print("─" * W)
print(f" Medicine        : {medicine['name']}")
print(f" Generic         : {medicine['generic_name']}")
print(f" Form / Strength : {medicine['form']} {medicine['strength']}")
print(f" Supplier        : {medicine['supplier']}")
print(f" Category        : {medicine['category']}")
print("─" * W)
print(f" Unit cost       : EGP {unit_cost_egp:>10,.2f}")
print(
    f" Holding/day     : EGP {holding_cost_per_unit_day:>10,.4f}  ({CAPITAL_RATE_PER_YEAR:.0%}/yr ÷ 365)"
)
print(
    f" Backorder/day   : EGP {backorder_penalty_per_unit_day:>10,.4f}  ({markup_rate:.0%} markup ÷ 365)"
)
print(
    f" Lost sale       : EGP {lost_sale_penalty_per_unit:>10,.2f}  ({markup_rate:.0%} markup)"
)
print(
    f" Waste           : EGP {waste_penalty_per_unit:>10,.2f}  (cost + {disposal_rate:.0%} disposal)"
)
print(f" Order multiple  : {order_multiple}")
print(f" Min order qty   : {min_order_qty}")
print(f" Shelf life      : {shelf_life_days:.0f} days")
print(f" Service target  : {service_level:.0%}")
print("─" * W)
print(f" Sales history   : {len(history)} days")
print(f" Mean daily      : {mean_daily:.1f} units   Std: {std_daily:.1f}")
print("─" * W)
print(f" Lead time source: {lt_source}")
if lead_times:
    print(
        f" Min/Med/Max     : {min(lead_times):.2f} / {median(lead_times):.2f} / {max(lead_times):.2f} days"
    )
print(f" Mean            : {lt_mean:.2f} days   Std: {lt_std:.2f}")
print(f" Warmup period   : {warmup_days} days  (derived: 3 × lt_mean)")
print("─" * W)
print(f" Salary/hr       : EGP {hourly_rate:>10,.2f}")
print(
    f" Per-order cost  : EGP {fixed_order_cost:>10,.2f}  ({REVIEW_MINUTES} min review)"
)
print("─" * W)
print(f" EOQ             : {eoq:.1f} units  (~{eoq / mean_daily:.1f} days of supply)")
print(f" Order cadence   : every {eoq / mean_daily:.1f} days")
print("─" * W)
print()

# ── build spec ────────────────────────────────────────────────────────────
weekly = ComponentSpec(kind="weekly", params={"weekdays": [4], "hour": 18})
lane_id = "wholesaler"

spec = ExperimentSpec(
    name=f"opt_{SKU_ID}_{medicine['name'].replace(' ', '_')}",
    horizon_days=HORIZON_DAYS,
    warmup_days=warmup_days,
    replications=REPLICATIONS,
    initial_on_hand=int(mean_daily * (lt_mean + 7)),
    target_service_level=service_level,
    shelf_life_days=shelf_life_days,
    cost_model=CostModel(
        holding_cost_per_unit_day=holding_cost_per_unit_day,
        backorder_penalty_per_unit_day=backorder_penalty_per_unit_day,
        lost_sale_penalty_per_unit=lost_sale_penalty_per_unit,
        waste_penalty_per_unit=waste_penalty_per_unit,
    ),
    demand=ComponentSpec(
        kind="empirical",
        params={"history": history, "bootstrap": True},
    ),
    forecast=ComponentSpec(
        kind="rolling",
        params={
            "prior_mean": round(mean_daily, 2),
            "prior_std": round(std_daily, 2),
            "window_days": min(90, len(history)),
        },
    ),
    lanes=(
        SupplyLane(
            lane_id=lane_id,
            kind=LaneKind.REGULAR,
            lead_time=lead_time_spec,
            unit_cost=unit_cost_egp,
            fixed_order_cost=fixed_order_cost,
            order_multiple=order_multiple,
            min_order_quantity=min_order_qty,
        ),
    ),
    candidates=(
        CandidateSpec(
            name="weekly_RsQ",
            policy=ComponentSpec(
                kind="R_s_Q",
                params={
                    "lane_id": lane_id,
                    "schedule": weekly.model_dump(),
                    "parameters": {
                        "kind": "statistical",
                        "params": {
                            "safety": {"kind": "normal"},
                            "sizing": {
                                "kind": "rounded",
                                "params": {
                                    "inner": {"kind": "eoq"},
                                    "multiple": order_multiple,
                                    "minimum": min_order_qty,
                                },
                            },
                        },
                    },
                },
            ),
        ),
    ),
)

# ── optimizer bounds ──────────────────────────────────────────────────────
protection_demand = mean_daily * (7 + lt_mean)

bounds = OptimizationBounds(
    s_min=int(protection_demand * 0.5),
    s_max=int(protection_demand * 2.5),
    Q_min=min_order_qty,
    Q_max=max(min_order_qty * 6, int(eoq * 2)),
    R_min=7,
    R_max=7,
)

# ── run ───────────────────────────────────────────────────────────────────
t0 = time.perf_counter()

result = OptimizePolicy(
    SimulationFactory(spec),
    ScipyDifferentialEvolutionOptimizer(),
).execute(
    spec=spec,
    policy_kind="R_s_Q",
    bounds=bounds,
    replications_per_eval=REPLICATIONS_PER_EVAL,
    max_evaluations=MAX_EVALUATIONS,
)

elapsed = time.perf_counter() - t0

print("── Result ────────────────────────────────────────────")
print(f"Best parameters  : {result.best_parameters}")
print(f"Total cost       : EGP {result.best_total_cost:>12,.0f}")
print(
    f"Fill rate        : {result.achieved_fill_rate:.2%}  "
    f"(target ≥ {service_level:.0%})"
)
print(f"Ready rate       : {result.achieved_ready_rate:.2%}")
print(f"Evaluations      : {result.evaluations}")
print(f"Converged        : {result.success}")
print(f"Wall time        : {elapsed:.1f} s")
print()
print(json.dumps(result.model_dump(mode="json"), indent=2))
