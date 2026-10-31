"""ISP showcase: reading a forecast and feeding a forecast are different interfaces."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator, Sequence
from random import Random
from typing import Protocol, runtime_checkable

from inventory_lab.domain.events import DemandEvent
from inventory_lab.ports.clock import Clock


class DemandGenerator(ABC):
    """Produces a demand stream. Historical replay and synthetic generation are peers."""

    @abstractmethod
    def generate(
        self, horizon_days: int, rng: Random, clock: Clock
    ) -> Iterator[DemandEvent]: ...

    @abstractmethod
    def describe(self) -> str: ...


@runtime_checkable
class ForecastReader(Protocol):
    """What planning needs: two numbers. Nothing else."""

    @property
    def mean_daily(self) -> float: ...

    @property
    def std_daily(self) -> float: ...


@runtime_checkable
class DemandObserver(Protocol):
    """What the engine needs: a write-only sink for realised demand."""

    def observe(self, day: int, quantity: int) -> None: ...


class DemandSource(ABC):
    """Optional convenience for a replayable historical series."""

    @abstractmethod
    def history(self) -> Sequence[int]: ...
