"""Review calendars: continuous, every R days, or 'every Friday evening'."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from math import floor, isclose

from inventory_lab.core.registry import BuildContext, ComponentRegistry
from inventory_lab.domain.base import NonNegativeFloat, PositiveInt, ValueObject
from inventory_lab.domain.errors import ConfigurationError, SimulationError
from inventory_lab.ports.clock import Clock, ReviewSchedule

schedule_registry: ComponentRegistry[ReviewSchedule] = ComponentRegistry("schedule")
_TOL = 1e-6


class ContinuousReview(ReviewSchedule):
    """(s,Q) semantics: an order can be made at any time."""

    reviews_on_change = True
    reviews_on_schedule = False
    expected_review_period_days = 0.0

    def next_after(self, now: float) -> float | None:
        return None

    def occurs_at(self, now: float, tol: float = _TOL) -> bool:
        return True

    def describe(self) -> str:
        return "continuous"


class FixedIntervalReview(ReviewSchedule):
    """Every R days, offset from the epoch (MRP/DRP bucket semantics)."""

    reviews_on_change = False
    reviews_on_schedule = True

    def __init__(self, period_days: float, offset_days: float = 0.0) -> None:
        if period_days <= 0:
            raise ConfigurationError("review period R must be positive")
        self._period, self._offset = period_days, offset_days

    @property
    def expected_review_period_days(self) -> float:
        return self._period

    def next_after(self, now: float) -> float:
        k = floor((now - self._offset) / self._period) + 1
        candidate = self._offset + k * self._period
        if candidate <= now + _TOL:
            candidate += self._period
        return max(candidate, self._offset)

    def occurs_at(self, now: float, tol: float = _TOL) -> bool:
        if now < self._offset - tol:
            return False
        k = round((now - self._offset) / self._period)
        return k >= 0 and isclose(self._offset + k * self._period, now, abs_tol=tol)

    def describe(self) -> str:
        return f"every {self._period:g}d (offset {self._offset:g})"


class WeeklyReview(ReviewSchedule):
    """Real calendars: 'every Friday at 18:00' so the supplier ships Monday."""

    reviews_on_change = False
    reviews_on_schedule = True

    def __init__(self, clock: Clock, weekdays: tuple[int, ...], hour: int = 18) -> None:
        if not weekdays or any(not 0 <= d <= 6 for d in weekdays):
            raise ConfigurationError(
                "weekdays must be a non-empty subset of 0..6 (Mon=0)"
            )
        if not 0 <= hour <= 23:
            raise ConfigurationError("hour must be in 0..23")
        self._clock, self._weekdays, self._hour = (
            clock,
            tuple(sorted(set(weekdays))),
            hour,
        )

    @property
    def expected_review_period_days(self) -> float:
        return 7.0 / len(self._weekdays)

    def _to_time(self, dt: datetime) -> float:
        return (dt - self._clock.start).total_seconds() / 86_400.0

    def next_after(self, now: float) -> float:
        current = self._clock.to_datetime(now)
        for add in range(8):
            day = (current + timedelta(days=add)).date()
            if day.weekday() not in self._weekdays:
                continue
            candidate = datetime.combine(
                day, time(hour=self._hour), tzinfo=current.tzinfo
            )
            t = self._to_time(candidate)
            if t > now + _TOL:
                return t
        raise SimulationError(
            "weekly schedule failed to find a next review within 8 days"
        )

    def occurs_at(self, now: float, tol: float = _TOL) -> bool:
        dt = self._clock.to_datetime(now)
        if dt.weekday() not in self._weekdays:
            return False
        target = dt.replace(hour=self._hour, minute=0, second=0, microsecond=0)
        return abs(self._to_time(target) - now) <= tol

    def describe(self) -> str:
        names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        return f"weekly on {','.join(names[d] for d in self._weekdays)} @{self._hour:02d}:00"


class ContinuousConfig(ValueObject):
    pass


class IntervalConfig(ValueObject):
    period_days: NonNegativeFloat
    offset_days: NonNegativeFloat = 0.0


class WeeklyConfig(ValueObject):
    weekdays: tuple[PositiveInt, ...] | tuple[int, ...] = (4,)
    hour: int = 18


@schedule_registry.register("continuous", ContinuousConfig)
def _build_continuous(config: ContinuousConfig, ctx: BuildContext) -> ReviewSchedule:
    return ContinuousReview()


@schedule_registry.register("interval", IntervalConfig)
def _build_interval(config: IntervalConfig, ctx: BuildContext) -> ReviewSchedule:
    return FixedIntervalReview(config.period_days, config.offset_days)


@schedule_registry.register("weekly", WeeklyConfig)
def _build_weekly(config: WeeklyConfig, ctx: BuildContext) -> ReviewSchedule:
    return WeeklyReview(ctx.clock, tuple(config.weekdays), config.hour)
