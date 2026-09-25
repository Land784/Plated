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

from menu.allergens import UnknownAllergenPolicy
from menu.planner import DEFAULT_MAX_ITEM_CALORIES, DEFAULT_MIN_ITEM_PROTEIN_G

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
class ProteinConfig:
    """Optional ``[protein]`` table: turns on per-hall protein picks.

    Only ``target_g`` is required. The two per-item limits are the
    planner's eligibility rules (see menu/planner.py for why they exist).
    """

    target_g: float
    min_item_protein_g: float = DEFAULT_MIN_ITEM_PROTEIN_G
    max_item_calories: float | None = DEFAULT_MAX_ITEM_CALORIES
    calorie_cap: float | None = None
    exclude_allergens: list[str] = field(default_factory=list)
    unknown_allergens: UnknownAllergenPolicy = UnknownAllergenPolicy.FLAG


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
    # None means no protein picks, just the station digest.
    protein: ProteinConfig | None = None

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


def _parse_positive_number(raw: object, where: str) -> float:
    # bool is an int subclass; `target_g = true` is a typo, not a number.
    if isinstance(raw, bool) or not isinstance(raw, int | float) or raw <= 0:
        raise UserConfigError(f"{where}: expected a positive number, got {raw!r}")
    return float(raw)


def _parse_protein(raw: object, where: str) -> ProteinConfig | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise UserConfigError(f"{where}: [protein] must be a table")

    if "target_g" not in raw:
        raise UserConfigError(f"{where}: [protein] requires 'target_g'")
    target = _parse_positive_number(raw["target_g"], f"{where} [protein] target_g")

    floor = raw.get("min_item_protein_g", DEFAULT_MIN_ITEM_PROTEIN_G)
    if isinstance(floor, bool) or not isinstance(floor, int | float) or floor < 0:
        raise UserConfigError(
            f"{where} [protein] min_item_protein_g: expected a number >= 0, got {floor!r}"
        )

    ceiling = raw.get("max_item_calories", DEFAULT_MAX_ITEM_CALORIES)
    cap = raw.get("calorie_cap")

    allergens = raw.get("exclude_allergens", [])
    if not isinstance(allergens, list) or not all(isinstance(a, str) for a in allergens):
        raise UserConfigError(f"{where} [protein] exclude_allergens: must be a list of strings")

    policy = raw.get("unknown_allergens", UnknownAllergenPolicy.FLAG.value)
    try:
        unknown = UnknownAllergenPolicy(policy)
    except ValueError as exc:
        choices = ", ".join(p.value for p in UnknownAllergenPolicy)
        raise UserConfigError(
            f"{where} [protein] unknown_allergens: expected one of {choices}, got {policy!r}"
        ) from exc

    return ProteinConfig(
        target_g=target,
        min_item_protein_g=float(floor),
        # A database row can null the ceiling to disable it; TOML has no null.
        max_item_calories=(
            None
            if ceiling is None
            else _parse_positive_number(ceiling, f"{where} [protein] max_item_calories")
        ),
        calorie_cap=(
            None if cap is None else _parse_positive_number(cap, f"{where} [protein] calorie_cap")
        ),
        exclude_allergens=[a.strip() for a in allergens if a.strip()],
        unknown_allergens=unknown,
    )


def parse_user(data: dict, source: str) -> UserConfig:
    """Build a UserConfig from already-parsed TOML data or a database row.

    Both sources share this one validation path; see
    menu/supabase_users.py for the row shape.
    """
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
        protein=_parse_protein(data.get("protein"), source),
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
