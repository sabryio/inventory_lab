# src/inventory_lab/policies/triggers.py
"""The 'do I act?' axis. Emergency triggers are ordinary triggers (LSP)."""

from __future__ import annotations

from collections.abc import Sequence

from inventory_lab.domain.errors import ConfigurationError
from inventory_lab.ports.demand import ForecastReader
from inventory_lab.ports.policy import TriggerContext, TriggerRule
from inventory_lab.ports.sourcing import EmergencyTrigger


class AlwaysTrigger(TriggerRule):
    """Periodic order-up-to: at a review, always top up."""

    def should_order(self, ctx: TriggerContext) -> bool:
        return True

    def describe(self) -> str:
        return "always"


class ReorderPointTrigger(TriggerRule):
    """Fire when net inventory <= s (Section 1.1 and 1.3)."""

    def should_order(self, ctx: TriggerContext) -> bool:
        return ctx.state.net_inventory <= ctx.parameters.require_reorder_point()

    def describe(self) -> str:
        return "net_inventory <= s"


class BackorderEmergencyTrigger(EmergencyTrigger):
    """Expedite as soon as the backlog exceeds a critical threshold."""

    def __init__(self, threshold_units: int) -> None:
        self._threshold = threshold_units

    def should_order(self, ctx: TriggerContext) -> bool:
        return ctx.state.backorders >= self._threshold and self._threshold >= 0

    def describe(self) -> str:
        return f"backorders >= {self._threshold}"


class ProjectedStockoutTrigger(EmergencyTrigger):
    """Expedite if demand before the next regular receipt cannot be covered.

    Anticipatory rather than reactive: it protects service *before* the backlog forms.
    """

    def __init__(self, forecast: ForecastReader, horizon_days: float) -> None:
        if horizon_days <= 0:
            raise ConfigurationError("projection horizon must be positive")
        self._forecast, self._horizon = forecast, horizon_days

    def should_order(self, ctx: TriggerContext) -> bool:
        arrivals = [
            o.quantity
            for o in ctx.open_orders
            if o.due_at - ctx.now <= self._horizon and o.lane_id != ctx.lane.lane_id
        ]
        projected = (
            ctx.state.on_hand
            + sum(arrivals)
            - self._forecast.mean_daily * self._horizon
        )
        return projected < 0

    def describe(self) -> str:
        return f"projected stockout within {self._horizon:g}d"


class LaneIdleTrigger(EmergencyTrigger):
    """Guard: never stack emergency orders (one expedite in flight at a time)."""

    def should_order(self, ctx: TriggerContext) -> bool:
        return all(o.lane_id != ctx.lane.lane_id for o in ctx.open_orders)

    def describe(self) -> str:
        return "no open order on this lane"


class AllTrigger(TriggerRule):
    """Composite AND — build arbitrary emergency logic without new classes."""

    def __init__(self, children: Sequence[TriggerRule]) -> None:
        if not children:
            raise ConfigurationError("all_of requires at least one child")
        self._children = tuple(children)

    def should_order(self, ctx: TriggerContext) -> bool:
        return all(c.should_order(ctx) for c in self._children)

    def describe(self) -> str:
        return " AND ".join(c.describe() for c in self._children)


class AnyTrigger(TriggerRule):
    """Composite OR."""

    def __init__(self, children: Sequence[TriggerRule]) -> None:
        if not children:
            raise ConfigurationError("any_of requires at least one child")
        self._children = tuple(children)

    def should_order(self, ctx: TriggerContext) -> bool:
        return any(c.should_order(ctx) for c in self._children)

    def describe(self) -> str:
        return " OR ".join(c.describe() for c in self._children)
