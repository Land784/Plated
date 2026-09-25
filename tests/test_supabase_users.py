import json
from datetime import date

import httpx
import pytest

from menu import supabase_users
from menu.supabase_users import (
    SupabaseError,
    claim_send,
    credentials_from_env,
    load_users_from_supabase,
    release_send,
    upsert_subscriber,
    user_to_row,
)
from menu.users import UserConfigError, parse_user

URL = "https://example.supabase.co"
SECRET = "sb_secret_test"
LEGACY = "eyJhbGciOiJIUzI1NiJ9.test"

ROW = {
    "name": "Wes",
    "ntfy_topic": "topic-abc",
    "timezone": "America/New_York",
    "halls": ["north-dining-hall"],
    "stations": ["Domer Diner"],
    "max_items_per_station": 4,
    "schedule": {"monday": {"lunch": "11:15"}},
    "macros": {"protein": {"target": 70}, "brunch": {"protein": {"target": 50}}},
    "picks": {"max_servings_per_item": 3},
}


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_rows_load_through_the_same_validation_as_files():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[ROW])

    users = load_users_from_supabase(URL, SECRET, client=_client(handler))

    assert users == [parse_user(ROW, "test")]
    request = seen[0]
    assert request.url.path == "/rest/v1/subscribers"
    assert request.url.params["active"] == "is.true"
    assert request.url.params["select"] == ",".join(supabase_users.SELECT_COLUMNS)


def test_secret_key_goes_only_in_the_apikey_header():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["apikey"] == SECRET
        assert "authorization" not in request.headers
        return httpx.Response(200, json=[])

    load_users_from_supabase(URL, SECRET, client=_client(handler))


def test_legacy_jwt_key_is_also_sent_as_bearer():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["apikey"] == LEGACY
        assert request.headers["authorization"] == f"Bearer {LEGACY}"
        return httpx.Response(200, json=[])

    load_users_from_supabase(URL, LEGACY, client=_client(handler))


def test_http_error_raises_instead_of_returning_no_subscribers():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Invalid API key"})

    with pytest.raises(SupabaseError, match="HTTP 401"):
        load_users_from_supabase(URL, SECRET, client=_client(handler))


def test_one_bad_row_fails_the_whole_load():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[ROW, {**ROW, "ntfy_topic": ""}])

    with pytest.raises(UserConfigError, match="ntfy_topic"):
        load_users_from_supabase(URL, SECRET, client=_client(handler))


def test_invalid_file_is_rejected_before_any_request():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request should be made for an invalid file")

    with pytest.raises(UserConfigError):
        upsert_subscriber(URL, SECRET, {"name": "Wes"}, source="wes.toml", client=_client(handler))


def test_upsert_writes_every_column_matched_on_topic():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201)

    # No [macros] table, plus a key that is not a column.
    data = {"name": "Wes", "ntfy_topic": "topic-abc", "nickname": "W"}
    upsert_subscriber(URL, SECRET, data, source="wes.toml", client=_client(handler))

    request = seen[0]
    assert request.method == "POST"
    assert request.url.params["on_conflict"] == "ntfy_topic"
    assert "resolution=merge-duplicates" in request.headers["prefer"]
    body = json.loads(request.content)
    assert set(body) == set(supabase_users.COLUMNS)
    # Written explicitly so re-pushing a file without [macros] clears it.
    assert body["macros"] is None
    # Picks defaults are written out in full.
    assert body["picks"]["max_servings_per_item"] == 2
    assert body["halls"] == ["north-dining-hall", "south-dining-hall"]


def test_row_round_trips_through_parse_user():
    user = parse_user(
        {
            **ROW,
            "macros": {
                "protein": {"target": 70, "tolerance": 5},
                "fat": {"max": 30},
                "fiber": {"min": 8},
                "brunch": {"protein": {"target": 50}},
            },
            "picks": {
                "max_item_calories": 900,
                "max_total_servings": 5,
                "exclude_allergens": ["Peanuts"],
                "unknown_allergens": "exclude",
            },
        },
        "test",
    )
    assert parse_user(user_to_row(user), "test") == user


def test_missing_credentials_name_every_missing_variable(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)

    with pytest.raises(SupabaseError, match="SUPABASE_URL, SUPABASE_SECRET_KEY"):
        credentials_from_env()


def test_credentials_strip_a_trailing_slash(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", f"{URL}/")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", SECRET)

    assert credentials_from_env() == (URL, SECRET)


def test_row_id_is_kept_but_never_written():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{**ROW, "id": "3f1c"}])

    [user] = load_users_from_supabase(URL, SECRET, client=_client(handler))

    assert user.id == "3f1c"
    assert "id" not in user_to_row(user)


@pytest.mark.parametrize(("returned", "claimed"), [([{"meal": "lunch"}], True), ([], False)])
def test_claim_is_true_only_for_the_first_run(returned, claimed):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json=returned)

    result = claim_send(URL, SECRET, "3f1c", "lunch", date(2026, 9, 25), client=_client(handler))

    assert result is claimed
    request = seen[0]
    assert request.url.path == "/rest/v1/sent_meals"
    assert "resolution=ignore-duplicates" in request.headers["prefer"]
    assert json.loads(request.content) == {
        "subscriber_id": "3f1c",
        "meal": "lunch",
        "local_date": "2026-09-25",
    }


def test_release_deletes_exactly_that_claim():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(204)

    release_send(URL, SECRET, "3f1c", "lunch", date(2026, 9, 25), client=_client(handler))

    request = seen[0]
    assert request.method == "DELETE"
    assert dict(request.url.params) == {
        "subscriber_id": "eq.3f1c",
        "meal": "eq.lunch",
        "local_date": "eq.2026-09-25",
    }
