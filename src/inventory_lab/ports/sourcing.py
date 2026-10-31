"""Emergency-lane activation is just a TriggerRule specialisation (LSP + OCP)."""

from __future__ import annotations

from abc import ABC

from inventory_lab.ports.policy import TriggerRule


class EmergencyTrigger(TriggerRule, ABC):
    """Marker abstraction: 'should we bypass the regular lane and expedite?'"""
