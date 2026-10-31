# src/inventory_lab/simulation/result.py
"""Immutable results — the contract between simulation and reporting."""

from __future__ import annotations

from inventory_lab.domain.base import ValueObject
from inventory_lab.domain.inventory import InventoryState, PurchaseOrder
from inventory_lab.ports.reporting import TraceRecord
from inventory_lab.simulation.costs import CostBreakdown


class OrderRecord(ValueObject):
    """Lightweight immutable record of a placed order, used for consolidation."""

    order_id: str
    lane_id: str
    quantity: int
    placed_at: float
    due_at: float
    unit_cost: float
    fixed_cost: float


class KpiSnapshot(ValueObject):
    measured_days: float
    units_demanded: int
    units_filled_immediately: int
    units_filled_late: int
    units_lost: int
    units_wasted: int
    units_received: int
    units_ordered: int
    units_ordered_emergency: int
    orders_placed: int
    emergency_orders_placed: int
    fill_rate: float
    event_fill_rate: float
    ready_rate: float
    stockout_days: float
    avg_on_hand: float
    avg_backorders: float
    inventory_turns: float
    costs: CostBreakdown
    total_cost: float
    final_state: InventoryState


class SimulationResult(ValueObject):
    candidate: str
    policy_code: str
    seed: int
    replication: int
    kpis: KpiSnapshot
    trace: tuple[TraceRecord, ...] = ()
    order_log: tuple[OrderRecord, ...] = ()
    """Per-order log for portfolio-level post-processing (e.g. consolidation).

    Empty by default to keep single-SKU simulations lean. ``PortfolioEngine``
    enables it by setting ``collect_order_log=True`` on the engine.
    """
