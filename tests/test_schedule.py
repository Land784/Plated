from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from menu.schedule import DEFAULT_WINDOW_MINUTES, due_meals
from menu.users import UserConfig

EASTERN = ZoneInfo("America/New_York")


def _user(**schedule) -> UserConfig:
    return UserConfig(
        name="Test",
        ntfy_topic="t",
        timezone="America/New_York",
        stations=["Domer Diner"],
        schedule=schedule,
    )


def _utc(local: str) -> datetime:
    """Local Eastern wall time -> aware UTC datetime."""
    return datetime.fromisoformat(local).replace(tzinfo=EASTERN).astimezone(UTC)


def _meals(user, local_now: str, window: int = DEFAULT_WINDOW_MINUTES) -> list[str]:
    return [d.meal for d in due_meals(user, _utc(local_now), window)]


def test_meal_is_due_from_its_send_time():
    user = _user(monday={"lunch": time(11, 15)})
    # 2026-09-21 is a Monday.
    assert _meals(user, "2026-09-21T11:15") == ["lunch"]


def test_meal_is_never_sent_early():
    user = _user(monday={"lunch": time(11, 15)})
    assert _meals(user, "2026-09-21T11:14") == []


def test_a_late_run_within_the_window_still_sends():
    # GitHub ran the Thursday 11:15 slot's run at 11:52. It must deliver.
    user = _user(monday={"lunch": time(11, 15)})
    assert _meals(user, "2026-09-21T11:52") == ["lunch"]


def test_a_run_after_the_window_treats_the_meal_as_stale():
    user = _user(monday={"lunch": time(11, 15)})
    assert _meals(user, "2026-09-21T12:00") == []
    assert _meals(user, "2026-09-21T12:00", window=60) == ["lunch"]


def test_only_the_matching_weekday_schedule_is_used():
    user = _user(monday={"lunch": time(11, 15)}, tuesday={"dinner": time(11, 15)})
    assert _meals(user, "2026-09-21T11:20") == ["lunch"]
    assert _meals(user, "2026-09-22T11:20") == ["dinner"]


def test_late_evening_uses_local_date_not_utc_date():
    # At 20:00 Eastern the UTC date has already rolled to tomorrow. The
    # menu we fetch must still be today's local menu.
    user = _user(monday={"dinner": time(20, 0)})
    due = due_meals(user, _utc("2026-09-21T20:05"))
    assert [(d.meal, d.local_date) for d in due] == [("dinner", date(2026, 9, 21))]


def test_window_reaches_back_across_midnight():
    user = _user(monday={"late-snack": time(23, 50)})
    due = due_meals(user, _utc("2026-09-22T00:10"))
    assert [(d.meal, d.local_date) for d in due] == [("late-snack", date(2026, 9, 21))]


def test_several_due_meals_come_back_oldest_first():
    user = _user(monday={"dinner": time(11, 20), "lunch": time(11, 5)})
    assert _meals(user, "2026-09-21T11:30") == ["lunch", "dinner"]


def test_unscheduled_day_yields_nothing():
    user = _user(monday={"lunch": time(11, 15)})
    # 2026-09-20 is a Sunday, with no entry at all.
    assert _meals(user, "2026-09-20T11:20") == []


def test_window_must_be_positive():
    with pytest.raises(ValueError):
        due_meals(_user(), _utc("2026-09-21T11:00"), 0)
