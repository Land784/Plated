import json
from pathlib import Path

from menu.digest import (
    build_hall_section,
    build_picks_section,
    filter_stations,
    group_by_station,
    normalize_station,
    render_stations,
)
from menu.macros import Goal
from menu.models import DayMenu, WeekMenu
from menu.users import MacrosConfig, PicksConfig

FIXTURE = Path(__file__).parent / "fixtures" / "real_north_lunch_2026-09-21.json"
DINNER = Path(__file__).parent / "fixtures" / "real_north_dinner_2026-09-24.json"
DINNER_STATIONS = ["Domer Diner", "Mezze", "Crust & Co"]


def _real_day() -> DayMenu:
    week = WeekMenu.model_validate(json.loads(FIXTURE.read_text()))
    return next(d for d in week.days if d.menu_items)


def _day(items: list[dict]) -> DayMenu:
    return DayMenu.model_validate({"date": "2026-09-21", "menu_items": items})


def test_normalize_strips_leading_article_and_case():
    # North publishes "The Global Compass", South publishes "Global
    # Compass" for the same station. They must match.
    assert normalize_station("The Global Compass") == normalize_station("Global Compass")
    assert normalize_station("  DOMER   DINER ") == "domer diner"


def test_group_by_station_attaches_items_to_preceding_header():
    day = _day(
        [
            {"is_station_header": True, "text": "Domer Diner", "station_id": 1},
            {"station_id": 1, "food": {"name": "Smash Burger"}},
            {"station_id": 1, "food": {"name": "Chicken Tenders"}},
            {"is_station_header": True, "text": "La Mesa", "station_id": 2},
            {"station_id": 2, "food": {"name": "Steak Pepito"}},
        ]
    )
    stations = group_by_station(day)
    assert [s.name for s in stations] == ["Domer Diner", "La Mesa"]
    assert stations[0].dish_names == ["Smash Burger", "Chicken Tenders"]
    assert stations[1].dish_names == ["Steak Pepito"]


def test_group_by_station_drops_empty_stations():
    day = _day(
        [
            {"is_station_header": True, "text": "Empty Station", "station_id": 1},
            {"is_station_header": True, "text": "Real Station", "station_id": 2},
            {"station_id": 2, "food": {"name": "Butter Chicken"}},
        ]
    )
    assert [s.name for s in group_by_station(day)] == ["Real Station"]


def test_duplicate_dishes_are_collapsed():
    # South really did list "Sliced Red Onion" twice in one station.
    day = _day(
        [
            {"is_station_header": True, "text": "Boom Boom Salad", "station_id": 1},
            {"station_id": 1, "food": {"name": "Sliced Red Onion"}},
            {"station_id": 1, "food": {"name": "Sliced Red Onion"}},
        ]
    )
    station = group_by_station(day)[0]
    assert station.dish_names == ["Sliced Red Onion"]


def test_filter_stations_matches_across_hall_naming_variants():
    day = _day(
        [
            {"is_station_header": True, "text": "The Global Compass", "station_id": 1},
            {"station_id": 1, "food": {"name": "Butter Chicken"}},
            {"is_station_header": True, "text": "Fountain Drinks", "station_id": 2},
            {"station_id": 2, "food": {"name": "Diet Coke"}},
        ]
    )
    kept = filter_stations(group_by_station(day), ["Global Compass"])
    assert [s.name for s in kept] == ["The Global Compass"]


def test_render_caps_items_and_reports_the_remainder():
    day = _day(
        [
            {"is_station_header": True, "text": "Pastaria", "station_id": 1},
            *[{"station_id": 1, "food": {"name": f"Item {i}"}} for i in range(6)],
        ]
    )
    lines = render_stations(group_by_station(day), max_items=2)
    assert lines == ["Pastaria", "  Item 0", "  Item 1", "  +4 more"]


def test_render_without_truncation_has_no_more_line():
    day = _day(
        [
            {"is_station_header": True, "text": "Crust & Co", "station_id": 1},
            {"station_id": 1, "food": {"name": "Sausage Pizza"}},
        ]
    )
    lines = render_stations(group_by_station(day), max_items=4)
    assert lines == ["Crust & Co", "  Sausage Pizza"]


def test_build_hall_section_on_real_fixture():
    section = build_hall_section("North Dining Hall", _real_day(), ["Homestyle"], max_items=2)
    assert section[0] == "NORTH DINING HALL"
    assert section[1] == "Homestyle"
    assert section[-1] == "  +2 more"


def test_build_hall_section_returns_empty_when_nothing_matches():
    assert build_hall_section("North", _real_day(), ["Nonexistent"], 4) == []


def test_build_hall_section_handles_missing_day():
    assert build_hall_section("North", None, ["Homestyle"], 4) == []


def _real_dinner() -> DayMenu:
    week = WeekMenu.model_validate(json.loads(DINNER.read_text()))
    return next(d for d in week.days if d.menu_items)


def _food(name: str, protein: float, calories: float, tags: list[str] | None = None) -> dict:
    return {
        "station_id": 1,
        "food": {
            "name": name,
            "rounded_nutrition_info": {
                "g_protein": protein,
                "calories": calories,
                "g_carbs": 0,
                "g_fat": 0,
            },
            "icons": {"food_icons": [{"name": t} for t in (tags or [])]},
        },
    }


PROTEIN_70 = MacrosConfig(goals={"protein": Goal(target=70)})


def _picks(halls, allowlist, macros=PROTEIN_70, picks=None, meal="dinner"):
    return build_picks_section(halls, allowlist, macros, picks or PicksConfig(), meal)


def test_picks_section_renders_the_real_dinner_combo():
    lines = _picks([("North Dining Hall", _real_dinner())], DINNER_STATIONS)
    assert lines == [
        "PICKS: protein 60-80g",
        "North Dining Hall: 78P 12C 16F · 513 cal",
        "  2× Garden Herb Grilled Chicken",
        # Only tag is "High Performance", a dietary label, so no allergen
        # information exists for this item.
        "     21P 0C 0F · 89 cal (1 tender) · allergens unknown",
        "  Pork Tenderloin Agrodolce",
        "     36P 12C 16F · 335 cal (6 oz portion) · Dairy, Fish, Soy",
    ]


def test_picks_only_draw_from_allowlisted_stations():
    # Crust & Co's only rows are bulk whole pizzas, none of them rankable.
    assert _picks([("North Dining Hall", _real_dinner())], ["Crust & Co"]) == []


def test_every_station_is_used_without_an_allowlist():
    lines = _picks([("North Dining Hall", _real_dinner())], None)
    assert lines[1] == "North Dining Hall: 78P 12C 16F · 513 cal"


def test_each_hall_gets_its_own_combo_and_misses_are_explained():
    north = _day(
        [
            {"is_station_header": True, "text": "Grill", "station_id": 1},
            _food("North Chicken", 40, 300, ["Soy"]),
        ]
    )
    south = _day(
        [
            {"is_station_header": True, "text": "Grill", "station_id": 1},
            _food("South Steak", 30, 400, ["Dairy"]),
        ]
    )
    macros = MacrosConfig(goals={"protein": Goal(min=100)})
    lines = _picks([("North", north), ("South", south)], ["Grill"], macros=macros)
    assert lines == [
        "PICKS: protein ≥100g",
        "North: 80P 0C 0F · 600 cal",
        "  closest available: protein 80g (want ≥100g)",
        "  2× North Chicken",
        "     40P 0C 0F · 300 cal · Soy",
        "South: 60P 0C 0F · 800 cal",
        "  closest available: protein 60g (want ≥100g)",
        "  2× South Steak",
        "     30P 0C 0F · 400 cal · Dairy",
    ]


def test_meal_override_goals_are_used_for_that_meal():
    macros = MacrosConfig(
        goals={"protein": Goal(target=70)}, meals={"brunch": {"protein": Goal(target=30)}}
    )
    lines = _picks([("North", _real_dinner())], DINNER_STATIONS, macros=macros, meal="brunch")
    assert lines[0] == "PICKS: protein 26-34g"


def test_no_goals_for_a_meal_means_no_picks():
    macros = MacrosConfig(meals={"dinner": {"protein": Goal(min=40)}})
    assert _picks([("North", _real_dinner())], DINNER_STATIONS, macros=macros, meal="lunch") == []


def test_excluded_allergens_are_dropped_from_picks():
    day = _day(
        [
            {"is_station_header": True, "text": "Grill", "station_id": 1},
            _food("Shrimp Bowl", 40, 300, ["Shellfish"]),
            _food("Chicken Bowl", 30, 300, ["Soy"]),
        ]
    )
    lines = _picks(
        [("North", day)],
        ["Grill"],
        macros=MacrosConfig(goals={"protein": Goal(min=30)}),
        picks=PicksConfig(exclude_allergens=["shellfish"]),
    )
    assert "Shrimp Bowl" not in "\n".join(lines)
    assert "  Chicken Bowl" in lines


def test_picks_skip_halls_with_no_menu():
    assert _picks([("North", None)], ["Grill"]) == []
