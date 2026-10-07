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
    "main_protein_g": 12,
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

    users, problems = load_users_from_supabase(URL, SECRET, client=_client(handler))

    assert users == [parse_user(ROW, "test")]
    assert problems == []
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


def test_a_bad_row_is_reported_and_the_others_still_load():
    rows = [
        {**ROW, "name": "mallory", "halls": []},
        ROW,
        {**ROW, "name": "", "id": "9f2e", "max_items_per_station": "lots"},
        {**ROW, "name": "trent", "schedule": {"funday": {"lunch": "11:00"}}},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=rows)

    users, problems = load_users_from_supabase(URL, SECRET, client=_client(handler))

    assert [u.name for u in users] == ["Wes"]
    assert problems == [
        "mallory: 'halls' must be a non-empty list",
        "9f2e: 'name' is required",
        "trent: unknown weekday 'funday'; expected one of monday, tuesday, wednesday, "
        "thursday, friday, saturday, sunday",
    ]


def test_a_non_number_is_reported_with_the_row_label():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{**ROW, "max_items_per_station": "lots"}])

    users, problems = load_users_from_supabase(URL, SECRET, client=_client(handler))

    assert users == []
    assert len(problems) == 1
    assert problems[0].startswith("Wes: ")


def test_invalid_file_is_rejected_before_any_request():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request should be made for an invalid file")

    with pytest.raises(UserConfigError):
        upsert_subscriber(URL, SECRET, {"name": "Wes"}, source="wes.toml", client=_client(handler))


def test_upsert_writes_every_column_matched_on_topic():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=[{"name": "Wes", "user_id": None}])
        return httpx.Response(201)

    # No [macros] table, plus a key that is not a column.
    data = {"name": "Wes", "ntfy_topic": "topic-abc", "nickname": "W"}
    upsert_subscriber(URL, SECRET, data, source="wes.toml", client=_client(handler))

    check, request = seen
    assert check.url.params["ntfy_topic"] == "eq.topic-abc"
    assert check.url.params["select"] == "name,user_id"
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


def test_parse_user_defaults_main_protein_g_when_the_key_is_missing():
    row = {key: value for key, value in ROW.items() if key != "main_protein_g"}
    assert parse_user(row, "test").main_protein_g == 10


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

    [user], _ = load_users_from_supabase(URL, SECRET, client=_client(handler))

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


def test_favorites_default_to_none_starred():
    assert parse_user(ROW, "test").favorites == []


def test_favorites_round_trip_and_are_written():
    user = parse_user({**ROW, "favorites": ["Domer Diner"]}, "test")
    row = user_to_row(user)
    assert row["favorites"] == ["Domer Diner"]
    assert parse_user(row, "test") == user


def test_favorites_must_be_a_list_of_strings():
    with pytest.raises(UserConfigError, match="favorites"):
        parse_user({**ROW, "favorites": "Domer Diner"}, "test")


def test_columns_the_web_app_adds_do_not_break_loading():
    """A row with every column, user_id and active included, still parses."""
    row = {**ROW, "id": "3f1c", "favorites": [], "user_id": "9a2b", "active": True}
    assert parse_user(row, "test").name == "Wes"


def test_user_id_is_never_selected_or_written():
    assert "user_id" not in supabase_users.SELECT_COLUMNS
    assert "favorites" in supabase_users.COLUMNS


def _push(handler, **kwargs):
    data = {"name": "Wes", "ntfy_topic": "topic-abc"}
    return upsert_subscriber(
        URL, SECRET, data, source="wes.toml", client=_client(handler), **kwargs
    )


def test_push_refuses_to_overwrite_a_linked_account():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[{"name": "Wes", "user_id": "9a2b"}])

    with pytest.raises(SupabaseError, match="web account") as info:
        _push(handler)

    assert "--force" in str(info.value)
    assert "topic-abc" not in str(info.value)
    assert [r.method for r in seen] == ["GET"]


def test_force_pushes_over_a_linked_account_without_checking():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201)

    _push(handler, force=True)

    assert [r.method for r in seen] == ["POST"]


def test_cli_push_passes_force(monkeypatch, tmp_path):
    from menu import cli

    path = tmp_path / "wes.toml"
    path.write_text('name = "Wes"\nntfy_topic = "topic-abc"\n')
    monkeypatch.setattr(cli.supabase_users, "credentials_from_env", lambda: (URL, SECRET))
    seen = {}

    def fake_upsert(url, key, data, *, source, force):
        seen["force"] = force
        return parse_user(data, source)

    monkeypatch.setattr(cli.supabase_users, "upsert_subscriber", fake_upsert)

    assert cli.main(["subscribers", "push", str(path)]) == 0
    assert seen == {"force": False}
    assert cli.main(["subscribers", "push", "--force", str(path)]) == 0
    assert seen == {"force": True}
