"""All network access to the Nutrislice API goes through this module.

Everything else in this package works on the pydantic models in
models.py, so it can be tested offline against fixtures. Tests must
never hit the live API (see CLAUDE.md).

VERIFIED 2026-09-20: the public-facing ``nd.nutrislice.com`` host
(what CLAUDE.md originally assumed as the API base) is a static
S3/CloudFront single-page-app shell with no backend of its own --
every path under it, including ``/menu/api/*``, falls back to serving
the same ``index.html``. The real JSON API lives on a separate
subdomain, ``nd.api.nutrislice.com``, found by pulling the site's
Angular JS bundle and reading the `menusApiDomain` getter, which
derives the API host from the page's own hostname (inserting an
"api." segment). Confirmed live via:

    GET https://nd.api.nutrislice.com/menu/api/schools/

which returns both dining halls with slugs "north-dining-hall" and
"south-dining-hall", each exposing menu_type slugs "breakfast",
"lunch", "late-lunch", "dinner", "brunch", and "special". See
config.example.toml for the confirmed values and
tests/fixtures/real_north_lunch_2026-09-21.json /
tests/fixtures/real_schools_2026-09-20.json for the captured
responses. school_slug/menu_type are still sourced from config.toml
rather than hardcoded, since a different Nutrislice tenant would need
different values and this could still change upstream.
"""

from __future__ import annotations

import json
import time
from datetime import date as Date
from datetime import timedelta
from pathlib import Path

import httpx

from menu.models import WeekMenu

BASE_URL = (
    "https://nd.api.nutrislice.com/menu/api/weeks/school/"
    "{school_slug}/menu-type/{menu_type}/{yyyy}/{mm}/{dd}/"
)

USER_AGENT = "plated-menu-bot/0.1 (personal project; github.com/Land784/Plated)"

DEFAULT_TIMEOUT = 10.0
MAX_RETRIES = 3
BACKOFF_SECONDS = 1.5

DEFAULT_CACHE_DIR = Path(".cache") / "menu"


class MenuFetchError(RuntimeError):
    """Raised when the Nutrislice API can't be reached or returns junk."""


def week_start(d: Date) -> Date:
    """The Sunday on or before ``d``.

    Nutrislice weeks run Sunday to Saturday: a request for Tuesday
    2026-09-22 returned days from Sunday 2026-09-20. Requesting and
    caching by the week's Sunday means every day of a week shares one
    request.
    """
    return d - timedelta(days=(d.weekday() + 1) % 7)


def _cache_path(cache_dir: Path, school_slug: str, menu_type: str, sunday: Date) -> Path:
    return cache_dir / f"{school_slug}__{menu_type}__{sunday.isoformat()}.json"


def _read_cache(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _write_cache(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def fetch_week_raw(
    school_slug: str,
    menu_type: str,
    d: Date,
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    use_cache: bool = True,
    client: httpx.Client | None = None,
) -> dict:
    """Fetch the raw JSON for the week containing ``d``.

    Requests and caches to disk by (school_slug, menu_type, the week's
    Sunday), so the live API is hit once per hall and meal type per
    week however many of its days are asked for, per CLAUDE.md's "being
    a good API citizen" section.
    """
    sunday = week_start(d)
    cache_file = _cache_path(cache_dir, school_slug, menu_type, sunday)

    if use_cache:
        cached = _read_cache(cache_file)
        if cached is not None:
            return cached

    url = BASE_URL.format(
        school_slug=school_slug,
        menu_type=menu_type,
        yyyy=sunday.year,
        mm=f"{sunday.month:02d}",
        dd=f"{sunday.day:02d}",
    )

    owns_client = client is None
    http_client = client or httpx.Client(
        timeout=DEFAULT_TIMEOUT, headers={"User-Agent": USER_AGENT}
    )

    try:
        payload: dict | None = None
        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = http_client.get(url)
                response.raise_for_status()
                payload = response.json()
                break
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt < MAX_RETRIES:
                    time.sleep(BACKOFF_SECONDS * attempt)
        if payload is None:
            raise MenuFetchError(f"Failed to fetch menu from {url}") from last_error
    finally:
        if owns_client:
            http_client.close()

    if use_cache:
        _write_cache(cache_file, payload)

    return payload


def fetch_week(
    school_slug: str,
    menu_type: str,
    d: Date,
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    use_cache: bool = True,
    client: httpx.Client | None = None,
) -> WeekMenu:
    """Fetch and parse the week containing ``d`` into a WeekMenu."""
    raw = fetch_week_raw(
        school_slug, menu_type, d, cache_dir=cache_dir, use_cache=use_cache, client=client
    )
    return WeekMenu.model_validate(raw)


def fetch_day(
    school_slug: str,
    menu_type: str,
    d: Date,
    **kwargs,
):
    """Fetch a single day's menu, or None if that day isn't in the response."""
    week = fetch_week(school_slug, menu_type, d, **kwargs)
    for day in week.days:
        if day.date == d:
            return day
    return None
