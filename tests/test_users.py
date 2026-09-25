from datetime import time
from pathlib import Path

import pytest

from menu.allergens import UnknownAllergenPolicy
from menu.macros import Goal
from menu.users import (
    DEFAULT_HALLS,
    DEFAULT_MAX_ITEMS,
    PicksConfig,
    UserConfigError,
    load_users,
    parse_user,
)

REPO_EXAMPLE = Path(__file__).parent.parent / "users.example.toml"

MINIMAL = {"name": "Wes", "ntfy_topic": "topic-abc"}


def test_minimal_user_gets_sensible_defaults():
    user = parse_user(MINIMAL, "test.toml")
    assert user.name == "Wes"
    assert user.halls == list(DEFAULT_HALLS)
    assert user.max_items_per_station == DEFAULT_MAX_ITEMS
    assert user.schedule == {}


def test_schedule_times_are_parsed():
    user = parse_user(
        {**MINIMAL, "schedule": {"monday": {"lunch": "11:15", "dinner": "17:30"}}},
        "test.toml",
    )
    assert user.schedule["monday"]["lunch"] == time(11, 15)
    assert user.schedule["monday"]["dinner"] == time(17, 30)


def test_name_and_topic_are_required():
    with pytest.raises(UserConfigError, match="name"):
        parse_user({"ntfy_topic": "t"}, "test.toml")
    with pytest.raises(UserConfigError, match="ntfy_topic"):
        parse_user({"name": "Wes"}, "test.toml")


def test_unknown_weekday_is_rejected():
    with pytest.raises(UserConfigError, match="unknown weekday"):
        parse_user({**MINIMAL, "schedule": {"funday": {"lunch": "11:15"}}}, "test.toml")


def test_malformed_time_is_rejected():
    with pytest.raises(UserConfigError):
        parse_user({**MINIMAL, "schedule": {"monday": {"lunch": "noon"}}}, "test.toml")
    with pytest.raises(UserConfigError):
        parse_user({**MINIMAL, "schedule": {"monday": {"lunch": "25:00"}}}, "test.toml")


def test_unknown_timezone_is_rejected():
    with pytest.raises(UserConfigError, match="timezone"):
        parse_user({**MINIMAL, "timezone": "Mars/Olympus"}, "test.toml")


def test_unknown_meal_slug_is_allowed_through():
    # Nutrislice can add menu types; an unrecognised slug simply returns
    # an empty menu, which alerts the owner rather than blocking config.
    user = parse_user({**MINIMAL, "schedule": {"monday": {"tea-time": "15:00"}}}, "t.toml")
    assert user.schedule["monday"]["tea-time"] == time(15, 0)


def test_committed_example_file_is_valid(tmp_path):
    # Copy into an isolated directory: the template deliberately lives
    # outside users/, so its own parent is the repo root.
    (tmp_path / "wes.toml").write_text(REPO_EXAMPLE.read_text())
    users = load_users(tmp_path)

    assert len(users) == 1
    example = users[0]
    assert example.schedule["sunday"]["brunch"] == time(10, 30)
    assert "Global Compass" in example.stations


def test_only_toml_files_are_loaded(tmp_path):
    (tmp_path / "wes.toml").write_text(REPO_EXAMPLE.read_text())
    (tmp_path / "README.md").write_text("not a subscriber")
    assert len(load_users(tmp_path)) == 1


def test_missing_directory_raises():
    with pytest.raises(UserConfigError, match="not found"):
        load_users(Path("/nonexistent/users/dir"))


def test_picks_are_off_without_a_macros_table():
    user = parse_user(MINIMAL, "test.toml")
    assert user.macros is None
    assert user.picks == PicksConfig()


def test_macros_parse_every_goal_type():
    user = parse_user(
        {
            **MINIMAL,
            "macros": {
                "protein": {"target": 70, "tolerance": 5},
                "carbs": {"max": 60},
                "fiber": {"min": 8},
                "sodium": {"min": 0, "max": 1500},
            },
        },
        "test.toml",
    )
    assert user.macros.goals == {
        "protein": Goal(target=70, tolerance=5),
        "carbs": Goal(max=60),
        "fiber": Goal(min=8),
        "sodium": Goal(min=0, max=1500),
    }


def test_meal_overrides_merge_over_defaults_per_nutrient():
    user = parse_user(
        {
            **MINIMAL,
            "macros": {
                "protein": {"target": 70},
                "fat": {"max": 30},
                "Brunch": {"protein": {"target": 50}},
            },
        },
        "test.toml",
    )
    assert user.macros.for_meal("brunch") == {
        "protein": Goal(target=50),
        "fat": Goal(max=30),
    }
    assert user.macros.for_meal("dinner")["protein"] == Goal(target=70)


def test_overrides_alone_are_allowed():
    user = parse_user({**MINIMAL, "macros": {"dinner": {"protein": {"min": 40}}}}, "test.toml")
    assert user.macros.for_meal("lunch") == {}
    assert user.macros.for_meal("dinner") == {"protein": Goal(min=40)}


def test_picks_table_overrides_defaults():
    user = parse_user(
        {
            **MINIMAL,
            "macros": {"protein": {"target": 50}},
            "picks": {
                "min_item_protein_g": 10,
                "max_item_calories": 900,
                "max_servings_per_item": 3,
                "max_total_servings": 5,
                "exclude_allergens": ["Peanuts", " Shellfish "],
                "unknown_allergens": "exclude",
            },
        },
        "test.toml",
    )
    assert user.picks == PicksConfig(
        min_item_protein_g=10,
        max_item_calories=900,
        max_servings_per_item=3,
        max_total_servings=5,
        exclude_allergens=["Peanuts", "Shellfish"],
        unknown_allergens=UnknownAllergenPolicy.EXCLUDE,
    )


def test_old_protein_table_explains_the_replacement():
    with pytest.raises(UserConfigError, match=r"replaced by \[macros\]"):
        parse_user({**MINIMAL, "protein": {"target_g": 70}}, "test.toml")


@pytest.mark.parametrize(
    ("macros", "match"),
    [
        ({}, "no goals"),
        ({"protein": 70}, "expected a table"),
        ({"protien": {"target": 70}}, "not a nutrient"),
        ({"protein": {"goal": 70}}, "unknown key"),
        ({"protein": {"tolerance": 5}}, "at least one of target, min, max"),
        ({"protein": {"target": 0}}, "positive number"),
        ({"protein": {"target": True}}, "expected a number"),
        ({"protein": {"min": -1}}, ">= 0"),
        ({"protein": {"min": 5, "tolerance": 2}}, "tolerance only applies"),
        ({"protein": {"min": 90, "max": 60}}, "no allowed range"),
        ({"fat": {"max": 30}}, "at least one target or min"),
        ({"protein": {"target": 70}, "brunch": {"fat": {"max": 20}}}, None),
        ({"brunch": {"fat": {"max": 20}}}, r"\[macros.brunch\] needs at least one target"),
        ({"brunch": {"protien": {"min": 20}}}, "must be a nutrient goal or a meal override"),
    ],
)
def test_malformed_macros_are_rejected(macros, match):
    if match is None:
        parse_user({**MINIMAL, "macros": macros}, "test.toml")  # valid: inherits protein
        return
    with pytest.raises(UserConfigError, match=match):
        parse_user({**MINIMAL, "macros": macros}, "test.toml")


@pytest.mark.parametrize(
    ("picks", "match"),
    [
        ({"max_servings": 2}, "unknown key"),
        ({"min_item_protein_g": -1}, "min_item_protein_g"),
        ({"max_item_calories": 0}, "max_item_calories"),
        ({"max_servings_per_item": 0}, "max_servings_per_item"),
        ({"max_total_servings": 6}, "max_total_servings"),
        ({"max_total_servings": 2.5}, "max_total_servings"),
        ({"exclude_allergens": "Peanuts"}, "exclude_allergens"),
        ({"unknown_allergens": "ignore"}, "unknown_allergens"),
    ],
)
def test_malformed_picks_are_rejected(picks, match):
    with pytest.raises(UserConfigError, match=match):
        parse_user({**MINIMAL, "macros": {"protein": {"target": 70}}, "picks": picks}, "test.toml")
