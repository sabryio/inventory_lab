# src/inventory_lab/infrastructure/presets.py
"""Built-in pharmacy scenario: a fast-moving generic with an unreliable wholesaler."""

from __future__ import annotations

from inventory_lab.application.specs import CandidateSpec, ExperimentSpec
from inventory_lab.domain.supply import ComponentSpec, LaneKind, SupplyLane
from inventory_lab.simulation.costs import CostModel

REGULAR = "wholesaler"
EXPEDITE = "direct_express"


def pharmacy_experiment(
    replications: int = 10, horizon_days: int = 365
) -> ExperimentSpec:
    weekly = ComponentSpec(
        kind="weekly", params={"weekdays": [4], "hour": 18}
    )  # Friday 18:00
    continuous = ComponentSpec(kind="continuous")

    regular_sizing = ComponentSpec(
        kind="rounded",
        params={"inner": {"kind": "eoq"}, "multiple": 12, "minimum": 24},
    )
    statistical = ComponentSpec(
        kind="statistical",
        params={"safety": {"kind": "normal"}, "sizing": regular_sizing},
    )
    expedite_params = ComponentSpec(
        kind="statistical",
        params={
            "safety": {"kind": "normal"},
            "sizing": {"kind": "fixed", "params": {"quantity": 24}},
            "service_level": 0.99,
        },
    )

    def regular_policy(kind: str, schedule: ComponentSpec) -> ComponentSpec:
        return ComponentSpec(
            kind=kind,
            params={
                "lane_id": REGULAR,
                "schedule": schedule.model_dump(),
                "parameters": statistical.model_dump(),
            },
        )

    return ExperimentSpec(
        name="pharmacy_generic_500ml_suspension",
        horizon_days=horizon_days,
        warmup_days=30,
        replications=replications,
        initial_on_hand=150,
        target_service_level=0.97,
        cost_model=CostModel(
            holding_cost_per_unit_day=0.0025,
            backorder_penalty_per_unit_day=0.60,
            lost_sale_penalty_per_unit=4.0,
        ),
        demand=ComponentSpec(
            kind="poisson",
            params={
                "mean_daily": 12.0,
                "weekday_factors": [1.3, 1.1, 1.0, 1.0, 1.2, 0.6, 0.2],
            },
        ),
        forecast=ComponentSpec(
            kind="rolling",
            params={"prior_mean": 12.0, "prior_std": 3.6, "window_days": 90},
        ),
        lanes=(
            SupplyLane(
                lane_id=REGULAR,
                kind=LaneKind.REGULAR,
                lead_time=ComponentSpec(
                    kind="normal", params={"mean_days": 4.0, "std_days": 1.2}
                ),
                unit_cost=3.20,
                fixed_order_cost=8.0,
                order_multiple=12,
                min_order_quantity=24,
            ),
            SupplyLane(
                lane_id=EXPEDITE,
                kind=LaneKind.EMERGENCY,
                lead_time=ComponentSpec(kind="fixed", params={"days": 1.0}),
                unit_cost=5.60,
                fixed_order_cost=60.0,
                order_multiple=6,
                min_order_quantity=6,
            ),
        ),
        candidates=(
            CandidateSpec(
                name="continuous_sQ", policy=regular_policy("s_Q", continuous)
            ),
            CandidateSpec(name="weekly_RS", policy=regular_policy("R_S", weekly)),
            CandidateSpec(name="weekly_RsQ", policy=regular_policy("R_s_Q", weekly)),
            CandidateSpec(name="weekly_RsS", policy=regular_policy("R_s_S", weekly)),
            CandidateSpec(
                name="weekly_RsQ_expedite",
                policy=ComponentSpec(
                    kind="multi_source",
                    params={
                        "regular": regular_policy("R_s_Q", weekly).model_dump(),
                        "emergency": {
                            "kind": "emergency",
                            "params": {
                                "lane_id": EXPEDITE,
                                "parameters": expedite_params.model_dump(),
                                "backorder_threshold": 12,
                                "projection_horizon_days": 3.0,
                            },
                        },
                    },
                ),
            ),
        ),
    )
