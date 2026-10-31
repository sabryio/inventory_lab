# src/inventory_lab/application/factory.py
"""Composition root. The ONLY module that knows every concrete implementation."""

from __future__ import annotations

from datetime import datetime, timedelta
from random import Random

from inventory_lab.application.specs import CandidateSpec, ExperimentSpec
from inventory_lab.core.registry import BuildContext
from inventory_lab.domain.base import ValueObject
from inventory_lab.forecasting.forecast import forecast_registry
from inventory_lab.infrastructure.tracing import InMemoryTraceSink

# Importing these modules registers their components (side-effect of the registry pattern).
from inventory_lab.policies import factories as _policy_factories  # noqa: F401
from inventory_lab.policies.factories import policy_registry
from inventory_lab.ports.clock import Clock
from inventory_lab.ports.demand import DemandObserver
from inventory_lab.safety_stock import composite as _ss_composite  # noqa: F401
from inventory_lab.safety_stock import empirical as _ss_empirical  # noqa: F401
from inventory_lab.safety_stock import fixed as _ss_fixed  # noqa: F401
from inventory_lab.simulation import demand as _demand_components  # noqa: F401
from inventory_lab.simulation.demand import demand_registry
from inventory_lab.simulation.engine import EngineConfig, SimulationEngine
from inventory_lab.simulation.ledger import InventoryLedger
from inventory_lab.sourcing.lead_time import lead_time_registry
from inventory_lab.sourcing.runtime import LaneRuntime


class SimulationClock(Clock, ValueObject):
    """Wall-clock anchor for calendar-based reviews."""

    start_date: datetime

    @property
    def start(self) -> datetime:
        return self.start_date

    def to_datetime(self, t: float) -> datetime:
        return self.start_date + timedelta(days=t)


class SimulationFactory:
    """Builds a fully wired engine from a spec. Swappable for a test double factory."""

    def __init__(self, spec: ExperimentSpec) -> None:
        self._spec = spec

    def create_engine(
        self, candidate: CandidateSpec, seed: int, replication: int
    ) -> SimulationEngine:
        spec = self._spec
        rng = Random(seed ^ 0x5EED)
        clock = SimulationClock(start_date=spec.start_date)

        lane_ctx = BuildContext(
            clock=clock, forecast=None, rng=rng, cost_model=spec.cost_model
        )
        lanes = {
            lane.lane_id: LaneRuntime(
                spec=lane, lead_time=lead_time_registry.create(lane.lead_time, lane_ctx)
            )
            for lane in spec.lanes
        }

        forecast = forecast_registry.create(spec.forecast, lane_ctx)
        ctx = BuildContext(
            clock=clock,
            forecast=forecast,
            rng=rng,
            cost_model=spec.cost_model,
            lanes=lanes,
            service_level=spec.target_service_level,
        )
        policy = policy_registry.create(candidate.policy, ctx)
        generator = demand_registry.create(spec.demand, ctx)
        events = list(generator.generate(spec.horizon_days, rng, clock))

        return SimulationEngine(
            config=EngineConfig(
                horizon_days=spec.horizon_days,
                warmup_days=spec.warmup_days,
                shortage_mode=spec.shortage_mode,
                collect_trace=spec.collect_trace,
            ),
            clock=clock,
            ledger=InventoryLedger(spec.initial_on_hand, spec.shortage_mode),
            lanes=lanes,
            policies=[policy],
            demand_events=events,
            cost_model=spec.cost_model,
            rng=rng,
            candidate=candidate.name,
            policy_code=policy.code,
            seed=seed,
            replication=replication,
            forecast_observer=forecast
            if isinstance(forecast, DemandObserver)
            else None,
            tracer=InMemoryTraceSink() if spec.collect_trace else None,
        )
