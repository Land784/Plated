"""Turn a day's raw menu into a short, station-grouped digest.

Nutrislice does not attach a station *name* to regular menu items -- they
only carry a numeric ``station_id``. The human-readable name ("Domer
Diner", "La Mesa") appears only on the ``is_station_header`` row that
precedes that station's items, in its ``text`` field. So grouping
requires walking a day's items in order and tracking the current header.

Station names are also not consistent between halls: North publishes
"The Global Compass" while South publishes "Global Compass" for what is
effectively the same station. All matching therefore goes through
:func:`normalize_station`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from menu.models import DayMenu, MenuItem

_WHITESPACE = re.compile(r"\s+")
_LEADING_ARTICLE = re.compile(r"^the\s+")


@dataclass
class Station:
    """A station header and the items served under it, in menu order."""

    name: str
    items: list[MenuItem] = field(default_factory=list)

    @property
    def dish_names(self) -> list[str]:
        """Item names, de-duplicated, preserving menu order.

        Real feeds repeat rows (South listed "Sliced Red Onion" twice in
        one station), which reads as a bug in a notification.
        """
        seen: set[str] = set()
        names: list[str] = []
        for item in self.items:
            if item.food is None:
                continue
            name = item.food.name.strip()
            if not name or name in seen:
                continue
            seen.add(name)
            names.append(name)
        return names


def normalize_station(name: str) -> str:
    """Normalize a station name for matching against an allowlist."""
    collapsed = _WHITESPACE.sub(" ", name).strip().lower()
    return _LEADING_ARTICLE.sub("", collapsed)


def group_by_station(day: DayMenu) -> list[Station]:
    """Group a day's items under their station headers, in menu order.

    Items appearing before any header are collected under an empty
    station name. Since filtering is allowlist-based, such items are
    dropped unless a caller explicitly asks for them.
    """
    stations: list[Station] = []
    current: Station | None = None

    for item in day.menu_items:
        if item.is_station_header:
            current = Station(name=(item.text or "").strip())
            stations.append(current)
            continue

        if item.food is None:
            continue

        if current is None:
            current = Station(name="")
            stations.append(current)

        current.items.append(item)

    return [s for s in stations if s.items]


def filter_stations(stations: list[Station], allowlist: list[str]) -> list[Station]:
    """Keep only stations whose normalized name is in ``allowlist``."""
    wanted = {normalize_station(name) for name in allowlist}
    return [s for s in stations if normalize_station(s.name) in wanted]


def render_stations(stations: list[Station], max_items: int) -> list[str]:
    """Render stations as display lines, capping items per station.

    Build-your-own stations enumerate ingredients rather than dishes
    (South's Pastaria lists 20 components), so an uncapped render is
    unusable on a phone. Truncation is always reported as "+N more"
    rather than hidden.
    """
    lines: list[str] = []
    for station in stations:
        names = station.dish_names
        if not names:
            continue
        lines.append(station.name)
        for name in names[:max_items]:
            lines.append(f"  {name}")
        remaining = len(names) - max_items
        if remaining > 0:
            lines.append(f"  +{remaining} more")
    return lines


def build_hall_section(
    hall_name: str,
    day: DayMenu | None,
    allowlist: list[str],
    max_items: int,
) -> list[str]:
    """Render one hall's section of the digest, or [] if it has nothing.

    Returning an empty list (rather than a "nothing here" line) lets the
    caller distinguish a hall with no matching food from one it should
    render, and lets a whole meal be detected as empty.
    """
    if day is None:
        return []
    stations = filter_stations(group_by_station(day), allowlist)
    body = render_stations(stations, max_items)
    if not body:
        return []
    return [hall_name.upper(), *body]
