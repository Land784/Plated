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
from menu.macros import DEFAULT_TOLERANCE_PCT, NUTRIENTS
from menu.planner import (
    DEFAULT_MAX_ITEM_CALORIES,
    DEFAULT_MAX_MAIN_SERVINGS,
    DEFAULT_SIDE_MIN_CALORIES,
)

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
DEFAULT_MAX_ITEMS = 3
# An item is a main at this much protein per listed serving (see
# menu/digest.py): in station lines and as the main of a picked plate.
DEFAULT_MAIN_PROTEIN_G = 10.0
DEFAULT_HALLS = ("north-dining-hall", "south-dining-hall")


class UserConfigError(ValueError):
    """Raised when a subscriber file is malformed."""


MAX_MAIN_SERVINGS_LIMIT = 3
# Plate rules replaced these; rows saved before the planner rebuild still
# carry them, so they are ignored rather than rejected.
RETIRED_PICKS_KEYS = frozenset(
    {"min_item_protein_g", "max_servings_per_item", "max_total_servings"}
)


@dataclass
class PicksConfig:
    """The ``[picks]`` table: whether picks are on and how plates are built.

    Every field has a default, so the table is optional. What a plate
    aims for is ``[macros]``; see menu/planner.py for the plate rules.
    """

    enabled: bool = False
    tolerance_pct: float = DEFAULT_TOLERANCE_PCT
    side_min_calories: float = DEFAULT_SIDE_MIN_CALORIES
    max_main_servings: int = DEFAULT_MAX_MAIN_SERVINGS
    # Rows over this are bulk recipe quantities, never mains or sides.
    max_item_calories: float | None = DEFAULT_MAX_ITEM_CALORIES
    exclude_allergens: list[str] = field(default_factory=list)
    unknown_allergens: UnknownAllergenPolicy = UnknownAllergenPolicy.FLAG


@dataclass
class UserConfig:
    name: str
    ntfy_topic: str
    # Supabase row id; None for a subscriber loaded from a TOML file.
    id: str | None = None
    timezone: str = DEFAULT_TIMEZONE
    halls: list[str] = field(default_factory=lambda: list(DEFAULT_HALLS))
    stations: list[str] = field(default_factory=list)
    # Stations the subscriber starred in the web app. Already first in
    # ``stations``, which is what the push renders; kept so the app knows
    # which are starred.
    favorites: list[str] = field(default_factory=list)
    max_items_per_station: int = DEFAULT_MAX_ITEMS
    main_protein_g: float = DEFAULT_MAIN_PROTEIN_G
    # weekday -> meal slug -> local send time
    schedule: dict[str, dict[str, time]] = field(default_factory=dict)
    # Per-meal targets by nutrient (protein, carbs, fat, calories).
    macros: dict[str, float] = field(default_factory=dict)
    picks: PicksConfig = field(default_factory=PicksConfig)

    @property
    def picks_on(self) -> bool:
        return self.picks.enabled and bool(self.macros)

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


def _parse_number(raw: object, where: str, *, allow_zero: bool) -> float:
    # bool is an int subclass; `target = true` is a typo, not a number.
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise UserConfigError(f"{where}: expected a number, got {raw!r}")
    if raw < 0 or (raw == 0 and not allow_zero):
        wanted = "a number >= 0" if allow_zero else "a positive number"
        raise UserConfigError(f"{where}: expected {wanted}, got {raw!r}")
    return float(raw)


def _parse_whole(raw: object, where: str, *, low: int, high: int) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or not low <= raw <= high:
        raise UserConfigError(f"{where}: expected a whole number from {low} to {high}, got {raw!r}")
    return raw


def _parse_macros(raw: object, where: str) -> dict[str, float]:
    """``protein = 60`` style targets; a database null clears one."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise UserConfigError(f"{where}: [macros] must be a table")
    nutrients = ", ".join(NUTRIENTS)
    targets: dict[str, float] = {}
    for key, value in raw.items():
        if key not in NUTRIENTS:
            raise UserConfigError(f"{where}: macros.{key} is not a target; choose from {nutrients}")
        if isinstance(value, dict):
            raise UserConfigError(
                f"{where}: macros.{key} is now a plain number (protein = 60); "
                "min/max goals were removed"
            )
        if value is not None:
            targets[key] = _parse_number(value, f"{where} macros.{key}", allow_zero=False)
    return targets


def _parse_picks(raw: object, where: str) -> PicksConfig:
    if raw is None:
        return PicksConfig()
    if not isinstance(raw, dict):
        raise UserConfigError(f"{where}: [picks] must be a table")
    known = set(PicksConfig.__dataclass_fields__)
    unknown = set(raw) - known - RETIRED_PICKS_KEYS
    if unknown:
        raise UserConfigError(
            f"{where}: [picks] unknown key(s) {', '.join(sorted(unknown))}; "
            f"use {', '.join(sorted(known))}"
        )

    config = PicksConfig()
    if "enabled" in raw:
        if not isinstance(raw["enabled"], bool):
            raise UserConfigError(f"{where} [picks] enabled: expected true or false")
        config.enabled = raw["enabled"]
    if "tolerance_pct" in raw:
        config.tolerance_pct = _parse_number(
            raw["tolerance_pct"], f"{where} [picks] tolerance_pct", allow_zero=False
        )
    if "side_min_calories" in raw:
        config.side_min_calories = _parse_number(
            raw["side_min_calories"], f"{where} [picks] side_min_calories", allow_zero=True
        )
    if "max_main_servings" in raw:
        config.max_main_servings = _parse_whole(
            raw["max_main_servings"],
            f"{where} [picks] max_main_servings",
            low=1,
            high=MAX_MAIN_SERVINGS_LIMIT,
        )
    if "max_item_calories" in raw:
        # A database row can null the ceiling to disable it; TOML has no null.
        ceiling = raw["max_item_calories"]
        config.max_item_calories = (
            None
            if ceiling is None
            else _parse_number(ceiling, f"{where} [picks] max_item_calories", allow_zero=False)
        )
    if "exclude_allergens" in raw:
        allergens = raw["exclude_allergens"]
        if not isinstance(allergens, list) or not all(isinstance(a, str) for a in allergens):
            raise UserConfigError(f"{where} [picks] exclude_allergens: must be a list of strings")
        config.exclude_allergens = [a.strip() for a in allergens if a.strip()]
    if "unknown_allergens" in raw:
        policy = raw["unknown_allergens"]
        try:
            config.unknown_allergens = UnknownAllergenPolicy(policy)
        except ValueError as exc:
            choices = ", ".join(p.value for p in UnknownAllergenPolicy)
            raise UserConfigError(
                f"{where} [picks] unknown_allergens: expected one of {choices}, got {policy!r}"
            ) from exc
    return config


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

    if "protein" in data:
        raise UserConfigError(
            f"{source}: the [protein] table was replaced by [macros] (targets such as "
            "protein = 60) and [picks] (on/off, plate rules and allergens); "
            "see users.example.toml"
        )

    timezone = data.get("timezone", DEFAULT_TIMEZONE)
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise UserConfigError(f"{source}: unknown timezone {timezone!r}") from exc

    stations = data.get("stations", [])
    if not isinstance(stations, list) or not all(isinstance(s, str) for s in stations):
        raise UserConfigError(f"{source}: 'stations' must be a list of strings")

    favorites = data.get("favorites", [])
    if not isinstance(favorites, list) or not all(isinstance(s, str) for s in favorites):
        raise UserConfigError(f"{source}: 'favorites' must be a list of strings")

    halls = data.get("halls", list(DEFAULT_HALLS))
    if not isinstance(halls, list) or not halls:
        raise UserConfigError(f"{source}: 'halls' must be a non-empty list")

    subscriber_id = data.get("id")
    if subscriber_id is not None and not isinstance(subscriber_id, str):
        raise UserConfigError(f"{source}: 'id' must be a string")

    return UserConfig(
        name=name.strip(),
        ntfy_topic=topic.strip(),
        id=subscriber_id,
        timezone=timezone,
        halls=list(halls),
        stations=list(stations),
        favorites=list(favorites),
        max_items_per_station=int(data.get("max_items_per_station", DEFAULT_MAX_ITEMS)),
        # A row from before the column existed has no key, so it gets the default.
        main_protein_g=_parse_number(
            data.get("main_protein_g", DEFAULT_MAIN_PROTEIN_G),
            f"{source} main_protein_g",
            allow_zero=True,
        ),
        schedule=_parse_schedule(data.get("schedule"), source),
        macros=_parse_macros(data.get("macros"), source),
        picks=_parse_picks(data.get("picks"), source),
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
