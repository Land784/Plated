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
from menu.macros import NUTRIENTS, Goal
from menu.planner import (
    DEFAULT_MAX_ITEM_CALORIES,
    DEFAULT_MAX_SERVINGS_PER_ITEM,
    DEFAULT_MAX_TOTAL_SERVINGS,
    DEFAULT_MIN_ITEM_PROTEIN_G,
    MAX_TOTAL_SERVINGS_LIMIT,
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
DEFAULT_MAX_ITEMS = 4
DEFAULT_HALLS = ("north-dining-hall", "south-dining-hall")


class UserConfigError(ValueError):
    """Raised when a subscriber file is malformed."""


GOAL_KEYS = ("target", "min", "max", "tolerance")


@dataclass
class MacrosConfig:
    """The ``[macros]`` table: nutrient goals that turn on meal picks.

    ``goals`` apply to every meal. ``meals`` holds per-meal overrides
    (``[macros.brunch]``), merged over ``goals`` one nutrient at a time,
    so an override that only sets protein keeps the default fat limit.
    """

    goals: dict[str, Goal] = field(default_factory=dict)
    meals: dict[str, dict[str, Goal]] = field(default_factory=dict)

    def for_meal(self, meal: str) -> dict[str, Goal]:
        return {**self.goals, **self.meals.get(meal, {})}


@dataclass
class PicksConfig:
    """The ``[picks]`` table: how picks are chosen, not what they aim for.

    Every field has a default, so the table is optional. The protein
    floor and calorie ceiling are the planner's eligibility rules (see
    menu/planner.py for why they exist).
    """

    min_item_protein_g: float = DEFAULT_MIN_ITEM_PROTEIN_G
    max_item_calories: float | None = DEFAULT_MAX_ITEM_CALORIES
    max_servings_per_item: int = DEFAULT_MAX_SERVINGS_PER_ITEM
    max_total_servings: int = DEFAULT_MAX_TOTAL_SERVINGS
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
    # None means no meal picks, just the station digest.
    macros: MacrosConfig | None = None
    picks: PicksConfig = field(default_factory=PicksConfig)

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


def _parse_goal(raw: object, where: str) -> Goal:
    if not isinstance(raw, dict):
        raise UserConfigError(f"{where}: expected a table like {{ target = 70 }}, got {raw!r}")
    unknown = set(raw) - set(GOAL_KEYS)
    if unknown:
        raise UserConfigError(
            f"{where}: unknown key(s) {', '.join(sorted(unknown))}; use {', '.join(GOAL_KEYS)}"
        )
    if not raw.keys() & {"target", "min", "max"}:
        raise UserConfigError(f"{where}: needs at least one of target, min, max")

    parts = {
        key: _parse_number(raw[key], f"{where} {key}", allow_zero=key != "target")
        for key in GOAL_KEYS
        if key in raw
    }
    if "tolerance" in parts and "target" not in parts:
        raise UserConfigError(f"{where}: tolerance only applies to a target")
    goal = Goal(**parts)
    low, high = goal.bounds()
    if low > high:
        raise UserConfigError(f"{where}: min, max and target leave no allowed range")
    return goal


def _parse_goal_table(raw: dict, where: str) -> dict[str, Goal]:
    return {nutrient: _parse_goal(value, f"{where}.{nutrient}") for nutrient, value in raw.items()}


def _parse_macros(raw: object, where: str) -> MacrosConfig | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise UserConfigError(f"{where}: [macros] must be a table")

    nutrients = ", ".join(NUTRIENTS)
    config = MacrosConfig()
    for key, value in raw.items():
        if key in NUTRIENTS:
            config.goals[key] = _parse_goal(value, f"{where} macros.{key}")
        elif isinstance(value, dict) and value and set(value) <= set(NUTRIENTS):
            # A meal override such as [macros.brunch]. Meal slugs are not
            # validated, matching [schedule].
            config.meals[key.strip().lower()] = _parse_goal_table(value, f"{where} macros.{key}")
        elif isinstance(value, dict) and set(value) <= set(GOAL_KEYS):
            raise UserConfigError(
                f"{where}: macros.{key} is not a nutrient; choose from {nutrients}"
            )
        else:
            raise UserConfigError(
                f"{where}: macros.{key} must be a nutrient goal or a meal override whose "
                f"keys are nutrients ({nutrients})"
            )

    sets = {"[macros]": config.goals} if config.goals else {}
    sets.update({f"[macros.{m}]": config.for_meal(m) for m in config.meals})
    if not sets:
        raise UserConfigError(f"{where}: [macros] has no goals")
    for label, goals in sets.items():
        if not any(g.drives_picks for g in goals.values()):
            raise UserConfigError(
                f"{where}: {label} needs at least one target or min; "
                "limits alone are met by eating nothing"
            )
    return config


def _parse_picks(raw: object, where: str) -> PicksConfig:
    if raw is None:
        return PicksConfig()
    if not isinstance(raw, dict):
        raise UserConfigError(f"{where}: [picks] must be a table")
    known = set(PicksConfig.__dataclass_fields__)
    unknown = set(raw) - known
    if unknown:
        raise UserConfigError(
            f"{where}: [picks] unknown key(s) {', '.join(sorted(unknown))}; "
            f"use {', '.join(sorted(known))}"
        )

    config = PicksConfig()
    if "min_item_protein_g" in raw:
        config.min_item_protein_g = _parse_number(
            raw["min_item_protein_g"], f"{where} [picks] min_item_protein_g", allow_zero=True
        )
    if "max_item_calories" in raw:
        # A database row can null the ceiling to disable it; TOML has no null.
        ceiling = raw["max_item_calories"]
        config.max_item_calories = (
            None
            if ceiling is None
            else _parse_number(ceiling, f"{where} [picks] max_item_calories", allow_zero=False)
        )
    if "max_servings_per_item" in raw:
        config.max_servings_per_item = _parse_whole(
            raw["max_servings_per_item"],
            f"{where} [picks] max_servings_per_item",
            low=1,
            high=MAX_TOTAL_SERVINGS_LIMIT,
        )
    if "max_total_servings" in raw:
        config.max_total_servings = _parse_whole(
            raw["max_total_servings"],
            f"{where} [picks] max_total_servings",
            low=1,
            high=MAX_TOTAL_SERVINGS_LIMIT,
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
            f"{source}: the [protein] table was replaced by [macros] (goals such as "
            "protein = { target = 70 }) and [picks] (item limits and allergens); "
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
