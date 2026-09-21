from menu.models import DayMenu, Food, MenuItem, NutritionInfo


def test_nutrition_info_accepts_nutrislice_aliases():
    n = NutritionInfo.model_validate({"calories": 250, "g_protein": 30, "g_fat": 5})
    assert n.calories == 250
    assert n.protein_g == 30
    assert n.fat_g == 5


def test_nutrition_info_missing_fields_are_none_not_zero():
    n = NutritionInfo.model_validate({"calories": 100})
    assert n.protein_g is None  # must not default to 0 -- see CLAUDE.md


def test_food_ignores_unknown_fields():
    food = Food.model_validate(
        {"name": "Orange Chicken", "some_new_field_nutrislice_added": {"x": 1}}
    )
    assert food.name == "Orange Chicken"
    assert food.allergens == []


def test_menu_item_without_food_does_not_crash():
    item = MenuItem.model_validate({"is_station_header": True})
    assert item.food is None
    assert item.is_station_header is True


def test_day_menu_parses_nested_items():
    day = DayMenu.model_validate(
        {
            "date": "2024-01-08",
            "menu_items": [
                {"food": {"name": "Rice"}, "station_id": 1},
                {"is_station_header": True, "text": "Grill", "station_id": 1},
            ],
        }
    )
    assert len(day.menu_items) == 2
    assert day.menu_items[0].food.name == "Rice"
