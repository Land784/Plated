"""Nutrients a subscriber can set targets on, and what a target means.

A subscriber sets up to four per-meal targets (protein, carbs, fat in
grams, calories). A plate meets a target when its total is within the
subscriber's tolerance of it: a 60g protein target at 15% accepts
51-69g. See menu/planner.py.
"""

from __future__ import annotations

from dataclasses import dataclass

from menu.models import MenuItem

DEFAULT_TOLERANCE_PCT = 15.0


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


def bounds(target: float, tolerance_pct: float) -> tuple[float, float]:
    tol = target * tolerance_pct / 100
    return target - tol, target + tol


def describe_range(nutrient: str, target: float, tolerance_pct: float) -> str:
    """The accepted range, e.g. "51-69g"."""
    low, high = bounds(target, tolerance_pct)
    return f"{low:.0f}-{high:.0f}{NUTRIENTS[nutrient].unit}"


def describe_targets(targets: dict[str, float]) -> str:
    """ "protein 60g, calories 700"."""
    return ", ".join(f"{n} {t:g}{NUTRIENTS[n].unit}" for n, t in targets.items())
