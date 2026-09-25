from datetime import time
from pathlib import Path

import pytest

from menu.allergens import UnknownAllergenPolicy
from menu.planner import DEFAULT_MAX_ITEM_CALORIES, DEFAULT_MIN_ITEM_PROTEIN_G
from menu.users import (
    DEFAULT_HALLS,
    DEFAULT_MAX_ITEMS,
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


def test_protein_picks_are_off_without_a_protein_table():
    assert parse_user(MINIMAL, "test.toml").protein is None


def test_protein_table_needs_only_a_target():
    user = parse_user({**MINIMAL, "protein": {"target_g": 70}}, "test.toml")
    assert user.protein.target_g == 70
    assert user.protein.min_item_protein_g == DEFAULT_MIN_ITEM_PROTEIN_G
    assert user.protein.max_item_calories == DEFAULT_MAX_ITEM_CALORIES
    assert user.protein.calorie_cap is None
    assert user.protein.exclude_allergens == []
    assert user.protein.unknown_allergens is UnknownAllergenPolicy.FLAG


def test_protein_table_accepts_every_option():
    user = parse_user(
        {
            **MINIMAL,
            "protein": {
                "target_g": 50,
                "min_item_protein_g": 10,
                "max_item_calories": 900,
                "calorie_cap": 1000,
                "exclude_allergens": ["Peanuts", " Shellfish "],
                "unknown_allergens": "exclude",
            },
        },
        "test.toml",
    )
    assert user.protein.max_item_calories == 900
    assert user.protein.calorie_cap == 1000
    assert user.protein.exclude_allergens == ["Peanuts", "Shellfish"]
    assert user.protein.unknown_allergens is UnknownAllergenPolicy.EXCLUDE


@pytest.mark.parametrize(
    ("protein", "match"),
    [
        ({}, "target_g"),
        ({"target_g": 0}, "positive number"),
        ({"target_g": True}, "positive number"),
        ({"target_g": "70"}, "positive number"),
        ({"target_g": 70, "min_item_protein_g": -1}, "min_item_protein_g"),
        ({"target_g": 70, "max_item_calories": 0}, "max_item_calories"),
        ({"target_g": 70, "exclude_allergens": "Peanuts"}, "exclude_allergens"),
        ({"target_g": 70, "unknown_allergens": "ignore"}, "unknown_allergens"),
    ],
)
def test_malformed_protein_table_is_rejected(protein, match):
    with pytest.raises(UserConfigError, match=match):
        parse_user({**MINIMAL, "protein": protein}, "test.toml")
