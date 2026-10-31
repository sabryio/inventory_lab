"""Use case: compare candidate policies with common random numbers and CIs."""

from __future__ import annotations

from math import sqrt
from statistics import mean, stdev

from inventory_lab.application.factory import SimulationFactory
from inventory_lab.application.specs import ExperimentSpec
from inventory_lab.domain.base import ValueObject
from inventory_lab.simulation.result import SimulationResult


class MetricSummary(ValueObject):
    mean: float
    std: float
    ci95_half_width: float


class CandidateReport(ValueObject):
    name: str
    policy_code: str
    replications: int
    metrics: dict[str, MetricSummary]
    meets_service_target: bool
    results: tuple[SimulationResult, ...] = ()


class ComparisonReport(ValueObject):
    experiment: str
    horizon_days: int
    replications: int
    target_service_level: float
    candidates: tuple[CandidateReport, ...]
    ranking: tuple[str, ...]
    """Cost-ascending among service-compliant candidates, then the non-compliant ones."""


_METRICS: tuple[tuple[str, str], ...] = (
    ("total_cost", "total_cost"),
    ("holding_cost", "costs.holding"),
    ("ordering_cost", "costs.ordering"),
    ("purchasing_cost", "costs.purchasing"),
    ("shortage_penalty", "costs.backorder_penalty"),
    ("lost_sales_penalty", "costs.lost_sales_penalty"),
    ("fill_rate", "fill_rate"),
    ("ready_rate", "ready_rate"),
    ("avg_on_hand", "avg_on_hand"),
    ("stockout_days", "stockout_days"),
    ("orders_placed", "orders_placed"),
    ("emergency_orders", "emergency_orders_placed"),
    ("units_lost", "units_lost"),
    ("inventory_turns", "inventory_turns"),
)


def _extract(kpis, path: str) -> float:
    value = kpis
    for part in path.split("."):
        value = getattr(value, part)
    return float(value)


def _summarise(values: list[float]) -> MetricSummary:
    mu = mean(values)
    sigma = stdev(values) if len(values) > 1 else 0.0
    half = 1.96 * sigma / sqrt(len(values)) if len(values) > 1 else 0.0
    return MetricSummary(mean=mu, std=sigma, ci95_half_width=half)


class ComparePolicies:
    """Single responsibility: run the experiment matrix and aggregate. No printing."""

    def __init__(self, factory: SimulationFactory) -> None:
        self._factory = factory

    def execute(
        self, spec: ExperimentSpec, *, keep_replications: bool = False
    ) -> ComparisonReport:
        reports: list[CandidateReport] = []
        for candidate in spec.candidates:
            runs = [
                self._factory.create_engine(candidate, spec.seed + r, r).run()
                for r in range(spec.replications)
            ]
            metrics = {
                label: _summarise([_extract(run.kpis, path) for run in runs])
                for label, path in _METRICS
            }
            compliant = metrics["fill_rate"].mean >= spec.target_service_level
            reports.append(
                CandidateReport(
                    name=candidate.name,
                    policy_code=runs[0].policy_code,
                    replications=len(runs),
                    metrics=metrics,
                    meets_service_target=compliant,
                    results=tuple(runs) if keep_replications else (),
                )
            )

        ranking = tuple(
            c.name
            for c in sorted(
                reports,
                key=lambda c: (
                    not c.meets_service_target,
                    c.metrics["total_cost"].mean,
                ),
            )
        )
        return ComparisonReport(
            experiment=spec.name,
            horizon_days=spec.horizon_days,
            replications=spec.replications,
            target_service_level=spec.target_service_level,
            candidates=tuple(reports),
            ranking=ranking,
        )
