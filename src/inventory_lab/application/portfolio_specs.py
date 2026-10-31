"""Portfolio-level specification: multiple SKUs sharing one or more supplier lanes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Self

from pydantic import Field, model_validator

from inventory_lab.domain.base import PositiveInt, Probability, ValueObject
from inventory_lab.domain.inventory import ShortageMode
from inventory_lab.domain.supply import ComponentSpec, SupplyLane
from inventory_lab.simulation.costs import CostModel


class SkuSpec(ValueObject):
    """Configuration for a single SKU within a portfolio."""

    sku_id: str = Field(min_length=1)
    demand: ComponentSpec
    forecast: ComponentSpec
    policy: ComponentSpec
    initial_on_hand: PositiveInt = 100
    shelf_life_days: float = Field(default=9_999.0, gt=0)


class PortfolioSpec(ValueObject):
    """A portfolio of SKUs sharing one or more supplier lanes.

    When multiple SKUs need ordering from the same lane at the same review, they
    can be consolidated into a single shipment — paying the fixed cost only once.
    """

    name: str = "portfolio"
    start_date: datetime = datetime(2026, 1, 5, tzinfo=UTC)
    horizon_days: PositiveInt = 365
    warmup_days: int = 30
    replications: PositiveInt = 10
    seed: int = 42
    shortage_mode: ShortageMode = ShortageMode.BACKORDER
    target_service_level: Probability = 0.95
    collect_trace: bool = False
    cost_model: CostModel = CostModel()
    lanes: tuple[SupplyLane, ...]
    skus: tuple[SkuSpec, ...]
    consolidation_enabled: bool = True

    @model_validator(mode="after")
    def _validate_portfolio(self) -> Self:
        if not self.lanes:
            raise ValueError("at least one supply lane is required")
        if len({lane.lane_id for lane in self.lanes}) != len(self.lanes):
            raise ValueError("lane_id values must be unique")
        if not self.skus:
            raise ValueError("at least one SKU is required")
        if len({sku.sku_id for sku in self.skus}) != len(self.skus):
            raise ValueError("sku_id values must be unique")
        if self.warmup_days >= self.horizon_days:
            raise ValueError("warmup_days must be smaller than horizon_days")
        return self
