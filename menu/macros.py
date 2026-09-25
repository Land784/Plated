"""Nutrients a subscriber can set goals on, and what a goal means.

A goal on one nutrient is any mix of a ``target`` (aim for this, within
a tolerance), a ``min`` and a ``max``. The planner turns each goal into
one allowed range for a meal's total; see :meth:`Goal.bounds`.

Only nutrients Nutrislice actually reports are offered: on 2026-09-24
every item at the tracked stations carried all seven below, while the
vitamin fields were always null.
"""

from __future__ import annotations

from dataclasses import dataclass

from menu.models import MenuItem

# A target with no explicit tolerance accepts totals within this
# fraction of it: a 70g protein target means 59.5-80.5g.
DEFAULT_TOLERANCE_FRACTION = 0.15


@dataclass(frozen=True)
class Nutrient:
    name: str
    unit: str
    field: str  # attribute on NutritionInfo


NUTRIENTS: dict[str, Nutrient] = {
    n.name: n
    for n in (
        Nutrient("protein", "g", "protein_g"),
        Nutrient("carbs", "g", "carbs_g"),
        Nutrient("fat", "g", "fat_g"),
        Nutrient("calories", "", "calories"),
        Nutrient("fiber", "g", "fiber_g"),
        Nutrient("sugar", "g", "sugar_g"),
        Nutrient("sodium", "mg", "sodium_mg"),
    )
}


def nutrient_value(item: MenuItem, nutrient: str) -> float | None:
    """One serving's reported value, or None if Nutrislice left it out.

    A reported 0 is returned as 0. It can't be told apart from a blank
    upstream, so it is passed through as reported rather than guessed at.
    """
    if item.food is None or item.food.nutrition is None:
        return None
    return getattr(item.food.nutrition, NUTRIENTS[nutrient].field)


@dataclass(frozen=True)
class Goal:
    target: float | None = None
    min: float | None = None
    max: float | None = None
    tolerance: float | None = None

    @property
    def drives_picks(self) -> bool:
        """True if the goal asks for *some* amount.

        Goals made only of maxima are satisfied by eating nothing, so a
        set of goals needs at least one target or min to pick anything.
        """
        return self.target is not None or self.min is not None

    def bounds(self) -> tuple[float, float]:
        """The allowed range for a meal's total, combining every part."""
        low, high = 0.0, float("inf")
        if self.target is not None:
            tol = (
                self.tolerance
                if self.tolerance is not None
                else self.target * DEFAULT_TOLERANCE_FRACTION
            )
            low, high = self.target - tol, self.target + tol
        if self.min is not None:
            low = max(low, self.min)
        if self.max is not None:
            high = min(high, self.max)
        return low, high


def describe_range(nutrient: str, goal: Goal) -> str:
    """The allowed range alone, e.g. "60-80g", "≤60g" or "≥8g"."""
    unit = NUTRIENTS[nutrient].unit
    low, high = goal.bounds()
    if high == float("inf"):
        return f"≥{low:.0f}{unit}"
    if low <= 0:
        return f"≤{high:.0f}{unit}"
    return f"{low:.0f}-{high:.0f}{unit}"


def describe_goal(nutrient: str, goal: Goal) -> str:
    """Human-readable goal, e.g. "protein 60-80g" or "carbs ≤60g"."""
    return f"{nutrient} {describe_range(nutrient, goal)}"
