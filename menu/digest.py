"""Turn a meal's raw menus into the text of one push notification.

The push answers "what's good today": a glance line per hall naming its
best mains, then the macro picks (for subscribers with ``[macros]``),
then one line per station. It is plain text, because iOS shows Markdown
raw, and it is read in a proportional font on a ~40-character-wide
phone, so there is no column alignment.

Nutrislice does not attach a station *name* to regular menu items -- they
only carry a numeric ``station_id``. The human-readable name ("Domer
Diner", "La Mesa") appears only on the ``is_station_header`` row that
precedes that station's items, in its ``text`` field. So grouping
requires walking a day's items in order and tracking the current header.

Station names are also not consistent between halls: North publishes
"The Global Compass" while South publishes "Global Compass" for what is
effectively the same station. All matching therefore goes through
:func:`normalize_station`.

Which items count as a station's "mains" is a display rule only. It
reads the planner's calorie ceiling to skip bulk rows, but it never
changes what the planner may rank, and it never changes a reported
value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from menu.macros import nutrient_value
from menu.models import DayMenu, MenuItem
from menu.notifier import compose_body
from menu.planner import MealPlan, PlannedItem, plan_meal
from menu.users import MacrosConfig, PicksConfig, UserConfig

_WHITESPACE = re.compile(r"\s+")
_LEADING_ARTICLE = re.compile(r"^the\s+")

# Nutrislice mixes dietary labels into the same tag list as allergens,
# with identical metadata (see AllergenTag in menu/models.py). These are
# not allergen information. It is deliberately a list of known
# NON-allergens rather than of allergens: a tag name nobody anticipated
# counts as allergen data instead of being silently ignored.
_DIETARY_LABELS = frozenset({"vegan", "vegetarian", "high performance"})

# Serving units that name a whole dish, so the item is a main whatever
# its protein ("1 taco" at 3g). Units seen in real menus and left out on
# purpose: slice (a pineapple garnish is "1 Slice"), pizza (bulk rows),
# bowl ("z bowl" is unclear), tender, bun, egg roll, potsticker, naan,
# link.
DISH_WORDS = (
    "taco",
    "burrito",
    "quesadilla",
    "pupusa",
    "arepa",
    "sandwich",
    "sub",
    "burger",
    "pepito",
    "torta",
    "hot dog",
    "patty",
    "pattie",
    "cutlet",
    "fillet",
    "filet",
    "chop",
    "portion",
    "rib",
    "wing",
    "shank",
    "wrap",
)
_DISH_UNIT = re.compile(r"\b(?:" + "|".join(map(re.escape, DISH_WORDS)) + r")\b", re.IGNORECASE)

GLANCE_SIZE = 3

# Below ntfy's 4,000-byte cap on the Firebase message (which every iPhone
# goes through, and which cuts the end off anything longer), leaving
# about 1 KB for the JSON around the body and its escaping.
BODY_BUDGET_BYTES = 3000

MEAL_TAGS = {
    "breakfast": "fried_egg",
    "brunch": "pancakes",
    "lunch": "sandwich",
    "dinner": "plate_with_cutlery",
}
DEFAULT_MEAL_TAG = "fork_and_knife"

HALL_PAGE_URL = "https://nd.nutrislice.com/menu/{slug}/"


@dataclass
class Station:
    """A station header and the items served under it, in menu order."""

    name: str
    items: list[MenuItem] = field(default_factory=list)

    @property
    def unique_items(self) -> list[MenuItem]:
        """Items de-duplicated by name, first row kept, menu order preserved.

        Real feeds repeat rows (South listed "Sliced Red Onion" twice in
        one station), which reads as a bug in a notification.
        """
        seen: set[str] = set()
        unique: list[MenuItem] = []
        for item in self.items:
            if item.food is None:
                continue
            name = item.food.name.strip()
            if not name or name in seen:
                continue
            seen.add(name)
            unique.append(item)
        return unique

    @property
    def dish_names(self) -> list[str]:
        return [_name(item) for item in self.unique_items]


@dataclass(frozen=True)
class MainsRule:
    """Which of a station's items are shown as its mains (display only)."""

    min_protein_g: float
    # The subscriber's [picks] max_item_calories; None turns the skip off.
    max_item_calories: float | None
    max_items: int


@dataclass
class HallSection:
    """One hall's station lines, under its upper-cased label."""

    label: str
    lines: list[str]


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
    """Keep only stations whose normalized name is in ``allowlist``, in menu order."""
    wanted = {normalize_station(name) for name in allowlist}
    return [s for s in stations if normalize_station(s.name) in wanted]


def stations_in_allowlist_order(day: DayMenu, allowlist: list[str]) -> list[Station]:
    """Allowlisted stations in the subscriber's order, so trimming drops the least wanted."""
    rank: dict[str, int] = {}
    for index, name in enumerate(allowlist):
        rank.setdefault(normalize_station(name), index)
    kept = filter_stations(group_by_station(day), allowlist)
    return sorted(kept, key=lambda s: rank[normalize_station(s.name)])


def _name(item: MenuItem) -> str:
    return item.food.name.strip() if item.food else "unknown item"


def _protein(item: MenuItem) -> float | None:
    return nutrient_value(item, "protein")


def _by_protein(item: MenuItem) -> float:
    """Sort key, highest protein first; an item without a value sorts last."""
    protein = _protein(item)
    return -protein if protein is not None else float("inf")


def has_dish_unit(item: MenuItem) -> bool:
    unit = item.food.serving_size.unit if item.food and item.food.serving_size else None
    return bool(unit and _DISH_UNIT.search(unit))


def _is_bulk(item: MenuItem, rule: MainsRule) -> bool:
    calories = nutrient_value(item, "calories")
    ceiling = rule.max_item_calories
    return ceiling is not None and calories is not None and calories > ceiling


def station_mains(station: Station, rule: MainsRule) -> list[MenuItem]:
    """The station's qualifying mains, highest protein first, ties in menu order.

    An item qualifies at ``rule.min_protein_g`` reported protein or with
    a dish-word serving unit. Rows over the calorie ceiling are bulk
    recipe quantities, not servings, and never qualify.
    """
    mains = []
    for item in station.unique_items:
        if _is_bulk(item, rule):
            continue
        protein = _protein(item)
        if (protein is not None and protein >= rule.min_protein_g) or has_dish_unit(item):
            mains.append(item)
    return sorted(mains, key=_by_protein)


def _fallback(station: Station) -> MenuItem | None:
    """The single highest-protein item, or the first item if none reports protein."""
    items = station.unique_items
    with_protein = [item for item in items if _protein(item) is not None]
    if with_protein:
        return min(with_protein, key=_by_protein)
    return items[0] if items else None


def station_lineup(station: Station, rule: MainsRule) -> list[str]:
    """Names to show for a station: its mains, or else one fallback item.

    A station is never left out just because nothing in it looks like a
    main (a build-your-own pasta bar), since the subscriber asked for it.
    """
    mains = station_mains(station, rule)
    if mains:
        return [_name(item) for item in mains[: rule.max_items]]
    fallback = _fallback(station)
    return [_name(fallback)] if fallback else []


def glance_line(label: str, stations: list[Station], rule: MainsRule) -> str | None:
    """ "North: a, b, c": the hall's best mains, at most one per station.

    Fallback items never appear here; a hall with no qualifying main
    has no glance line.
    """
    tops = [mains[0] for station in stations if (mains := station_mains(station, rule))]
    best = sorted(tops, key=_by_protein)[:GLANCE_SIZE]
    if not best:
        return None
    return f"{label}: {', '.join(_name(item) for item in best)}"


def station_lines(stations: list[Station], rule: MainsRule) -> list[str]:
    return [
        f"{station.name}: {', '.join(names)}"
        for station in stations
        if (names := station_lineup(station, rule))
    ]


def _amount(value: float | None, suffix: str) -> str:
    return f"{value:g}{suffix}" if value is not None else f"?{suffix}"


def _macro_line(values: dict[str, float | None]) -> str:
    """ "78P 12C 16F · 513 cal"; a nutrient Nutrislice left out shows as "?"."""
    return (
        f"{_amount(values['protein'], 'P')} {_amount(values['carbs'], 'C')} "
        f"{_amount(values['fat'], 'F')} · {_amount(values['calories'], ' cal')}"
    )


def _times(value: float | None, servings: int) -> float | None:
    return value * servings if value is not None else None


def _allergens_unknown(item: MenuItem) -> bool:
    """True unless Nutrislice reported a tag that isn't a dietary label.

    An item tagged only "High Performance" has no allergen information
    at all. Absence of a tag never means safe.
    """
    tags = item.food.allergens if item.food else []
    return not any(tag.name.strip().lower() not in _DIETARY_LABELS for tag in tags)


def _pick_line(planned: PlannedItem, flag_unknown: bool) -> str:
    """ "2× Garden Herb Grilled Chicken · 42P · 178 cal", for all servings.

    Multiplying a reported per-serving value by the serving count is
    arithmetic on reported data, like the totals, not an estimate.
    """
    n = planned.servings
    count = f"{n}× " if n > 1 else ""
    protein = _amount(_times(planned.per_serving["protein"], n), "P")
    calories = _amount(_times(planned.per_serving["calories"], n), " cal")
    line = f"{count}{_name(planned.item)} · {protein} · {calories}"
    if flag_unknown and _allergens_unknown(planned.item):
        line += " · allergens unknown"
    return line


def _plan_key(plan: MealPlan) -> tuple:
    return tuple(
        (_name(p.item), p.servings, tuple(sorted(p.per_serving.items()))) for p in plan.items
    )


def _picks_block(label: str, plan: MealPlan, picks: PicksConfig) -> list[str]:
    # Without exclusions every item would be flagged; the disclaimer
    # already covers that case.
    flag = bool(picks.exclude_allergens)
    lines = [f"PICKS · {label} · {_macro_line(plan.totals)}"]
    lines.extend(_pick_line(planned, flag) for planned in plan.items)
    if plan.misses:
        lines.append(f"closest: {', '.join(plan.misses)}")
    return lines


def plan_halls(
    halls: list[tuple[str, DayMenu | None]],
    allowlist: list[str] | None,
    macros: MacrosConfig,
    picks: PicksConfig,
    meal: str,
) -> list[tuple[str, MealPlan]]:
    """One combo per hall for ``meal``'s goals, skipping halls with none.

    Picks come only from the allowlisted stations (every station when
    ``allowlist`` is None), and each combo is planned from a single
    hall's items.
    """
    goals = macros.for_meal(meal)
    if not goals:
        return []

    plans: list[tuple[str, MealPlan]] = []
    for label, day in halls:
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
        if plan.items:
            plans.append((label, plan))
    return plans


def build_picks_blocks(
    halls: list[tuple[str, DayMenu | None]],
    allowlist: list[str] | None,
    macros: MacrosConfig,
    picks: PicksConfig,
    meal: str,
) -> list[list[str]]:
    """The PICKS blocks: one shared block when every hall's combo is identical.

    Identical means the same items, servings and per-serving values, so
    a merged block says exactly what each hall's would have.
    """
    plans = plan_halls(halls, allowlist, macros, picks, meal)
    if len(plans) > 1 and len({_plan_key(plan) for _, plan in plans}) == 1:
        label = "both halls" if len(plans) == 2 else "all halls"
        return [_picks_block(label, plans[0][1], picks)]
    return [_picks_block(label, plan, picks) for label, plan in plans]


def join_blocks(blocks: list[list[str]]) -> list[str]:
    lines: list[str] = []
    for block in blocks:
        if not block:
            continue
        if lines:
            lines.append("")
        lines.extend(block)
    return lines


def _render(head: list[list[str]], sections: list[HallSection], dropped: list[int]) -> list[str]:
    halls = []
    for section, removed in zip(sections, dropped, strict=True):
        more = [f"+{removed} station{'s' if removed != 1 else ''}"] if removed else []
        halls.append([section.label.upper(), *section.lines, *more])
    return join_blocks([*head, *halls])


def fit_to_budget(
    head: list[list[str]], sections: list[HallSection], budget: int = BODY_BUDGET_BYTES
) -> list[str]:
    """Join the message, dropping station lines from the end until it fits.

    The size checked is the body as sent, disclaimer included. The last
    hall's last station goes first; each hall's removed lines become one
    "+N stations" line. ``head`` (the glance and picks) is never cut.
    """
    kept = [list(section.lines) for section in sections]
    dropped = [0] * len(sections)
    while True:
        trimmed = [HallSection(s.label, lines) for s, lines in zip(sections, kept, strict=True)]
        lines = _render(head, trimmed, dropped)
        if len(compose_body("\n".join(lines)).encode("utf-8")) <= budget:
            return lines
        last = next((i for i in reversed(range(len(kept))) if kept[i]), None)
        if last is None:
            return lines  # only the uncuttable part is left
        kept[last].pop()
        dropped[last] += 1


def hall_label(slug: str) -> str:
    """ "north-dining-hall" -> "North"."""
    return slug.replace("-", " ").title().split()[0]


def hall_page_url(slug: str) -> str:
    return HALL_PAGE_URL.format(slug=slug)


def notification_title(meal: str, day: date) -> str:
    """ "Dinner · Thu Sep 24"; "late-lunch" reads "Late Lunch"."""
    return f"{meal.replace('-', ' ').title()} · {day:%a %b} {day.day}"


def meal_tags(meal: str) -> list[str]:
    """ntfy emoji shortcodes, which phones show before the title."""
    return [MEAL_TAGS.get(meal, DEFAULT_MEAL_TAG)]


def build_message(
    user: UserConfig,
    menus: dict[str, DayMenu | None],
    meal: str,
    budget: int = BODY_BUDGET_BYTES,
) -> list[str]:
    """The message lines for one meal, or [] when no hall has station content.

    ``menus`` maps each of ``user.halls`` to its menu (None if
    unpublished). Picks alone never make a message: they come from the
    same stations, so no station lines means no menu was published.
    """
    rule = MainsRule(
        min_protein_g=user.main_protein_g,
        max_item_calories=user.picks.max_item_calories,
        max_items=user.max_items_per_station,
    )
    glance: list[str] = []
    sections: list[HallSection] = []
    for slug in user.halls:
        day = menus.get(slug)
        if day is None:
            continue
        stations = stations_in_allowlist_order(day, user.stations)
        label = hall_label(slug)
        if line := glance_line(label, stations, rule):
            glance.append(line)
        if lines := station_lines(stations, rule):
            sections.append(HallSection(label, lines))
    if not sections:
        return []

    picks: list[list[str]] = []
    if user.macros is not None:
        halls = [(hall_label(slug), menus.get(slug)) for slug in user.halls]
        picks = build_picks_blocks(halls, user.stations, user.macros, user.picks, meal)
    return fit_to_budget([glance, *picks], sections, budget)
