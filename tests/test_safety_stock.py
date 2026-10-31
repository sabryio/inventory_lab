from math import isclose, sqrt
from statistics import NormalDist

import pytest
from pydantic import ValidationError

from inventory_lab.domain.planning import SafetyStockContext
from inventory_lab.safety_stock.composite import MaxOfSafetyStock
from inventory_lab.safety_stock.fixed import FixedSafetyStock
from inventory_lab.safety_stock.normal import NormalSafetyStock


def test_continuous_review_uses_lead_time_only():
    ctx = SafetyStockContext(
        mean_daily_demand=10,
        daily_demand_std=3,
        lead_time_mean_days=4,
        lead_time_std_days=0,
        review_period_days=0,
        cycle_service_level=0.95,
    )
    result = NormalSafetyStock().compute(ctx)
    expected = NormalDist().inv_cdf(0.95) * 3 * sqrt(4)
    assert isclose(result.units, expected, rel_tol=1e-9)


def test_periodic_review_needs_more_safety_stock_than_continuous():
    base = {
        "mean_daily_demand": 10,
        "daily_demand_std": 3,
        "lead_time_mean_days": 4,
        "cycle_service_level": 0.95,
    }
    continuous = NormalSafetyStock().compute(
        SafetyStockContext(**base, review_period_days=0)
    )
    periodic = NormalSafetyStock().compute(
        SafetyStockContext(**base, review_period_days=7)
    )
    assert (
        periodic.units > continuous.units
    )  # the Section 1.2 "blind spot" cost, quantified


def test_lead_time_variability_is_priced_in():
    base = {
        "mean_daily_demand": 10,
        "daily_demand_std": 3,
        "lead_time_mean_days": 4,
        "cycle_service_level": 0.97,
    }
    reliable = NormalSafetyStock().compute(
        SafetyStockContext(**base, lead_time_std_days=0)
    )
    erratic = NormalSafetyStock().compute(
        SafetyStockContext(**base, lead_time_std_days=2)
    )
    assert erratic.units > reliable.units


def test_max_of_is_a_transparent_substitute():
    ctx = SafetyStockContext(
        mean_daily_demand=10, daily_demand_std=3, lead_time_mean_days=4
    )
    composite = MaxOfSafetyStock([NormalSafetyStock(), FixedSafetyStock(1_000)])
    assert composite.compute(ctx).units == 1_000  # LSP: same return type, same contract


def test_service_level_bounds_are_validated_at_the_boundary():
    with pytest.raises(ValidationError):
        SafetyStockContext(
            mean_daily_demand=1,
            daily_demand_std=1,
            lead_time_mean_days=1,
            cycle_service_level=1.0,
        )
