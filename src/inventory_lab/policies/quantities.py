"""The 'how much?' axis: fixed Q, up-to S, or min-max."""

from __future__ import annotations

from inventory_lab.ports.policy import QuantityRule, SizingContext


class FixedQuantityRule(QuantityRule):
    """(s,Q) and (R,s,Q): always the same Q, even if stock is far below s."""

    def quantity(self, ctx: SizingContext) -> int:
        return max(0, round(ctx.parameters.require_order_quantity()))

    def describe(self) -> str:
        return "Q (fixed)"


class OrderUpToRule(QuantityRule):
    """(R,S): variable quantity that lifts net inventory to S."""

    def quantity(self, ctx: SizingContext) -> int:
        target = ctx.parameters.require_order_up_to()
        return max(0, round(target - ctx.net_inventory))

    def describe(self) -> str:
        return "S - net_inventory"


class MinMaxRule(QuantityRule):
    """(R,s,S): triggered at s, topped up to s + Q (a pragmatic min-max)."""

    def quantity(self, ctx: SizingContext) -> int:
        target = (
            ctx.parameters.require_reorder_point()
            + ctx.parameters.require_order_quantity()
        )
        return max(0, round(target - ctx.net_inventory))

    def describe(self) -> str:
        return "(s + Q) - net_inventory"
