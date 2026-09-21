"""Allergen filtering logic.

Missing allergen data means "unknown", not "safe" -- never treat an
item as allergen-free just because no allergen tags are present (see
CLAUDE.md).
"""

from __future__ import annotations

from enum import StrEnum

from menu.models import MenuItem


class UnknownAllergenPolicy(StrEnum):
    FLAG = "flag"
    EXCLUDE = "exclude"


def has_known_allergen_data(item: MenuItem) -> bool:
    """True if Nutrislice actually reported allergen tags for this item."""
    return bool(item.food and item.food.allergens)


def item_is_allergen_safe(item: MenuItem, excluded_allergens: set[str]) -> bool | None:
    """Return True/False if we can tell, or None if allergen data is unknown."""
    if not has_known_allergen_data(item):
        return None
    tags = {a.name.lower() for a in item.food.allergens}
    excluded = {a.lower() for a in excluded_allergens}
    return not (tags & excluded)


def is_unknown(item: MenuItem, excluded_allergens: set[str]) -> bool:
    return item_is_allergen_safe(item, excluded_allergens) is None


def filter_items(
    items: list[MenuItem],
    excluded_allergens: set[str],
    *,
    unknown_policy: UnknownAllergenPolicy = UnknownAllergenPolicy.FLAG,
) -> tuple[list[MenuItem], list[MenuItem]]:
    """Split items into (kept, dropped).

    With unknown_policy=FLAG, items with unknown allergen data stay in
    the kept list (callers should render them with a flag). With
    EXCLUDE, they move to dropped, alongside items known to contain an
    excluded allergen.
    """
    keep: list[MenuItem] = []
    dropped: list[MenuItem] = []

    for item in items:
        verdict = item_is_allergen_safe(item, excluded_allergens)
        if verdict is False:
            dropped.append(item)
        elif verdict is None and unknown_policy is UnknownAllergenPolicy.EXCLUDE:
            dropped.append(item)
        else:
            keep.append(item)

    return keep, dropped
