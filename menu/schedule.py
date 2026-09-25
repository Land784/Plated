"""Decide which meals are due to send on this run.

A run is due to send every meal whose scheduled time has passed within
the last ``window`` minutes. Runs are started two ways, and neither is
trusted to be on time:

- A database check in Supabase (supabase/migrations/) wakes the runner
  within five minutes of a scheduled meal. This is the on-time path.
- GitHub's own schedule, every few hours, as a heartbeat and catch-up
  sweep. GitHub treats schedules as best effort: in September 2026 a
  */30 cron ran only 5-6 times a day, so a design that needed a run
  inside a meal's 30-minute slot sent nothing at all for four days.

Looking back over a window makes a late run still deliver. Several runs
can see the same meal, so sends are claimed in Supabase's sent_meals
table first (menu/supabase_users.py); a meal already claimed is skipped.

Everything is evaluated in the subscriber's own timezone. That matters
for more than politeness: after about 8pm Eastern the UTC date has
already rolled over, so using a UTC date would fetch tomorrow's menu.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from menu.users import WEEKDAYS, UserConfig

# A meal older than this is stale: lunch notifications at 2pm help no one.
DEFAULT_WINDOW_MINUTES = 45


@dataclass(frozen=True)
class DueMeal:
    """A meal that should be sent on this run."""

    meal: str
    #: Local calendar date whose menu should be fetched.
    local_date: date
    #: The subscriber's configured send time, as a local datetime.
    scheduled: datetime


def due_meals(
    user: UserConfig, now_utc: datetime, window_minutes: int = DEFAULT_WINDOW_MINUTES
) -> list[DueMeal]:
    """Meals whose local send time falls in (now - window, now], oldest first."""
    if window_minutes <= 0:
        raise ValueError("window_minutes must be positive")

    tz = user.zoneinfo
    now = now_utc.astimezone(tz)
    earliest = now - timedelta(minutes=window_minutes)

    due: list[DueMeal] = []
    # A window just after midnight reaches back into yesterday's schedule.
    for day in sorted({earliest.date(), now.date()}):
        for meal, at in user.schedule.get(WEEKDAYS[day.weekday()], {}).items():
            scheduled = datetime.combine(day, at, tzinfo=tz)
            if earliest < scheduled <= now:
                due.append(DueMeal(meal=meal, local_date=day, scheduled=scheduled))
    return sorted(due, key=lambda d: d.scheduled)
