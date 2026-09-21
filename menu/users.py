"""Per-user subscriber config.

Each subscriber is one TOML file in a directory. Real subscriber files
live in the private runner repo, never here -- an ntfy topic is open
pub/sub, so anyone who learns a topic name can both read it and publish
to it.

Note that every ``*.toml`` in the directory is treated as a live
subscriber, which is why the template is kept outside it, at
``users.example.toml``. A placeholder left in ``users/`` would be sent
to for real.

Loading is strict and fails loudly: a malformed file raises rather than
being skipped, because a silently skipped subscriber is a subscriber who
quietly stops getting notifications and never finds out.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

DEFAULT_TIMEZONE = "America/New_York"
DEFAULT_MAX_ITEMS = 4
DEFAULT_HALLS = ("north-dining-hall", "south-dining-hall")


class UserConfigError(ValueError):
    """Raised when a subscriber file is malformed."""


@dataclass
class UserConfig:
    name: str
    ntfy_topic: str
    timezone: str = DEFAULT_TIMEZONE
    halls: list[str] = field(default_factory=lambda: list(DEFAULT_HALLS))
    stations: list[str] = field(default_factory=list)
    max_items_per_station: int = DEFAULT_MAX_ITEMS
    # weekday -> meal slug -> local send time
    schedule: dict[str, dict[str, time]] = field(default_factory=dict)

    @property
    def zoneinfo(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


def _parse_time(raw: object, where: str) -> time:
    if not isinstance(raw, str):
        raise UserConfigError(f'{where}: expected a "HH:MM" string, got {raw!r}')
    parts = raw.strip().split(":")
    if len(parts) != 2:
        raise UserConfigError(f'{where}: expected "HH:MM", got {raw!r}')
    try:
        hour, minute = int(parts[0]), int(parts[1])
        return time(hour=hour, minute=minute)
    except ValueError as exc:
        raise UserConfigError(f"{where}: invalid time {raw!r}") from exc


def _parse_schedule(raw: object, where: str) -> dict[str, dict[str, time]]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise UserConfigError(f"{where}: [schedule] must be a table")

    schedule: dict[str, dict[str, time]] = {}
    for day, meals in raw.items():
        key = day.strip().lower()
        if key not in WEEKDAYS:
            raise UserConfigError(
                f"{where}: unknown weekday {day!r}; expected one of {', '.join(WEEKDAYS)}"
            )
        if not isinstance(meals, dict):
            raise UserConfigError(f'{where}: [schedule.{key}] must be a table of meal = "HH:MM"')
        # Meal slugs are passed through unvalidated on purpose: Nutrislice
        # can add menu types, and an unknown slug simply returns an empty
        # menu, which already alerts the owner via a failed run.
        schedule[key] = {
            meal.strip().lower(): _parse_time(value, f"{where} [schedule.{key}] {meal}")
            for meal, value in meals.items()
        }
    return schedule


def parse_user(data: dict, source: str) -> UserConfig:
    """Build a UserConfig from already-parsed TOML data."""
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise UserConfigError(f"{source}: 'name' is required")

    topic = data.get("ntfy_topic")
    if not isinstance(topic, str) or not topic.strip():
        raise UserConfigError(f"{source}: 'ntfy_topic' is required")

    timezone = data.get("timezone", DEFAULT_TIMEZONE)
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise UserConfigError(f"{source}: unknown timezone {timezone!r}") from exc

    stations = data.get("stations", [])
    if not isinstance(stations, list) or not all(isinstance(s, str) for s in stations):
        raise UserConfigError(f"{source}: 'stations' must be a list of strings")

    halls = data.get("halls", list(DEFAULT_HALLS))
    if not isinstance(halls, list) or not halls:
        raise UserConfigError(f"{source}: 'halls' must be a non-empty list")

    return UserConfig(
        name=name.strip(),
        ntfy_topic=topic.strip(),
        timezone=timezone,
        halls=list(halls),
        stations=list(stations),
        max_items_per_station=int(data.get("max_items_per_station", DEFAULT_MAX_ITEMS)),
        schedule=_parse_schedule(data.get("schedule"), source),
    )


def load_users(directory: Path) -> list[UserConfig]:
    """Load every ``*.toml`` subscriber file in ``directory``, sorted by filename."""
    if not directory.is_dir():
        raise UserConfigError(f"users directory not found: {directory}")

    users: list[UserConfig] = []
    for path in sorted(directory.glob("*.toml")):
        with path.open("rb") as handle:
            data = tomllib.load(handle)
        users.append(parse_user(data, source=path.name))
    return users
