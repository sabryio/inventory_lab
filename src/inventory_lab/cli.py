# src/inventory_lab/cli.py
"""Thin adapter: parse args, delegate to a use case, hand the result to a reporter."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from inventory_lab.application.compare import ComparePolicies
from inventory_lab.application.factory import SimulationFactory
from inventory_lab.application.reporting import (
    ConsoleReporter,
    CsvReporter,
    JsonReporter,
)
from inventory_lab.application.specs import ExperimentSpec
from inventory_lab.domain.errors import InventoryLabError
from inventory_lab.domain.planning import SafetyStockContext
from inventory_lab.infrastructure.config_loader import load_experiment
from inventory_lab.infrastructure.presets import pharmacy_experiment
from inventory_lab.safety_stock.normal import NormalSafetyStock

_REPORTERS = {"console": ConsoleReporter, "json": JsonReporter, "csv": CsvReporter}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="inventory-lab", description="Inventory policy laboratory"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    compare = sub.add_parser(
        "compare", help="Compare policies over Monte-Carlo replications"
    )
    compare.add_argument(
        "--config",
        type=Path,
        help="JSON/YAML experiment file (default: pharmacy preset)",
    )
    compare.add_argument("--replications", type=int, default=None)
    compare.add_argument("--horizon", type=int, default=None)
    compare.add_argument("--seed", type=int, default=None)
    compare.add_argument(
        "--trace", action="store_true", help="Record safety-stock/decision trace"
    )
    compare.add_argument("--format", choices=tuple(_REPORTERS), default="console")
    compare.add_argument(
        "--out", type=Path, help="Write output to a file instead of stdout"
    )

    safety = sub.add_parser(
        "safety-stock", help="Analytic safety stock for given uncertainty"
    )
    safety.add_argument("--mean-daily", type=float, required=True)
    safety.add_argument("--std-daily", type=float, required=True)
    safety.add_argument("--lead-time", type=float, required=True)
    safety.add_argument("--lead-time-std", type=float, default=0.0)
    safety.add_argument("--review-period", type=float, default=0.0)
    safety.add_argument("--service-level", type=float, default=0.97)

    sub.add_parser("components", help="List registered component kinds")

    optimize = sub.add_parser(
        "optimize",
        help="Find optimal (s,Q) or (R,s,Q) parameters via simulation search",
    )
    optimize.add_argument(
        "--policy",
        choices=["s_Q", "R_s_Q", "R_s_S"],
        required=True,
        help="Policy type to optimize",
    )
    optimize.add_argument(
        "--config",
        type=Path,
        help="JSON/YAML experiment file (default: pharmacy preset)",
    )
    optimize.add_argument(
        "--replications",
        type=int,
        default=5,
        help="Replications per evaluation — more = slower but more accurate (default: 5)",
    )
    optimize.add_argument(
        "--max-evals",
        type=int,
        default=100,
        help="Maximum number of objective evaluations (default: 100)",
    )
    optimize.add_argument("--s-min", type=int, default=1, metavar="S_MIN")
    optimize.add_argument("--s-max", type=int, default=500, metavar="S_MAX")
    optimize.add_argument("--Q-min", type=int, default=1, metavar="Q_MIN")
    optimize.add_argument("--Q-max", type=int, default=1000, metavar="Q_MAX")
    optimize.add_argument(
        "--R-min",
        type=int,
        default=1,
        metavar="R_MIN",
        help="Min review period in days (R_s_Q / R_s_S only)",
    )
    optimize.add_argument(
        "--R-max",
        type=int,
        default=30,
        metavar="R_MAX",
        help="Max review period in days (R_s_Q / R_s_S only)",
    )
    optimize.add_argument("--format", choices=("json", "console"), default="json")
    optimize.add_argument("--out", type=Path, help="Write result to a file")

    return parser


def _resolve_spec(args: argparse.Namespace) -> ExperimentSpec:
    spec = load_experiment(args.config) if args.config else pharmacy_experiment()
    overrides = {
        key: value
        for key, value in (
            ("replications", args.replications),
            ("horizon_days", args.horizon),
            ("seed", args.seed),
            ("collect_trace", True if args.trace else None),
        )
        if value is not None
    }
    return spec.model_copy(update=overrides) if overrides else spec


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "compare":
            spec = _resolve_spec(args)
            report = ComparePolicies(SimulationFactory(spec)).execute(spec)
            rendered = _REPORTERS[args.format]().render(report)
        elif args.command == "optimize":
            from inventory_lab.application.optimize import OptimizePolicy
            from inventory_lab.infrastructure.optimization import (
                ScipyDifferentialEvolutionOptimizer,
            )
            from inventory_lab.ports.optimization import OptimizationBounds

            spec = (
                load_experiment(args.config) if args.config else pharmacy_experiment()
            )
            bounds = OptimizationBounds(
                s_min=args.s_min,
                s_max=args.s_max,
                Q_min=args.Q_min,
                Q_max=args.Q_max,
                R_min=args.R_min,
                R_max=args.R_max,
            )
            result = OptimizePolicy(
                SimulationFactory(spec),
                ScipyDifferentialEvolutionOptimizer(),
            ).execute(
                spec=spec,
                policy_kind=args.policy,
                bounds=bounds,
                replications_per_eval=args.replications,
                max_evaluations=args.max_evals,
            )
            rendered = (
                result.model_dump_json(indent=2)
                if args.format == "json"
                else (
                    f"policy_kind      : {result.policy_kind}\n"
                    f"best_parameters  : {result.best_parameters}\n"
                    f"best_total_cost  : {result.best_total_cost:,.2f}\n"
                    f"achieved_fill    : {result.achieved_fill_rate:.2%}\n"
                    f"achieved_ready   : {result.achieved_ready_rate:.2%}\n"
                    f"evaluations      : {result.evaluations}\n"
                    f"success          : {result.success}"
                )
            )
        elif args.command == "safety-stock":
            result = NormalSafetyStock().compute(
                SafetyStockContext(
                    mean_daily_demand=args.mean_daily,
                    daily_demand_std=args.std_daily,
                    lead_time_mean_days=args.lead_time,
                    lead_time_std_days=args.lead_time_std,
                    review_period_days=args.review_period,
                    cycle_service_level=args.service_level,
                )
            )
            rendered = result.model_dump_json(indent=2)
        else:
            from inventory_lab.planning.sizing import sizing_registry
            from inventory_lab.policies.factories import policy_registry
            from inventory_lab.policies.schedules import schedule_registry
            from inventory_lab.safety_stock.normal import safety_stock_registry
            from inventory_lab.simulation.demand import demand_registry
            from inventory_lab.sourcing.lead_time import lead_time_registry

            rendered = "\n".join(
                f"{name}: {', '.join(reg.kinds)}"
                for name, reg in (
                    ("policy", policy_registry),
                    ("schedule", schedule_registry),
                    ("parameters/safety_stock", safety_stock_registry),
                    ("lot_sizing", sizing_registry),
                    ("demand", demand_registry),
                    ("lead_time", lead_time_registry),
                )
            )
    except InventoryLabError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if getattr(args, "out", None):
        args.out.write_text(rendered, encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
