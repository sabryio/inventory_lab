"""Order interception port for real-time consolidation.

DIP hinge: the engine depends on this Protocol, not on any concrete coordinator.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from inventory_lab.domain.inventory import PurchaseOrder


@runtime_checkable
class OrderInterceptor(Protocol):
    """Intercept orders before they are placed.

    A shared instance is injected into every SKU engine in a portfolio so that
    cross-SKU coordination (e.g. consolidation) can happen without coupling the
    engines to each other.

    The ``owner`` parameter on ``flush_pending`` lets each engine retrieve only
    its own orders so that a shared coordinator can safely route consolidated
    orders back to the correct per-SKU ledger.
    """

    def intercept(
        self, proposed: PurchaseOrder, now: float, owner: str | None = None
    ) -> PurchaseOrder | None:
        """Called immediately before an order would be committed to the ledger.

        Returns:
            PurchaseOrder: place *this* order (may be a modified copy of ``proposed``).
            None: suppress the order; the coordinator is responsible for
                  re-emitting a consolidated version via ``flush_pending``.
        """
        ...

    def flush_pending(
        self, now: float, owner: str | None = None
    ) -> list[PurchaseOrder]:
        """Release deferred orders at the end of a consolidation window.

        The engine calls this once per snapshot event (day boundary), passing its
        own ``candidate`` name as ``owner`` so it receives only its own orders.
        When ``owner`` is ``None`` all pending orders are returned (useful for
        single-engine or testing scenarios).
        """
        ...
