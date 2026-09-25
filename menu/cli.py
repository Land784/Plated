"""Command-line entry point: uv run python -m menu <command>"""

from __future__ import annotations

import argparse
import sys
import tomllib
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from menu import client, supabase_users
from menu.allergens import UnknownAllergenPolicy
from menu.config import PlatedConfig, load_config
from menu.digest import build_hall_section, build_protein_section
from menu.models import DayMenu, MenuItem
from menu.notifier import ConsoleNotifier, NtfyNotifier
from menu.planner import MealPlan, build_meal_plan
from menu.schedule import due_meals
from menu.users import DEFAULT_TIMEZONE, UserConfig, load_users


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


def _build_today_plans(config: PlatedConfig, meal: str | None) -> tuple[str, dict[str, MealPlan]]:
    """One plan per hall. Halls are never pooled: a meal is eaten at one."""
    meal_period, menu_type = _meal_period_and_type(config, meal)
    d = date.today()
    days = _fetch_all_halls(config, menu_type, d)

    plans = {
        hall_name: build_meal_plan(
            _visible_items(day),
            excluded_allergens=set(config.excluded_allergens),
            protein_target_g=config.protein_target_g,
            calorie_cap=config.calorie_cap,
            unknown_policy=UnknownAllergenPolicy(config.unknown_allergen_policy),
        )
        for hall_name, day in days.items()
    }
    return meal_period, plans


def _format_plan(hall_name: str, plan: MealPlan) -> str:
    lines = [f"{hall_name}:"]
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


def _format_plans(meal_period: str, plans: dict[str, MealPlan]) -> str:
    body = "\n\n".join(_format_plan(hall, plan) for hall, plan in plans.items())
    return f"Meal plan ({meal_period}):\n{body}"


def cmd_plan(args: argparse.Namespace) -> int:
    config = load_config()
    if not config.dining_halls:
        print("No dining halls configured -- see config.example.toml", file=sys.stderr)
        return 1
    meal_period, plans = _build_today_plans(config, args.meal)
    print(_format_plans(meal_period, plans))
    return 0


def cmd_notify(args: argparse.Namespace) -> int:
    config = load_config()
    if not config.dining_halls:
        print("No dining halls configured -- see config.example.toml", file=sys.stderr)
        return 1
    meal_period, plans = _build_today_plans(config, args.meal)
    message = _format_plans(meal_period, plans)

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


def _load_subscribers(args: argparse.Namespace) -> list[UserConfig]:
    if args.supabase:
        url, key = supabase_users.credentials_from_env()
        return supabase_users.load_users_from_supabase(url, key)
    return load_users(Path(args.users))


def _build_message(user: UserConfig, meal: str, local_date: date) -> list[str]:
    """Protein picks (if configured) followed by each hall's stations.

    Returns [] when no hall has station content. Picks alone never make a
    message: they come from the same stations, so an empty station list
    means no menu was published.
    """
    halls = [(_hall_label(hall), client.fetch_day(hall, meal, local_date)) for hall in user.halls]
    cap = user.max_items_per_station
    station_blocks = [
        section
        for hall_name, day in halls
        if (section := build_hall_section(hall_name, day, user.stations, cap))
    ]
    if not station_blocks:
        return []

    blocks = station_blocks
    if user.protein is not None:
        picks = build_protein_section(halls, user.stations, user.protein)
        if picks:
            blocks = [picks, *station_blocks]

    lines: list[str] = []
    for block in blocks:
        if lines:
            lines.append("")
        lines.extend(block)
    return lines


def cmd_dispatch(args: argparse.Namespace) -> int:
    """Send each subscriber the menus due in this run's time slot."""
    users = _load_subscribers(args)
    now_utc = _resolve_now(args.now, args.tz)

    sent = 0
    problems: list[str] = []

    for user in users:
        for due in due_meals(user, now_utc, args.interval):
            label = f"{user.name}/{due.meal} on {due.local_date.isoformat()}"
            try:
                sections = _build_message(user, due.meal, due.local_date)
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


def cmd_subscribers_push(args: argparse.Namespace) -> int:
    """Validate subscriber TOML files and upsert them into Supabase."""
    url, key = supabase_users.credentials_from_env()
    for raw_path in args.files:
        path = Path(raw_path)
        with path.open("rb") as handle:
            data = tomllib.load(handle)
        user = supabase_users.upsert_subscriber(url, key, data, source=path.name)
        print(f"saved {user.name} ({path.name})")
    return 0


def cmd_subscribers_list(args: argparse.Namespace) -> int:
    """List active Supabase subscribers. Topics are never printed."""
    url, key = supabase_users.credentials_from_env()
    users = supabase_users.load_users_from_supabase(url, key)
    for user in users:
        meals = sum(len(m) for m in user.schedule.values())
        protein = f"{user.protein.target_g:g}g protein" if user.protein else "no protein picks"
        print(
            f"{user.name}: {len(user.stations)} stations, {meals} scheduled meals/week, {protein}"
        )
    print(f"{len(users)} active subscriber(s)", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="menu", description="ND dining hall menu tool")
    sub = parser.add_subparsers(dest="command", required=True)

    for name, func in (("fetch", cmd_fetch), ("plan", cmd_plan), ("notify", cmd_notify)):
        p = sub.add_parser(name)
        p.add_argument("--meal", help="Meal period key from config.toml (e.g. lunch, dinner)")
        p.set_defaults(func=func)

    d = sub.add_parser("dispatch", help="Send due menu digests to all subscribers")
    source = d.add_mutually_exclusive_group()
    source.add_argument("--users", default="users", help="Directory of subscriber *.toml files")
    source.add_argument(
        "--supabase",
        action="store_true",
        help="Load subscribers from Supabase (needs SUPABASE_URL and SUPABASE_SECRET_KEY)",
    )
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

    subs = sub.add_parser("subscribers", help="Manage subscribers stored in Supabase")
    subs_sub = subs.add_subparsers(dest="subscribers_command", required=True)
    push = subs_sub.add_parser("push", help="Validate TOML files and upsert them")
    push.add_argument("files", nargs="+", help="Subscriber *.toml files")
    push.set_defaults(func=cmd_subscribers_push)
    lst = subs_sub.add_parser("list", help="List active subscribers (topics hidden)")
    lst.set_defaults(func=cmd_subscribers_list)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
