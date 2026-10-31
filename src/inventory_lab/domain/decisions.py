"""The single output contract of every policy — the basis of Liskov substitutability."""

from __future__ import annotations

from typing import Self

from pydantic import model_validator

from inventory_lab.domain.base import PositiveInt, ValueObject
from inventory_lab.domain.planning import ReplenishmentParameters


class OrderIntent(ValueObject):
    """A policy's request. The engine, not the policy, turns it into a PurchaseOrder."""

    lane_id: str
    quantity: PositiveInt
    rationale: str = ""


class PolicyDecision(ValueObject):
    """Audit-friendly decision: what, why, and with which parameters."""

    policy_code: str
    orders: tuple[OrderIntent, ...] = ()
    rationale: str = ""
    reviewed: bool = True
    net_inventory: int | None = None
    parameters: ReplenishmentParameters | None = None

    @model_validator(mode="after")
    def _consistency(self) -> Self:
        if not self.reviewed and self.orders:
            raise ValueError("a decision that was not reviewed cannot contain orders")
        return self

    @property
    def is_noop(self) -> bool:
        return not self.orders

    @classmethod
    def noop(cls, policy_code: str, rationale: str, *, reviewed: bool = True) -> Self:
        return cls(policy_code=policy_code, rationale=rationale, reviewed=reviewed)
