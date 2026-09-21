"""Loads config.toml (gitignored) with environment variable overrides
for secrets. See config.example.toml for the template.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_PATH = Path("config.toml")


@dataclass
class DiningHallConfig:
    slug: str
    name: str


@dataclass
class PlatedConfig:
    dining_halls: list[DiningHallConfig] = field(default_factory=list)
    meal_types: dict[str, str] = field(default_factory=dict)
    excluded_allergens: list[str] = field(default_factory=list)
    protein_target_g: float = 40.0
    calorie_cap: float | None = None
    unknown_allergen_policy: str = "flag"
    ntfy_topic: str | None = None


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> PlatedConfig:
    data: dict = {}
    if path.exists():
        with path.open("rb") as f:
            data = tomllib.load(f)

    halls = [
        DiningHallConfig(slug=h["slug"], name=h.get("name", h["slug"]))
        for h in data.get("dining_halls", [])
    ]

    return PlatedConfig(
        dining_halls=halls,
        meal_types=data.get("meal_types", {}),
        excluded_allergens=data.get("allergens", {}).get("exclude", []),
        protein_target_g=data.get("planner", {}).get("protein_target_g", 40.0),
        calorie_cap=data.get("planner", {}).get("calorie_cap"),
        unknown_allergen_policy=data.get("allergens", {}).get("unknown_policy", "flag"),
        ntfy_topic=os.environ.get("NTFY_TOPIC") or data.get("notify", {}).get("ntfy_topic"),
    )
