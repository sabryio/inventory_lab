"""Time abstractions: calendars are a policy concern, not an engine concern."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime


class Clock(ABC):
    """Maps simulation time (float days) onto wall-clock semantics."""

    @property
    @abstractmethod
    def start(self) -> datetime: ...

    @abstractmethod
    def to_datetime(self, t: float) -> datetime: ...

    def day_index(self, t: float) -> int:
        return int(t)


class ReviewSchedule(ABC):
    """WHEN a policy is allowed to look at stock.

    Two independent capabilities, because a multi-source composite may need both:
      * reviews_on_change   -> continuous review (any time)
      * reviews_on_schedule -> periodic review (calendar wake-ups)
    """

    @property
    @abstractmethod
    def reviews_on_change(self) -> bool: ...

    @property
    @abstractmethod
    def reviews_on_schedule(self) -> bool: ...

    @property
    @abstractmethod
    def expected_review_period_days(self) -> float:
        """R used for safety stock. 0 for pure continuous review."""

    @abstractmethod
    def next_after(self, now: float) -> float | None:
        """Next scheduled review strictly after `now`, or None if not calendar-driven."""

    @abstractmethod
    def occurs_at(self, now: float, tol: float = 1e-6) -> bool:
        """Is `now` a review opportunity? Continuous schedules always say yes."""

    @abstractmethod
    def describe(self) -> str: ...
