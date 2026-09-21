from menu.allergens import UnknownAllergenPolicy
from menu.planner import build_meal_plan
from tests.conftest import make_item


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
