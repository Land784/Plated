"""Macro-goal meal planner.

Given one hall's items and a subscriber's goals (see menu/macros.py),
find the combination of servings that meets every goal and supplies the
most of what the goals ask for per calorie (for a lone protein goal,
protein per calorie). Combos hold at most ``max_total_servings`` servings and at
most ``max_servings_per_item`` of any one item, so "2x grilled chicken"
is a valid pick. If no combo meets every goal, the one that misses by
the least is returned and labelled as such.

This is an exhaustive search over a small space rather than a greedy
pass: greedy stopped at the first item that crossed the target, which
could overshoot by a whole entree. The result is still one sentence to
explain: "of the combos that meet your goals, the most protein (or
whatever you asked for) per calorie".

Eligibility rules keep the search honest against real Nutrislice data.
None of them changes a reported value; they only decide what is ranked:

- Items missing any nutrient the goals depend on are never ranked or
  estimated (CLAUDE.md: never invent, estimate, or fill in).
- A per-item calorie ceiling. Some rows are bulk recipe quantities
  rather than servings (a 2473 cal "Cheese Pizza" with serving "1
  pizza"), and the serving unit can't tell them apart from real
  servings, so calories are the only usable signal.
- A per-item protein floor, applied only when protein has a goal.
  Without it, protein-per-calorie ranking once made a single lettuce
  leaf the top pick for a 40g target.

Every plan draws from a single hall's menu. Callers must not pool halls,
since nobody eats at North and South in the same meal.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from itertools import combinations_with_replacement

from menu.allergens import UnknownAllergenPolicy, filter_items, is_unknown
from menu.macros import NUTRIENTS, Goal, describe_range, nutrient_value
from menu.models import MenuItem

DEFAULT_MIN_ITEM_PROTEIN_G = 15.0
DEFAULT_MAX_ITEM_CALORIES = 1200.0
DEFAULT_MAX_SERVINGS_PER_ITEM = 2
DEFAULT_MAX_TOTAL_SERVINGS = 4
# Hard ceiling on max_total_servings: the search grows combinatorially.
MAX_TOTAL_SERVINGS_LIMIT = 5
# When more items are eligible than this, only the most useful for the
# goals are searched, which keeps a run to a few thousand combos.
CANDIDATE_POOL = 24

# Always shown per item and in totals, whatever the goals are.
DISPLAY_NUTRIENTS = ("protein", "carbs", "fat", "calories")


@dataclass
class PlannedItem:
    item: MenuItem
    servings: int
    # One serving's values as reported; None where Nutrislice left it out.
    per_serving: dict[str, float | None]


@dataclass
class MealPlan:
    items: list[PlannedItem] = field(default_factory=list)
    # Sum over servings; None if any chosen item lacks that nutrient.
    totals: dict[str, float | None] = field(default_factory=dict)
    goals_met: bool = False
    # One entry per goal the plan misses, e.g. "protein 57g (want 60-80g)".
    misses: list[str] = field(default_factory=list)
    flagged_unknown_allergens: list[MenuItem] = field(default_factory=list)


def _eligible(
    items: list[MenuItem],
    goals: dict[str, Goal],
    *,
    min_item_protein_g: float,
    max_item_calories: float | None,
) -> list[MenuItem]:
    required = set(goals) | {"calories"}
    protein_floor = "protein" in goals and goals["protein"].drives_picks
    eligible: list[MenuItem] = []
    seen: set[str] = set()
    for item in items:
        if item.food is None:
            continue
        values = {n: nutrient_value(item, n) for n in required}
        if any(v is None for v in values.values()):
            continue
        calories = values["calories"]
        if calories <= 0:
            continue
        if max_item_calories is not None and calories > max_item_calories:
            continue
        if protein_floor and values["protein"] < min_item_protein_g:
            continue
        name = item.food.name.strip()
        if name in seen:
            continue
        seen.add(name)
        eligible.append(item)
    return eligible


def _usefulness(item: MenuItem, goals: dict[str, Goal]) -> float:
    """How much of the asked-for amounts one serving supplies, per calorie."""
    supplied = 0.0
    for nutrient, goal in goals.items():
        if not goal.drives_picks:
            continue
        wanted = goal.target if goal.target is not None else goal.min
        if wanted:
            supplied += nutrient_value(item, nutrient) / wanted
    return supplied / nutrient_value(item, "calories")


def _violation(totals: dict[str, float], bounds: dict[str, tuple[float, float]]) -> float:
    """Total relative distance outside every goal's range; 0 means all met."""
    miss = 0.0
    for nutrient, (low, high) in bounds.items():
        value = totals[nutrient]
        if value < low:
            miss += (low - value) / max(low, 1.0)
        elif value > high:
            miss += (value - high) / max(high, 1.0)
    return miss


def _efficiency(totals: dict[str, float], goals: dict[str, Goal]) -> float:
    """Share of each asked-for amount supplied, summed, per calorie.

    For a lone protein target this is protein per calorie. Calories are
    the denominator, never part of the sum.
    """
    supplied = 0.0
    for nutrient, goal in goals.items():
        if nutrient == "calories" or not goal.drives_picks:
            continue
        wanted = goal.target if goal.target is not None else goal.min
        if wanted:
            supplied += totals[nutrient] / wanted
    return supplied / totals["calories"]


def _target_distance(totals: dict[str, float], goals: dict[str, Goal]) -> float:
    return sum(
        abs(totals[n] - g.target) / g.target for n, g in goals.items() if g.target is not None
    )


def plan_meal(
    items: list[MenuItem],
    goals: dict[str, Goal],
    *,
    excluded_allergens: set[str] | None = None,
    unknown_policy: UnknownAllergenPolicy = UnknownAllergenPolicy.FLAG,
    min_item_protein_g: float = DEFAULT_MIN_ITEM_PROTEIN_G,
    max_item_calories: float | None = DEFAULT_MAX_ITEM_CALORIES,
    max_servings_per_item: int = DEFAULT_MAX_SERVINGS_PER_ITEM,
    max_total_servings: int = DEFAULT_MAX_TOTAL_SERVINGS,
) -> MealPlan:
    """Best combo from one hall's items for ``goals``; see module docstring."""
    excluded = excluded_allergens or set()
    safe_items, _dropped = filter_items(items, excluded, unknown_policy=unknown_policy)
    plan = MealPlan(flagged_unknown_allergens=[i for i in safe_items if is_unknown(i, excluded)])

    if not any(g.drives_picks for g in goals.values()):
        return plan

    candidates = _eligible(
        safe_items,
        goals,
        min_item_protein_g=min_item_protein_g,
        max_item_calories=max_item_calories,
    )
    if not candidates:
        return plan
    if len(candidates) > CANDIDATE_POOL:
        candidates = sorted(candidates, key=lambda i: _usefulness(i, goals), reverse=True)
        candidates = candidates[:CANDIDATE_POOL]

    scored = set(goals) | {"calories"}
    values = [{n: nutrient_value(item, n) for n in scored} for item in candidates]
    bounds = {n: g.bounds() for n, g in goals.items()}

    best_key: tuple | None = None
    best_combo: tuple[int, ...] = ()
    total_cap = max(1, min(max_total_servings, MAX_TOTAL_SERVINGS_LIMIT))
    for size in range(1, total_cap + 1):
        for combo in combinations_with_replacement(range(len(candidates)), size):
            if max(Counter(combo).values()) > max_servings_per_item:
                continue
            totals = {n: sum(values[i][n] for i in combo) for n in scored}
            miss = _violation(totals, bounds)
            # Meeting every goal beats any miss; then the most of what was
            # asked for per calorie; then closest to targets; then fewest
            # servings. Fewest calories alone was tried first and always
            # landed at the bottom of a target's range: 62g protein for
            # 507 cal over 78g for 513.
            key = (
                miss > 0,
                miss,
                -_efficiency(totals, goals),
                _target_distance(totals, goals),
                size,
            )
            if best_key is None or key < best_key:
                best_key, best_combo = key, combo

    counts = Counter(best_combo)
    for index in sorted(counts, key=lambda i: best_combo.index(i)):
        item = candidates[index]
        plan.items.append(
            PlannedItem(
                item=item,
                servings=counts[index],
                per_serving={n: nutrient_value(item, n) for n in (*DISPLAY_NUTRIENTS, *goals)},
            )
        )

    for nutrient in {*DISPLAY_NUTRIENTS, *goals}:
        per_item = [(p.per_serving[nutrient], p.servings) for p in plan.items]
        plan.totals[nutrient] = (
            None if any(v is None for v, _ in per_item) else sum(v * s for v, s in per_item)
        )

    plan.goals_met = not best_key[0]
    for nutrient, goal in goals.items():
        low, high = bounds[nutrient]
        total = plan.totals[nutrient]
        if not low <= total <= high:
            unit = NUTRIENTS[nutrient].unit
            plan.misses.append(
                f"{nutrient} {total:g}{unit} (want {describe_range(nutrient, goal)})"
            )
    return plan
