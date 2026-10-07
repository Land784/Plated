import json

import httpx
import pytest

from menu import cli, invite
from menu.invite import InviteError, invite_subscriber, new_subscriber_row
from menu.users import parse_user

URL = "https://example.supabase.co"
SECRET = "sb_secret_test"
SITE = "https://plated.example.app"
USER_ID = "8d0f6a5e-4a7a-4b8e-9d55-6a2f1d0c1e11"
TOPIC = "plated-abcdefghjkmnpqrs"


class FakeSupabase:
    """Answers the handful of requests an invite makes, and records them."""

    def __init__(self, *, subscribers=(), stations=("Domer Diner", "La Mesa"), fail=None):
        self.requests: list[httpx.Request] = []
        self.subscribers = list(subscribers)
        self.stations = list(stations)
        self.fail = fail or set()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path, method = request.url.path, request.method
        if (method, path) in self.fail:
            return httpx.Response(422, json={"msg": "nope"})
        if path == "/auth/v1/invite":
            return httpx.Response(200, json={"id": USER_ID, "email": "x@nd.edu"})
        if path == "/rest/v1/stations":
            return httpx.Response(200, json=[{"station": s} for s in self.stations])
        if path == "/rest/v1/subscribers" and method == "GET":
            name = request.url.params["name"].removeprefix("eq.")
            return httpx.Response(200, json=[s for s in self.subscribers if s["name"] == name])
        if path == "/rest/v1/subscribers" and method == "POST":
            # The database fills the topic; the select keeps it out of the reply.
            return httpx.Response(201, json=[{"id": "new-row", "name": "x"}])
        if path == "/rest/v1/subscribers" and method == "PATCH":
            return httpx.Response(200, json=[{"id": "old-row"}])
        raise AssertionError(f"unexpected {method} {path}")

    @property
    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))

    def calls(self) -> list[tuple[str, str]]:
        return [(r.method, r.url.path) for r in self.requests]


def _invite(fake: FakeSupabase, **kwargs):
    defaults = {"email": "new@nd.edu", "name": "aanderson", "site_url": SITE}
    return invite_subscriber(URL, SECRET, **{**defaults, **kwargs}, client=fake.client)


def test_default_row_matches_the_web_apps_first_run_defaults():
    row = new_subscriber_row("aanderson", USER_ID, ["Domer Diner", "La Mesa"])

    assert row["halls"] == ["north-dining-hall", "south-dining-hall"]
    assert row["stations"] == ["Domer Diner", "La Mesa"]
    assert row["favorites"] == []
    assert row["user_id"] == USER_ID
    assert row["macros"] is None
    for day in ("monday", "tuesday", "wednesday", "thursday", "friday"):
        assert row["schedule"][day] == {"lunch": "12:00", "dinner": "17:30"}
    for day in ("saturday", "sunday"):
        assert row["schedule"][day] == {"brunch": "11:00", "dinner": "17:30"}
    # The database picks the topic.
    assert "ntfy_topic" not in row
    # And it is a valid subscriber once it has one.
    parse_user({**row, "ntfy_topic": TOPIC}, "test")


def test_invite_creates_the_auth_user_then_the_row():
    fake = FakeSupabase()

    result = _invite(fake)

    assert fake.calls() == [
        ("GET", "/rest/v1/subscribers"),
        ("GET", "/rest/v1/stations"),
        ("POST", "/auth/v1/invite"),
        ("POST", "/rest/v1/subscribers"),
    ]
    auth = fake.requests[2]
    assert auth.url.params["redirect_to"] == SITE
    assert json.loads(auth.content) == {"email": "new@nd.edu", "data": {"name": "aanderson"}}
    assert auth.headers["apikey"] == SECRET

    stations = fake.requests[1]
    assert stations.url.params["is_food"] == "is.true"

    insert = fake.requests[3]
    body = json.loads(insert.content)
    assert body["user_id"] == USER_ID
    assert body["name"] == "aanderson"
    assert body["stations"] == ["Domer Diner", "La Mesa"]
    # The reply never carries the topic.
    assert insert.url.params["select"] == "id,name"
    assert result.linked is False
    assert result.user_id == USER_ID


def test_link_sets_user_id_on_the_existing_row_only():
    fake = FakeSupabase(subscribers=[{"id": "old-row", "name": "wschmidt", "user_id": None}])

    result = _invite(fake, name="wschmidt", link="wschmidt")

    assert fake.calls() == [
        ("GET", "/rest/v1/subscribers"),
        ("POST", "/auth/v1/invite"),
        ("PATCH", "/rest/v1/subscribers"),
    ]
    patch = fake.requests[2]
    assert json.loads(patch.content) == {"user_id": USER_ID}
    assert patch.url.params["id"] == "eq.old-row"
    # A row that got linked in the meantime is not overwritten.
    assert patch.url.params["user_id"] == "is.null"
    assert result.linked is True


@pytest.mark.parametrize(
    ("subscribers", "kwargs", "match"),
    [
        ([{"id": "a", "name": "aanderson", "user_id": None}], {}, "--link aanderson"),
        ([], {"link": "ghost"}, "no subscriber named 'ghost'"),
        (
            [{"id": "a", "name": "w", "user_id": None}, {"id": "b", "name": "w", "user_id": None}],
            {"link": "w"},
            "2 subscribers are named 'w'",
        ),
        ([{"id": "a", "name": "w", "user_id": USER_ID}], {"link": "w"}, "already linked"),
    ],
)
def test_bad_names_fail_before_anyone_is_invited(subscribers, kwargs, match):
    fake = FakeSupabase(subscribers=subscribers)

    with pytest.raises(InviteError, match=match):
        _invite(fake, **kwargs)

    assert ("POST", "/auth/v1/invite") not in fake.calls()


def test_an_empty_station_catalog_fails_before_anyone_is_invited():
    fake = FakeSupabase(stations=[])

    with pytest.raises(InviteError, match="menu menus store"):
        _invite(fake)

    assert ("POST", "/auth/v1/invite") not in fake.calls()


def test_a_rejected_invite_writes_no_row():
    fake = FakeSupabase(fail={("POST", "/auth/v1/invite")})

    with pytest.raises(InviteError, match="HTTP 422"):
        _invite(fake)

    assert ("POST", "/rest/v1/subscribers") not in fake.calls()


def test_a_failed_row_write_names_the_orphaned_auth_user():
    fake = FakeSupabase(fail={("POST", "/rest/v1/subscribers")})

    with pytest.raises(InviteError, match=USER_ID):
        _invite(fake)


def test_cli_needs_the_site_url(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", URL)
    monkeypatch.setenv("SUPABASE_SECRET_KEY", SECRET)
    monkeypatch.delenv("PLATED_SITE_URL", raising=False)

    with pytest.raises(InviteError, match="PLATED_SITE_URL"):
        cli.main(["subscribers", "invite", "new@nd.edu", "--name", "aanderson"])


def test_cli_invites_and_never_prints_a_topic(monkeypatch, capsys):
    monkeypatch.setenv("SUPABASE_URL", URL)
    monkeypatch.setenv("SUPABASE_SECRET_KEY", SECRET)
    monkeypatch.setenv("PLATED_SITE_URL", f"{SITE}/")
    seen = {}

    def fake_invite(url, key, **kwargs):
        seen.update(kwargs)
        return invite.InviteResult(name="aanderson", user_id=USER_ID, linked=False)

    monkeypatch.setattr(cli.invite, "invite_subscriber", fake_invite)

    assert cli.main(["subscribers", "invite", "new@nd.edu", "--name", "aanderson"]) == 0
    assert seen == {
        "email": "new@nd.edu",
        "name": "aanderson",
        "site_url": SITE,
        "link": None,
    }
    out = capsys.readouterr()
    assert "invited new@nd.edu" in out.out
    assert "plated-" not in out.out + out.err
