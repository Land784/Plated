from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from menu.schedule import due_meals, slot_bounds
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


def test_slot_bounds_floors_to_the_interval():
    start, end = slot_bounds(_utc("2026-09-21T11:17"), EASTERN, 30)
    assert start.hour == 11 and start.minute == 0
    assert end.hour == 11 and end.minute == 30


def test_meal_fires_in_the_slot_containing_its_time():
    # Monday lunch at 11:15 belongs to the 11:00-11:30 slot.
    user = _user(monday={"lunch": time(11, 15)})
    assert [d.meal for d in due_meals(user, _utc("2026-09-21T11:00"), 30)] == ["lunch"]


def test_meal_does_not_fire_in_the_neighbouring_slot():
    user = _user(monday={"lunch": time(11, 15)})
    assert due_meals(user, _utc("2026-09-21T10:30"), 30) == []
    assert due_meals(user, _utc("2026-09-21T11:30"), 30) == []


def test_run_delayed_less_than_one_interval_still_fires_once():
    # A run scheduled for 11:00 that actually executes at 11:22 floors
    # back into the 11:00 slot, so the meal is not missed.
    user = _user(monday={"lunch": time(11, 15)})
    delayed = due_meals(user, _utc("2026-09-21T11:22"), 30)
    assert [d.meal for d in delayed] == ["lunch"]


def test_only_todays_weekday_schedule_is_used():
    user = _user(
        monday={"lunch": time(11, 15)},
        tuesday={"dinner": time(11, 15)},
    )
    # 2026-09-21 is a Monday, 2026-09-22 a Tuesday.
    assert [d.meal for d in due_meals(user, _utc("2026-09-21T11:00"), 30)] == ["lunch"]
    assert [d.meal for d in due_meals(user, _utc("2026-09-22T11:00"), 30)] == ["dinner"]


def test_late_evening_uses_local_date_not_utc_date():
    # At 20:00 Eastern the UTC date has already rolled to tomorrow. The
    # menu we fetch must still be today's local menu.
    user = _user(monday={"dinner": time(20, 0)})
    due = due_meals(user, _utc("2026-09-21T20:00"), 30)
    assert len(due) == 1
    assert due[0].local_date == date(2026, 9, 21)


def test_multiple_meals_in_one_slot_are_returned_in_time_order():
    user = _user(monday={"dinner": time(11, 20), "lunch": time(11, 5)})
    assert [d.meal for d in due_meals(user, _utc("2026-09-21T11:00"), 30)] == [
        "lunch",
        "dinner",
    ]


def test_unscheduled_day_yields_nothing():
    user = _user(monday={"lunch": time(11, 15)})
    # Sunday has no entry at all.
    assert due_meals(user, _utc("2026-09-20T11:00"), 30) == []


def test_interval_changes_slot_width():
    user = _user(monday={"lunch": time(11, 50)})
    # 11:50 is outside the 11:00-11:30 half-hour slot but inside the
    # 11:00-12:00 hourly one.
    assert due_meals(user, _utc("2026-09-21T11:00"), 30) == []
    assert [d.meal for d in due_meals(user, _utc("2026-09-21T11:00"), 60)] == ["lunch"]
