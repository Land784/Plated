import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from menu import menus_store
from menu.client import MenuFetchError
from menu.digest import (
    NON_FOOD_STATIONS,
    build_message,
    group_by_station,
    is_food_station,
    normalize_station,
)
from menu.models import DayMenu, WeekMenu
from menu.supabase_users import SupabaseError
from menu.users import parse_user

FIXTURES = Path(__file__).parent / "fixtures"
URL = "https://example.supabase.co"
SECRET = "sb_secret_test"
DAY = date(2026, 9, 24)
NOW = datetime(2026, 9, 24, 10, 0, tzinfo=UTC)


def _day(name: str, d: str = "2026-09-24") -> DayMenu:
    week = WeekMenu.model_validate(json.loads((FIXTURES / name).read_text()))
    return next(day for day in week.days if day.date.isoformat() == d)


REAL_DAYS = [
    ("real_north_dinner_2026-09-24.json", "2026-09-24"),
    ("real_south_dinner_2026-09-24.json", "2026-09-24"),
    ("real_north_lunch_2026-09-21.json", "2026-09-21"),
]


def _rebuild(day: DayMenu) -> DayMenu:
    # Through JSON text, the way the row comes back out of jsonb.
    items = json.loads(json.dumps(menus_store.trim_day(day)))
    return DayMenu.model_validate({"date": day.date.isoformat(), "menu_items": items})


# Fields the trim drops on purpose: nothing outside the model reads them.
UNREAD = {"description", "has_nutrition_info"}


@pytest.mark.parametrize(("fixture", "d"), REAL_DAYS)
def test_trimmed_items_rebuild_the_same_stations(fixture, d):
    day = _day(fixture, d)
    original = group_by_station(day)
    rebuilt = group_by_station(_rebuild(day))

    assert original
    assert [s.name for s in rebuilt] == [s.name for s in original]
    for before, after in zip(original, rebuilt, strict=True):
        assert [i.station_id for i in after.items] == [i.station_id for i in before.items]
        assert [i.food.model_dump(exclude=UNREAD) for i in after.items] == [
            i.food.model_dump(exclude=UNREAD) for i in before.items
        ]


def test_a_push_rendered_from_stored_rows_matches_one_from_nutrislice():
    menus = {
        "north-dining-hall": _day("real_north_dinner_2026-09-24.json"),
        "south-dining-hall": _day("real_south_dinner_2026-09-24.json"),
    }
    stations = sorted({s.name for day in menus.values() for s in group_by_station(day)})
    user = parse_user({"name": "t", "ntfy_topic": "t", "stations": stations}, "test")

    rebuilt = {hall: _rebuild(day) for hall, day in menus.items()}

    assert build_message(user, rebuilt, "dinner") == build_message(user, menus, "dinner")


def test_trimmed_item_has_exactly_the_contract_shape():
    items = menus_store.trim_day(_day("real_north_dinner_2026-09-24.json"))

    header, food = items[0], items[1]
    assert header == {"is_station_header": True, "text": "Comfort Kitchen", "station_id": 85896}
    assert food == {
        "station_id": 85896,
        "food": {
            "name": "Clubhouse Potato Chips",
            "rounded_nutrition_info": {
                "calories": 125.0,
                "g_protein": 1.0,
                "g_fat": 10.0,
                "g_carbs": 10.0,
                "mg_sodium": 549.0,
                "g_fiber": 1.0,
                "g_sugar": 1.0,
            },
            # The upstream "z" for "oz" is kept as reported.
            "serving_size_info": {"serving_size_amount": "2", "serving_size_unit": "z"},
            "icons": {"food_icons": [{"name": "Vegan"}, {"name": "Vegetarian"}]},
        },
    }


def test_missing_values_stay_null_and_bulk_and_duplicate_rows_stay():
    day = DayMenu.model_validate(
        {
            "date": "2026-09-24",
            "menu_items": [
                {"is_station_header": True, "text": "Crust & Co", "station_id": 1},
                {"station_id": 1, "food": {"name": "Mystery", "rounded_nutrition_info": None}},
                {
                    "station_id": 1,
                    "food": {"name": "Cheese Pizza", "rounded_nutrition_info": {"calories": 2473}},
                },
                {"station_id": 1, "food": {"name": "Cheese Pizza"}},
                {"text": "a blank row with no food"},
            ],
        }
    )
    foods = [item["food"] for item in menus_store.trim_day(day) if "food" in item]

    assert [f["name"] for f in foods] == ["Mystery", "Cheese Pizza", "Cheese Pizza"]
    assert foods[0]["rounded_nutrition_info"] is None
    assert foods[0]["serving_size_info"] is None
    assert foods[0]["icons"] == {"food_icons": []}
    assert foods[1]["rounded_nutrition_info"]["calories"] == 2473
    assert foods[1]["rounded_nutrition_info"]["g_protein"] is None


def test_a_stored_row_is_far_smaller_than_the_raw_response():
    raw = json.loads((FIXTURES / "real_south_dinner_2026-09-24.json").read_text())
    day = _day("real_south_dinner_2026-09-24.json")
    trimmed = len(json.dumps(menus_store.trim_day(day)))
    full = len(json.dumps(raw["days"][0]["menu_items"]))
    assert trimmed < full / 5


@pytest.mark.parametrize(
    "name",
    ["Beverages", "Coffee & Tea", "COFFEE AND TEA", "  Salad   Bar ", "The Desserts", "Dessert"],
)
def test_non_food_stations(name):
    assert not is_food_station(name)


@pytest.mark.parametrize(
    "name", ["Domer Diner", "The Global Compass", "Breakfast", "Omelets", "Sunrise Kitchen"]
)
def test_food_stations(name):
    assert is_food_station(name)


def test_non_food_list_is_already_normalized():
    assert all(normalize_station(name) == name for name in NON_FOOD_STATIONS)


def test_station_rows_carry_the_mains_the_push_would_show():
    day = _day("real_south_dinner_2026-09-24.json")
    rows = menus_store.station_rows(DAY, "south-dining-hall", "dinner", day)
    by_station = {row["station"]: row for row in rows}

    assert set(rows[0]) == {"date", "hall", "meal", "station", "normalized", "is_food", "mains"}
    assert rows[0]["date"] == "2026-09-24"
    global_compass = by_station["Global Compass"]
    assert global_compass["normalized"] == "global compass"
    assert global_compass["is_food"] is True
    assert global_compass["mains"][0] == "Beef Pad See Ew"
    # A taco counts as a main by its serving unit.
    assert "Tacos Al Pastor" in by_station["La Mesa"]["mains"]
    # A station with no main falls back to its items by protein, as in the push.
    assert by_station["Pastaria"]["mains"][:3] == [
        "Halal Chicken & Beef Pepperoni",
        "Elbow Macaroni",
        "Penne Pasta",
    ]


def test_station_rows_keep_the_published_spelling():
    rows = menus_store.station_rows(
        DAY, "north-dining-hall", "dinner", _day("real_north_dinner_2026-09-24.json")
    )
    row = next(r for r in rows if r["normalized"] == "global compass")
    assert row["station"] == "The Global Compass"


def test_a_station_repeated_in_one_menu_is_one_row():
    day = DayMenu.model_validate(
        {
            "date": "2026-09-24",
            "menu_items": [
                {"is_station_header": True, "text": "Grill", "station_id": 1},
                {"station_id": 1, "food": {"name": "Fries"}},
                {"is_station_header": True, "text": "Grill", "station_id": 1},
                {
                    "station_id": 1,
                    "food": {"name": "Chicken", "rounded_nutrition_info": {"g_protein": 30}},
                },
            ],
        }
    )
    rows = menus_store.station_rows(DAY, "north-dining-hall", "lunch", day)
    assert [(r["station"], r["mains"]) for r in rows] == [("Grill", ["Chicken"])]


def test_menu_row_is_none_for_an_empty_menu():
    empty = DayMenu.model_validate({"date": "2026-09-20", "menu_items": []})
    assert menus_store.menu_row(DAY, "north-dining-hall", "lunch", empty, NOW) is None


# ---- PostgREST writes ----------------------------------------------------


class FakeSupabase:
    """Records requests; answers every GET with ``existing``."""

    def __init__(self, existing=None, fail_on=None):
        self.requests: list[httpx.Request] = []
        self.existing = existing or []
        self.fail_on = fail_on

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail_on and self.fail_on(request):
            return httpx.Response(500, json={"message": "boom"})
        if request.method == "GET":
            return httpx.Response(200, json=self.existing)
        return httpx.Response(201 if request.method == "POST" else 204)

    @property
    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


def _fetcher(served: dict, failing: set | None = None):
    calls: list[tuple] = []

    def fetch(hall, meal, d):
        calls.append((hall, meal, d))
        if failing and (hall, meal) in failing:
            raise MenuFetchError("Nutrislice down")
        return served.get((hall, meal))

    fetch.calls = calls
    return fetch


SERVED = {
    ("north-dining-hall", "dinner"): _day("real_north_dinner_2026-09-24.json"),
    ("south-dining-hall", "dinner"): _day("real_south_dinner_2026-09-24.json"),
}


def test_store_day_fetches_every_hall_and_meal_once():
    fake = FakeSupabase()
    fetch = _fetcher(SERVED)

    menus_store.store_day(URL, SECRET, DAY, now=NOW, fetch=fetch, client=fake.client)

    assert sorted(fetch.calls) == sorted(
        (hall, meal, DAY)
        for hall in ("north-dining-hall", "south-dining-hall")
        for meal in ("breakfast", "brunch", "lunch", "late-lunch", "dinner")
    )


def test_store_day_upserts_menus_then_replaces_stations_then_prunes():
    fake = FakeSupabase()

    problems = menus_store.store_day(
        URL, SECRET, DAY, now=NOW, fetch=_fetcher(SERVED), client=fake.client
    )

    assert problems == []
    upsert, delete_stations, insert_stations, prune = fake.requests
    for request in fake.requests:
        assert request.headers["apikey"] == SECRET

    assert (upsert.method, upsert.url.path) == ("POST", "/rest/v1/menus")
    assert upsert.url.params["on_conflict"] == "date,hall,meal"
    assert "resolution=merge-duplicates" in upsert.headers["prefer"]
    rows = json.loads(upsert.content)
    # Only menus with food are stored: dinner at each hall.
    assert [(r["date"], r["hall"], r["meal"]) for r in rows] == [
        ("2026-09-24", "north-dining-hall", "dinner"),
        ("2026-09-24", "south-dining-hall", "dinner"),
    ]
    assert rows[0]["fetched_at"] == "2026-09-24T10:00:00+00:00"
    assert rows[0]["items"] == menus_store.trim_day(SERVED[("north-dining-hall", "dinner")])

    assert (delete_stations.method, delete_stations.url.path) == (
        "DELETE",
        "/rest/v1/menu_stations",
    )
    assert delete_stations.url.params["date"] == "eq.2026-09-24"
    assert delete_stations.url.params["or"] == (
        "(and(hall.eq.north-dining-hall,meal.eq.dinner),"
        "and(hall.eq.south-dining-hall,meal.eq.dinner))"
    )

    assert (insert_stations.method, insert_stations.url.path) == (
        "POST",
        "/rest/v1/menu_stations",
    )
    station_rows = json.loads(insert_stations.content)
    assert {r["hall"] for r in station_rows} == {"north-dining-hall", "south-dining-hall"}

    assert (prune.method, prune.url.path) == ("DELETE", "/rest/v1/menus")
    assert dict(prune.url.params) == {"date": "lt.2026-07-26"}


def test_a_failed_fetch_is_reported_and_the_rest_is_stored():
    fake = FakeSupabase()
    fetch = _fetcher(SERVED, failing={("south-dining-hall", "dinner")})

    problems = menus_store.store_day(URL, SECRET, DAY, now=NOW, fetch=fetch, client=fake.client)

    assert problems == ["menus store: south-dining-hall/dinner on 2026-09-24: Nutrislice down"]
    rows = json.loads(fake.requests[0].content)
    assert [r["hall"] for r in rows] == ["north-dining-hall"]


def test_nothing_published_writes_nothing_but_still_prunes():
    fake = FakeSupabase()

    problems = menus_store.store_day(
        URL, SECRET, DAY, now=NOW, fetch=_fetcher({}), client=fake.client
    )

    assert problems == []
    assert [(r.method, r.url.path) for r in fake.requests] == [("DELETE", "/rest/v1/menus")]


def test_a_supabase_failure_is_reported_not_raised():
    fake = FakeSupabase(fail_on=lambda r: r.method == "POST" and r.url.path.endswith("/menus"))

    problems = menus_store.store_day(
        URL, SECRET, DAY, now=NOW, fetch=_fetcher(SERVED), client=fake.client
    )

    assert len(problems) == 1
    assert problems[0].startswith("menus store: saving menus for 2026-09-24 failed: HTTP 500")
    # Stations reference the menus rows, so they are not attempted.
    assert all(not r.url.path.endswith("menu_stations") for r in fake.requests)


@pytest.mark.parametrize(("existing", "expected"), [([{"date": "2026-09-24"}], True), ([], False)])
def test_has_menus_for(existing, expected):
    fake = FakeSupabase(existing=existing)

    assert menus_store.has_menus_for(URL, SECRET, DAY, client=fake.client) is expected
    request = fake.requests[0]
    assert request.url.path == "/rest/v1/menus"
    assert dict(request.url.params) == {"select": "date", "date": "eq.2026-09-24", "limit": "1"}


def test_has_menus_for_raises_on_error():
    fake = FakeSupabase(fail_on=lambda r: True)
    with pytest.raises(SupabaseError):
        menus_store.has_menus_for(URL, SECRET, DAY, client=fake.client)
