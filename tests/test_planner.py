import json
from pathlib import Path

from menu.allergens import UnknownAllergenPolicy
from menu.models import WeekMenu
from menu.planner import build_meal_plan
from tests.conftest import make_item

DINNER = Path(__file__).parent / "fixtures" / "real_north_dinner_2026-09-24.json"


def test_picks_highest_protein_per_calorie_first():
    lean = make_item("Grilled Chicken", protein_g=40, calories=200)
    fatty = make_item("Fried Chicken", protein_g=30, calories=500)

    plan = build_meal_plan([fatty, lean], excluded_allergens=set(), protein_target_g=35)

    assert plan.items[0].item is lean
    assert plan.target_met is True


def test_items_missing_protein_are_never_ranked():
    no_data = make_item("Mystery Soup", protein_g=None, calories=200)
    good = make_item("Chicken", protein_g=30, calories=300)

    plan = build_meal_plan([no_data, good], excluded_allergens=set(), protein_target_g=20)

    assert all(p.item is not no_data for p in plan.items)


def test_calorie_cap_is_respected():
    a = make_item("A", protein_g=20, calories=400)
    b = make_item("B", protein_g=20, calories=400)

    plan = build_meal_plan([a, b], excluded_allergens=set(), protein_target_g=100, calorie_cap=500)

    assert plan.total_calories <= 500
    assert plan.target_met is False


def test_excluded_allergen_items_are_never_selected():
    unsafe = make_item("Peanut Bar", protein_g=50, calories=200, allergens=["Peanuts"])
    safe = make_item("Chicken", protein_g=20, calories=300)

    plan = build_meal_plan([unsafe, safe], excluded_allergens={"peanuts"}, protein_target_g=10)

    assert all(p.item is not unsafe for p in plan.items)


def test_unknown_allergen_items_are_flagged_but_still_usable():
    unknown = make_item("Mystery Bowl", protein_g=30, calories=300, allergens=[])

    plan = build_meal_plan(
        [unknown],
        excluded_allergens={"peanuts"},
        protein_target_g=10,
        unknown_policy=UnknownAllergenPolicy.FLAG,
    )

    assert unknown in plan.flagged_unknown_allergens
    assert any(p.item is unknown for p in plan.items)


def test_tiny_items_below_the_protein_floor_are_not_ranked():
    # Regression: ranking purely by protein per calorie once made a
    # single lettuce leaf the top pick for a 40g target.
    lettuce = make_item("Romaine", protein_g=1, calories=5)
    chicken = make_item("Chicken", protein_g=30, calories=300)

    plan = build_meal_plan([lettuce, chicken], excluded_allergens=set(), protein_target_g=40)

    assert [p.item for p in plan.items] == [chicken]


def test_bulk_recipe_rows_over_the_calorie_ceiling_are_not_ranked():
    # Real row: "Cheese Pizza", serving "1 pizza", 2473 cal, 116g protein.
    bulk = make_item("Cheese Pizza", protein_g=116, calories=2473)
    burger = make_item("Smash Burger", protein_g=28, calories=569)

    plan = build_meal_plan([bulk, burger], excluded_allergens=set(), protein_target_g=70)

    assert [p.item for p in plan.items] == [burger]
    assert bulk.food.nutrition.calories == 2473  # left as reported, not corrected


def test_eligibility_limits_are_configurable():
    small = make_item("Hard Boiled Egg", protein_g=6, calories=70)

    plan = build_meal_plan(
        [small], excluded_allergens=set(), protein_target_g=5, min_item_protein_g=5
    )

    assert plan.target_met is True


def test_duplicate_rows_are_ranked_once():
    first = make_item("Garden Herb Grilled Chicken", protein_g=21, calories=89)
    repeat = make_item("Garden Herb Grilled Chicken", protein_g=21, calories=89)

    plan = build_meal_plan([first, repeat], excluded_allergens=set(), protein_target_g=100)

    assert [p.item for p in plan.items] == [first]


def test_real_dinner_fixture_builds_a_sensible_combo():
    items = [
        item
        for day in WeekMenu.model_validate(json.loads(DINNER.read_text())).days
        for item in day.menu_items
        if not item.is_station_header
    ]

    plan = build_meal_plan(items, excluded_allergens=set(), protein_target_g=70)

    assert [p.item.food.name for p in plan.items] == [
        "Garden Herb Grilled Chicken",
        "Pork Tenderloin Agrodolce",
        "Black Bean Veggie Burger",
    ]
    assert plan.total_protein_g == 72
    assert plan.total_calories == 595
    assert plan.target_met is True
