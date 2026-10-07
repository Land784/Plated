import json
from datetime import date
from pathlib import Path

import httpx

from menu import client


def _load_fixture(name: str) -> dict:
    path = Path(__file__).parent / "fixtures" / name
    return json.loads(path.read_text())


def test_fetch_week_parses_fixture(tmp_path):
    fixture = _load_fixture("sample_week.json")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=fixture)

    test_client = httpx.Client(transport=httpx.MockTransport(handler))

    week = client.fetch_week(
        "north-dining-hall",
        "lunch",
        date(2024, 1, 8),
        cache_dir=tmp_path,
        use_cache=False,
        client=test_client,
    )

    assert len(week.days) == 2
    day = week.days[0]
    assert day.date == date(2024, 1, 8)
    named_items = [i for i in day.menu_items if i.food]
    assert len(named_items) == 2
    assert named_items[0].food.nutrition.protein_g == 35


def test_fetch_day_finds_matching_date(tmp_path):
    fixture = _load_fixture("sample_week.json")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=fixture)

    test_client = httpx.Client(transport=httpx.MockTransport(handler))

    day = client.fetch_day(
        "north-dining-hall",
        "lunch",
        date(2024, 1, 9),
        cache_dir=tmp_path,
        use_cache=False,
        client=test_client,
    )

    assert day is not None
    assert day.menu_items == []


def test_fetch_week_requests_the_verified_api_host(tmp_path):
    """Regression test for the host bug: the real API is on
    nd.api.nutrislice.com, not nd.nutrislice.com (see menu/client.py's
    module docstring). If BASE_URL regresses back to the wrong host,
    this should catch it.
    """
    fixture = _load_fixture("sample_week.json")
    seen_urls = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        return httpx.Response(200, json=fixture)

    test_client = httpx.Client(transport=httpx.MockTransport(handler))

    client.fetch_week(
        "north-dining-hall",
        "lunch",
        date(2024, 1, 8),
        cache_dir=tmp_path,
        use_cache=False,
        client=test_client,
    )

    assert len(seen_urls) == 1
    # Requested for Monday 2024-01-08; Nutrislice weeks start on Sunday.
    assert seen_urls[0] == (
        "https://nd.api.nutrislice.com/menu/api/weeks/school/"
        "north-dining-hall/menu-type/lunch/2024/01/07/"
    )


def test_fetch_week_uses_cache(tmp_path):
    fixture = _load_fixture("sample_week.json")
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, json=fixture)

    test_client = httpx.Client(transport=httpx.MockTransport(handler))
    d = date(2024, 1, 8)

    client.fetch_week("north-dining-hall", "lunch", d, cache_dir=tmp_path, client=test_client)
    client.fetch_week("north-dining-hall", "lunch", d, cache_dir=tmp_path, client=test_client)

    assert calls["count"] == 1


def test_week_start_is_the_sunday_on_or_before():
    assert client.week_start(date(2026, 10, 4)) == date(2026, 10, 4)  # Sunday
    assert client.week_start(date(2026, 10, 7)) == date(2026, 10, 4)  # Wednesday
    assert client.week_start(date(2026, 10, 10)) == date(2026, 10, 4)  # Saturday
    assert client.week_start(date(2026, 10, 11)) == date(2026, 10, 11)


def test_two_dates_in_one_week_share_one_request(tmp_path):
    """The cache is keyed by the week, so a second day of the same week is free."""
    fixture = _load_fixture("sample_week.json")
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, json=fixture)

    test_client = httpx.Client(transport=httpx.MockTransport(handler))
    for d in (date(2024, 1, 8), date(2024, 1, 9), date(2024, 1, 13)):
        client.fetch_week("north-dining-hall", "lunch", d, cache_dir=tmp_path, client=test_client)

    assert calls["count"] == 1
    assert [p.name for p in tmp_path.iterdir()] == ["north-dining-hall__lunch__2024-01-07.json"]


def test_the_next_week_is_a_new_request(tmp_path):
    fixture = _load_fixture("sample_week.json")
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, json=fixture)

    test_client = httpx.Client(transport=httpx.MockTransport(handler))
    for d in (date(2024, 1, 13), date(2024, 1, 14)):
        client.fetch_week("north-dining-hall", "lunch", d, cache_dir=tmp_path, client=test_client)

    assert calls["count"] == 2
