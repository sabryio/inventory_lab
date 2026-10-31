"""A generic, typed component registry: the mechanism that makes OCP mechanical."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from inventory_lab.domain.base import ValueObject
from inventory_lab.domain.errors import ComponentNotRegisteredError, ConfigurationError
from inventory_lab.domain.supply import ComponentSpec

ProductT = TypeVar("ProductT")


class BuildContext(ValueObject):
    """Dependencies offered to factories. Explicit, validated, and mockable."""

    model_config = ValueObject.model_config.copy()
    model_config["arbitrary_types_allowed"] = True

    clock: Any
    forecast: Any
    rng: Any
    cost_model: Any
    lanes: Mapping[str, Any] = {}
    service_level: float = 0.95
    # Populated when a primary supply lane is known at build time.
    lead_time: Any = None
    review_period_days: float = 0.0
    # Convenience accessor so EOQ factories don't have to drill into cost_model.
    default_order_cost: float = 0.0


Factory = Callable[[Any, BuildContext], ProductT]


class _Entry[ProductT]:
    __slots__ = ("config_model", "factory")

    def __init__(
        self, config_model: type[BaseModel], factory: Factory[ProductT]
    ) -> None:
        self.config_model, self.factory = config_model, factory


class ComponentRegistry[ProductT]:
    """Register implementations under a string key; create them from a ComponentSpec.

    Adding a policy/strategy never edits this class, the specs, or the engine.
    """

    def __init__(self, name: str) -> None:
        self._name = name
        self._entries: dict[str, _Entry[ProductT]] = {}

    def register(
        self, kind: str, config_model: type[BaseModel]
    ) -> Callable[[Factory[ProductT]], Factory[ProductT]]:
        def decorator(factory: Factory[ProductT]) -> Factory[ProductT]:
            if kind in self._entries:
                raise ConfigurationError(f"{self._name}: {kind!r} already registered")
            self._entries[kind] = _Entry(config_model, factory)
            return factory

        return decorator

    def create(self, spec: ComponentSpec, ctx: BuildContext) -> ProductT:
        entry = self._entries.get(spec.kind)
        if entry is None:
            raise ComponentNotRegisteredError(
                self._name, spec.kind, tuple(self._entries)
            )
        try:
            config = entry.config_model.model_validate(spec.params)
        except ValidationError as exc:
            raise ConfigurationError(
                f"{self._name}[{spec.kind}]: invalid params\n{exc}"
            ) from exc
        return entry.factory(config, ctx)

    @property
    def kinds(self) -> tuple[str, ...]:
        return tuple(sorted(self._entries))
