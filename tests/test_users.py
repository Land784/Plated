from datetime import time
from pathlib import Path

import pytest

from menu.allergens import UnknownAllergenPolicy
from menu.users import (
    DEFAULT_HALLS,
    DEFAULT_MAIN_PROTEIN_G,
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
    assert user.main_protein_g == DEFAULT_MAIN_PROTEIN_G == 10
    assert user.schedule == {}


def test_main_protein_floor_can_be_set_or_zeroed():
    assert parse_user({**MINIMAL, "main_protein_g": 15}, "test.toml").main_protein_g == 15
    assert parse_user({**MINIMAL, "main_protein_g": 0}, "test.toml").main_protein_g == 0


@pytest.mark.parametrize("value", [-1, "10", True, None])
def test_malformed_main_protein_floor_is_rejected(value):
    with pytest.raises(UserConfigError, match="main_protein_g"):
        parse_user({**MINIMAL, "main_protein_g": value}, "test.toml")


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
    assert user.macros == {}
    assert user.picks == PicksConfig()
    assert user.picks_on is False


def test_macros_are_plain_targets_and_a_null_clears_one():
    user = parse_user(
        {**MINIMAL, "macros": {"protein": 60, "calories": 700, "fat": None}}, "test.toml"
    )
    assert user.macros == {"protein": 60, "calories": 700}


def test_picks_need_the_switch_and_a_target():
    on = {"enabled": True}
    assert parse_user({**MINIMAL, "macros": {"protein": 60}, "picks": on}, "t").picks_on
    assert not parse_user({**MINIMAL, "macros": {"protein": 60}}, "t").picks_on
    assert not parse_user({**MINIMAL, "picks": on}, "t").picks_on


def test_retired_picks_keys_on_old_rows_are_ignored():
    old = {"min_item_protein_g": 15, "max_servings_per_item": 2, "max_total_servings": 4}
    assert parse_user({**MINIMAL, "picks": old}, "t").picks == PicksConfig()


def test_picks_table_overrides_defaults():
    user = parse_user(
        {
            **MINIMAL,
            "macros": {"protein": 50},
            "picks": {
                "enabled": True,
                "tolerance_pct": 10,
                "side_min_calories": 80,
                "max_main_servings": 3,
                "max_item_calories": 900,
                "exclude_allergens": ["Peanuts", " Shellfish "],
                "unknown_allergens": "exclude",
            },
        },
        "test.toml",
    )
    assert user.picks == PicksConfig(
        enabled=True,
        tolerance_pct=10,
        side_min_calories=80,
        max_main_servings=3,
        max_item_calories=900,
        exclude_allergens=["Peanuts", "Shellfish"],
        unknown_allergens=UnknownAllergenPolicy.EXCLUDE,
    )


def test_old_protein_table_explains_the_replacement():
    with pytest.raises(UserConfigError, match=r"replaced by \[macros\]"):
        parse_user({**MINIMAL, "protein": {"target_g": 70}}, "test.toml")


@pytest.mark.parametrize(
    ("macros", "match"),
    [
        ({"protein": {"target": 70}}, "plain number"),
        ({"fiber": 8}, "not a target"),
        ({"protien": 70}, "not a target"),
        ({"protein": 0}, "positive number"),
        ({"protein": True}, "expected a number"),
        ([70], "must be a table"),
    ],
)
def test_malformed_macros_are_rejected(macros, match):
    with pytest.raises(UserConfigError, match=match):
        parse_user({**MINIMAL, "macros": macros}, "test.toml")


@pytest.mark.parametrize(
    ("picks", "match"),
    [
        ({"max_servings": 4}, "unknown key"),
        ({"enabled": "yes"}, "enabled"),
        ({"tolerance_pct": 0}, "tolerance_pct"),
        ({"side_min_calories": -1}, "side_min_calories"),
        ({"max_item_calories": 0}, "max_item_calories"),
        ({"max_main_servings": 0}, "max_main_servings"),
        ({"max_main_servings": 4}, "max_main_servings"),
        ({"max_main_servings": 2.5}, "max_main_servings"),
        ({"exclude_allergens": "Peanuts"}, "exclude_allergens"),
        ({"unknown_allergens": "ignore"}, "unknown_allergens"),
    ],
)
def test_malformed_picks_are_rejected(picks, match):
    with pytest.raises(UserConfigError, match=match):
        parse_user({**MINIMAL, "macros": {"protein": 70}, "picks": picks}, "test.toml")
