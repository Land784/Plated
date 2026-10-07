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

    def calls(self) -> list[tuple[str, str]]:
        return [(r.method, r.url.path.removeprefix("/rest/v1/")) for r in self.requests]


def _week(name: str) -> WeekMenu:
    return WeekMenu.model_validate(json.loads((FIXTURES / name).read_text()))


def _fetcher(served: dict, failing: set | None = None):
    calls: list[tuple] = []

    def fetch(hall, meal, d):
        calls.append((hall, meal, d))
        if failing and (hall, meal) in failing:
            raise MenuFetchError("Nutrislice down")
        return served.get((hall, meal), WeekMenu())

    fetch.calls = calls
    return fetch


SERVED = {
    # An empty Sunday and a Monday with food.
    ("north-dining-hall", "lunch"): _week("real_north_lunch_2026-09-21.json"),
    ("north-dining-hall", "dinner"): _week("real_north_dinner_2026-09-24.json"),
    ("south-dining-hall", "dinner"): _week("real_south_dinner_2026-09-24.json"),
}

ALL_MENUS = sorted(
    (hall, meal, DAY)
    for hall in ("north-dining-hall", "south-dining-hall")
    for meal in ("breakfast", "brunch", "lunch", "late-lunch", "dinner")
)


def _store(fake: FakeSupabase, fetch=None) -> list[str]:
    return menus_store.store_week(
        URL, SECRET, DAY, now=NOW, fetch=fetch or _fetcher(SERVED), client=fake.client
    )


def test_store_week_makes_one_week_request_per_hall_and_meal():
    fake = FakeSupabase()
    fetch = _fetcher(SERVED)

    _store(fake, fetch)

    assert sorted(fetch.calls) == ALL_MENUS


def test_store_week_saves_every_day_with_food_then_prunes_then_records():
    fake = FakeSupabase()

    problems = _store(fake)

    assert problems == []
    assert fake.calls() == [
        ("POST", "menus"),  # north lunch
        ("DELETE", "menu_stations"),
        ("POST", "menu_stations"),
        ("POST", "menus"),  # north dinner
        ("DELETE", "menu_stations"),
        ("POST", "menu_stations"),
        ("POST", "menus"),  # south dinner
        ("DELETE", "menu_stations"),
        ("POST", "menu_stations"),
        ("DELETE", "menus"),
        ("DELETE", "menu_store_runs"),
        ("POST", "menu_store_runs"),
    ]
    for request in fake.requests:
        assert request.headers["apikey"] == SECRET

    lunch = fake.requests[0]
    assert lunch.url.params["on_conflict"] == "date,hall,meal"
    assert "resolution=merge-duplicates" in lunch.headers["prefer"]
    rows = json.loads(lunch.content)
    # The week's empty Sunday is skipped; its Monday is stored, not only DAY.
    assert [(r["date"], r["hall"], r["meal"]) for r in rows] == [
        ("2026-09-21", "north-dining-hall", "lunch")
    ]
    assert rows[0]["fetched_at"] == "2026-09-24T10:00:00+00:00"
    assert rows[0]["items"] == menus_store.trim_day(SERVED[("north-dining-hall", "lunch")].days[1])

    clear = fake.requests[1]
    assert dict(clear.url.params) == {
        "hall": "eq.north-dining-hall",
        "meal": "eq.lunch",
        "date": "in.(2026-09-21)",
    }
    station_rows = json.loads(fake.requests[2].content)
    assert {(r["date"], r["hall"], r["meal"]) for r in station_rows} == {
        ("2026-09-21", "north-dining-hall", "lunch")
    }

    prune_menus, prune_runs, record = fake.requests[-3:]
    assert dict(prune_menus.url.params) == {"date": "lt.2026-07-26"}
    assert dict(prune_runs.url.params) == {"local_date": "lt.2026-07-26"}
    assert json.loads(record.content) == {
        "local_date": "2026-09-24",
        "stored_at": "2026-09-24T10:00:00+00:00",
    }
    assert record.url.params["on_conflict"] == "local_date"


def test_a_failed_fetch_is_reported_the_rest_stored_and_no_run_recorded():
    fake = FakeSupabase()
    fetch = _fetcher(SERVED, failing={("south-dining-hall", "dinner")})

    problems = _store(fake, fetch)

    assert problems == [
        "menus store: south-dining-hall/dinner for the week of 2026-09-24: Nutrislice down"
    ]
    saved = [
        json.loads(r.content)[0]["hall"]
        for r in fake.requests
        if r.url.path.endswith("menus") and r.method == "POST"
    ]
    assert saved == ["north-dining-hall", "north-dining-hall"]
    # Partial, so the next run retries.
    assert ("POST", "menu_store_runs") not in fake.calls()


def test_nothing_published_writes_nothing_but_still_prunes_and_records():
    fake = FakeSupabase()

    problems = _store(fake, _fetcher({}))

    assert problems == []
    assert fake.calls() == [
        ("DELETE", "menus"),
        ("DELETE", "menu_store_runs"),
        ("POST", "menu_store_runs"),
    ]


def test_a_supabase_failure_is_reported_not_raised_and_other_menus_go_on():
    def fail(request: httpx.Request) -> bool:
        return (
            request.method == "POST"
            and request.url.path.endswith("/menus")
            and json.loads(request.content)[0]["hall"] == "south-dining-hall"
        )

    fake = FakeSupabase(fail_on=fail)

    problems = _store(fake)

    assert len(problems) == 1
    assert problems[0].startswith(
        "menus store: south-dining-hall/dinner for the week of 2026-09-24: "
        "saving south-dining-hall/dinner menus failed: HTTP 500"
    )
    # North was stored in full; South's stations hang off its menus rows,
    # so they are not attempted.
    assert fake.calls().count(("POST", "menu_stations")) == 2
    assert ("POST", "menu_store_runs") not in fake.calls()


@pytest.mark.parametrize(
    ("existing", "expected"), [([{"local_date": "2026-09-24"}], True), ([], False)]
)
def test_has_store_run(existing, expected):
    fake = FakeSupabase(existing=existing)

    assert menus_store.has_store_run(URL, SECRET, DAY, client=fake.client) is expected
    request = fake.requests[0]
    assert request.url.path == "/rest/v1/menu_store_runs"
    assert dict(request.url.params) == {
        "select": "local_date",
        "local_date": "eq.2026-09-24",
        "limit": "1",
    }


def test_has_store_run_raises_on_error():
    fake = FakeSupabase(fail_on=lambda r: True)
    with pytest.raises(SupabaseError):
        menus_store.has_store_run(URL, SECRET, DAY, client=fake.client)
