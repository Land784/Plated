import importlib.util
import json
import threading
from datetime import date
from http.server import ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from menu import menus_store, preview
from menu.digest import build_message, full_menu_link
from menu.models import DayMenu, WeekMenu
from menu.notifier import DISCLAIMER, compose_body
from menu.users import parse_user

FIXTURES = Path(__file__).parent / "fixtures"
URL = "https://example.supabase.co"
PUBLISHABLE = "sb_publishable_test"
ENV = {"SUPABASE_URL": URL, "SUPABASE_PUBLISHABLE_KEY": PUBLISHABLE}
NORTH, SOUTH = "north-dining-hall", "south-dining-hall"
STATIONS = ["Domer Diner", "Mezze", "Global Compass", "Pastaria"]


def _day(name: str) -> DayMenu:
    return WeekMenu.model_validate(json.loads((FIXTURES / name).read_text())).days[0]


DAYS = {
    NORTH: _day("real_north_dinner_2026-09-24.json"),
    SOUTH: _day("real_south_dinner_2026-09-24.json"),
}
# What the menus table holds for 2026-09-24 dinner.
ROWS = [{"hall": hall, "items": menus_store.trim_day(day)} for hall, day in DAYS.items()]


def _request(**overrides) -> dict:
    return {
        "halls": [SOUTH, NORTH],
        "stations": STATIONS,
        "meal": "dinner",
        "date": "2026-09-24",
        **overrides,
    }


def test_preview_is_the_push_dispatch_would_send():
    req = preview.parse_request(_request())

    result = preview.render_preview(req, {row["hall"]: row["items"] for row in ROWS})

    user = parse_user(
        {"name": "x", "ntfy_topic": "x", "halls": [SOUTH, NORTH], "stations": STATIONS}, "t"
    )
    expected = compose_body("\n".join(build_message(user, DAYS, "dinner")), full_menu_link(user))
    assert result == {
        "title": "Dinner · Thu Sep 24",
        "tags": ["plate_with_cutlery"],
        "body": expected,
        "bytes": len(expected.encode("utf-8")),
        "sent": True,
    }
    # South is preferred, so it leads and its page is the link.
    assert result["body"].startswith("South: ")
    assert "Full menu: https://nd.nutrislice.com/menu/south-dining-hall/" in result["body"]
    assert result["body"].endswith(DISCLAIMER)


def test_no_rows_means_no_menu_published():
    req = preview.parse_request(_request())
    assert preview.render_preview(req, {}) == {"sent": False, "reason": "no menu published"}


def test_no_stations_chosen():
    req = preview.parse_request(_request(stations=[]))
    result = preview.render_preview(req, {row["hall"]: row["items"] for row in ROWS})
    assert result == {"sent": False, "reason": "no stations chosen"}


def test_menu_published_but_none_of_the_stations_serve_it():
    req = preview.parse_request(_request(stations=["Sunrise Kitchen"]))
    result = preview.render_preview(req, {row["hall"]: row["items"] for row in ROWS})
    assert result == {"sent": False, "reason": "none of your stations serve this meal"}


def test_only_the_requested_halls_are_rendered():
    req = preview.parse_request(_request(halls=[NORTH]))
    result = preview.render_preview(req, {row["hall"]: row["items"] for row in ROWS})
    assert "SOUTH" not in result["body"]
    assert "NORTH FULL MENU" in result["body"]


@pytest.mark.parametrize(
    "bad",
    [
        [],
        "not an object",
        _request(halls=[]),
        _request(halls=["east-dining-hall"]),
        _request(halls=[NORTH, NORTH]),
        _request(halls=NORTH),
        _request(stations="Domer Diner"),
        _request(stations=[1]),
        _request(stations=["x" * 101]),
        _request(stations=["s"] * 101),
        _request(meal="second-breakfast"),
        _request(date="tomorrow"),
        _request(date=20260924),
        {k: v for k, v in _request().items() if k != "meal"},
    ],
)
def test_bad_input_is_rejected(bad):
    with pytest.raises(preview.PreviewInputError):
        preview.parse_request(bad)


def test_fetch_reads_one_query_with_the_publishable_key():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=ROWS)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    req = preview.parse_request(_request())

    rows = preview.fetch_menu_items(URL, PUBLISHABLE, req, client=client)

    assert set(rows) == {NORTH, SOUTH}
    [request] = seen
    assert request.url.path == "/rest/v1/menus"
    assert dict(request.url.params) == {
        "select": "hall,items",
        "date": "eq.2026-09-24",
        "meal": "eq.dinner",
        "hall": f"in.({SOUTH},{NORTH})",
    }
    assert request.headers["apikey"] == PUBLISHABLE
    assert "authorization" not in request.headers


def _supabase(rows=ROWS, status=200) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(status, json=rows)))


def test_handle_request_end_to_end():
    status, payload = preview.handle_request(
        json.dumps(_request()).encode(),
        "1.2.3.4",
        limiter=preview.RateLimiter(),
        env=ENV,
        client=_supabase(),
    )
    assert status == 200
    assert payload["sent"] is True
    assert payload["title"] == "Dinner · Thu Sep 24"


@pytest.mark.parametrize("body", [b"{not json", b"[]", json.dumps(_request(meal="x")).encode()])
def test_handle_request_answers_400_to_bad_input(body):
    status, payload = preview.handle_request(
        body, "1.2.3.4", limiter=preview.RateLimiter(), env=ENV, client=_supabase()
    )
    assert status == 400
    assert "error" in payload


def test_handle_request_answers_413_to_a_huge_body():
    status, _ = preview.handle_request(
        b" " * (preview.MAX_BODY_BYTES + 1),
        "1.2.3.4",
        limiter=preview.RateLimiter(),
        env=ENV,
        client=_supabase(),
    )
    assert status == 413


def test_handle_request_answers_502_when_supabase_fails():
    status, payload = preview.handle_request(
        json.dumps(_request()).encode(),
        "1.2.3.4",
        limiter=preview.RateLimiter(),
        env=ENV,
        client=_supabase(status=500),
    )
    assert status == 502
    assert payload == {"error": "could not load menus"}


def test_handle_request_answers_500_when_unconfigured():
    status, payload = preview.handle_request(
        json.dumps(_request()).encode(), "1.2.3.4", limiter=preview.RateLimiter(), env={}
    )
    assert status == 500
    assert payload == {"error": "preview is not configured"}


def test_rate_limit_is_30_a_minute_per_ip():
    now = [0.0]
    limiter = preview.RateLimiter(clock=lambda: now[0])

    assert all(limiter.allow("1.2.3.4") for _ in range(30))
    assert not limiter.allow("1.2.3.4")
    assert limiter.allow("5.6.7.8")
    now[0] = 60.1
    assert limiter.allow("1.2.3.4")


def test_handle_request_answers_429_over_the_limit():
    limiter = preview.RateLimiter(limit=1)
    body = json.dumps(_request()).encode()
    assert (
        preview.handle_request(body, "ip", limiter=limiter, env=ENV, client=_supabase())[0] == 200
    )
    status, payload = preview.handle_request(
        body, "ip", limiter=limiter, env=ENV, client=_supabase()
    )
    assert status == 429
    assert "error" in payload


@pytest.mark.parametrize(
    ("forwarded", "real", "expected"),
    [
        ("9.9.9.9, 10.0.0.1", None, "9.9.9.9"),
        (None, "8.8.8.8", "8.8.8.8"),
        (None, None, "127.0.0.1"),
    ],
)
def test_client_ip(forwarded, real, expected):
    assert preview.client_ip(forwarded, real, ("127.0.0.1", 5000)) == expected


# ---- the Vercel adapter -----------------------------------------------------


def _load_vercel_handler():
    path = Path(__file__).parent.parent / "web" / "api" / "preview.py"
    spec = importlib.util.spec_from_file_location("vercel_preview", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_vercel_handler_adapts_http_to_handle_request(monkeypatch):
    module = _load_vercel_handler()
    seen = {}

    def fake_handle(body, ip, *, limiter, env):
        seen.update(body=body, ip=ip, limiter=limiter)
        return 200, {"sent": False, "reason": "no menu published"}

    monkeypatch.setattr(module, "handle_request", fake_handle)
    server = ThreadingHTTPServer(("127.0.0.1", 0), module.handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}/api/preview"
        # Loopback only; trust_env=False so no proxy setting can reroute it.
        with httpx.Client(trust_env=False) as local:
            response = local.post(base, json={"a": 1}, headers={"x-forwarded-for": "7.7.7.7"})
            wrong_method = local.get(base)
    finally:
        server.shutdown()
        server.server_close()

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json; charset=utf-8"
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"sent": False, "reason": "no menu published"}
    assert json.loads(seen["body"]) == {"a": 1}
    assert seen["ip"] == "7.7.7.7"
    assert seen["limiter"] is module.LIMITER
    assert wrong_method.status_code == 405


def test_preview_date_defaults_nothing():
    """The web app always sends a date; the function never guesses one."""
    req = preview.parse_request(_request())
    assert req.date == date(2026, 9, 24)
