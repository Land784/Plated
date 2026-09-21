"""Pydantic models for the Nutrislice menu API.

The exact JSON shape returned by Nutrislice is UNVERIFIED (see
CLAUDE.md). These models are a best-effort guess based on the commonly
observed Nutrislice schema used by other schools. Before relying on
this in production:

1. Capture a real response (DevTools Network tab, see
   tests/fixtures/README.md) and save it to tests/fixtures/.
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

from pydantic import BaseModel, ConfigDict, Field


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


class AllergenTag(BaseModel):
    """A single allergen/dietary icon as reported by Nutrislice.

    Presence of this list is NOT proof of safety. Absence of a tag
    means "unknown", not "allergen-free" -- see allergens.py.
    """

    model_config = ConfigDict(extra="ignore")

    name: str


class Food(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    name: str
    description: str | None = None
    nutrition: NutritionInfo | None = Field(default=None, alias="rounded_nutrition_info")
    serving_size_amount: float | None = None
    serving_size_unit: str | None = None
    allergens: list[AllergenTag] = Field(default_factory=list)


class MenuItem(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    food: Food | None = None
    station: str | None = None
    is_station_header: bool = False


class DayMenu(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    date: Date
    menu_items: list[MenuItem] = Field(default_factory=list)


class WeekMenu(BaseModel):
    model_config = ConfigDict(extra="ignore")

    days: list[DayMenu] = Field(default_factory=list)
