"""Multi-line consolidated purchase orders for supplier consolidation."""

from __future__ import annotations

from inventory_lab.domain.base import NonNegativeFloat, PositiveInt, ValueObject


class OrderLineItem(ValueObject):
    """A single SKU's contribution to a consolidated order."""

    sku_id: str
    quantity: PositiveInt
    unit_cost: NonNegativeFloat


class ConsolidatedPurchaseOrder(ValueObject):
    """A single order containing multiple SKUs from the same supplier.

    The fixed delivery/ordering cost is paid ONCE regardless of how many SKUs
    are included — this is the core saving of supplier consolidation.
    """

    order_id: str
    lane_id: str
    line_items: tuple[OrderLineItem, ...]
    placed_at: float
    due_at: float
    fixed_cost: NonNegativeFloat  # paid once for the whole shipment

    @property
    def total_quantity(self) -> int:
        return sum(item.quantity for item in self.line_items)

    @property
    def total_variable_cost(self) -> float:
        return sum(item.quantity * item.unit_cost for item in self.line_items)

    @property
    def total_cost(self) -> float:
        return self.fixed_cost + self.total_variable_cost

    @property
    def sku_count(self) -> int:
        return len(self.line_items)
