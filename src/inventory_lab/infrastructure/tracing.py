# src/inventory_lab/infrastructure/tracing.py
"""Trace sinks: Null Object keeps the engine free of `if tracing` branches."""

from __future__ import annotations

from inventory_lab.ports.reporting import TraceRecord


class NullTraceSink:
    def record(self, record: TraceRecord) -> None:
        return None


class InMemoryTraceSink:
    def __init__(self, limit: int = 20_000) -> None:
        self._records: list[TraceRecord] = []
        self._limit = limit

    def record(self, record: TraceRecord) -> None:
        if len(self._records) < self._limit:
            self._records.append(record)

    @property
    def records(self) -> tuple[TraceRecord, ...]:
        return tuple(self._records)
