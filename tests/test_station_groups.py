from datetime import date

import pytest

from menu import invite, menus_store
from menu.digest import (
    STATION_GROUPS,
    MainsRule,
    filter_stations,
    group_by_station,
    is_food_station,
    normalize_station,
    station_group_label,
    station_lines,
    stations_in_allowlist_order,
)
from menu.models import DayMenu

SOUTH_BOWLS = ["Athenian Rice Bowl", "Jerusalem Rice Bowl", "Harvest Bowl"]


@pytest.mark.parametrize("name", [*SOUTH_BOWLS, "Bowls", "bowl", "The  Poke BOWLS"])
def test_every_bowl_counter_normalizes_to_one_group(name):
    assert normalize_station(name) == "bowls"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Green & Grains", "green & grains"),
        ("Pasta Stir Fry", "pasta stir fry"),
        ("The Global Compass", "global compass"),
        ("Bowling Alley Grill", "bowling alley grill"),  # a word boundary, not a prefix
        ("Superbowl Wings", "superbowl wings"),
    ],
)
def test_other_stations_keep_their_own_name(name, expected):
    assert normalize_station(name) == expected


def test_a_bowl_toppings_bar_stays_its_own_non_food_station():
    """Grouping it would make the whole bowls group non-food in the catalog."""
    assert normalize_station("Harvest Bowl Toppings") == "harvest bowl toppings"
    assert not is_food_station("Harvest Bowl Toppings")
    assert is_food_station("Bowls")
    assert all(is_food_station(name) for name in SOUTH_BOWLS)


def test_group_label():
    assert STATION_GROUPS["bowls"]["label"] == "Bowls"
    assert station_group_label("bowls") == "Bowls"
    assert station_group_label(normalize_station("Harvest Bowl")) == "Bowls"
    assert station_group_label("domer diner") is None


def _day(station: str) -> DayMenu:
    return DayMenu.model_validate(
        {
            "date": "2026-10-07",
            "menu_items": [
                {"is_station_header": True, "text": "Domer Diner", "station_id": 1},
                {"station_id": 1, "food": {"name": "Burger", "serving_size_info": {}}},
                {"is_station_header": True, "text": station, "station_id": 99},
                {
                    "station_id": 99,
                    "food": {
                        "name": "Chicken Rice Bowl",
                        "rounded_nutrition_info": {"g_protein": 30},
                    },
                },
            ],
        }
    )


@pytest.mark.parametrize("allowlist_entry", ["Bowls", "Harvest Bowl", "Athenian Rice Bowl"])
@pytest.mark.parametrize("published", SOUTH_BOWLS)
def test_any_bowl_entry_allows_the_days_bowl_counter(allowlist_entry, published):
    kept = filter_stations(group_by_station(_day(published)), [allowlist_entry])
    assert [s.name for s in kept] == [published]


def test_station_lines_print_the_days_published_name():
    stations = stations_in_allowlist_order(_day("Jerusalem Rice Bowl"), ["Bowls", "Domer Diner"])
    rule = MainsRule(min_protein_g=10, max_item_calories=1200, max_items=3)
    assert station_lines(stations, rule) == [
        "• Jerusalem Rice Bowl: Chicken Rice Bowl",
        "• Domer Diner: Burger",
    ]


def test_menu_stations_rows_carry_the_group():
    rows = menus_store.station_rows(
        date(2026, 10, 7), "south-dining-hall", "lunch", _day("Athenian Rice Bowl")
    )
    bowl = next(r for r in rows if r["station"] == "Athenian Rice Bowl")
    assert bowl["normalized"] == "bowls"
    assert bowl["is_food"] is True


def test_invite_orders_the_bowls_group_as_a_south_food_station():
    rows = [
        {"station": "Bowls", "halls": ["south-dining-hall"], "meals": ["lunch"], "is_food": True},
        {
            "station": "Mezze",
            "halls": ["north-dining-hall", "south-dining-hall"],
            "meals": ["dinner"],
        },
        {"station": "Pastaria", "halls": ["south-dining-hall"], "meals": ["dinner"]},
    ]
    assert invite.catalog_order(rows) == ["Mezze", "Bowls", "Pastaria"]
