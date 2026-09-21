"""Regression test against a real captured Nutrislice response.

This guards the model shapes in menu/models.py against upstream schema
drift: if Nutrislice changes its JSON, this test breaks loudly instead
of the pipeline silently losing nutrition/allergen data in production.
See tests/fixtures/README.md for how the fixture was captured.
"""

import json
from pathlib import Path

from menu.models import WeekMenu

FIXTURE = Path(__file__).parent / "fixtures" / "real_north_lunch_2026-09-21.json"


def _load_week() -> WeekMenu:
    raw = json.loads(FIXTURE.read_text())
    return WeekMenu.model_validate(raw)


def _by_name(week: WeekMenu, name: str):
    for day in week.days:
        for item in day.menu_items:
            if item.food and item.food.name == name:
                return item
    raise AssertionError(f"{name!r} not found in fixture")


def test_empty_day_parses_with_no_items():
    week = _load_week()
    empty_day = next(d for d in week.days if d.menu_items == [])
    assert empty_day.date.isoformat() == "2026-09-20"


def test_station_header_has_no_food():
    week = _load_week()
    day = next(d for d in week.days if d.menu_items)
    header = next(i for i in day.menu_items if i.is_station_header)
    assert header.food is None
    assert header.text == "Homestyle"


def test_item_with_allergen_icons_parses_nutrition_and_tags():
    week = _load_week()
    pizza = _by_name(week, "Cheese Pizza")
    assert pizza.food.nutrition.protein_g == 116.0
    assert pizza.food.nutrition.calories == 2473.0
    tag_names = {a.name for a in pizza.food.allergens}
    assert {"Dairy", "Wheat"} <= tag_names


def test_item_with_no_icon_data_has_empty_allergens_not_invented_ones():
    week = _load_week()
    ribeye = _by_name(week, "Shaved Ribeye")
    # Real fixture: Nutrislice reported zero icons for this item. That
    # must come through as an empty list -- never as "safe" or
    # populated with guessed values.
    assert ribeye.food.allergens == []
    assert ribeye.food.nutrition.protein_g == 97.0


def test_serving_size_is_preserved_verbatim_including_data_quality_quirks():
    week = _load_week()
    quinoa = _by_name(week, "Quinoa")
    # Real upstream data quirk: unit is "z", not "oz". Must be passed
    # through as-is, not silently corrected.
    assert quinoa.food.serving_size.amount == "4"
    assert quinoa.food.serving_size.unit == "z"

    pasta = _by_name(week, "Vegetarian Macaroni Pasta Salad")
    assert pasta.food.serving_size.amount == "0.75"
    assert pasta.food.serving_size.unit == "cups"
