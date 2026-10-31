"""Built-in multi-SKU portfolio presets. All monetary values are in EGP."""

from __future__ import annotations

from inventory_lab.application.portfolio_specs import PortfolioSpec, SkuSpec
from inventory_lab.domain.supply import ComponentSpec, LaneKind, SupplyLane
from inventory_lab.simulation.costs import CostModel

_WHOLESALER = "wholesaler"


def pharmacy_portfolio_experiment(
    replications: int = 10, horizon_days: int = 365
) -> PortfolioSpec:
    """10-SKU pharmacy portfolio sharing one wholesaler (all costs in EGP).

    Economics: unit_cost = EGP 165, holding = EGP 0.825/unit/day (~25%/yr),
    fixed_order_cost = EGP 825 (manual weekly review).  Weekly Friday review
    aligns all SKUs on the same day — when consolidated they pay EGP 825 once
    instead of 10 × EGP 825, saving EGP 7,425 per shipment.
    """
    weekly = ComponentSpec(kind="weekly", params={"weekdays": [4], "hour": 18})

    wholesaler = SupplyLane(
        lane_id=_WHOLESALER,
        kind=LaneKind.REGULAR,
        lead_time=ComponentSpec(
            kind="normal", params={"mean_days": 4.0, "std_days": 1.0}
        ),
        unit_cost=165.0,  # EGP (≈ 3.00 EUR × 55)
        fixed_order_cost=825.0,  # EGP (≈ 15 EUR × 55) — semi-manual ordering
        order_multiple=12,
        min_order_quantity=12,
    )

    skus: list[SkuSpec] = []
    for i in range(1, 11):
        mean_demand = 5.0 + i * 2.0  # 7, 9, 11, ..., 25 units/day
        skus.append(
            SkuSpec(
                sku_id=f"SKU-{i:03d}",
                initial_on_hand=int(mean_demand * 10),
                demand=ComponentSpec(
                    kind="poisson",
                    params={"mean_daily": mean_demand},
                ),
                forecast=ComponentSpec(
                    kind="rolling",
                    params={
                        "prior_mean": mean_demand,
                        "prior_std": mean_demand * 0.3,
                        "window_days": 60,
                    },
                ),
                policy=ComponentSpec(
                    kind="R_s_Q",
                    params={
                        "lane_id": _WHOLESALER,
                        "schedule": weekly.model_dump(),
                        "parameters": {
                            "kind": "statistical",
                            "params": {
                                "safety": {"kind": "normal"},
                                "sizing": {
                                    "kind": "rounded",
                                    "params": {
                                        "inner": {"kind": "eoq"},
                                        "multiple": 12,
                                        "minimum": 24,
                                    },
                                },
                            },
                        },
                    },
                ),
            )
        )

    return PortfolioSpec(
        name="pharmacy_portfolio_10_skus",
        horizon_days=horizon_days,
        warmup_days=30,
        replications=replications,
        target_service_level=0.95,
        cost_model=CostModel(
            holding_cost_per_unit_day=0.825,  # EGP
            backorder_penalty_per_unit_day=33.0,  # EGP
            lost_sale_penalty_per_unit=220.0,  # EGP
            waste_penalty_per_unit=192.5,  # EGP
        ),
        lanes=(wholesaler,),
        skus=tuple(skus),
        consolidation_enabled=True,
    )
