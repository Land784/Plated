"""Save each day's menus to Supabase for the web app.

The notify job is the only thing that talks to Nutrislice. Once a day it
copies today's menus into ``public.menus`` (supabase/migrations/), one
row per (date, hall, meal), so the web app's preview and station picker
read Supabase and never Nutrislice.

A row's ``items`` is the day's ``menu_items`` trimmed to the fields the
models in menu/models.py read, in menu order, so
``DayMenu.model_validate({"date": ..., "menu_items": items})`` rebuilds
it and :func:`menu.digest.group_by_station` works unchanged. Values are
copied exactly as reported: nulls, bulk recipe rows and duplicate rows
all stay. Dropping the rest (ingredients, icon URLs, ids) takes a row
from ~100 KB to ~25 KB.

Alongside each row, ``public.menu_stations`` gets one row per station
with the names the push would list for it (its mains, by the same rule
as menu/digest.py). The station picker's example dishes come from there,
so SQL only has to count, never re-implement the mains rule.

Writes use the secret key over PostgREST, like menu/supabase_users.py.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx

from menu import client as nutrislice
from menu.digest import (
    MainsRule,
    Station,
    group_by_station,
    is_food_station,
    normalize_station,
    station_lineup,
)
from menu.models import DayMenu, MenuItem
from menu.planner import DEFAULT_MAX_ITEM_CALORIES
from menu.supabase_users import TIMEOUT, SupabaseError, api_headers, raise_for_status
from menu.users import DEFAULT_HALLS, DEFAULT_MAIN_PROTEIN_G

MENUS_TABLE = "menus"
STATIONS_TABLE = "menu_stations"

# Every confirmed menu type that serves food ("special" has never been
# seen with items). One week request per hall per type covers a week.
STORED_MEALS = ("breakfast", "brunch", "lunch", "late-lunch", "dinner")
STORED_HALLS = DEFAULT_HALLS

RETENTION_DAYS = 60

# The day starts at this local time: the first run after it stores the
# day's menus. Late enough that the day's menus are published.
STORE_TIMEZONE = "America/New_York"
STORE_AFTER = time(5, 0)

# How many names to keep per station row. The picker shows three, chosen
# by how often each appears over two weeks, so a few spares help it count.
STORED_MAINS = 8
EXAMPLE_RULE = MainsRule(
    min_protein_g=DEFAULT_MAIN_PROTEIN_G,
    max_item_calories=DEFAULT_MAX_ITEM_CALORIES,
    max_items=STORED_MAINS,
)

# The nutrition keys the models read, under Nutrislice's names.
NUTRITION_KEYS = ("calories", "g_protein", "g_fat", "g_carbs", "mg_sodium", "g_fiber", "g_sugar")

Fetch = Callable[[str, str, date], DayMenu | None]


# ---- trimming --------------------------------------------------------------


def trim_item(item: MenuItem) -> dict | None:
    """One menu row in the stored shape, or None for a row with no food."""
    if item.is_station_header:
        return {"is_station_header": True, "text": item.text, "station_id": item.station_id}
    food = item.food
    if food is None:
        return None  # group_by_station skips these too
    nutrition = food.nutrition.model_dump(by_alias=True) if food.nutrition else None
    serving = food.serving_size.model_dump(by_alias=True) if food.serving_size else None
    return {
        "station_id": item.station_id,
        "food": {
            "name": food.name,
            "rounded_nutrition_info": (
                {key: nutrition[key] for key in NUTRITION_KEYS} if nutrition else None
            ),
            "serving_size_info": serving,
            "icons": {"food_icons": [{"name": tag.name} for tag in food.allergens]},
        },
    }


def trim_day(day: DayMenu) -> list[dict]:
    return [row for item in day.menu_items if (row := trim_item(item)) is not None]


def has_food(day: DayMenu | None) -> bool:
    return day is not None and any(item.food for item in day.menu_items)


def menu_row(d: date, hall: str, meal: str, day: DayMenu | None, now: datetime) -> dict | None:
    """The ``menus`` row for one hall and meal, or None when nothing is served."""
    if not has_food(day):
        return None
    return {
        "date": d.isoformat(),
        "hall": hall,
        "meal": meal,
        # Written explicitly: the column default only applies on insert.
        "fetched_at": now.isoformat(),
        "items": trim_day(day),
    }


def _merged_stations(day: DayMenu) -> list[Station]:
    """Stations by published name, in menu order; a repeated header joins the first."""
    merged: dict[str, Station] = {}
    for station in group_by_station(day):
        if not station.name:
            continue  # items before any header have no station to pick
        merged.setdefault(station.name, Station(station.name)).items.extend(station.items)
    return list(merged.values())


def station_rows(d: date, hall: str, meal: str, day: DayMenu) -> list[dict]:
    """One ``menu_stations`` row per station, with the names the push would list."""
    return [
        {
            "date": d.isoformat(),
            "hall": hall,
            "meal": meal,
            "station": station.name,
            "normalized": normalize_station(station.name),
            "is_food": is_food_station(station.name),
            "mains": station_lineup(station, EXAMPLE_RULE),
        }
        for station in _merged_stations(day)
    ]


# ---- PostgREST -------------------------------------------------------------


def _http(client: httpx.Client | None) -> httpx.Client:
    return client or httpx.Client(timeout=TIMEOUT)


def has_menus_for(url: str, key: str, d: date, *, client: httpx.Client | None = None) -> bool:
    """Whether any ``menus`` row exists for ``d``: the day's store already ran."""
    http = _http(client)
    try:
        response = http.get(
            f"{url}/rest/v1/{MENUS_TABLE}",
            params={"select": "date", "date": f"eq.{d.isoformat()}", "limit": "1"},
            headers=api_headers(key),
        )
    finally:
        if client is None:
            http.close()
    raise_for_status(response, f"checking menus for {d}")
    return bool(response.json())


def upsert_menus(url: str, key: str, rows: list[dict], http: httpx.Client) -> None:
    response = http.post(
        f"{url}/rest/v1/{MENUS_TABLE}",
        params={"on_conflict": "date,hall,meal"},
        json=rows,
        headers={**api_headers(key), "Prefer": "resolution=merge-duplicates,return=minimal"},
    )
    raise_for_status(response, f"saving menus for {rows[0]['date']}")


def replace_station_rows(
    url: str, key: str, d: date, menus: list[tuple[str, str]], rows: list[dict], http: httpx.Client
) -> None:
    """Swap the station rows of exactly these (hall, meal) menus on ``d``.

    Deleting first means a station that dropped off a re-stored menu
    doesn't linger in the picker.
    """
    pairs = ",".join(f"and(hall.eq.{hall},meal.eq.{meal})" for hall, meal in menus)
    response = http.delete(
        f"{url}/rest/v1/{STATIONS_TABLE}",
        params={"date": f"eq.{d.isoformat()}", "or": f"({pairs})"},
        headers=api_headers(key),
    )
    raise_for_status(response, f"clearing stations for {d}")
    if not rows:
        return
    response = http.post(
        f"{url}/rest/v1/{STATIONS_TABLE}",
        json=rows,
        headers={**api_headers(key), "Prefer": "return=minimal"},
    )
    raise_for_status(response, f"saving stations for {d}")


def delete_menus_before(url: str, key: str, cutoff: date, http: httpx.Client) -> None:
    """Retention. Station rows go with their menu (on delete cascade)."""
    response = http.delete(
        f"{url}/rest/v1/{MENUS_TABLE}",
        params={"date": f"lt.{cutoff.isoformat()}"},
        headers=api_headers(key),
    )
    raise_for_status(response, f"deleting menus before {cutoff}")


# ---- the job ---------------------------------------------------------------


def store_due(now_utc: datetime) -> date | None:
    """The local date to store if it is past STORE_AFTER there, else None."""
    local = now_utc.astimezone(ZoneInfo(STORE_TIMEZONE))
    return local.date() if local.time() >= STORE_AFTER else None


def store_day(
    url: str,
    key: str,
    d: date,
    *,
    now: datetime,
    fetch: Fetch | None = None,
    client: httpx.Client | None = None,
) -> list[str]:
    """Fetch every hall and meal for ``d``, save them, and prune old rows.

    Returns problems instead of raising, so the caller can report them
    without anything else failing. A menu that fails to fetch is skipped
    and the rest are saved.
    """
    fetch = fetch or nutrislice.fetch_day
    problems: list[str] = []
    menus: list[tuple[str, str]] = []
    rows: list[dict] = []
    stations: list[dict] = []
    for hall in STORED_HALLS:
        for meal in STORED_MEALS:
            try:
                day = fetch(hall, meal, d)
            except Exception as exc:  # noqa: BLE001 - one menu must not stop the rest
                problems.append(f"menus store: {hall}/{meal} on {d}: {exc}")
                continue
            if (row := menu_row(d, hall, meal, day, now)) is None:
                continue
            menus.append((hall, meal))
            rows.append(row)
            stations.extend(station_rows(d, hall, meal, day))

    http = _http(client)
    try:
        if rows:
            try:
                upsert_menus(url, key, rows, http)
                replace_station_rows(url, key, d, menus, stations, http)
            except (SupabaseError, httpx.HTTPError) as exc:
                problems.append(f"menus store: {exc}")
        try:
            delete_menus_before(url, key, d - timedelta(days=RETENTION_DAYS), http)
        except (SupabaseError, httpx.HTTPError) as exc:
            problems.append(f"menus store: {exc}")
    finally:
        if client is None:
            http.close()
    return problems
