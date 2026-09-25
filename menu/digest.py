"""Turn a day's raw menu into a short, station-grouped digest.

Nutrislice does not attach a station *name* to regular menu items -- they
only carry a numeric ``station_id``. The human-readable name ("Domer
Diner", "La Mesa") appears only on the ``is_station_header`` row that
precedes that station's items, in its ``text`` field. So grouping
requires walking a day's items in order and tracking the current header.

Station names are also not consistent between halls: North publishes
"The Global Compass" while South publishes "Global Compass" for what is
effectively the same station. All matching therefore goes through
:func:`normalize_station`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from menu.allergens import has_known_allergen_data
from menu.macros import describe_goal
from menu.models import DayMenu, MenuItem
from menu.planner import MealPlan, PlannedItem, plan_meal
from menu.users import MacrosConfig, PicksConfig

_WHITESPACE = re.compile(r"\s+")
_LEADING_ARTICLE = re.compile(r"^the\s+")

# Nutrislice mixes dietary labels into the same tag list as allergens,
# with identical metadata (see AllergenTag in menu/models.py). These are
# hidden from the allergen display. It is deliberately a list of known
# NON-allergens rather than of allergens: a tag name nobody anticipated
# stays visible instead of being silently dropped.
_DIETARY_LABELS = frozenset({"vegan", "vegetarian", "high performance"})


@dataclass
class Station:
    """A station header and the items served under it, in menu order."""

    name: str
    items: list[MenuItem] = field(default_factory=list)

    @property
    def dish_names(self) -> list[str]:
        """Item names, de-duplicated, preserving menu order.

        Real feeds repeat rows (South listed "Sliced Red Onion" twice in
        one station), which reads as a bug in a notification.
        """
        seen: set[str] = set()
        names: list[str] = []
        for item in self.items:
            if item.food is None:
                continue
            name = item.food.name.strip()
            if not name or name in seen:
                continue
            seen.add(name)
            names.append(name)
        return names


def normalize_station(name: str) -> str:
    """Normalize a station name for matching against an allowlist."""
    collapsed = _WHITESPACE.sub(" ", name).strip().lower()
    return _LEADING_ARTICLE.sub("", collapsed)


def group_by_station(day: DayMenu) -> list[Station]:
    """Group a day's items under their station headers, in menu order.

    Items appearing before any header are collected under an empty
    station name. Since filtering is allowlist-based, such items are
    dropped unless a caller explicitly asks for them.
    """
    stations: list[Station] = []
    current: Station | None = None

    for item in day.menu_items:
        if item.is_station_header:
            current = Station(name=(item.text or "").strip())
            stations.append(current)
            continue

        if item.food is None:
            continue

        if current is None:
            current = Station(name="")
            stations.append(current)

        current.items.append(item)

    return [s for s in stations if s.items]


def filter_stations(stations: list[Station], allowlist: list[str]) -> list[Station]:
    """Keep only stations whose normalized name is in ``allowlist``."""
    wanted = {normalize_station(name) for name in allowlist}
    return [s for s in stations if normalize_station(s.name) in wanted]


def render_stations(stations: list[Station], max_items: int) -> list[str]:
    """Render stations as display lines, capping items per station.

    Build-your-own stations enumerate ingredients rather than dishes
    (South's Pastaria lists 20 components), so an uncapped render is
    unusable on a phone. Truncation is always reported as "+N more"
    rather than hidden.
    """
    lines: list[str] = []
    for station in stations:
        names = station.dish_names
        if not names:
            continue
        lines.append(station.name)
        for name in names[:max_items]:
            lines.append(f"  {name}")
        remaining = len(names) - max_items
        if remaining > 0:
            lines.append(f"  +{remaining} more")
    return lines


def build_hall_section(
    hall_name: str,
    day: DayMenu | None,
    allowlist: list[str],
    max_items: int,
) -> list[str]:
    """Render one hall's section of the digest, or [] if it has nothing.

    Returning an empty list (rather than a "nothing here" line) lets the
    caller distinguish a hall with no matching food from one it should
    render, and lets a whole meal be detected as empty.
    """
    if day is None:
        return []
    stations = filter_stations(group_by_station(day), allowlist)
    body = render_stations(stations, max_items)
    if not body:
        return []
    return [hall_name.upper(), *body]


def _allergen_note(item: MenuItem) -> str:
    """Allergen tags as reported, or "allergens unknown".

    An item whose only tags are dietary labels ("High Performance") has
    no allergen information at all, and reads the same as an untagged
    item. Absence of a tag never means safe.
    """
    if not has_known_allergen_data(item):
        return "allergens unknown"
    names = [a.name for a in item.food.allergens if a.name.strip().lower() not in _DIETARY_LABELS]
    return ", ".join(names) if names else "allergens unknown"


def _amount(value: float | None, suffix: str) -> str:
    return f"{value:g}{suffix}" if value is not None else f"?{suffix}"


def _macro_line(values: dict[str, float | None]) -> str:
    """ "21P 0C 0F · 89 cal"; a nutrient Nutrislice left out shows as "?"."""
    return (
        f"{_amount(values['protein'], 'P')} {_amount(values['carbs'], 'C')} "
        f"{_amount(values['fat'], 'F')} · {_amount(values['calories'], ' cal')}"
    )


def _render_pick(planned: PlannedItem) -> list[str]:
    food = planned.item.food
    serving = food.serving_size if food else None
    # Numbers are one serving exactly as Nutrislice lists it, quirks and
    # all ("4 z"), because nutrients are only comparable per listed serving.
    listed = " ".join(p for p in (serving.amount, serving.unit) if p) if serving else ""
    size = f" ({listed})" if listed else ""
    name = food.name if food else "unknown item"
    count = f"{planned.servings}× " if planned.servings > 1 else ""
    return [
        f"  {count}{name}",
        f"     {_macro_line(planned.per_serving)}{size} · {_allergen_note(planned.item)}",
    ]


def _plan_headline(hall_name: str, plan: MealPlan) -> list[str]:
    headline = f"{hall_name}: {_macro_line(plan.totals)}"
    if plan.goals_met:
        return [headline]
    return [headline, f"  closest available: {', '.join(plan.misses)}"]


def build_picks_section(
    halls: list[tuple[str, DayMenu | None]],
    allowlist: list[str] | None,
    macros: MacrosConfig,
    picks: PicksConfig,
    meal: str,
) -> list[str]:
    """Render one combo per hall for ``meal``'s goals, or [] if none.

    Picks come only from the allowlisted stations (every station when
    ``allowlist`` is None), and each combo is planned from a single
    hall's items.
    """
    goals = macros.for_meal(meal)
    if not goals:
        return []

    lines: list[str] = []
    for hall_name, day in halls:
        if day is None:
            continue
        stations = group_by_station(day)
        if allowlist is not None:
            stations = filter_stations(stations, allowlist)
        items = [item for station in stations for item in station.items]
        plan = plan_meal(
            items,
            goals,
            excluded_allergens=set(picks.exclude_allergens),
            unknown_policy=picks.unknown_allergens,
            min_item_protein_g=picks.min_item_protein_g,
            max_item_calories=picks.max_item_calories,
            max_servings_per_item=picks.max_servings_per_item,
            max_total_servings=picks.max_total_servings,
        )
        if not plan.items:
            continue
        lines.extend(_plan_headline(hall_name, plan))
        for planned in plan.items:
            lines.extend(_render_pick(planned))

    if not lines:
        return []
    summary = ", ".join(describe_goal(n, g) for n, g in goals.items())
    return [f"PICKS: {summary}", *lines]
