import json
from datetime import date
from pathlib import Path

import pytest

from menu.digest import (
    BODY_BUDGET_BYTES,
    HallSection,
    MainsRule,
    build_message,
    build_picks_blocks,
    filter_stations,
    fit_to_budget,
    glance_line,
    group_by_station,
    hall_label,
    hall_page_url,
    meal_tags,
    normalize_station,
    notification_title,
    station_lineup,
    station_mains,
    stations_in_allowlist_order,
)
from menu.macros import Goal
from menu.models import DayMenu, WeekMenu
from menu.notifier import compose_body
from menu.users import MacrosConfig, PicksConfig, parse_user

FIXTURES = Path(__file__).parent / "fixtures"
# The example subscriber's allowlist, in its order.
STATIONS = [
    "Domer Diner",
    "La Mesa",
    "Mezze",
    "Crust & Co",
    "Green & Grains",
    "Comfort Kitchen",
    "Athenian Rice Bowl",
    "Global Compass",
    "Curry Bar",
    "Harvest Bowl",
    "Pastaria",
    "Pasta Stir Fry",
    "Homestyle",
]
RULE = MainsRule(min_protein_g=10, max_item_calories=1200, max_items=3)


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


def _real_dinner(hall: str) -> DayMenu:
    path = FIXTURES / f"real_{hall}_dinner_2026-09-24.json"
    week = WeekMenu.model_validate(json.loads(path.read_text()))
    return next(d for d in week.days if d.menu_items)


NORTH = _real_dinner("north")
SOUTH = _real_dinner("south")
MENUS = {"north-dining-hall": NORTH, "south-dining-hall": SOUTH}


def _station(day: DayMenu, name: str):
    return next(s for s in group_by_station(day) if normalize_station(s.name) == name.lower())


def _food(
    name: str,
    protein: float | None,
    calories: float | None,
    tags: list[str] | None = None,
    unit: str | None = None,
) -> dict:
    nutrition = {"g_protein": protein, "calories": calories, "g_carbs": 0, "g_fat": 0}
    food = {
        "name": name,
        "rounded_nutrition_info": {k: v for k, v in nutrition.items() if v is not None},
        "icons": {"food_icons": [{"name": t} for t in (tags or [])]},
    }
    if unit is not None:
        food["serving_size_info"] = {"serving_size_amount": "1", "serving_size_unit": unit}
    return {"station_id": 1, "food": food}


def _header(name: str) -> dict:
    return {"is_station_header": True, "text": name, "station_id": 1}


# --- the mains rule ---


def test_dish_unit_makes_a_low_protein_item_a_main():
    # 3g protein, but its serving is "1 taco".
    assert station_lineup(_station(SOUTH, "La Mesa"), RULE) == ["Tacos Al Pastor"]


def test_protein_floor_decides_mains_without_a_dish_unit():
    # Fried Catfish 12g ("1 fillet"), Dirty Rice 11g; Coleslaw 0g is a side.
    assert station_lineup(_station(NORTH, "Comfort Kitchen"), RULE) == [
        "Fried Catfish",
        "Dirty Rice",
    ]


def test_mains_rank_by_protein_and_are_capped():
    # Cantina 56g, Smash Burger 28g, Grilled Chicken 21g, then two more.
    assert station_lineup(_station(NORTH, "Domer Diner"), RULE) == [
        "Cantina Sandwich",
        "Smash Burger",
        "Garden Herb Grilled Chicken",
    ]


def test_bulk_rows_never_qualify_but_the_station_still_shows_one():
    # All three are whole pizzas at 2473-3996 cal; the fallback ignores
    # the ceiling and shows the highest-protein one.
    assert station_lineup(_station(NORTH, "Crust & Co"), RULE) == ["Pepperoni Pizza"]


def test_a_station_with_no_main_falls_back_to_its_highest_protein_item():
    # Pastaria is a build-your-own bar; nothing reaches 10g. Two items
    # tie at 6g, and the tie goes to menu order.
    assert station_lineup(_station(SOUTH, "Pastaria"), RULE) == ["Halal Chicken & Beef Pepperoni"]


def test_fallback_without_any_protein_value_is_the_first_item():
    day = _day([_header("Pastaria"), _food("Penne", None, 200), _food("Pesto", None, 150)])
    assert station_lineup(group_by_station(day)[0], RULE) == ["Penne"]


def test_dish_words_match_whole_words_only():
    day = _day(
        [
            _header("Grill"),
            _food("Grilled Hot Dog", 8, 265, unit="hot dog+bun"),
            _food("Pineapple", 0, 16, unit="Slice"),
            _food("Subway Roll", 2, 100, unit="subway roll"),
            _food("Pork Chop", 5, 300, unit="stuffed chop"),
        ]
    )
    names = station_lineup(group_by_station(day)[0], RULE)
    assert names == ["Grilled Hot Dog", "Pork Chop"]


def test_a_weight_portion_unit_does_not_make_a_main():
    # Curtido, a 1g slaw, is served as "4 oz portion".
    day = _day([_header("La Mesa"), _food("Curtido", 1, 30, unit="oz portion")])
    assert station_mains(group_by_station(day)[0], RULE) == []


def test_plural_dish_units_count():
    day = _day(
        [
            _header("Grill"),
            _food("Tacos", 3, 160, unit="tacos"),
            _food("Wings", 5, 200, unit="wings"),
            _food("Sliders", 8, 200, unit="patties"),
        ]
    )
    names = station_lineup(group_by_station(day)[0], MainsRule(10, 1200, 5))
    assert names == ["Sliders", "Wings", "Tacos"]


def test_main_protein_floor_is_per_subscriber():
    rule = MainsRule(min_protein_g=20, max_item_calories=1200, max_items=3)
    assert station_lineup(_station(NORTH, "Mezze"), rule) == ["Pork Tenderloin Agrodolce"]


def test_mains_rule_does_not_change_picks_eligibility():
    # Quinoa (15g) is a main at the default floor, and a pick candidate
    # only at the planner's own floor, which the mains rule never reads.
    macros = MacrosConfig(goals={"protein": Goal(min=15)})
    picks = PicksConfig(min_item_protein_g=16, max_servings_per_item=1, max_total_servings=1)
    day = _day([_header("Mezze"), _food("Quinoa", 15, 403)])
    assert station_lineup(group_by_station(day)[0], RULE) == ["Quinoa"]
    assert build_picks_blocks([("North", day)], ["Mezze"], macros, picks, "dinner") == []


# --- glance and station order ---


def test_glance_takes_at_most_one_main_per_station():
    day = _day(
        [
            _header("Grill"),
            _food("Steak", 50, 500),
            _food("Chicken", 45, 300),
            _food("Pork", 40, 400),
            _header("Mezze"),
            _food("Falafel", 10, 200),
        ]
    )
    assert glance_line("North", group_by_station(day), RULE) == "North: Steak, Falafel"


def test_glance_skips_fallback_items_and_ranks_by_protein():
    stations = stations_in_allowlist_order(SOUTH, STATIONS)
    # Pasta Stir-Fry Station (fallback) and Pastaria never appear.
    assert glance_line("South", stations, RULE) == (
        "South: Pork Tenderloin Agrodolce, Mushroom Florentine Pork Chops, "
        "Pepperoni & Cheese French Bread Pizza"
    )


def test_hall_with_no_mains_has_no_glance():
    day = _day([_header("Pastaria"), _food("Penne", 5, 200)])
    assert glance_line("North", group_by_station(day), RULE) is None


def test_stations_follow_the_allowlist_order_and_keep_published_names():
    stations = stations_in_allowlist_order(NORTH, STATIONS)
    assert [s.name for s in stations] == [
        "Domer Diner",
        "La Mesa",
        "Mezze",
        "Crust & Co",
        "Green & Grains",
        "Comfort Kitchen",
        "The Global Compass",
    ]


# --- picks ---

PROTEIN_70 = MacrosConfig(goals={"protein": Goal(target=70)})


def _picks(halls, allowlist=STATIONS, macros=PROTEIN_70, picks=None, meal="dinner"):
    return build_picks_blocks(halls, allowlist, macros, picks or PicksConfig(), meal)


def test_identical_hall_combos_merge_into_one_block():
    assert _picks([("North", NORTH), ("South", SOUTH)]) == [
        [
            "PICKS · both halls · 78P 12C 16F · 513 cal",
            "2× Garden Herb Grilled Chicken · 42P · 178 cal",
            "Pork Tenderloin Agrodolce · 36P · 335 cal",
        ]
    ]


def test_different_combos_get_a_block_per_hall_with_misses():
    north = _day([_header("Grill"), _food("North Chicken", 40, 300, ["Soy"])])
    south = _day([_header("Grill"), _food("South Steak", 30, 400, ["Dairy"])])
    macros = MacrosConfig(goals={"protein": Goal(min=100)})
    assert _picks([("North", north), ("South", south)], ["Grill"], macros=macros) == [
        [
            "PICKS · North · 80P 0C 0F · 600 cal",
            "2× North Chicken · 80P · 600 cal",
            "closest: protein 80g (want ≥100g)",
        ],
        [
            "PICKS · South · 60P 0C 0F · 800 cal",
            "2× South Steak · 60P · 800 cal",
            "closest: protein 60g (want ≥100g)",
        ],
    ]


def test_same_combo_with_different_allergen_tags_is_not_merged():
    north = _day([_header("Grill"), _food("Chicken", 40, 300, ["Soy"])])
    south = _day([_header("Grill"), _food("Chicken", 40, 300, ["High Performance"])])
    macros = MacrosConfig(goals={"protein": Goal(min=80)})
    blocks = _picks([("North", north), ("South", south)], ["Grill"], macros=macros)
    assert [block[0] for block in blocks] == [
        "PICKS · North · 80P 0C 0F · 600 cal",
        "PICKS · South · 80P 0C 0F · 600 cal",
    ]


def test_one_hall_with_a_plan_is_named_not_merged():
    assert _picks([("North", NORTH), ("South", None)])[0][0] == (
        "PICKS · North · 78P 12C 16F · 513 cal"
    )


def test_unknown_allergens_are_flagged_only_when_excluding_allergens():
    picks = PicksConfig(exclude_allergens=["Peanuts"])
    [block] = _picks([("North", NORTH), ("South", SOUTH)], picks=picks)
    # Grilled Chicken's only tag is the dietary label "High Performance".
    assert block[1:] == [
        "2× Garden Herb Grilled Chicken · 42P · 178 cal · allergens unknown",
        "Pork Tenderloin Agrodolce · 36P · 335 cal",
    ]


def test_a_missing_nutrient_prints_a_question_mark():
    day = _day(
        [
            _header("Grill"),
            {
                "station_id": 1,
                "food": {
                    "name": "Mystery Meat",
                    "rounded_nutrition_info": {"g_protein": 35, "calories": 300},
                },
            },
        ]
    )
    macros = MacrosConfig(goals={"protein": Goal(min=60)})
    [block] = _picks([("North", day)], ["Grill"], macros=macros)
    assert block[:2] == ["PICKS · North · 70P ?C ?F · 600 cal", "2× Mystery Meat · 70P · 600 cal"]


def test_meal_override_goals_are_used_for_that_meal():
    macros = MacrosConfig(
        goals={"protein": Goal(target=70)}, meals={"brunch": {"protein": Goal(target=30)}}
    )
    [block] = _picks([("North", NORTH)], macros=macros, meal="brunch")
    assert block[0].startswith("PICKS · North · 3")


def test_no_goals_for_a_meal_means_no_picks():
    macros = MacrosConfig(meals={"dinner": {"protein": Goal(min=40)}})
    assert _picks([("North", NORTH)], macros=macros, meal="lunch") == []


def test_excluded_allergens_are_dropped_from_picks():
    day = _day(
        [
            _header("Grill"),
            _food("Shrimp Bowl", 40, 300, ["Shellfish"]),
            _food("Chicken Bowl", 30, 300, ["Soy"]),
        ]
    )
    blocks = _picks(
        [("North", day)],
        ["Grill"],
        macros=MacrosConfig(goals={"protein": Goal(min=30)}),
        picks=PicksConfig(exclude_allergens=["shellfish"]),
    )
    assert "Shrimp Bowl" not in str(blocks)
    assert "Chicken Bowl · 30P · 300 cal" in blocks[0]


def test_picks_only_draw_from_allowlisted_stations():
    # Crust & Co's only rows are bulk whole pizzas, none of them rankable.
    assert _picks([("North", NORTH)], ["Crust & Co"]) == []


def test_picks_skip_halls_with_no_menu():
    assert _picks([("North", None)]) == []


# --- the whole message ---


def _user(**overrides):
    return parse_user(
        {
            "name": "Wes",
            "ntfy_topic": "topic-abc",
            "stations": STATIONS,
            "max_items_per_station": 3,
            "macros": {"protein": {"target": 70}},
            **overrides,
        },
        "test",
    )


def test_real_dinner_message():
    assert build_message(_user(), MENUS, "dinner") == [
        "North: Cantina Sandwich, Southwest Salad, Pork Tenderloin Agrodolce",
        "South: Pork Tenderloin Agrodolce, Mushroom Florentine Pork Chops, "
        "Pepperoni & Cheese French Bread Pizza",
        "",
        "PICKS · both halls · 78P 12C 16F · 513 cal",
        "2× Garden Herb Grilled Chicken · 42P · 178 cal",
        "Pork Tenderloin Agrodolce · 36P · 335 cal",
        "",
        "NORTH",
        "Domer Diner: Cantina Sandwich, Smash Burger, Garden Herb Grilled Chicken",
        "La Mesa: Cochinita Pibil",
        "Mezze: Pork Tenderloin Agrodolce, Quinoa, Pork Osso Buco",
        "Crust & Co: Pepperoni Pizza",
        "Green & Grains: Southwest Salad",
        "Comfort Kitchen: Fried Catfish, Dirty Rice",
        "The Global Compass: Beef Pad See Ew",
        "",
        "SOUTH",
        "Domer Diner: Garden Herb Grilled Chicken, Smash Beef Patty, Black Bean Veggie Burger",
        "La Mesa: Tacos Al Pastor",
        "Mezze: Pork Tenderloin Agrodolce",
        "Crust & Co: Pepperoni & Cheese French Bread Pizza, Meatball Pizza, Pepperoni Pizza",
        "Comfort Kitchen: Mushroom Florentine Pork Chops, Beef Au Poivre",
        "Global Compass: Beef Pad See Ew",
        "Pastaria: Halal Chicken & Beef Pepperoni",
        "Pasta Stir Fry: Pasta Stir-Fry Station",
    ]


def test_subscriber_without_macros_gets_no_picks():
    lines = build_message(_user(macros=None), MENUS, "dinner")
    assert not any(line.startswith("PICKS") for line in lines)
    assert lines[3] == "NORTH"


def test_hall_order_follows_the_subscriber():
    lines = build_message(_user(halls=["south-dining-hall", "north-dining-hall"]), MENUS, "dinner")
    assert lines[0].startswith("South: ")
    assert lines.index("SOUTH") < lines.index("NORTH")


def test_hall_without_a_menu_is_left_out():
    lines = build_message(
        _user(), {"north-dining-hall": None, "south-dining-hall": SOUTH}, "dinner"
    )
    assert lines[0].startswith("South: ")
    assert "NORTH" not in lines
    assert lines[2] == "PICKS · South · 78P 12C 16F · 513 cal"


def test_no_station_content_means_no_message():
    assert build_message(_user(), {}, "dinner") == []
    assert build_message(_user(stations=["Nonexistent"]), MENUS, "dinner") == []


def test_real_message_is_well_inside_the_budget():
    body = compose_body("\n".join(build_message(_user(), MENUS, "dinner")))
    assert len(body.encode("utf-8")) <= BODY_BUDGET_BYTES


# --- byte guard ---


# Each station line is ~110 bytes, so both halls together are ~3,300.
STATIONS_PER_HALL = 15


def _oversize_menus() -> dict[str, DayMenu]:
    def hall(prefix: str) -> DayMenu:
        rows = []
        for station in range(STATIONS_PER_HALL):
            rows.append(_header(f"{prefix} Station {station:02d}"))
            rows += [_food(f"{prefix} Slow Braised Dish Number {i}", 30 - i, 400) for i in range(3)]
        return _day(rows)

    return {"north-dining-hall": hall("North"), "south-dining-hall": hall("South")}


def test_oversize_message_drops_station_lines_from_the_end():
    menus = _oversize_menus()
    stations = [
        f"{h} Station {i:02d}" for h in ("North", "South") for i in range(STATIONS_PER_HALL)
    ]
    user = _user(stations=stations)
    lines = build_message(user, menus, "dinner")
    body = compose_body("\n".join(lines))

    assert len(body.encode("utf-8")) <= BODY_BUDGET_BYTES
    # Glance and picks are untouched.
    assert lines[0].startswith("North: North Slow Braised Dish Number 0")
    assert lines[3].startswith("PICKS · ")
    # South lost stations first, from its end; North kept every station.
    north = lines[lines.index("NORTH") + 1 : lines.index("SOUTH") - 1]
    assert len(north) == STATIONS_PER_HALL
    south = lines[lines.index("SOUTH") + 1 :]
    assert south[-1].startswith("+") and south[-1].endswith(" stations")
    assert south[-2].startswith("South Station ")
    removed = int(south[-1][1:].split()[0])
    assert len(south) - 1 + removed == STATIONS_PER_HALL
    assert south[-2].startswith(f"South Station {STATIONS_PER_HALL - removed - 1:02d}:")


def test_trimming_moves_to_the_previous_hall_once_the_last_is_empty():
    north = HallSection("North", [f"Station {i}: " + "x" * 80 for i in range(20)])
    south = HallSection("South", [f"Station {i}: " + "y" * 80 for i in range(20)])
    lines = fit_to_budget([["North: a"]], [north, south], budget=1500)

    assert len(compose_body("\n".join(lines)).encode("utf-8")) <= 1500
    assert lines[lines.index("SOUTH") + 1 :] == ["+20 stations"]
    assert lines[lines.index("SOUTH") - 2].startswith("+")
    assert lines[0] == "North: a"


def test_a_message_under_budget_is_not_trimmed():
    lines = build_message(_user(), MENUS, "dinner")
    assert not any(line.startswith("+") for line in lines)


# --- title and headers ---


@pytest.mark.parametrize(
    ("meal", "tag"),
    [
        ("breakfast", "fried_egg"),
        ("brunch", "pancakes"),
        ("lunch", "sandwich"),
        ("dinner", "plate_with_cutlery"),
        ("late-lunch", "fork_and_knife"),
        ("special", "fork_and_knife"),
    ],
)
def test_each_meal_gets_its_emoji_tag(meal, tag):
    assert meal_tags(meal) == [tag]


def test_title_names_the_meal_and_date_without_padding():
    assert notification_title("dinner", date(2026, 9, 24)) == "Dinner · Thu Sep 24"
    assert notification_title("late-lunch", date(2026, 10, 2)) == "Late Lunch · Fri Oct 2"


def test_hall_label_and_page():
    assert hall_label("north-dining-hall") == "North"
    assert hall_page_url("south-dining-hall") == (
        "https://nd.nutrislice.com/menu/south-dining-hall/"
    )
