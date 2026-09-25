from datetime import date

from menu import cli
from menu.models import DayMenu
from menu.users import parse_user

MENU = DayMenu.model_validate(
    {
        "date": "2026-09-24",
        "menu_items": [
            {"is_station_header": True, "text": "Grill", "station_id": 1},
            {
                "station_id": 1,
                "food": {
                    "name": "Grilled Chicken",
                    "rounded_nutrition_info": {
                        "g_protein": 40,
                        "calories": 300,
                        "g_carbs": 0,
                        "g_fat": 5,
                    },
                },
            },
        ],
    }
)

USER = {
    "name": "Wes",
    "ntfy_topic": "topic-abc",
    "halls": ["north-dining-hall"],
    "stations": ["Grill"],
}


def _serve(monkeypatch, day: DayMenu | None) -> None:
    monkeypatch.setattr(cli.client, "fetch_day", lambda hall, meal, d: day)


def test_picks_lead_the_message(monkeypatch):
    _serve(monkeypatch, MENU)
    user = parse_user({**USER, "macros": {"protein": {"target": 40}}}, "test")

    lines = cli._build_message(user, "dinner", date(2026, 9, 24))

    assert lines == [
        "PICKS: protein 34-46g",
        "North Dining Hall: 40P 0C 5F · 300 cal",
        "  Grilled Chicken",
        "     40P 0C 5F · 300 cal · allergens unknown",
        "",
        "NORTH DINING HALL",
        "Grill",
        "  Grilled Chicken",
    ]


def test_subscriber_without_macros_gets_the_plain_digest(monkeypatch):
    _serve(monkeypatch, MENU)
    user = parse_user(USER, "test")

    lines = cli._build_message(user, "dinner", date(2026, 9, 24))

    assert lines == ["NORTH DINING HALL", "Grill", "  Grilled Chicken"]


def test_no_published_menu_means_no_message(monkeypatch):
    _serve(monkeypatch, None)
    user = parse_user({**USER, "macros": {"protein": {"target": 40}}}, "test")

    assert cli._build_message(user, "dinner", date(2026, 9, 24)) == []
