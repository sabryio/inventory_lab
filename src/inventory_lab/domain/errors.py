"""Typed failure modes. Callers can react to categories, not string messages."""

from __future__ import annotations


class InventoryLabError(Exception):
    """Base class for every error raised by this application."""


class ConfigurationError(InventoryLabError):
    """A spec/config cannot produce a valid object graph."""


class ComponentNotRegisteredError(ConfigurationError):
    def __init__(self, registry: str, kind: str, available: tuple[str, ...]) -> None:
        super().__init__(
            f"Unknown {registry} component {kind!r}. Registered: {', '.join(sorted(available))}"
        )
        self.registry, self.kind, self.available = registry, kind, available


class MissingParameterError(ConfigurationError):
    """A rule required a parameter the provider did not supply (e.g. Q for (s,Q))."""


class SimulationError(InventoryLabError):
    """Runtime failure inside the simulation engine."""


class InvariantViolation(SimulationError):
    """The inventory ledger reached a state that must be impossible."""


class OrderRejectedError(SimulationError):
    """An order could not be placed on the requested lane."""
