"""Registry wiring. Adding (R,s,S) or multi_source touched nothing above this file."""

from __future__ import annotations

from inventory_lab.core.registry import BuildContext, ComponentRegistry
from inventory_lab.domain.base import ValueObject
from inventory_lab.domain.errors import ConfigurationError
from inventory_lab.domain.supply import ComponentSpec
from inventory_lab.planning.providers import parameter_registry
from inventory_lab.policies.composite import MultiSourcePolicy
from inventory_lab.policies.quantities import (
    FixedQuantityRule,
    MinMaxRule,
    OrderUpToRule,
)
from inventory_lab.policies.rule_based import RuleBasedPolicy
from inventory_lab.policies.schedules import schedule_registry
from inventory_lab.policies.triggers import (
    AllTrigger,
    AlwaysTrigger,
    AnyTrigger,
    BackorderEmergencyTrigger,
    LaneIdleTrigger,
    ProjectedStockoutTrigger,
    ReorderPointTrigger,
)
from inventory_lab.ports.policy import InventoryPolicy, QuantityRule, TriggerRule

policy_registry: ComponentRegistry[InventoryPolicy] = ComponentRegistry("policy")


class ReplenishmentPolicyConfig(ValueObject):
    lane_id: str
    schedule: ComponentSpec
    parameters: ComponentSpec
    code: str | None = None


class EmergencyConfig(ValueObject):
    """Declarative emergency activation rule for the expedite lane."""

    lane_id: str
    schedule: ComponentSpec = ComponentSpec(kind="continuous")
    parameters: ComponentSpec
    backorder_threshold: int | None = None
    projection_horizon_days: float | None = None
    require_idle_lane: bool = True


class MultiSourceConfig(ValueObject):
    regular: ComponentSpec
    emergency: ComponentSpec


def _lane(ctx: BuildContext, lane_id: str):
    runtime = ctx.lanes.get(lane_id)
    if runtime is None:
        raise ConfigurationError(
            f"unknown lane {lane_id!r}; known: {sorted(ctx.lanes)}"
        )
    return runtime


def _build_rule_policy(
    config: ReplenishmentPolicyConfig,
    ctx: BuildContext,
    default_code: str,
    trigger: TriggerRule,
    quantity: QuantityRule,
) -> InventoryPolicy:
    runtime = _lane(ctx, config.lane_id)
    schedule = schedule_registry.create(config.schedule, ctx)
    local = ctx.model_copy(
        update={
            "lead_time": runtime.lead_time,
            "review_period_days": schedule.expected_review_period_days,
            "default_order_cost": runtime.spec.fixed_order_cost,
        }
    )
    provider = parameter_registry.create(config.parameters, local)
    return RuleBasedPolicy(
        code=config.code or default_code,
        lane=runtime.spec,
        schedule=schedule,
        trigger=trigger,
        quantity_rule=quantity,
        parameters=provider,
    )


@policy_registry.register("s_Q", ReplenishmentPolicyConfig)
def _build_s_q(config: ReplenishmentPolicyConfig, ctx: BuildContext) -> InventoryPolicy:
    return _build_rule_policy(
        config, ctx, "(s,Q)", ReorderPointTrigger(), FixedQuantityRule()
    )


@policy_registry.register("R_S", ReplenishmentPolicyConfig)
def _build_r_s(config: ReplenishmentPolicyConfig, ctx: BuildContext) -> InventoryPolicy:
    return _build_rule_policy(config, ctx, "(R,S)", AlwaysTrigger(), OrderUpToRule())


@policy_registry.register("R_s_Q", ReplenishmentPolicyConfig)
def _build_r_s_q(
    config: ReplenishmentPolicyConfig, ctx: BuildContext
) -> InventoryPolicy:
    return _build_rule_policy(
        config, ctx, "(R,s,Q)", ReorderPointTrigger(), FixedQuantityRule()
    )


@policy_registry.register("R_s_S", ReplenishmentPolicyConfig)
def _build_r_s_s(
    config: ReplenishmentPolicyConfig, ctx: BuildContext
) -> InventoryPolicy:
    return _build_rule_policy(
        config, ctx, "(R,s,S)", ReorderPointTrigger(), MinMaxRule()
    )


@policy_registry.register("emergency", EmergencyConfig)
def _build_emergency(config: EmergencyConfig, ctx: BuildContext) -> InventoryPolicy:
    children: list[TriggerRule] = []
    if config.backorder_threshold is not None:
        children.append(BackorderEmergencyTrigger(config.backorder_threshold))
    if config.projection_horizon_days is not None:
        children.append(
            ProjectedStockoutTrigger(ctx.forecast, config.projection_horizon_days)
        )
    if not children:
        raise ConfigurationError(
            "emergency policy needs a backorder_threshold or a projection horizon"
        )
    activation: TriggerRule = (
        children[0] if len(children) == 1 else AnyTrigger(children)
    )
    if config.require_idle_lane:
        activation = AllTrigger([activation, LaneIdleTrigger()])
    rule_config = ReplenishmentPolicyConfig(
        lane_id=config.lane_id,
        schedule=config.schedule,
        parameters=config.parameters,
        code="emergency",
    )
    return _build_rule_policy(
        rule_config, ctx, "emergency", activation, OrderUpToRule()
    )


@policy_registry.register("multi_source", MultiSourceConfig)
def _build_multi_source(
    config: MultiSourceConfig, ctx: BuildContext
) -> InventoryPolicy:
    regular = policy_registry.create(config.regular, ctx)
    emergency = policy_registry.create(config.emergency, ctx)
    return MultiSourcePolicy(f"{regular.code}+EXP", [regular, emergency])
