"""Subscribers stored in Supabase, as an alternative to ``users/*.toml``.

Rows in ``public.subscribers`` (supabase/migrations/) use the same keys
as a subscriber TOML file, so each row goes through
:func:`menu.users.parse_user` exactly like a file does. There is one
validation path whichever source is used.

Access is Supabase's PostgREST endpoint over plain httpx, not the
``supabase`` client library: two queries don't justify a dependency
tree. The table has row level security on and no policies, so only the
secret key can read it. That key and the URL come from the environment
(``SUPABASE_URL``, ``SUPABASE_SECRET_KEY``) and never from a file in
this repo.
"""

from __future__ import annotations

import os

import httpx

from menu.macros import Goal
from menu.users import MacrosConfig, UserConfig, parse_user

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
    "max_items_per_station",
    "schedule",
    "macros",
    "picks",
)

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


def _headers(key: str) -> dict[str, str]:
    headers = {"apikey": key}
    # Legacy service_role keys are JWTs and also go in Authorization.
    # The newer sb_secret_ keys are not JWTs; the gateway rejects them
    # there, and needs only the apikey header.
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _raise_for_status(response: httpx.Response, action: str) -> None:
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
            params={"select": ",".join(COLUMNS), "active": "is.true", "order": "created_at"},
            headers=_headers(key),
        )
    finally:
        if client is None:
            http.close()
    _raise_for_status(response, "loading subscribers")
    rows = response.json()
    if not isinstance(rows, list):
        raise SupabaseError(f"loading subscribers: expected a list, got {type(rows).__name__}")
    return rows


def load_users_from_supabase(
    url: str, key: str, *, client: httpx.Client | None = None
) -> list[UserConfig]:
    """Load and validate every active subscriber.

    Strict like :func:`menu.users.load_users`: one bad row fails the load
    rather than silently dropping a subscriber.
    """
    rows = fetch_subscriber_rows(url, key, client=client)
    return [parse_user(row, source=f"supabase:{row.get('name', '?')}") for row in rows]


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
        "max_items_per_station": user.max_items_per_station,
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
    url: str, key: str, data: dict, *, source: str, client: httpx.Client | None = None
) -> UserConfig:
    """Validate ``data`` like a subscriber file, then insert or update it.

    Rows are matched on ``ntfy_topic``, so re-pushing an edited file
    updates that person rather than duplicating them. Every column is
    written from the validated config, defaults included, so a key
    deleted from the file is cleared in the row rather than left stale.
    """
    user = parse_user(data, source=source)
    row = user_to_row(user)
    http = client or httpx.Client(timeout=TIMEOUT)
    try:
        response = http.post(
            f"{url}/rest/v1/{TABLE}",
            params={"on_conflict": "ntfy_topic"},
            json=row,
            headers={
                **_headers(key),
                "Prefer": "resolution=merge-duplicates,return=minimal",
            },
        )
    finally:
        if client is None:
            http.close()
    _raise_for_status(response, f"saving {source}")
    return user
