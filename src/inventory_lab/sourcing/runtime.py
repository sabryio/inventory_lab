"""Pair a lane's data with its lead-time sampler (composition over inheritance)."""

from __future__ import annotations

from inventory_lab.domain.base import ValueObject
from inventory_lab.domain.supply import SupplyLane
from inventory_lab.ports.supply import LeadTimeModel


class LaneRuntime(ValueObject):
    model_config = ValueObject.model_config.copy()
    model_config["arbitrary_types_allowed"] = True

    spec: SupplyLane
    lead_time: LeadTimeModel
