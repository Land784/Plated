"""Invite someone to the web app: an auth user plus their subscriber row.

Sign-ups are closed, so this is the only way in. It creates the Supabase
Auth user with the admin invite endpoint, which emails them a sign-in
link, then either inserts a subscriber row for them with the web app's
first-run defaults or, with ``link``, attaches them to an existing row
(subscribers who predate the web app).

Everything that can be checked is checked before the invite is sent, so
a typo doesn't leave an auth user with no row. The database generates
the new row's ntfy topic (supabase/migrations/), and nothing here ever
reads or prints it.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

import httpx

from menu.digest import normalize_station
from menu.supabase_users import (
    TABLE,
    TIMEOUT,
    SupabaseError,
    api_headers,
    raise_for_status,
)
from menu.users import DEFAULT_HALLS, DEFAULT_MAX_ITEMS, WEEKDAYS

SITE_URL_ENV = "PLATED_SITE_URL"
STATIONS_VIEW = "stations"

# The web app's first-run defaults: lunch and dinner on weekdays,
# brunch and dinner at weekends.
WEEKDAY_MEALS = {"lunch": "12:00", "dinner": "17:30"}
WEEKEND_MEALS = {"brunch": "11:00", "dinner": "17:30"}
DEFAULT_SCHEDULE = {
    day: dict(WEEKEND_MEALS if day in ("saturday", "sunday") else WEEKDAY_MEALS) for day in WEEKDAYS
}


class InviteError(SupabaseError):
    """Raised when an invite can't be made; says what, if anything, was created."""


@dataclass(frozen=True)
class InviteResult:
    name: str
    user_id: str
    linked: bool


def site_url_from_env() -> str:
    site = os.environ.get(SITE_URL_ENV, "").strip().rstrip("/")
    if not site:
        raise InviteError(f"missing environment variable: {SITE_URL_ENV}")
    return site


def new_subscriber_row(name: str, user_id: str, stations: list[str]) -> dict:
    """A new subscriber: both halls (North first), every food station, no picks.

    No ntfy_topic: the column default generates one.
    """
    return {
        "name": name,
        "user_id": user_id,
        "halls": list(DEFAULT_HALLS),
        "stations": list(stations),
        "favorites": [],
        # Explicit, so a row never depends on the column default.
        "max_items_per_station": DEFAULT_MAX_ITEMS,
        "schedule": DEFAULT_SCHEDULE,
        "macros": None,
    }


def _subscribers_named(http: httpx.Client, url: str, key: str, name: str) -> list[dict]:
    response = http.get(
        f"{url}/rest/v1/{TABLE}",
        params={"select": "id,name,user_id", "name": f"eq.{name}"},
        headers=api_headers(key),
    )
    raise_for_status(response, f"looking up subscriber {name!r}")
    return response.json()


def _has_article(name: str) -> bool:
    return re.match(r"the\s+", name.strip(), re.IGNORECASE) is not None


def catalog_order(rows: list[dict]) -> list[str]:
    """Station names in the web app's catalog order (web/lib/plated/stations.ts).

    Food stations only, spellings merged by normalized name (preferring
    one without "The"), then: not breakfast-only before breakfast-only;
    at both halls, then North-only, then South-only; then by name,
    ignoring case. A new subscriber's ``stations`` must be in this order,
    the same list the app would write for "every station on".
    """
    merged: dict[str, dict] = {}
    for row in rows:
        name = row.get("station")
        if not isinstance(name, str) or not name.strip() or row.get("is_food") is False:
            continue
        acc = merged.setdefault(
            normalize_station(name), {"names": [], "halls": set(), "meals": set()}
        )
        acc["names"].append(name.strip())
        acc["halls"].update(h for h in row.get("halls") or [] if h in DEFAULT_HALLS)
        acc["meals"].update(row.get("meals") or [])

    entries = []
    for acc in merged.values():
        if not acc["halls"]:
            continue  # seen only at a hall the app doesn't offer
        name = next((n for n in acc["names"] if not _has_article(n)), acc["names"][0])
        breakfast_only = bool(acc["meals"]) and acc["meals"] <= {"breakfast"}
        north, south = DEFAULT_HALLS
        hall_rank = 0 if len(acc["halls"]) == 2 else 1 if north in acc["halls"] else 2
        entries.append((breakfast_only, hall_rank, name.casefold(), name))
    return [name for *_, name in sorted(entries)]


def food_stations(http: httpx.Client, url: str, key: str) -> list[str]:
    """Every food station seen in the last two weeks, in catalog order."""
    response = http.get(
        f"{url}/rest/v1/{STATIONS_VIEW}",
        params={"select": "station,halls,meals,is_food", "is_food": "is.true"},
        headers=api_headers(key),
    )
    raise_for_status(response, "loading the station catalog")
    return catalog_order(response.json())


def _link_target(http: httpx.Client, url: str, key: str, link: str) -> str:
    rows = _subscribers_named(http, url, key, link)
    if not rows:
        raise InviteError(f"no subscriber named {link!r} to link")
    if len(rows) > 1:
        raise InviteError(f"{len(rows)} subscribers are named {link!r}; link one by hand")
    if rows[0].get("user_id"):
        raise InviteError(f"subscriber {link!r} is already linked to an account")
    return rows[0]["id"]


def _send_invite(
    http: httpx.Client, url: str, key: str, email: str, name: str, site_url: str
) -> str:
    response = http.post(
        f"{url}/auth/v1/invite",
        params={"redirect_to": site_url},
        json={"email": email, "data": {"name": name}},
        headers=api_headers(key),
    )
    if not response.is_success:
        raise InviteError(
            f"inviting {email} failed: HTTP {response.status_code}: {response.text[:300]}"
        )
    user_id = response.json().get("id")
    if not isinstance(user_id, str) or not user_id:
        raise InviteError(f"inviting {email}: the reply had no user id")
    return user_id


def _orphaned(user_id: str, exc: Exception) -> InviteError:
    return InviteError(
        f"auth user {user_id} was invited but its subscriber row was not saved ({exc}). "
        "Delete that user under Authentication > Users and run the invite again."
    )


def invite_subscriber(
    url: str,
    key: str,
    *,
    email: str,
    name: str,
    site_url: str,
    link: str | None = None,
    client: httpx.Client | None = None,
) -> InviteResult:
    """Invite ``email`` and give them a subscriber row (new, or ``link``'s)."""
    if "@" not in email:
        raise InviteError(f"{email!r} is not an email address")
    name = name.strip()
    if not name:
        raise InviteError("a name is required")

    http = client or httpx.Client(timeout=TIMEOUT)
    try:
        if link is not None:
            row_id = _link_target(http, url, key, link)
        else:
            if _subscribers_named(http, url, key, name):
                raise InviteError(
                    f"a subscriber named {name!r} already exists; "
                    f"to give them an account, use --link {name}"
                )
            stations = food_stations(http, url, key)
            if not stations:
                raise InviteError(
                    "the station catalog is empty, so the new subscriber would get no "
                    "stations; run `menu menus store` first"
                )

        user_id = _send_invite(http, url, key, email, name, site_url)

        try:
            if link is not None:
                response = http.patch(
                    f"{url}/rest/v1/{TABLE}",
                    params={"id": f"eq.{row_id}", "user_id": "is.null", "select": "id"},
                    json={"user_id": user_id},
                    headers={**api_headers(key), "Prefer": "return=representation"},
                )
                raise_for_status(response, f"linking {link!r}")
                if not response.json():
                    raise InviteError(f"subscriber {link!r} was linked by someone else meanwhile")
            else:
                response = http.post(
                    f"{url}/rest/v1/{TABLE}",
                    # Only these come back, so the generated topic never does.
                    params={"select": "id,name"},
                    json=new_subscriber_row(name, user_id, stations),
                    headers={**api_headers(key), "Prefer": "return=representation"},
                )
                raise_for_status(response, f"saving subscriber {name!r}")
        except (SupabaseError, httpx.HTTPError) as exc:
            raise _orphaned(user_id, exc) from exc
    finally:
        if client is None:
            http.close()

    return InviteResult(
        name=link if link is not None else name, user_id=user_id, linked=link is not None
    )
