"""Command-line entry point: uv run python -m menu <fetch|plan|notify>"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from menu import client
from menu.allergens import UnknownAllergenPolicy
from menu.config import PlatedConfig, load_config
from menu.models import DayMenu, MenuItem
from menu.notifier import ConsoleNotifier, NtfyNotifier
from menu.planner import MealPlan, build_meal_plan


def _meal_period_and_type(config: PlatedConfig, requested: str | None) -> tuple[str, str]:
    meal_period = requested or next(iter(config.meal_types), "lunch")
    menu_type = config.meal_types.get(meal_period, meal_period)
    return meal_period, menu_type


def _fetch_all_halls(config: PlatedConfig, menu_type: str, d: date) -> dict[str, DayMenu | None]:
    return {hall.name: client.fetch_day(hall.slug, menu_type, d) for hall in config.dining_halls}


def _visible_items(day: DayMenu | None) -> list[MenuItem]:
    if day is None:
        return []
    return [item for item in day.menu_items if not item.is_station_header and item.food]


def cmd_fetch(args: argparse.Namespace) -> int:
    config = load_config()
    if not config.dining_halls:
        print("No dining halls configured -- see config.example.toml", file=sys.stderr)
        return 1

    d = date.today()
    meal_period, menu_type = _meal_period_and_type(config, args.meal)
    days = _fetch_all_halls(config, menu_type, d)

    for hall_name, day in days.items():
        print(f"\n== {hall_name} ({meal_period}, {d.isoformat()}) ==")
        items = _visible_items(day)
        if not items:
            print("  No menu data for today.")
            continue
        for item in items:
            nutrition = item.food.nutrition
            protein = nutrition.protein_g if nutrition else None
            calories = nutrition.calories if nutrition else None
            allergens = ", ".join(a.name for a in item.food.allergens) or "unknown"
            print(
                f"  - {item.food.name} | protein: {protein} | "
                f"calories: {calories} | allergens: {allergens}"
            )
    return 0


def _build_today_plan(config: PlatedConfig, meal: str | None) -> tuple[str, MealPlan]:
    meal_period, menu_type = _meal_period_and_type(config, meal)
    d = date.today()
    days = _fetch_all_halls(config, menu_type, d)

    all_items: list[MenuItem] = []
    for day in days.values():
        all_items.extend(_visible_items(day))

    plan = build_meal_plan(
        all_items,
        excluded_allergens=set(config.excluded_allergens),
        protein_target_g=config.protein_target_g,
        calorie_cap=config.calorie_cap,
        unknown_policy=UnknownAllergenPolicy(config.unknown_allergen_policy),
    )
    return meal_period, plan


def _format_plan(meal_period: str, plan: MealPlan) -> str:
    lines = [f"Meal plan ({meal_period}):"]
    if not plan.items:
        lines.append("  No items met the criteria.")
    for planned in plan.items:
        lines.append(f"  - {planned.reason}")
    lines.append(
        f"Total: {plan.total_protein_g:g}g protein / {plan.total_calories:g} cal "
        f"(target met: {plan.target_met})"
    )
    if plan.flagged_unknown_allergens:
        names = ", ".join(i.food.name for i in plan.flagged_unknown_allergens if i.food)
        lines.append(f"Unknown allergen data (confirm with staff): {names}")
    return "\n".join(lines)


def cmd_plan(args: argparse.Namespace) -> int:
    config = load_config()
    if not config.dining_halls:
        print("No dining halls configured -- see config.example.toml", file=sys.stderr)
        return 1
    meal_period, plan = _build_today_plan(config, args.meal)
    print(_format_plan(meal_period, plan))
    return 0


def cmd_notify(args: argparse.Namespace) -> int:
    config = load_config()
    if not config.dining_halls:
        print("No dining halls configured -- see config.example.toml", file=sys.stderr)
        return 1
    meal_period, plan = _build_today_plan(config, args.meal)
    message = _format_plan(meal_period, plan)

    notifier = NtfyNotifier(topic=config.ntfy_topic) if config.ntfy_topic else ConsoleNotifier()
    notifier.send(title=f"Dining hall plan: {meal_period}", message=message)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="menu", description="ND dining hall menu tool")
    sub = parser.add_subparsers(dest="command", required=True)

    for name, func in (("fetch", cmd_fetch), ("plan", cmd_plan), ("notify", cmd_notify)):
        p = sub.add_parser(name)
        p.add_argument("--meal", help="Meal period key from config.toml (e.g. lunch, dinner)")
        p.set_defaults(func=func)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
