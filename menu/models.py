"""Pydantic models for the Nutrislice menu API.

VERIFIED 2026-09-20 against a live response from
``https://nd.api.nutrislice.com/menu/api/weeks/school/north-dining-hall/menu-type/lunch/...``
(see ``tests/fixtures/real_north_lunch_2026-09-21.json`` and
``menu/client.py`` for how the correct API host was found). These
models match that real response as of that date, but Nutrislice is
unofficial and undocumented, so the shape can still drift:

1. If parsing breaks or looks wrong, capture a fresh response and save
   it to ``tests/fixtures/`` (see ``tests/fixtures/README.md``).
2. Compare the saved JSON against these models and adjust field names,
   types, and optionality to match.
3. Add/extend a regression test in tests/test_models.py that parses
   the real fixture.

All fields are Optional unless we're confident they're always present,
because missing/changed fields must not crash the pipeline. Extra
fields are ignored rather than rejected, so an unrelated schema change
upstream doesn't break parsing.
"""

from __future__ import annotations

from datetime import date as Date

from pydantic import AliasPath, BaseModel, ConfigDict, Field


class NutritionInfo(BaseModel):
    """Nutrition facts for a single serving, as reported by Nutrislice.

    Never fill in missing values -- a missing protein value means the
    item has no protein score and is not ranked (see CLAUDE.md).
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    calories: float | None = None
    protein_g: float | None = Field(default=None, alias="g_protein")
    fat_g: float | None = Field(default=None, alias="g_fat")
    carbs_g: float | None = Field(default=None, alias="g_carbs")
    sodium_mg: float | None = Field(default=None, alias="mg_sodium")


class ServingSizeInfo(BaseModel):
    """Serving size as recorded by Nutrislice.

    Kept as raw strings, not parsed into numbers/units, because the
    real data is inconsistent (e.g. unit "z" instead of "oz" shows up
    in real fixtures) and amounts can be fractional ("0.75"). Never
    corrected or normalized here -- see CLAUDE.md's "never invent,
    estimate, or fill in" rule. Record it as given; let a caller that
    actually needs a parsed number handle the fallout of bad upstream
    data explicitly.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    amount: str | None = Field(default=None, alias="serving_size_amount")
    unit: str | None = Field(default=None, alias="serving_size_unit")


class AllergenTag(BaseModel):
    """A single tag from Nutrislice's ``food.icons.food_icons`` list.

    IMPORTANT: despite the field name below (``Food.allergens``),
    Nutrislice does NOT structurally separate allergens from unrelated
    dietary/nutrition claims -- "Dairy", "Wheat", and "Peanuts" sit in
    the exact same list, with the exact same metadata (same
    food_icon_group, type, and behavior values), as "Vegan",
    "Vegetarian", and "High Performance". The only signal is the name
    string. This is fine for allergen *exclusion* matching (we only
    check whether a specific excluded name appears), but it means an
    item with only non-allergen tags (e.g. just "Vegan") still counts
    as "has known icon data" even though no allergen was specifically
    ruled out. See allergens.py for how this is used, and CLAUDE.md's
    "missing allergen data means unknown, not safe" rule.
    """

    model_config = ConfigDict(extra="ignore")

    name: str


class Food(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    name: str
    description: str | None = None
    nutrition: NutritionInfo | None = Field(default=None, alias="rounded_nutrition_info")
    serving_size: ServingSizeInfo | None = Field(default=None, alias="serving_size_info")
    has_nutrition_info: bool = False
    allergens: list[AllergenTag] = Field(
        default_factory=list, validation_alias=AliasPath("icons", "food_icons")
    )


class MenuItem(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    food: Food | None = None
    # Nutrislice gives a numeric station_id, not a station name, on
    # regular items. The human-readable name ("Homestyle", "Grill",
    # etc.) only appears on the is_station_header row that precedes
    # that station's items, in `text`. Matching station_id -> name
    # would need a stateful pass over a day's items in order; not
    # implemented here since nothing in the planner needs it yet.
    station_id: int | None = None
    text: str | None = None
    is_station_header: bool = False


class DayMenu(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    date: Date
    menu_items: list[MenuItem] = Field(default_factory=list)


class WeekMenu(BaseModel):
    model_config = ConfigDict(extra="ignore")

    days: list[DayMenu] = Field(default_factory=list)
