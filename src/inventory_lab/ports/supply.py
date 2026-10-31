"""Lead-time uncertainty is a first-class abstraction: safety stock depends on its variance."""

from __future__ import annotations

from abc import ABC, abstractmethod
from random import Random


class LeadTimeModel(ABC):
    @property
    @abstractmethod
    def mean_days(self) -> float: ...

    @property
    @abstractmethod
    def std_days(self) -> float: ...

    @abstractmethod
    def sample(self, rng: Random) -> float: ...
