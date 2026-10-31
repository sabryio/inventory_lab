"""Composite pattern: a multi-sourced plan IS a policy (LSP), so the engine is unchanged."""

from __future__ import annotations

from collections.abc import Sequence

from inventory_lab.domain.decisions import PolicyDecision
from inventory_lab.domain.errors import ConfigurationError
from inventory_lab.domain.planning import PolicyContext
from inventory_lab.ports.clock import ReviewSchedule
from inventory_lab.ports.policy import InventoryPolicy


class _EarliestSchedule(ReviewSchedule):
    """Union of child calendars: wake up whenever any child wants to review."""

    def __init__(self, children: Sequence[ReviewSchedule]) -> None:
        self._children = tuple(children)

    @property
    def reviews_on_change(self) -> bool:
        return any(c.reviews_on_change for c in self._children)

    @property
    def reviews_on_schedule(self) -> bool:
        return any(c.reviews_on_schedule for c in self._children)

    @property
    def expected_review_period_days(self) -> float:
        periodic = [
            c.expected_review_period_days
            for c in self._children
            if c.reviews_on_schedule
        ]
        return min(periodic) if periodic else 0.0

    def next_after(self, now: float) -> float | None:
        times = [t for c in self._children if (t := c.next_after(now)) is not None]
        return min(times) if times else None

    def occurs_at(self, now: float, tol: float = 1e-6) -> bool:
        return any(c.occurs_at(now, tol) for c in self._children)

    def describe(self) -> str:
        return " | ".join(c.describe() for c in self._children)


class MultiSourcePolicy(InventoryPolicy):
    """Regular lane + emergency lane, each a full policy with its own parameters.

    Children are gated by their own calendars, so a weekly regular policy and a
    continuous emergency policy coexist without either knowing about the other.
    """

    def __init__(self, code: str, children: Sequence[InventoryPolicy]) -> None:
        if not children:
            raise ConfigurationError("multi_source requires at least one child policy")
        self._code = code
        self._children = tuple(children)
        self._schedule = _EarliestSchedule([c.schedule for c in children])

    @property
    def code(self) -> str:
        return self._code

    @property
    def schedule(self) -> ReviewSchedule:
        return self._schedule

    def decide(self, ctx: PolicyContext) -> PolicyDecision:
        orders, rationales, params, nets = [], [], None, None
        for child in self._children:
            if not child.schedule.occurs_at(ctx.now):
                continue
            decision = child.decide(ctx)
            orders.extend(decision.orders)
            rationales.append(f"[{child.code}] {decision.rationale}")
            params = params or decision.parameters
            nets = decision.net_inventory if nets is None else nets
        if not rationales:
            return PolicyDecision.noop(
                self._code, "no child calendar open", reviewed=False
            )
        return PolicyDecision(
            policy_code=self._code,
            orders=tuple(orders),
            rationale=" ;; ".join(rationales),
            parameters=params,
            net_inventory=nets,
        )
