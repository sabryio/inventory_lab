"""The policy contract plus deliberately narrow contexts for its collaborators."""

from __future__ import annotations

from abc import ABC, abstractmethod

from inventory_lab.domain.base import ValueObject
from inventory_lab.domain.decisions import PolicyDecision
from inventory_lab.domain.inventory import InventoryState, PurchaseOrder
from inventory_lab.domain.planning import PolicyContext, ReplenishmentParameters
from inventory_lab.domain.supply import SupplyLane
from inventory_lab.ports.clock import ReviewSchedule


class TriggerContext(ValueObject):
    """Only what a trigger may see (ISP)."""

    now: float
    state: InventoryState
    parameters: ReplenishmentParameters
    open_orders: tuple[PurchaseOrder, ...] = ()
    lane: SupplyLane


class SizingContext(ValueObject):
    """Only what a quantity rule may see (ISP)."""

    net_inventory: int
    parameters: ReplenishmentParameters
    lane: SupplyLane


class TriggerRule(ABC):
    @abstractmethod
    def should_order(self, ctx: TriggerContext) -> bool: ...

    @abstractmethod
    def describe(self) -> str: ...


class QuantityRule(ABC):
    @abstractmethod
    def quantity(self, ctx: SizingContext) -> int:
        """Return a non-negative desired quantity; 0 means 'do not order'."""

    @abstractmethod
    def describe(self) -> str: ...


class InventoryPolicy(ABC):
    """LSP contract for ALL policies:
    * total function: never raises for a valid context; returns a PolicyDecision
    * no side effects: never mutates state or places orders itself
    * quantities are strictly positive integers, lane constraints applied downstream
    """

    @property
    @abstractmethod
    def code(self) -> str:
        """Stable identifier, e.g. '(R,s,Q)'."""

    @property
    @abstractmethod
    def schedule(self) -> ReviewSchedule: ...

    @abstractmethod
    def decide(self, ctx: PolicyContext) -> PolicyDecision: ...
