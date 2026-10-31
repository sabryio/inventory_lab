# src/inventory_lab/application/reporting.py
"""Reporters: same report object, many presentations (OCP + DIP)."""

from __future__ import annotations

import csv
import io
import json

from inventory_lab.application.compare import ComparisonReport
from inventory_lab.domain.base import ValueObject


class JsonReporter:
    def render(self, report: ValueObject) -> str:
        return json.dumps(report.model_dump(mode="json"), indent=2)


class ConsoleReporter:
    """Human-readable comparison table for decision meetings."""

    _COLUMNS = (
        ("total_cost", "Total €", 11, "{:,.0f}"),
        ("holding_cost", "Holding", 10, "{:,.0f}"),
        ("ordering_cost", "Ordering", 9, "{:,.0f}"),
        ("shortage_penalty", "Shortage", 9, "{:,.0f}"),
        ("fill_rate", "Fill %", 8, "{:.2%}"),
        ("ready_rate", "Ready %", 8, "{:.2%}"),
        ("avg_on_hand", "Avg OH", 8, "{:,.1f}"),
        ("orders_placed", "Orders", 7, "{:,.1f}"),
        ("emergency_orders", "EXP", 6, "{:,.1f}"),
    )

    def render(self, report: ValueObject) -> str:
        if not isinstance(report, ComparisonReport):
            raise TypeError("ConsoleReporter expects a ComparisonReport")
        lines = [
            (
                f"Experiment: {report.experiment} | {report.horizon_days} days "
                f"| {report.replications} replications | target fill {report.target_service_level:.1%}"
            ),
            "",
        ]
        header = f"{'#':<3}{'Candidate':<26}{'Policy':<14}"
        header += "".join(f"{label:>{width}}" for _, label, width, _ in self._COLUMNS)
        lines += [header, "-" * len(header)]
        by_name = {c.name: c for c in report.candidates}
        for rank, name in enumerate(report.ranking, start=1):
            candidate = by_name[name]
            flag = " " if candidate.meets_service_target else "*"
            row = f"{rank:<2}{flag}{name[:25]:<26}{candidate.policy_code:<14}"
            for key, _, width, fmt in self._COLUMNS:
                row += f"{fmt.format(candidate.metrics[key].mean):>{width}}"
            lines.append(row)
        lines += [
            "",
            "* = misses the service target (ranked last regardless of cost).",
            "Costs are means over replications; ±95% CI available in the JSON output.",
        ]
        return "\n".join(lines)


class CsvReporter:
    def render(self, report: ValueObject) -> str:
        if not isinstance(report, ComparisonReport):
            raise TypeError("CsvReporter expects a ComparisonReport")
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        metric_keys = list(report.candidates[0].metrics)
        writer.writerow(
            ["candidate", "policy", "meets_target"]
            + [
                f"{k}_{suffix}"
                for k in metric_keys
                for suffix in ("mean", "std", "ci95")
            ]
        )
        for candidate in report.candidates:
            row: list[object] = [
                candidate.name,
                candidate.policy_code,
                candidate.meets_service_target,
            ]
            for key in metric_keys:
                metric = candidate.metrics[key]
                row += [metric.mean, metric.std, metric.ci95_half_width]
            writer.writerow(row)
        return buffer.getvalue()
