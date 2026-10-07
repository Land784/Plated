"""Subscribers stored in Supabase, as an alternative to ``users/*.toml``.

Rows in ``public.subscribers`` (supabase/migrations/) use the same keys
as a subscriber TOML file, so each row goes through
:func:`menu.users.parse_user` exactly like a file does. There is one
validation path whichever source is used.

Access is Supabase's PostgREST endpoint over plain httpx, not the
``supabase`` client library: two queries don't justify a dependency
tree. The table has row level security on; its only policies let a
signed-in web user read and edit their own row, so only the secret key
can read every row. That key and the URL come from the environment
(``SUPABASE_URL``, ``SUPABASE_SECRET_KEY``) and never from a file in
this repo.
"""

from __future__ import annotations

import os
from datetime import date

import httpx

from menu.macros import Goal
from menu.users import MacrosConfig, UserConfig, UserConfigError, parse_user

URL_ENV = "SUPABASE_URL"
KEY_ENV = "SUPABASE_SECRET_KEY"
TABLE = "subscribers"

# The subscriber-file keys. Also the only columns ever selected or
# written, so an unrelated key in a TOML file can't reach the database.
COLUMNS = (
    "name",
    "ntfy_topic",
    "timezone",
    "halls",
    "stations",
    "favorites",
    "max_items_per_station",
    "main_protein_g",
    "schedule",
    "macros",
    "picks",
)

# Read alongside COLUMNS but never written: the database assigns it.
SELECT_COLUMNS = ("id", *COLUMNS)

# One row per (subscriber, meal, date) already sent; see menu/schedule.py.
SENT_TABLE = "sent_meals"

TIMEOUT = 15.0


class SupabaseError(RuntimeError):
    """Raised when Supabase is misconfigured or a request fails."""


def credentials_from_env() -> tuple[str, str]:
    url = os.environ.get(URL_ENV, "").strip().rstrip("/")
    key = os.environ.get(KEY_ENV, "").strip()
    missing = [name for name, value in ((URL_ENV, url), (KEY_ENV, key)) if not value]
    if missing:
        raise SupabaseError(f"missing environment variable(s): {', '.join(missing)}")
    return url, key


def api_headers(key: str) -> dict[str, str]:
    headers = {"apikey": key}
    # Legacy service_role keys are JWTs and also go in Authorization.
    # The newer sb_secret_ and sb_publishable_ keys need only the apikey
    # header (the gateway also accepts an sb_secret_ key as a Bearer,
    # checked 2026-10-07), so they are sent there alone.
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    return headers


def raise_for_status(response: httpx.Response, action: str) -> None:
    if response.is_success:
        return
    # PostgREST error bodies describe the query, never the key, so they
    # are safe to surface in a failed-run log.
    raise SupabaseError(f"{action} failed: HTTP {response.status_code}: {response.text[:300]}")


def fetch_subscriber_rows(url: str, key: str, *, client: httpx.Client | None = None) -> list[dict]:
    """Active subscriber rows, oldest first."""
    http = client or httpx.Client(timeout=TIMEOUT)
    try:
        response = http.get(
            f"{url}/rest/v1/{TABLE}",
            params={
                "select": ",".join(SELECT_COLUMNS),
                "active": "is.true",
                "order": "created_at",
            },
            headers=api_headers(key),
        )
    finally:
        if client is None:
            http.close()
    raise_for_status(response, "loading subscribers")
    rows = response.json()
    if not isinstance(rows, list):
        raise SupabaseError(f"loading subscribers: expected a list, got {type(rows).__name__}")
    return rows


def _row_label(row: object) -> str:
    if isinstance(row, dict):
        for key in ("name", "id"):
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return "?"


def load_users_from_supabase(
    url: str, key: str, *, client: httpx.Client | None = None
) -> tuple[list[UserConfig], list[str]]:
    """Load and validate every active subscriber, each row on its own.

    Returns the valid subscribers and one problem per invalid row
    ("<name or id>: <error>"). A row that a signed-in user saved in a bad
    shape must not stop everyone else's notifications, but it must not
    pass silently either: callers report the problems and fail the run.
    """
    users: list[UserConfig] = []
    problems: list[str] = []
    for row in fetch_subscriber_rows(url, key, client=client):
        label = _row_label(row)
        try:
            if not isinstance(row, dict):
                raise UserConfigError(f"{label}: expected an object")
            users.append(parse_user(row, source=label))
        except UserConfigError as exc:
            problems.append(str(exc))  # already starts with the label
        except (ValueError, TypeError) as exc:  # e.g. int() of a non-number
            problems.append(f"{label}: {exc}")
    return users, problems


def _goal_to_json(goal: Goal) -> dict:
    return {
        key: value
        for key, value in (
            ("target", goal.target),
            ("min", goal.min),
            ("max", goal.max),
            ("tolerance", goal.tolerance),
        )
        if value is not None
    }


def _macros_to_json(macros: MacrosConfig | None) -> dict | None:
    if macros is None:
        return None
    data: dict = {nutrient: _goal_to_json(goal) for nutrient, goal in macros.goals.items()}
    for meal, goals in macros.meals.items():
        data[meal] = {nutrient: _goal_to_json(goal) for nutrient, goal in goals.items()}
    return data


def user_to_row(user: UserConfig) -> dict:
    """Serialize a validated config into a ``subscribers`` row."""
    picks = user.picks
    return {
        "name": user.name,
        "ntfy_topic": user.ntfy_topic,
        "timezone": user.timezone,
        "halls": user.halls,
        "stations": user.stations,
        "favorites": user.favorites,
        "max_items_per_station": user.max_items_per_station,
        "main_protein_g": user.main_protein_g,
        "schedule": {
            day: {meal: f"{at:%H:%M}" for meal, at in meals.items()}
            for day, meals in user.schedule.items()
        },
        "macros": _macros_to_json(user.macros),
        "picks": {
            "min_item_protein_g": picks.min_item_protein_g,
            "max_item_calories": picks.max_item_calories,
            "max_servings_per_item": picks.max_servings_per_item,
            "max_total_servings": picks.max_total_servings,
            "exclude_allergens": picks.exclude_allergens,
            "unknown_allergens": picks.unknown_allergens.value,
        },
    }


def upsert_subscriber(
    url: str,
    key: str,
    data: dict,
    *,
    source: str,
    force: bool = False,
    client: httpx.Client | None = None,
) -> UserConfig:
    """Validate ``data`` like a subscriber file, then insert or update it.

    Rows are matched on ``ntfy_topic``, so re-pushing an edited file
    updates that person rather than duplicating them. Every column is
    written from the validated config, defaults included, so a key
    deleted from the file is cleared in the row rather than left stale.

    A row linked to a web account (user_id set) is edited in the app, so
    it is refused unless ``force``: a push would silently undo the
    person's own changes.
    """
    user = parse_user(data, source=source)
    row = user_to_row(user)
    http = client or httpx.Client(timeout=TIMEOUT)
    try:
        if not force:
            existing = http.get(
                f"{url}/rest/v1/{TABLE}",
                params={"select": "name,user_id", "ntfy_topic": f"eq.{user.ntfy_topic}"},
                headers=api_headers(key),
            )
            raise_for_status(existing, f"checking {source}")
            linked = [r for r in existing.json() if r.get("user_id")]
            if linked:
                # The message names the row, never the topic.
                raise SupabaseError(
                    f"{source}: subscriber {linked[0].get('name')!r} has a web account and "
                    "edits their settings in the app; pushing would overwrite them. "
                    "Use --force to push anyway."
                )
        response = http.post(
            f"{url}/rest/v1/{TABLE}",
            params={"on_conflict": "ntfy_topic"},
            json=row,
            headers={
                **api_headers(key),
                "Prefer": "resolution=merge-duplicates,return=minimal",
            },
        )
    finally:
        if client is None:
            http.close()
    raise_for_status(response, f"saving {source}")
    return user


def _sent_key(subscriber_id: str, meal: str, local_date: date) -> dict[str, str]:
    return {"subscriber_id": subscriber_id, "meal": meal, "local_date": local_date.isoformat()}


def claim_send(
    url: str,
    key: str,
    subscriber_id: str,
    meal: str,
    local_date: date,
    *,
    client: httpx.Client | None = None,
) -> bool:
    """Record that this meal is being sent. False if a run already did.

    The row's primary key makes this atomic: a duplicate insert is
    ignored and returns no rows, so two runs can never both claim it.
    """
    http = client or httpx.Client(timeout=TIMEOUT)
    try:
        response = http.post(
            f"{url}/rest/v1/{SENT_TABLE}",
            json=_sent_key(subscriber_id, meal, local_date),
            headers={
                **api_headers(key),
                "Prefer": "resolution=ignore-duplicates,return=representation",
            },
        )
    finally:
        if client is None:
            http.close()
    raise_for_status(response, f"claiming {meal} on {local_date}")
    return bool(response.json())


def release_send(
    url: str,
    key: str,
    subscriber_id: str,
    meal: str,
    local_date: date,
    *,
    client: httpx.Client | None = None,
) -> None:
    """Undo a claim after a failed send, so a later run retries it."""
    params = {k: f"eq.{v}" for k, v in _sent_key(subscriber_id, meal, local_date).items()}
    http = client or httpx.Client(timeout=TIMEOUT)
    try:
        response = http.delete(
            f"{url}/rest/v1/{SENT_TABLE}", params=params, headers=api_headers(key)
        )
    finally:
        if client is None:
            http.close()
    raise_for_status(response, f"releasing {meal} on {local_date}")
