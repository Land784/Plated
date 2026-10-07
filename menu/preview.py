"""Render the push a subscriber would get, for the web app's preview page.

The web app posts its unsaved settings (halls, stations, a meal and a
date); this reads that day's menus from the ``menus`` table (written by
menu/menus_store.py) and renders them with exactly the functions
``dispatch`` uses, so the preview can't drift from the real push.

It runs as a Vercel Python function (web/api/preview.py, a thin adapter
over :func:`handle_request`). It reads with the publishable key, since
menus are public, and needs no secret and no sign-in. Everything a
subscriber can't set in the web app (items per station, the mains
protein floor, picks) is left at the defaults every invited subscriber
has.
"""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date

import httpx

from menu.digest import build_message, full_menu_link, meal_tags, notification_title
from menu.menus_store import MENUS_TABLE, STORED_MEALS
from menu.models import DayMenu
from menu.notifier import compose_body
from menu.supabase_users import TIMEOUT, URL_ENV, api_headers, raise_for_status
from menu.users import DEFAULT_HALLS, UserConfig

PUBLISHABLE_KEY_ENV = "SUPABASE_PUBLISHABLE_KEY"

MAX_BODY_BYTES = 16_384
MAX_STATIONS = 100
MAX_STATION_NAME = 100

RATE_LIMIT = 30
RATE_WINDOW_SECONDS = 60.0


class PreviewInputError(ValueError):
    """The request body isn't a valid preview request."""


@dataclass(frozen=True)
class PreviewRequest:
    halls: list[str]
    stations: list[str]
    meal: str
    date: date


def parse_request(data: object) -> PreviewRequest:
    if not isinstance(data, dict):
        raise PreviewInputError("expected a JSON object")

    halls = data.get("halls")
    if (
        not isinstance(halls, list)
        or not halls
        or not all(isinstance(h, str) and h in DEFAULT_HALLS for h in halls)
        or len(set(halls)) != len(halls)
    ):
        raise PreviewInputError(f"halls: one or both of {', '.join(DEFAULT_HALLS)}, no repeats")

    stations = data.get("stations")
    if (
        not isinstance(stations, list)
        or len(stations) > MAX_STATIONS
        or not all(isinstance(s, str) and len(s) <= MAX_STATION_NAME for s in stations)
    ):
        raise PreviewInputError(
            f"stations: a list of at most {MAX_STATIONS} names of up to "
            f"{MAX_STATION_NAME} characters"
        )

    meal = data.get("meal")
    if meal not in STORED_MEALS:
        raise PreviewInputError(f"meal: one of {', '.join(STORED_MEALS)}")

    raw_date = data.get("date")
    try:
        day = date.fromisoformat(raw_date) if isinstance(raw_date, str) else None
    except ValueError:
        day = None
    if day is None:
        raise PreviewInputError("date: YYYY-MM-DD")

    return PreviewRequest(halls=list(halls), stations=list(stations), meal=meal, date=day)


def preview_user(req: PreviewRequest) -> UserConfig:
    # Never sent anywhere, so the topic is a placeholder.
    return UserConfig(name="preview", ntfy_topic="preview", halls=req.halls, stations=req.stations)


def render_preview(req: PreviewRequest, items_by_hall: Mapping[str, list[dict]]) -> dict:
    """The push as dispatch would send it, from stored ``menus.items``.

    ``items_by_hall`` maps a hall slug to its stored items; a hall with
    no row is unpublished.
    """
    if not req.stations:
        return {"sent": False, "reason": "no stations chosen"}
    menus = {
        hall: (
            DayMenu.model_validate({"date": req.date, "menu_items": items_by_hall[hall]})
            if hall in items_by_hall
            else None
        )
        for hall in req.halls
    }
    user = preview_user(req)
    lines = build_message(user, menus, req.meal)
    if not lines:
        published = any(day is not None for day in menus.values())
        reason = "none of your stations serve this meal" if published else "no menu published"
        return {"sent": False, "reason": reason}
    body = compose_body("\n".join(lines), full_menu_link(user))
    return {
        "title": notification_title(req.meal, req.date),
        "tags": meal_tags(req.meal),
        "body": body,
        "bytes": len(body.encode("utf-8")),
        "sent": True,
    }


def fetch_menu_items(
    url: str, key: str, req: PreviewRequest, *, client: httpx.Client | None = None
) -> dict[str, list[dict]]:
    """Stored items for each requested hall that has a row."""
    http = client or httpx.Client(timeout=TIMEOUT)
    try:
        response = http.get(
            f"{url}/rest/v1/{MENUS_TABLE}",
            params={
                "select": "hall,items",
                "date": f"eq.{req.date.isoformat()}",
                "meal": f"eq.{req.meal}",
                "hall": f"in.({','.join(req.halls)})",
            },
            headers=api_headers(key),
        )
    finally:
        if client is None:
            http.close()
    raise_for_status(response, "loading menus")
    return {row["hall"]: row["items"] for row in response.json()}


class RateLimiter:
    """At most ``limit`` requests per ``window`` seconds per IP, in memory.

    Per function instance, so it's a speed bump rather than a guarantee;
    enough to stop a stuck debounce loop from hammering Supabase.
    """

    def __init__(
        self,
        limit: int = RATE_LIMIT,
        window: float = RATE_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.limit = limit
        self.window = window
        self.clock = clock
        self._hits: dict[str, deque[float]] = {}

    def allow(self, ip: str) -> bool:
        now = self.clock()
        if len(self._hits) > 10_000:  # forget idle IPs so memory stays bounded
            self._hits = {k: v for k, v in self._hits.items() if v and v[-1] > now - self.window}
        hits = self._hits.setdefault(ip, deque())
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True


def client_ip(forwarded_for: str | None, real_ip: str | None, peer: tuple) -> str:
    """The caller's IP: Vercel sets x-forwarded-for (overwriting any sent)."""
    if forwarded_for and forwarded_for.split(",")[0].strip():
        return forwarded_for.split(",")[0].strip()
    if real_ip and real_ip.strip():
        return real_ip.strip()
    return str(peer[0]) if peer else "unknown"


def handle_request(
    body: bytes,
    ip: str,
    *,
    limiter: RateLimiter,
    env: Mapping[str, str],
    client: httpx.Client | None = None,
) -> tuple[int, dict]:
    """One POST /api/preview: (HTTP status, JSON payload)."""
    if not limiter.allow(ip):
        return 429, {"error": "too many previews; wait a minute"}
    if len(body) > MAX_BODY_BYTES:
        return 413, {"error": "request too large"}
    try:
        req = parse_request(json.loads(body))
    except (ValueError, PreviewInputError) as exc:  # JSONDecodeError is a ValueError
        message = str(exc) if isinstance(exc, PreviewInputError) else "invalid JSON"
        return 400, {"error": message}

    url = env.get(URL_ENV, "").strip().rstrip("/")
    key = env.get(PUBLISHABLE_KEY_ENV, "").strip()
    if not url or not key:
        return 500, {"error": "preview is not configured"}
    try:
        items = fetch_menu_items(url, key, req, client=client)
    except Exception:  # noqa: BLE001 - details stay server-side
        # The response never carries the cause, but the function log does,
        # so a misconfigured deployment can be diagnosed from Vercel's logs.
        logging.getLogger(__name__).exception("preview: could not load menus from %s", url)
        return 502, {"error": "could not load menus"}
    return 200, render_preview(req, items)
