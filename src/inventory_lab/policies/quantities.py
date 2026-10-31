"""The 'how much?' axis: fixed Q, up-to S, or min-max."""

from __future__ import annotations

from math import ceil

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


class MultiFixedLotRule(QuantityRule):
    """(R,s,n·Q): order ceil(gap / Q)·Q — truckload-friendly, still threshold-gated.

    Closes the gap between current net inventory and S by ordering in whole multiples
    of Q. Useful when Q represents a packaging unit (case, pallet) and partial orders
    are not accepted by the supplier.
    """

    def quantity(self, ctx: SizingContext) -> int:
        q = ctx.parameters.require_order_quantity()
        gap = ctx.parameters.require_order_up_to() - ctx.net_inventory
        if gap <= 0:
            return 0
        return int(ceil(gap / q) * q)

    def describe(self) -> str:
        return "ceil(gap/Q)·Q (packaging multiple)"
