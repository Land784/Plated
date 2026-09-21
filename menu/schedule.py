"""Decide which meals are due to send on this run.

GitHub Actions cron fires on a fixed interval and is regularly delayed
several minutes under load, so "is it time?" cannot be answered by
comparing against an exact clock time.

Instead each run owns one time *slot*. The run floors its own wall-clock
time to the polling interval and sends any meal whose scheduled time
falls inside that slot. Flooring the actual run time is what makes this
tolerant of delay: a run that fires late but by less than one full
interval still floors into the slot it was scheduled for. Only a delay
longer than the whole interval can duplicate or skip a meal, which is an
accepted tradeoff -- the failure mode is seeing a menu twice.

Everything is evaluated in the subscriber's own timezone. That matters
for more than politeness: after about 8pm Eastern the UTC date has
already rolled over, so using a UTC date would fetch tomorrow's menu.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from menu.users import WEEKDAYS, UserConfig


@dataclass(frozen=True)
class DueMeal:
    """A meal that should be sent on this run."""

    meal: str
    #: Local calendar date whose menu should be fetched.
    local_date: date
    #: The subscriber's configured send time, as a local datetime.
    scheduled: datetime


def slot_bounds(
    now_utc: datetime, tz: ZoneInfo, interval_minutes: int
) -> tuple[datetime, datetime]:
    """Return the [start, end) local-time slot containing ``now_utc``."""
    if interval_minutes <= 0:
        raise ValueError("interval_minutes must be positive")

    local = now_utc.astimezone(tz).replace(second=0, microsecond=0)
    start = local - timedelta(minutes=local.minute % interval_minutes)
    return start, start + timedelta(minutes=interval_minutes)


def due_meals(user: UserConfig, now_utc: datetime, interval_minutes: int) -> list[DueMeal]:
    """Meals from ``user``'s schedule whose time falls in this run's slot."""
    start, end = slot_bounds(now_utc, user.zoneinfo, interval_minutes)
    todays = user.schedule.get(WEEKDAYS[start.weekday()], {})

    due: list[DueMeal] = []
    for meal, at in sorted(todays.items(), key=lambda kv: kv[1]):
        target = start.replace(hour=at.hour, minute=at.minute)
        if start <= target < end:
            due.append(DueMeal(meal=meal, local_date=start.date(), scheduled=target))
    return due
