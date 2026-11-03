import time

from menu.allergens import UnknownAllergenPolicy
from menu.planner import plan_plate
from tests.conftest import make_item

CHICKEN = make_item("Grilled Chicken", protein_g=40, calories=300, carbs_g=0, fat_g=8)
PORK = make_item("Pork Tenderloin", protein_g=36, calories=335, carbs_g=2, fat_g=12)
RICE = make_item("Brown Rice", protein_g=5, calories=220, carbs_g=45, fat_g=2)
BROCCOLI = make_item("Roasted Broccoli", protein_g=4, calories=90, carbs_g=8, fat_g=5)
COOKIE = make_item("Cookie", protein_g=2, calories=250, carbs_g=35, fat_g=12)


def _names(plan) -> list[tuple[int, str]]:
    return [(p.servings, p.item.food.name) for p in plan.items]


def test_a_plate_is_one_main_plus_the_sides_that_land_closest():
    plan = plan_plate([CHICKEN, PORK], [RICE, BROCCOLI, COOKIE], {"protein": 50, "calories": 600})

    assert _names(plan) == [(1, "Grilled Chicken"), (1, "Brown Rice"), (1, "Roasted Broccoli")]
    assert plan.totals["protein"] == 49
    assert plan.totals["calories"] == 610
    assert plan.goals_met is True


def test_the_main_can_be_doubled_but_a_plate_never_has_two_mains():
    plan = plan_plate([CHICKEN, PORK], [RICE], {"protein": 80})

    assert _names(plan) == [(2, "Grilled Chicken")]


def test_max_main_servings_caps_the_main():
    plan = plan_plate([CHICKEN], [RICE], {"protein": 80}, max_main_servings=1)

    assert plan.items[0].servings == 1
    assert plan.goals_met is False


def test_sides_are_one_serving_each_and_never_the_same_side_twice():
    plan = plan_plate([CHICKEN], [RICE], {"protein": 40, "carbs": 90})

    assert _names(plan) == [(1, "Grilled Chicken"), (1, "Brown Rice")]


def test_meeting_every_target_beats_a_closer_plate_that_misses_one():
    # Within 15% on both (14% off each) vs. exact calories but protein 18% under.
    meets = make_item("Meets", protein_g=57, calories=570)
    close = make_item("Close", protein_g=41, calories=500)

    plan = plan_plate([close, meets], [], {"protein": 50, "calories": 500})

    assert _names(plan) == [(1, "Meets")]
    assert plan.goals_met is True


def test_fewer_items_win_a_tie():
    exact = make_item("Exact", protein_g=50, calories=500)
    zero = make_item("Water Cup", protein_g=0, calories=60)

    plan = plan_plate([exact], [zero], {"protein": 50})

    assert _names(plan) == [(1, "Exact")]


def test_unmeetable_targets_return_the_closest_plate_and_say_what_missed():
    small = make_item("Small Main", protein_g=30, calories=300)

    plan = plan_plate([small], [], {"protein": 60}, max_main_servings=1)

    assert _names(plan) == [(1, "Small Main")]
    assert plan.goals_met is False
    assert plan.misses == ["protein 30g (want 51-69g)"]


def test_tolerance_pct_sets_the_accepted_range():
    steak = make_item("Steak", protein_g=56, calories=600)

    assert plan_plate([steak], [], {"protein": 50}, max_main_servings=1).goals_met is True
    plan = plan_plate([steak], [], {"protein": 50}, tolerance_pct=10, max_main_servings=1)
    assert plan.misses == ["protein 56g (want 45-55g)"]


def test_items_picked_earlier_today_are_skipped():
    plan = plan_plate(
        [CHICKEN, PORK],
        [RICE, BROCCOLI],
        {"protein": 50, "calories": 600},
        skip={"Grilled Chicken", "Brown Rice"},
    )

    names = [name for _, name in _names(plan)]
    assert "Grilled Chicken" not in names and "Brown Rice" not in names
    assert names[0] == "Pork Tenderloin"


def test_no_targets_plan_nothing():
    assert plan_plate([CHICKEN], [RICE], {}).items == []


def test_items_missing_a_target_nutrient_are_never_ranked():
    no_carbs = make_item("Mystery Bowl", protein_g=40, calories=400)

    assert plan_plate([no_carbs], [], {"protein": 40, "carbs": 30}).items == []


def test_a_reported_zero_is_used_as_zero():
    plan = plan_plate([CHICKEN], [], {"carbs": 10, "protein": 40}, max_main_servings=1)

    assert plan.totals["carbs"] == 0
    assert plan.misses == ["carbs 0g (want 8-12g)"]


def test_duplicate_rows_count_as_one_item():
    twin = make_item("Brown Rice", protein_g=5, calories=220, carbs_g=45, fat_g=2)

    plan = plan_plate([CHICKEN], [RICE, twin], {"protein": 40, "carbs": 90})

    assert _names(plan) == [(1, "Grilled Chicken"), (1, "Brown Rice")]


def test_excluded_allergen_items_are_never_selected():
    fish = make_item("Salmon", protein_g=40, calories=300, allergens=["Fish"])
    tofu = make_item("Tofu", protein_g=20, calories=200, allergens=["Soy"])

    plan = plan_plate([fish, tofu], [], {"protein": 40}, excluded_allergens={"fish"})

    assert _names(plan) == [(2, "Tofu")]


def test_unknown_allergen_items_are_still_usable_by_default():
    untagged = make_item("House Special", protein_g=40, calories=300)

    plan = plan_plate([untagged], [], {"protein": 40}, excluded_allergens={"Fish"})

    assert _names(plan) == [(1, "House Special")]


def test_exclude_policy_drops_items_tagged_only_with_dietary_labels():
    vegan_only = make_item("Vegan Bowl", protein_g=40, calories=300, allergens=["Vegan"])

    plan = plan_plate(
        [vegan_only],
        [],
        {"protein": 40},
        excluded_allergens={"Fish"},
        unknown_policy=UnknownAllergenPolicy.EXCLUDE,
    )

    assert plan.items == []


def test_a_whole_hall_plans_well_under_a_second():
    mains = [
        make_item(f"Main {i}", protein_g=15 + i, calories=200 + 9 * i, carbs_g=i, fat_g=i % 9)
        for i in range(40)
    ]
    sides = [
        make_item(f"Side {i}", protein_g=i % 7, calories=50 + 3 * i, carbs_g=i % 40, fat_g=i % 11)
        for i in range(200)
    ]
    targets = {"protein": 60, "carbs": 70, "fat": 20, "calories": 700}

    start = time.perf_counter()
    plan = plan_plate(mains, sides, targets)
    assert time.perf_counter() - start < 1.0
    assert 1 <= len(plan.items) <= 3
