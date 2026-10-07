"""Save each day's menus to Supabase for the web app.

The notify job is the only thing that talks to Nutrislice. Once a day it
copies the current week's menus into ``public.menus``
(supabase/migrations/), one row per (date, hall, meal), so the web
app's preview and station picker read Supabase and never Nutrislice.

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
from menu.models import DayMenu, MenuItem, WeekMenu
from menu.planner import DEFAULT_MAX_ITEM_CALORIES
from menu.supabase_users import TIMEOUT, SupabaseError, api_headers, raise_for_status
from menu.users import DEFAULT_HALLS, DEFAULT_MAIN_PROTEIN_G

MENUS_TABLE = "menus"
STATIONS_TABLE = "menu_stations"
# One row per local date whose store finished with no problems.
RUNS_TABLE = "menu_store_runs"

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

FetchWeek = Callable[[str, str, date], WeekMenu]


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


def has_store_run(url: str, key: str, d: date, *, client: httpx.Client | None = None) -> bool:
    """Whether a store for local date ``d`` already finished without problems."""
    http = _http(client)
    try:
        response = http.get(
            f"{url}/rest/v1/{RUNS_TABLE}",
            params={"select": "local_date", "local_date": f"eq.{d.isoformat()}", "limit": "1"},
            headers=api_headers(key),
        )
    finally:
        if client is None:
            http.close()
    raise_for_status(response, f"checking the menus store for {d}")
    return bool(response.json())


def record_store_run(url: str, key: str, d: date, now: datetime, http: httpx.Client) -> None:
    response = http.post(
        f"{url}/rest/v1/{RUNS_TABLE}",
        params={"on_conflict": "local_date"},
        json={"local_date": d.isoformat(), "stored_at": now.isoformat()},
        headers={**api_headers(key), "Prefer": "resolution=merge-duplicates,return=minimal"},
    )
    raise_for_status(response, f"recording the menus store for {d}")


def upsert_menus(url: str, key: str, rows: list[dict], http: httpx.Client) -> None:
    response = http.post(
        f"{url}/rest/v1/{MENUS_TABLE}",
        params={"on_conflict": "date,hall,meal"},
        json=rows,
        headers={**api_headers(key), "Prefer": "resolution=merge-duplicates,return=minimal"},
    )
    raise_for_status(response, f"saving {rows[0]['hall']}/{rows[0]['meal']} menus")


def replace_station_rows(
    url: str,
    key: str,
    hall: str,
    meal: str,
    dates: list[date],
    rows: list[dict],
    http: httpx.Client,
) -> None:
    """Swap the station rows of one hall and meal on exactly these dates.

    Deleting first means a station that dropped off a re-stored menu
    doesn't linger in the picker.
    """
    response = http.delete(
        f"{url}/rest/v1/{STATIONS_TABLE}",
        params={
            "hall": f"eq.{hall}",
            "meal": f"eq.{meal}",
            "date": f"in.({','.join(d.isoformat() for d in dates)})",
        },
        headers=api_headers(key),
    )
    raise_for_status(response, f"clearing {hall}/{meal} stations")
    if not rows:
        return
    response = http.post(
        f"{url}/rest/v1/{STATIONS_TABLE}",
        json=rows,
        headers={**api_headers(key), "Prefer": "return=minimal"},
    )
    raise_for_status(response, f"saving {hall}/{meal} stations")


def delete_before(url: str, key: str, cutoff: date, http: httpx.Client) -> None:
    """Retention. Station rows go with their menu (on delete cascade)."""
    for table, column in ((MENUS_TABLE, "date"), (RUNS_TABLE, "local_date")):
        response = http.delete(
            f"{url}/rest/v1/{table}",
            params={column: f"lt.{cutoff.isoformat()}"},
            headers=api_headers(key),
        )
        raise_for_status(response, f"deleting {table} before {cutoff}")


# ---- the job ---------------------------------------------------------------


def store_due(now_utc: datetime) -> date | None:
    """The local date to store if it is past STORE_AFTER there, else None."""
    local = now_utc.astimezone(ZoneInfo(STORE_TIMEZONE))
    return local.date() if local.time() >= STORE_AFTER else None


def _store_menu(
    url: str, key: str, hall: str, meal: str, week: WeekMenu, now: datetime, http: httpx.Client
) -> None:
    """Every day of one hall and meal's week that serves food."""
    days = [day for day in week.days if has_food(day)]
    if not days:
        return
    upsert_menus(url, key, [menu_row(day.date, hall, meal, day, now) for day in days], http)
    stations = [row for day in days for row in station_rows(day.date, hall, meal, day)]
    replace_station_rows(url, key, hall, meal, [day.date for day in days], stations, http)


def store_week(
    url: str,
    key: str,
    d: date,
    *,
    now: datetime,
    fetch: FetchWeek | None = None,
    client: httpx.Client | None = None,
) -> list[str]:
    """Store every day of the week containing ``d``, for every hall and meal.

    The week request is the one Nutrislice call per hall and meal, so
    storing all of it costs nothing extra and lets the preview show the
    rest of the week. Then prunes rows over RETENTION_DAYS old.

    Returns problems instead of raising. A hall and meal that fails is
    skipped and the rest are stored; only a store with no problems is
    recorded in ``menu_store_runs`` (as local date ``d``), so a partial
    one is retried by the next run.
    """
    fetch = fetch or nutrislice.fetch_week
    problems: list[str] = []
    http = _http(client)
    try:
        for hall in STORED_HALLS:
            for meal in STORED_MEALS:
                try:
                    week = fetch(hall, meal, d)
                    _store_menu(url, key, hall, meal, week, now, http)
                except Exception as exc:  # noqa: BLE001 - one menu must not stop the rest
                    problems.append(f"menus store: {hall}/{meal} for the week of {d}: {exc}")
        try:
            delete_before(url, key, d - timedelta(days=RETENTION_DAYS), http)
            if not problems:
                record_store_run(url, key, d, now, http)
        except (SupabaseError, httpx.HTTPError) as exc:
            problems.append(f"menus store: {exc}")
    finally:
        if client is None:
            http.close()
    return problems
