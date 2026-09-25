"""Shared test helpers."""

from __future__ import annotations

from menu.models import AllergenTag, Food, MenuItem, NutritionInfo


def make_item(
    name: str,
    *,
    protein_g: float | None = None,
    calories: float | None = None,
    allergens: list[str] | None = None,
    has_nutrition: bool = True,
    **nutrients: float | None,
) -> MenuItem:
    """Build a MenuItem for tests without needing a full JSON fixture.

    Extra keyword arguments are NutritionInfo fields (carbs_g, fat_g,
    fiber_g, sugar_g, sodium_mg).
    """
    nutrition = (
        NutritionInfo(calories=calories, protein_g=protein_g, **nutrients)
        if has_nutrition
        else None
    )
    food = Food(
        name=name,
        nutrition=nutrition,
        allergens=[AllergenTag(name=a) for a in (allergens or [])],
    )
    return MenuItem(food=food)
