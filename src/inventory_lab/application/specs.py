# src/inventory_lab/application/specs.py
"""The validated, declarative experiment contract."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Self

from pydantic import Field, model_validator

from inventory_lab.domain.base import PositiveInt, Probability, ValueObject
from inventory_lab.domain.inventory import ShortageMode
from inventory_lab.domain.supply import ComponentSpec, SupplyLane
from inventory_lab.simulation.costs import CostModel


class CandidateSpec(ValueObject):
    name: str = Field(min_length=1)
    policy: ComponentSpec


class ExperimentSpec(ValueObject):
    name: str = "experiment"
    start_date: datetime = datetime(2026, 1, 5, tzinfo=UTC)  # a Monday
    horizon_days: PositiveInt = 365
    warmup_days: int = 30
    replications: PositiveInt = 10
    seed: int = 42
    shortage_mode: ShortageMode = ShortageMode.BACKORDER
    initial_on_hand: int = 120
    target_service_level: Probability = 0.97
    collect_trace: bool = False
    cost_model: CostModel = CostModel()
    demand: ComponentSpec
    forecast: ComponentSpec
    lanes: tuple[SupplyLane, ...]
    candidates: tuple[CandidateSpec, ...]

    @model_validator(mode="after")
    def _validate_experiment(self) -> Self:
        if not self.lanes:
            raise ValueError("at least one supply lane is required")
        if len({lane.lane_id for lane in self.lanes}) != len(self.lanes):
            raise ValueError("lane_id values must be unique")
        if not self.candidates:
            raise ValueError("at least one candidate policy is required")
        if len({c.name for c in self.candidates}) != len(self.candidates):
            raise ValueError("candidate names must be unique")
        if self.warmup_days >= self.horizon_days:
            raise ValueError("warmup_days must be smaller than horizon_days")
        return self
