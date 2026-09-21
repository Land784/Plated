"""Command-line entry point: uv run python -m menu <fetch|plan|notify>"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from menu import client
from menu.allergens import UnknownAllergenPolicy
from menu.config import PlatedConfig, load_config
from menu.digest import build_hall_section
from menu.models import DayMenu, MenuItem
from menu.notifier import ConsoleNotifier, NtfyNotifier
from menu.planner import MealPlan, build_meal_plan
from menu.schedule import due_meals
from menu.users import DEFAULT_TIMEZONE, load_users


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


def _hall_label(slug: str) -> str:
    """ "north-dining-hall" -> "North Dining Hall"."""
    return slug.replace("-", " ").title()


def _resolve_now(raw: str | None, tz_name: str) -> datetime:
    """Resolve --now into an aware UTC datetime.

    A naive value is interpreted as wall-clock time in ``tz_name`` so that
    `--now 2026-09-21T11:15` triggers an 11:15 local meal, which is what
    you want when testing a schedule.
    """
    if raw is None:
        return datetime.now(UTC)
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(tz_name))
    return parsed.astimezone(UTC)


def cmd_dispatch(args: argparse.Namespace) -> int:
    """Send each subscriber the menus due in this run's time slot."""
    users = load_users(Path(args.users))
    now_utc = _resolve_now(args.now, args.tz)

    sent = 0
    problems: list[str] = []

    for user in users:
        for due in due_meals(user, now_utc, args.interval):
            label = f"{user.name}/{due.meal} on {due.local_date.isoformat()}"
            try:
                sections: list[str] = []
                for hall in user.halls:
                    day = client.fetch_day(hall, due.meal, due.local_date)
                    section = build_hall_section(
                        _hall_label(hall), day, user.stations, user.max_items_per_station
                    )
                    if section:
                        if sections:
                            sections.append("")
                        sections.extend(section)
            except Exception as exc:  # noqa: BLE001 - one user must not break the rest
                problems.append(f"{label}: fetch failed: {exc}")
                continue

            if not sections:
                detail = "no stations configured" if not user.stations else "no menu published"
                problems.append(f"{label}: nothing to send ({detail})")
                continue

            title = f"{due.meal.replace('-', ' ').title()} - {due.local_date:%a %b %d}"
            notifier = ConsoleNotifier() if args.dry_run else NtfyNotifier(topic=user.ntfy_topic)
            try:
                notifier.send(title=title, message="\n".join(sections))
                sent += 1
            except Exception as exc:  # noqa: BLE001
                problems.append(f"{label}: send failed: {exc}")

    print(f"dispatch: {sent} notification(s) sent", file=sys.stderr)

    # Everything deliverable has now been delivered. Only after that do we
    # fail the run, so a single empty meal cannot suppress other people's
    # notifications. A non-zero exit is what surfaces problems to the repo
    # owner via GitHub's failed-run email, while subscribers stay silent.
    if problems:
        for problem in problems:
            print(f"dispatch: {problem}", file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="menu", description="ND dining hall menu tool")
    sub = parser.add_subparsers(dest="command", required=True)

    for name, func in (("fetch", cmd_fetch), ("plan", cmd_plan), ("notify", cmd_notify)):
        p = sub.add_parser(name)
        p.add_argument("--meal", help="Meal period key from config.toml (e.g. lunch, dinner)")
        p.set_defaults(func=func)

    d = sub.add_parser("dispatch", help="Send due menu digests to all subscribers")
    d.add_argument("--users", default="users", help="Directory of subscriber *.toml files")
    d.add_argument(
        "--interval",
        type=int,
        default=30,
        help="Polling interval in minutes; must match the cron schedule",
    )
    d.add_argument("--now", help="Override the clock (ISO 8601), for testing")
    d.add_argument(
        "--tz",
        default=DEFAULT_TIMEZONE,
        help="Timezone used to interpret a naive --now",
    )
    d.add_argument("--dry-run", action="store_true", help="Print to console instead of sending")
    d.set_defaults(func=cmd_dispatch)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
