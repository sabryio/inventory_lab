"""Conservation of units — the strongest guard against simulator bugs."""

from inventory_lab.application.factory import SimulationFactory
from inventory_lab.infrastructure.presets import pharmacy_experiment


def test_units_are_conserved_and_no_illegal_state_occurs():
    spec = pharmacy_experiment(replications=1, horizon_days=120).model_copy(
        update={"warmup_days": 0, "collect_trace": False}
    )
    for candidate in spec.candidates:
        result = (
            SimulationFactory(spec)
            .create_engine(candidate, seed=7, replication=0)
            .run()
        )
        k = result.kpis
        out = k.units_filled_immediately + k.units_filled_late + k.final_state.on_hand
        assert spec.initial_on_hand + k.units_received == out, candidate.name
        assert k.units_demanded == (
            k.units_filled_immediately
            + k.units_filled_late
            + k.units_lost
            + k.final_state.backorders
        ), candidate.name
        # InventoryState's validator already forbids on_hand>0 with backorders>0.
        assert not (k.final_state.on_hand > 0 and k.final_state.backorders > 0)


def test_same_seed_is_reproducible():
    spec = pharmacy_experiment(replications=1, horizon_days=90)
    factory = SimulationFactory(spec)
    a = factory.create_engine(spec.candidates[0], seed=99, replication=0).run()
    b = factory.create_engine(spec.candidates[0], seed=99, replication=0).run()
    assert a.kpis == b.kpis


def test_emergency_lane_actually_fires_under_pressure():
    spec = pharmacy_experiment(replications=3, horizon_days=180).model_copy(
        update={"initial_on_hand": 0, "warmup_days": 0}
    )
    factory = SimulationFactory(spec)
    expedite = next(c for c in spec.candidates if c.name == "weekly_RsQ_expedite")
    plain = next(c for c in spec.candidates if c.name == "weekly_RsQ")
    exp_runs = [
        factory.create_engine(expedite, seed=s, replication=s).run() for s in range(3)
    ]
    plain_runs = [
        factory.create_engine(plain, seed=s, replication=s).run() for s in range(3)
    ]
    assert sum(r.kpis.emergency_orders_placed for r in exp_runs) > 0
    assert sum(r.kpis.emergency_orders_placed for r in plain_runs) == 0
