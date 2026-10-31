"""Decorator over the strategy port: extension by composition, not inheritance."""

from __future__ import annotations

from collections.abc import Sequence

from inventory_lab.core.registry import BuildContext
from inventory_lab.domain.base import ValueObject
from inventory_lab.domain.errors import ConfigurationError
from inventory_lab.domain.planning import SafetyStockContext, SafetyStockResult
from inventory_lab.domain.supply import ComponentSpec
from inventory_lab.ports.planning import SafetyStockStrategy
from inventory_lab.safety_stock.normal import safety_stock_registry


class MaxOfSafetyStock(SafetyStockStrategy):
    """Take the most conservative of several strategies (e.g. statistical vs. legal floor)."""

    def __init__(self, children: Sequence[SafetyStockStrategy]) -> None:
        if not children:
            raise ConfigurationError("max_of requires at least one child strategy")
        self._children = tuple(children)

    def compute(self, ctx: SafetyStockContext) -> SafetyStockResult:
        results = [child.compute(ctx) for child in self._children]
        winner = max(results, key=lambda r: r.units)
        return winner.model_copy(
            update={
                "method": f"max_of({', '.join(r.method for r in results)})",
                "notes": winner.notes,
            }
        )


class MaxOfConfig(ValueObject):
    children: tuple[ComponentSpec, ...]


@safety_stock_registry.register("max_of", MaxOfConfig)
def _build_max_of(config: MaxOfConfig, ctx: BuildContext) -> SafetyStockStrategy:
    return MaxOfSafetyStock(
        [safety_stock_registry.create(c, ctx) for c in config.children]
    )
