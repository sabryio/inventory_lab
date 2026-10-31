"""One policy engine. The four textbook policies are configurations of it."""

from __future__ import annotations

from inventory_lab.domain.decisions import OrderIntent, PolicyDecision
from inventory_lab.domain.planning import PolicyContext
from inventory_lab.domain.supply import SupplyLane
from inventory_lab.ports.clock import ReviewSchedule
from inventory_lab.ports.planning import ParameterProvider
from inventory_lab.ports.policy import (
    InventoryPolicy,
    QuantityRule,
    SizingContext,
    TriggerContext,
    TriggerRule,
)


class RuleBasedPolicy(InventoryPolicy):
    """Pure decision function: schedule × trigger × quantity, parameterised by a provider.

    It never touches the ledger, the RNG, or the clock; it cannot place an order.
    That is what makes it trivially testable and safely substitutable.
    """

    def __init__(
        self,
        code: str,
        lane: SupplyLane,
        schedule: ReviewSchedule,
        trigger: TriggerRule,
        quantity_rule: QuantityRule,
        parameters: ParameterProvider,
    ) -> None:
        self._code = code
        self._lane = lane
        self._schedule = schedule
        self._trigger = trigger
        self._quantity_rule = quantity_rule
        self._parameters = parameters

    @property
    def code(self) -> str:
        return self._code

    @property
    def schedule(self) -> ReviewSchedule:
        return self._schedule

    def decide(self, ctx: PolicyContext) -> PolicyDecision:
        params = self._parameters.parameters_for(ctx)
        net = ctx.state.net_inventory
        trigger_ctx = TriggerContext(
            now=ctx.now,
            state=ctx.state,
            parameters=params,
            open_orders=ctx.open_orders,
            lane=self._lane,
        )

        if not self._trigger.should_order(trigger_ctx):
            return PolicyDecision(
                policy_code=self._code,
                net_inventory=net,
                parameters=params,
                rationale=f"trigger not met ({self._trigger.describe()}); net={net}",
            )

        qty = self._quantity_rule.quantity(
            SizingContext(net_inventory=net, parameters=params, lane=self._lane)
        )
        if qty <= 0:
            return PolicyDecision(
                policy_code=self._code,
                net_inventory=net,
                parameters=params,
                rationale="trigger met but computed quantity is 0",
            )

        return PolicyDecision(
            policy_code=self._code,
            net_inventory=net,
            parameters=params,
            orders=(
                OrderIntent(
                    lane_id=self._lane.lane_id,
                    quantity=qty,
                    rationale=(
                        f"{self._trigger.describe()} → {self._quantity_rule.describe()}"
                    ),
                ),
            ),
            rationale=(
                f"net={net}, s={params.reorder_point}, S={params.order_up_to_level}, "
                f"Q={params.order_quantity}, SS={params.safety_stock:.1f} → order {qty}"
            ),
        )
