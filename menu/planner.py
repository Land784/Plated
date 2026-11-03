"""Plate planner: one main plus up to two sides, closest to the targets.

Given one hall's mains and sides (the caller decides which is which,
using the push's mains rule; see menu/digest.py) and a subscriber's
targets (see menu/macros.py), pick the plate whose totals land closest
to the targets:

- a plate is exactly one main, at 1 to ``max_main_servings`` servings,
  plus 0-2 different sides at one serving each;
- a plate *meets* the targets when every total is within
  ``tolerance_pct`` of its target;
- plates that meet beat plates that don't, then the smallest summed
  relative distance from each target wins, then fewer items, then fewer
  servings. If none meets, the closest plate is returned with its
  misses.

Earlier versions searched any combo of up to four servings for the most
protein per calorie, which picked "2x grilled chicken" every day and
never a side.

Eligibility rules never change a reported value; they only decide what
is ranked. Items missing a targeted nutrient or calories are never
ranked or estimated (CLAUDE.md: never invent, estimate, or fill in).

Every plan draws from a single hall's menu. Callers must not pool halls,
since nobody eats at North and South in the same meal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations

from menu.allergens import UnknownAllergenPolicy, filter_items
from menu.macros import DEFAULT_TOLERANCE_PCT, NUTRIENTS, bounds, describe_range, nutrient_value
from menu.models import MenuItem

DEFAULT_MAX_MAIN_SERVINGS = 2
DEFAULT_SIDE_MIN_CALORIES = 50.0
DEFAULT_MAX_ITEM_CALORIES = 1200.0
# Sides tried in pairs per main: the best singles for that main.
# shortcut: a pair of two individually mediocre sides can be missed;
# raise this if picks look worse than a hand-built plate.
PAIR_POOL = 12

# Always shown per item and in totals, whatever the targets are.
DISPLAY_NUTRIENTS = ("protein", "carbs", "fat", "calories")


@dataclass
class PlannedItem:
    item: MenuItem
    servings: int
    # One serving's values as reported; None where Nutrislice left it out.
    per_serving: dict[str, float | None]


@dataclass
class MealPlan:
    # The main first, then sides.
    items: list[PlannedItem] = field(default_factory=list)
    # Sum over servings; None if any chosen item lacks that nutrient.
    totals: dict[str, float | None] = field(default_factory=dict)
    goals_met: bool = False
    # One entry per target the plan misses, e.g. "protein 57g (want 51-69g)".
    misses: list[str] = field(default_factory=list)


def _rankable(items: list[MenuItem], scored: set[str], skip: set[str]) -> list[MenuItem]:
    kept: list[MenuItem] = []
    seen = set(skip)
    for item in items:
        if item.food is None:
            continue
        name = item.food.name.strip()
        if name in seen:
            continue
        values = [nutrient_value(item, n) for n in scored]
        if any(v is None for v in values) or nutrient_value(item, "calories") <= 0:
            continue
        seen.add(name)
        kept.append(item)
    return kept


def plan_plate(
    mains: list[MenuItem],
    sides: list[MenuItem],
    targets: dict[str, float],
    *,
    tolerance_pct: float = DEFAULT_TOLERANCE_PCT,
    max_main_servings: int = DEFAULT_MAX_MAIN_SERVINGS,
    excluded_allergens: set[str] | None = None,
    unknown_policy: UnknownAllergenPolicy = UnknownAllergenPolicy.FLAG,
    skip: set[str] | frozenset[str] = frozenset(),
) -> MealPlan:
    """The best plate from one hall's items for ``targets``; see module docstring.

    ``skip`` names items already picked earlier the same day.
    """
    excluded = excluded_allergens or set()
    safe_mains, _ = filter_items(mains, excluded, unknown_policy=unknown_policy)
    safe_sides, _ = filter_items(sides, excluded, unknown_policy=unknown_policy)
    plan = MealPlan()
    if not targets:
        return plan

    scored = set(targets) | {"calories"}
    skipped = set(skip)
    main_pool = _rankable(safe_mains, scored, skipped)
    # A side that is also listed as a main elsewhere stays a main only.
    side_pool = _rankable(safe_sides, scored, skipped | {m.food.name.strip() for m in main_pool})
    if not main_pool:
        return plan

    ranges = {n: bounds(t, tolerance_pct) for n, t in targets.items()}
    side_values = [{n: nutrient_value(s, n) for n in targets} for s in side_pool]

    def key(totals: dict[str, float], n_items: int, servings: int) -> tuple:
        meets = all(low <= totals[n] <= high for n, (low, high) in ranges.items())
        distance = sum(abs(totals[n] - t) / t for n, t in targets.items())
        return (not meets, distance, n_items, servings)

    def add(base: dict[str, float], *picked: int) -> dict[str, float]:
        return {n: base[n] + sum(side_values[i][n] for i in picked) for n in targets}

    best: tuple | None = None
    best_plate: tuple[MenuItem, int, tuple[int, ...]] | None = None
    for main in main_pool:
        for servings in range(1, max(1, max_main_servings) + 1):
            base = {n: nutrient_value(main, n) * servings for n in targets}
            singles = sorted(
                range(len(side_pool)), key=lambda i: key(add(base, i), 2, servings + 1)
            )
            plates = [(), *((i,) for i in singles), *combinations(singles[:PAIR_POOL], 2)]
            for sides_picked in plates:
                k = key(
                    add(base, *sides_picked), 1 + len(sides_picked), servings + len(sides_picked)
                )
                if best is None or k < best:
                    best, best_plate = k, (main, servings, sides_picked)

    main, servings, sides_picked = best_plate
    chosen = [(main, servings), *((side_pool[i], 1) for i in sides_picked)]
    for item, n in chosen:
        plan.items.append(
            PlannedItem(
                item=item,
                servings=n,
                per_serving={x: nutrient_value(item, x) for x in DISPLAY_NUTRIENTS},
            )
        )
    for nutrient in DISPLAY_NUTRIENTS:
        per_item = [(p.per_serving[nutrient], p.servings) for p in plan.items]
        plan.totals[nutrient] = (
            None if any(v is None for v, _ in per_item) else sum(v * s for v, s in per_item)
        )

    plan.goals_met = not best[0]
    for nutrient, target in targets.items():
        low, high = ranges[nutrient]
        total = plan.totals[nutrient]
        if not low <= total <= high:
            unit = NUTRIENTS[nutrient].unit
            want = describe_range(nutrient, target, tolerance_pct)
            plan.misses.append(f"{nutrient} {total:g}{unit} (want {want})")
    return plan
