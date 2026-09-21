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
) -> MenuItem:
    """Build a MenuItem for tests without needing a full JSON fixture."""
    nutrition = NutritionInfo(calories=calories, protein_g=protein_g) if has_nutrition else None
    food = Food(
        name=name,
        nutrition=nutrition,
        allergens=[AllergenTag(name=a) for a in (allergens or [])],
    )
    return MenuItem(food=food)
