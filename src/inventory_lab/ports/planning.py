"""Parameterisation ports: safety stock, lot sizing, and their composition."""

from __future__ import annotations

from abc import ABC, abstractmethod

from inventory_lab.domain.planning import (
    PolicyContext,
    ReplenishmentParameters,
    SafetyStockContext,
    SafetyStockResult,
)


class SafetyStockStrategy(ABC):
    """SRP: one statistical rule, no knowledge of policies or calendars."""

    @abstractmethod
    def compute(self, ctx: SafetyStockContext) -> SafetyStockResult: ...


class LotSizingStrategy(ABC):
    """SRP: how many units per lot, ignoring when we order."""

    @abstractmethod
    def quantity(self, mean_daily_demand: float) -> float: ...


class ParameterProvider(ABC):
    """DIP hinge: policies depend on this, not on any formula.

    Implementations may return constants (textbook) or recompute s/S/Q live from a
    rolling forecast (dynamic safety stock).
    """

    @abstractmethod
    def parameters_for(self, ctx: PolicyContext) -> ReplenishmentParameters: ...
