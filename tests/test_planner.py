import json
from pathlib import Path

import pytest

from menu.allergens import UnknownAllergenPolicy
from menu.macros import Goal
from menu.models import WeekMenu
from menu.planner import MAX_TOTAL_SERVINGS_LIMIT, plan_meal
from tests.conftest import make_item

DINNER = Path(__file__).parent / "fixtures" / "real_north_dinner_2026-09-24.json"

PROTEIN_70 = {"protein": Goal(target=70)}


def _names(plan) -> list[tuple[int, str]]:
    return [(p.servings, p.item.food.name) for p in plan.items]


def test_most_protein_per_calorie_within_the_range_wins():
    # Real 2026-09-24 values. Both combos land 8g from the 70g target;
    # 78g for 513 cal beats 62g for 507 cal.
    chicken = make_item("Grilled Chicken", protein_g=21, calories=89)
    pork = make_item("Pork Tenderloin", protein_g=36, calories=335)
    pibil = make_item("Cochinita Pibil", protein_g=20, calories=329)

    plan = plan_meal([pibil, pork, chicken], PROTEIN_70)

    assert sorted(_names(plan)) == [(1, "Pork Tenderloin"), (2, "Grilled Chicken")]
    assert plan.totals["protein"] == 78
    assert plan.totals["calories"] == 513
    assert plan.goals_met is True


def test_a_target_accepts_totals_within_fifteen_percent():
    # 80g is inside 70 +/- 10.5; a single 80g item meets the goal.
    steak = make_item("Steak", protein_g=80, calories=600)

    assert plan_meal([steak], PROTEIN_70).goals_met is True


def test_explicit_tolerance_narrows_the_range():
    steak = make_item("Steak", protein_g=80, calories=600)

    plan = plan_meal([steak], {"protein": Goal(target=70, tolerance=5)})

    assert plan.goals_met is False
    assert plan.misses == ["protein 80g (want 65-75g)"]


def test_repeats_are_capped_per_item():
    chicken = make_item("Grilled Chicken", protein_g=21, calories=89)

    plan = plan_meal([chicken], PROTEIN_70, max_servings_per_item=3)

    assert _names(plan) == [(3, "Grilled Chicken")]
    assert plan.totals["protein"] == 63


def test_total_servings_are_capped():
    chicken = make_item("Grilled Chicken", protein_g=21, calories=89)
    pork = make_item("Pork Tenderloin", protein_g=36, calories=335)

    plan = plan_meal([chicken, pork], PROTEIN_70, max_total_servings=1)

    assert sum(p.servings for p in plan.items) == 1


def test_every_goal_type_constrains_the_combo():
    lean = make_item("Grilled Chicken", protein_g=40, calories=200, fat_g=2, fiber_g=0)
    fatty = make_item("Fried Chicken", protein_g=40, calories=300, fat_g=25, fiber_g=0)
    beans = make_item("Black Beans", protein_g=15, calories=220, fat_g=1, fiber_g=12)

    plan = plan_meal(
        [lean, fatty, beans],
        {"protein": Goal(target=55), "fat": Goal(max=10), "fiber": Goal(min=10)},
    )

    assert sorted(_names(plan)) == [(1, "Black Beans"), (1, "Grilled Chicken")]
    assert plan.goals_met is True


def test_unmeetable_goals_return_the_closest_combo_and_say_what_missed():
    chicken = make_item("Grilled Chicken", protein_g=21, calories=89, carbs_g=0)

    plan = plan_meal([chicken], {"protein": Goal(min=100)}, max_servings_per_item=2)

    assert _names(plan) == [(2, "Grilled Chicken")]
    assert plan.goals_met is False
    assert plan.misses == ["protein 42g (want ≥100g)"]


def test_only_maxima_pick_nothing():
    chicken = make_item("Grilled Chicken", protein_g=21, calories=89)

    assert plan_meal([chicken], {"fat": Goal(max=30)}).items == []


def test_items_missing_a_goal_nutrient_are_never_ranked():
    no_fiber = make_item("Mystery Soup", protein_g=30, calories=200, fiber_g=None)
    good = make_item("Chicken", protein_g=30, calories=300, fiber_g=0)

    plan = plan_meal([no_fiber, good], {"protein": Goal(target=30), "fiber": Goal(max=5)})

    assert _names(plan) == [(1, "Chicken")]


def test_a_reported_zero_is_used_as_zero():
    chicken = make_item("Grilled Chicken", protein_g=21, calories=89, carbs_g=0)

    plan = plan_meal([chicken], {"protein": Goal(min=20), "carbs": Goal(max=0)})

    assert plan.goals_met is True


def test_tiny_items_below_the_protein_floor_are_not_ranked():
    # Regression: protein-per-calorie ranking once made a single lettuce
    # leaf the top pick for a 40g target.
    lettuce = make_item("Romaine", protein_g=1, calories=5)
    chicken = make_item("Chicken", protein_g=40, calories=300)

    plan = plan_meal([lettuce, chicken], {"protein": Goal(target=40)})

    assert _names(plan) == [(1, "Chicken")]


def test_protein_floor_only_applies_with_a_protein_goal():
    rice = make_item("Jasmine Rice", protein_g=8, calories=402, carbs_g=88)

    plan = plan_meal([rice], {"carbs": Goal(target=80)})

    assert _names(plan) == [(1, "Jasmine Rice")]


def test_bulk_recipe_rows_over_the_calorie_ceiling_are_not_ranked():
    # Real row: "Cheese Pizza", serving "1 pizza", 2473 cal, 116g protein.
    bulk = make_item("Cheese Pizza", protein_g=116, calories=2473)
    burger = make_item("Smash Burger", protein_g=28, calories=569)

    plan = plan_meal([bulk, burger], PROTEIN_70)

    assert all(p.item is not bulk for p in plan.items)
    assert bulk.food.nutrition.calories == 2473  # left as reported, not corrected


def test_duplicate_rows_count_as_one_item():
    first = make_item("Garden Herb Grilled Chicken", protein_g=21, calories=89)
    repeat = make_item("Garden Herb Grilled Chicken", protein_g=21, calories=89)

    plan = plan_meal([first, repeat], PROTEIN_70, max_servings_per_item=1)

    assert _names(plan) == [(1, "Garden Herb Grilled Chicken")]


def test_excluded_allergen_items_are_never_selected():
    unsafe = make_item("Peanut Bar", protein_g=50, calories=200, allergens=["Peanuts"])
    safe = make_item("Chicken", protein_g=40, calories=300)

    plan = plan_meal([unsafe, safe], {"protein": Goal(min=30)}, excluded_allergens={"peanuts"})

    assert _names(plan) == [(1, "Chicken")]


def test_unknown_allergen_items_are_flagged_but_still_usable():
    unknown = make_item("Mystery Bowl", protein_g=30, calories=300, allergens=[])

    plan = plan_meal(
        [unknown],
        {"protein": Goal(min=20)},
        excluded_allergens={"peanuts"},
        unknown_policy=UnknownAllergenPolicy.FLAG,
    )

    assert unknown in plan.flagged_unknown_allergens
    assert _names(plan) == [(1, "Mystery Bowl")]


def test_totals_stay_unknown_when_a_chosen_item_lacks_a_display_nutrient():
    # Carbs aren't a goal, so an item without carbs is still eligible,
    # but the carb total can't be claimed.
    chicken = make_item("Chicken", protein_g=40, calories=300, carbs_g=None)

    plan = plan_meal([chicken], {"protein": Goal(min=30)})

    assert plan.totals["carbs"] is None


@pytest.mark.parametrize("servings", [0, MAX_TOTAL_SERVINGS_LIMIT + 1])
def test_total_servings_outside_the_search_limit_are_clamped(servings):
    chicken = make_item("Grilled Chicken", protein_g=21, calories=89)

    plan = plan_meal(
        [chicken], {"protein": Goal(min=500)}, max_servings_per_item=9, max_total_servings=servings
    )

    assert sum(p.servings for p in plan.items) <= MAX_TOTAL_SERVINGS_LIMIT


def test_real_dinner_fixture_builds_a_sensible_combo():
    items = [
        item
        for day in WeekMenu.model_validate(json.loads(DINNER.read_text())).days
        for item in day.menu_items
        if not item.is_station_header
    ]

    plan = plan_meal(items, PROTEIN_70)

    assert _names(plan) == [(2, "Garden Herb Grilled Chicken"), (1, "Pork Tenderloin Agrodolce")]
    assert plan.totals == {"protein": 78, "carbs": 12, "fat": 16, "calories": 513}
    assert plan.goals_met is True
