"""Protein-focused meal planner.

Greedy, explainable algorithm: rank allergen-safe items by protein per
calorie, then take items in that order until the protein target is hit
or the calorie cap would be exceeded. See "Meal planner behavior" in
CLAUDE.md.

Two eligibility rules keep the ranking honest against real Nutrislice
data. Neither changes a reported value; they only decide what gets
ranked:

- A per-item protein floor. Ranking purely by protein per calorie made
  a single lettuce leaf the top pick for a 40g target, because a tiny
  item can have an excellent ratio while contributing almost nothing.
- A per-item calorie ceiling. Some rows are bulk recipe quantities
  rather than servings (a 2473 cal "Cheese Pizza" with serving "1
  pizza"), and the serving unit can't tell them apart from real
  servings, so calories are the only usable signal. An item over the
  ceiling is left unranked, not corrected.

Every plan draws from a single hall's menu. Callers must not pool halls,
since nobody eats at North and South in the same meal.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from menu.allergens import UnknownAllergenPolicy, filter_items, is_unknown
from menu.models import MenuItem

DEFAULT_MIN_ITEM_PROTEIN_G = 15.0
DEFAULT_MAX_ITEM_CALORIES = 1200.0


@dataclass
class PlannedItem:
    item: MenuItem
    protein_g: float
    calories: float
    protein_per_calorie: float
    reason: str


@dataclass
class MealPlan:
    items: list[PlannedItem] = field(default_factory=list)
    total_protein_g: float = 0.0
    total_calories: float = 0.0
    target_met: bool = False
    flagged_unknown_allergens: list[MenuItem] = field(default_factory=list)


def _rankable(
    items: list[MenuItem],
    *,
    min_item_protein_g: float,
    max_item_calories: float | None,
) -> list[tuple[MenuItem, float, float]]:
    """Items eligible for ranking, as (item, protein_g, calories).

    Items missing either value are never ranked or estimated -- see
    CLAUDE.md's "never invent, estimate, or fill in" rule. Rows repeated
    under the same name keep only their first occurrence.
    """
    ranked = []
    seen: set[str] = set()
    for item in items:
        if item.food is None or item.food.nutrition is None:
            continue
        protein = item.food.nutrition.protein_g
        calories = item.food.nutrition.calories
        if protein is None or protein <= 0 or calories is None or calories <= 0:
            continue
        if protein < min_item_protein_g:
            continue
        if max_item_calories is not None and calories > max_item_calories:
            continue
        name = item.food.name.strip()
        if name in seen:
            continue
        seen.add(name)
        ranked.append((item, protein, calories))
    return ranked


def build_meal_plan(
    items: list[MenuItem],
    *,
    excluded_allergens: set[str],
    protein_target_g: float,
    calorie_cap: float | None = None,
    unknown_policy: UnknownAllergenPolicy = UnknownAllergenPolicy.FLAG,
    min_item_protein_g: float = DEFAULT_MIN_ITEM_PROTEIN_G,
    max_item_calories: float | None = DEFAULT_MAX_ITEM_CALORIES,
) -> MealPlan:
    """Greedily build a small set of items meeting the protein target."""
    safe_items, _dropped = filter_items(items, excluded_allergens, unknown_policy=unknown_policy)
    flagged = [i for i in safe_items if is_unknown(i, excluded_allergens)]

    candidates = _rankable(
        safe_items,
        min_item_protein_g=min_item_protein_g,
        max_item_calories=max_item_calories,
    )
    candidates.sort(key=lambda t: t[1] / t[2], reverse=True)

    plan = MealPlan(flagged_unknown_allergens=flagged)

    for item, protein, calories in candidates:
        if plan.target_met:
            break
        if calorie_cap is not None and plan.total_calories + calories > calorie_cap:
            continue

        ppc = protein / calories
        name = item.food.name if item.food else "unknown item"
        reason = (
            f"{name}: {protein:g}g protein / {calories:g} cal ({ppc:.3f} g protein per calorie)"
        )
        plan.items.append(
            PlannedItem(
                item=item,
                protein_g=protein,
                calories=calories,
                protein_per_calorie=ppc,
                reason=reason,
            )
        )
        plan.total_protein_g += protein
        plan.total_calories += calories

        if plan.total_protein_g >= protein_target_g:
            plan.target_met = True

    return plan
