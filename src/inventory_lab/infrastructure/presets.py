# src/inventory_lab/infrastructure/presets.py
"""Built-in pharmacy scenarios. All monetary values are in Egyptian Pounds (EGP)."""

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
            holding_cost_per_unit_day=0.825,  # EGP — capital + storage (~25%/yr on EGP 176 unit)
            backorder_penalty_per_unit_day=33.0,  # EGP / unit / day backordered
            lost_sale_penalty_per_unit=220.0,  # EGP — margin + goodwill loss
            waste_penalty_per_unit=192.5,  # EGP — purchase cost + disposal
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
                unit_cost=176.0,  # EGP (≈ 3.20 EUR × 55)
                fixed_order_cost=440.0,  # EGP (≈ 8 EUR × 55)
                order_multiple=12,
                min_order_quantity=24,
            ),
            SupplyLane(
                lane_id=EXPEDITE,
                kind=LaneKind.EMERGENCY,
                lead_time=ComponentSpec(kind="fixed", params={"days": 1.0}),
                unit_cost=308.0,  # EGP (≈ 5.60 EUR × 55)
                fixed_order_cost=3_300.0,  # EGP (≈ 60 EUR × 55)
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


def pharmacy_stress_experiment(
    replications: int = 10, horizon_days: int = 365
) -> ExperimentSpec:
    """Stress test: high demand variance, long lead times, short shelf life."""
    weekly = ComponentSpec(kind="weekly", params={"weekdays": [4], "hour": 18})
    continuous = ComponentSpec(kind="continuous")

    regular_sizing = ComponentSpec(
        kind="rounded",
        params={"inner": {"kind": "eoq"}, "multiple": 12, "minimum": 24},
    )
    statistical = ComponentSpec(
        kind="statistical",
        params={"safety": {"kind": "normal"}, "sizing": regular_sizing},
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
        name="pharmacy_stress_test",
        horizon_days=horizon_days,
        warmup_days=30,
        replications=replications,
        initial_on_hand=100,
        target_service_level=0.95,
        shelf_life_days=90.0,
        cost_model=CostModel(
            holding_cost_per_unit_day=1.0,  # EGP
            backorder_penalty_per_unit_day=44.0,  # EGP
            lost_sale_penalty_per_unit=275.0,  # EGP
            waste_penalty_per_unit=220.0,  # EGP
        ),
        demand=ComponentSpec(
            kind="poisson",
            params={
                "mean_daily": 18.0,
                "weekday_factors": [1.5, 1.3, 1.1, 1.0, 1.4, 0.7, 0.3],
            },
        ),
        forecast=ComponentSpec(
            kind="rolling",
            params={"prior_mean": 18.0, "prior_std": 5.0, "window_days": 60},
        ),
        lanes=(
            SupplyLane(
                lane_id=REGULAR,
                kind=LaneKind.REGULAR,
                lead_time=ComponentSpec(
                    kind="normal", params={"mean_days": 7.0, "std_days": 2.5}
                ),
                unit_cost=192.5,  # EGP
                fixed_order_cost=550.0,  # EGP
                order_multiple=12,
                min_order_quantity=24,
            ),
        ),
        candidates=(
            CandidateSpec(
                name="continuous_sQ", policy=regular_policy("s_Q", continuous)
            ),
            CandidateSpec(name="weekly_RS", policy=regular_policy("R_S", weekly)),
            CandidateSpec(name="weekly_RsQ", policy=regular_policy("R_s_Q", weekly)),
            CandidateSpec(name="weekly_RsS", policy=regular_policy("R_s_S", weekly)),
            CandidateSpec(name="weekly_Rs_nQ", policy=regular_policy("R_s_nQ", weekly)),
        ),
    )


def pharmacy_daily_experiment(
    replications: int = 10, horizon_days: int = 365
) -> ExperimentSpec:
    """Daily automated ordering (EDI/API): negligible per-order cost, small lots."""
    continuous = ComponentSpec(kind="continuous")
    statistical = ComponentSpec(
        kind="statistical",
        params={
            "safety": {"kind": "normal"},
            "sizing": {"kind": "fixed", "params": {"quantity": 12}},
        },
    )

    def policy(kind: str) -> ComponentSpec:
        return ComponentSpec(
            kind=kind,
            params={
                "lane_id": REGULAR,
                "schedule": continuous.model_dump(),
                "parameters": statistical.model_dump(),
            },
        )

    return ExperimentSpec(
        name="pharmacy_daily_ordering",
        horizon_days=horizon_days,
        warmup_days=14,
        replications=replications,
        initial_on_hand=60,
        target_service_level=0.97,
        shelf_life_days=180.0,
        cost_model=CostModel(
            holding_cost_per_unit_day=0.825,  # EGP
            backorder_penalty_per_unit_day=33.0,  # EGP
            lost_sale_penalty_per_unit=220.0,  # EGP
            waste_penalty_per_unit=192.5,  # EGP
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
                    kind="normal", params={"mean_days": 1.0, "std_days": 0.25}
                ),
                unit_cost=176.0,  # EGP
                fixed_order_cost=5.5,  # EGP — automated, negligible per-order cost
                order_multiple=1,
                min_order_quantity=1,
            ),
        ),
        candidates=(
            CandidateSpec(name="daily_sQ", policy=policy("s_Q")),
            CandidateSpec(name="daily_RS", policy=policy("R_S")),
        ),
    )


def pharmacy_weekly_experiment(
    replications: int = 10, horizon_days: int = 365
) -> ExperimentSpec:
    """Weekly manual ordering: case-pack multiples, Friday review."""
    weekly = ComponentSpec(kind="weekly", params={"weekdays": [4], "hour": 18})
    regular_sizing = ComponentSpec(
        kind="rounded",
        params={"inner": {"kind": "eoq"}, "multiple": 12, "minimum": 24},
    )
    statistical = ComponentSpec(
        kind="statistical",
        params={"safety": {"kind": "normal"}, "sizing": regular_sizing},
    )

    def policy(kind: str) -> ComponentSpec:
        return ComponentSpec(
            kind=kind,
            params={
                "lane_id": REGULAR,
                "schedule": weekly.model_dump(),
                "parameters": statistical.model_dump(),
            },
        )

    return ExperimentSpec(
        name="pharmacy_weekly_ordering",
        horizon_days=horizon_days,
        warmup_days=30,
        replications=replications,
        initial_on_hand=150,
        target_service_level=0.97,
        shelf_life_days=180.0,
        cost_model=CostModel(
            holding_cost_per_unit_day=0.825,  # EGP
            backorder_penalty_per_unit_day=33.0,  # EGP
            lost_sale_penalty_per_unit=220.0,  # EGP
            waste_penalty_per_unit=192.5,  # EGP
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
                unit_cost=176.0,  # EGP
                fixed_order_cost=825.0,  # EGP — manual purchasing run
                order_multiple=12,
                min_order_quantity=24,
            ),
        ),
        candidates=(
            CandidateSpec(name="weekly_RsQ", policy=policy("R_s_Q")),
            CandidateSpec(name="weekly_RsS", policy=policy("R_s_S")),
            CandidateSpec(name="weekly_RS", policy=policy("R_S")),
            CandidateSpec(name="weekly_Rs_nQ", policy=policy("R_s_nQ")),
        ),
    )
