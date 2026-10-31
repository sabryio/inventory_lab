"""Output ports: the application never knows whether it prints, writes JSON, or streams."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable

from inventory_lab.domain.base import ValueObject


class TraceRecord(ValueObject):
    time: float
    policy_code: str
    net_inventory: int
    safety_stock: float
    reorder_point: float | None
    order_up_to_level: float | None
    order_quantity: float | None
    ordered: int
    lane_id: str | None
    rationale: str


@runtime_checkable
class TraceSink(Protocol):
    def record(self, record: TraceRecord) -> None: ...


class Reporter(ABC):
    @abstractmethod
    def render(self, report: ValueObject) -> str: ...
