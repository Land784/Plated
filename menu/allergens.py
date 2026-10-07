"""Allergen filtering logic.

Missing allergen data means "unknown", not "safe" -- never treat an
item as allergen-free just because no allergen tags are present (see
CLAUDE.md).
"""

from __future__ import annotations

from enum import StrEnum

from menu.models import MenuItem

# Nutrislice mixes dietary labels into the same tag list as allergens,
# with identical metadata (see AllergenTag in menu/models.py). These are
# not allergen information. It is deliberately a list of known
# NON-allergens rather than of allergens: a tag name nobody anticipated
# counts as allergen data instead of being silently ignored.
DIETARY_LABELS = frozenset({"vegan", "vegetarian", "high performance"})


class UnknownAllergenPolicy(StrEnum):
    FLAG = "flag"
    EXCLUDE = "exclude"


def has_known_allergen_data(item: MenuItem) -> bool:
    """True if Nutrislice reported at least one tag that isn't a dietary label.

    An item tagged only "High Performance" or "Vegan" has no allergen
    information at all, so it is unknown exactly like an untagged item.
    """
    tags = item.food.allergens if item.food else []
    return any(tag.name.strip().lower() not in DIETARY_LABELS for tag in tags)


def item_is_allergen_safe(item: MenuItem, excluded_allergens: set[str]) -> bool | None:
    """Return True/False if we can tell, or None if allergen data is unknown."""
    tags = {a.name.strip().lower() for a in item.food.allergens} if item.food else set()
    excluded = {a.strip().lower() for a in excluded_allergens}
    # A matching tag excludes the item whatever else is (or isn't) known.
    if tags & excluded:
        return False
    if not has_known_allergen_data(item):
        return None
    return True


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
