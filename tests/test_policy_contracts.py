"""LSP suite: every registered policy must satisfy the same behavioural contract."""

import pytest

from inventory_lab.domain.inventory import InventoryState
from inventory_lab.domain.planning import PolicyContext, ReplenishmentParameters
from inventory_lab.domain.supply import ComponentSpec, SupplyLane
from inventory_lab.planning.providers import StaticParameters
from inventory_lab.policies.quantities import FixedQuantityRule, OrderUpToRule
from inventory_lab.policies.rule_based import RuleBasedPolicy
from inventory_lab.policies.schedules import ContinuousReview, FixedIntervalReview
from inventory_lab.policies.triggers import AlwaysTrigger, ReorderPointTrigger

LANE = SupplyLane(
    lane_id="L", lead_time=ComponentSpec(kind="fixed", params={"days": 2})
)


def _policy(trigger, rule, params):
    return RuleBasedPolicy(
        "test", LANE, ContinuousReview(), trigger, rule, StaticParameters(params)
    )


@pytest.mark.parametrize(
    ("trigger", "rule", "params"),
    [
        (
            ReorderPointTrigger(),
            FixedQuantityRule(),
            ReplenishmentParameters(reorder_point=10, order_quantity=50),
        ),
        (
            AlwaysTrigger(),
            OrderUpToRule(),
            ReplenishmentParameters(order_up_to_level=100),
        ),
        (
            ReorderPointTrigger(),
            OrderUpToRule(),
            ReplenishmentParameters(reorder_point=10, order_up_to_level=100),
        ),
    ],
)
@pytest.mark.parametrize("on_hand", [0, 5, 10, 11, 500])
def test_all_policies_honour_the_contract(trigger, rule, params, on_hand):
    policy = _policy(trigger, rule, params)
    decision = policy.decide(
        PolicyContext(now=1.0, state=InventoryState(on_hand=on_hand))
    )
    assert decision.reviewed is True  # continuous ⇒ always reviewed
    assert all(o.quantity > 0 for o in decision.orders)  # never a zero/negative order
    assert all(o.lane_id == "L" for o in decision.orders)  # only its own lane
    assert decision.rationale  # always auditable


def test_fixed_quantity_is_independent_of_how_far_below_s_we_are():
    policy = _policy(
        ReorderPointTrigger(),
        FixedQuantityRule(),
        ReplenishmentParameters(reorder_point=10, order_quantity=50),
    )
    quantities = {
        policy.decide(PolicyContext(now=0, state=InventoryState(on_hand=oh)))
        .orders[0]
        .quantity
        for oh in (0, 3, 9, 10)
    }
    assert quantities == {50}  # the defining property of (s,Q)


def test_order_up_to_absorbs_backorders():
    policy = _policy(
        AlwaysTrigger(), OrderUpToRule(), ReplenishmentParameters(order_up_to_level=100)
    )
    ctx = PolicyContext(now=0, state=InventoryState(on_hand=0, backorders=20))
    assert policy.decide(ctx).orders[0].quantity == 120  # net inventory = -20


def test_periodic_policy_is_silent_between_reviews():
    schedule = FixedIntervalReview(period_days=7)
    assert schedule.occurs_at(7.0) and schedule.occurs_at(14.0)
    assert not schedule.occurs_at(8.5)
    assert schedule.next_after(7.0) == 14.0
