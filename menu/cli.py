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
from menu.digest import build_hall_section, build_picks_section
from menu.macros import Goal, describe_goal
from menu.models import DayMenu, MenuItem
from menu.notifier import ConsoleNotifier, NtfyNotifier
from menu.schedule import DEFAULT_WINDOW_MINUTES, due_meals
from menu.users import DEFAULT_TIMEZONE, MacrosConfig, PicksConfig, UserConfig, load_users


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


def _build_today_picks(config: PlatedConfig, meal: str | None) -> tuple[str, list[str]]:
    """Picks for config.toml's single user, from every station of each hall.

    config.toml predates subscriber files, so its protein target and
    calorie cap are translated into [macros] goals here.
    """
    meal_period, menu_type = _meal_period_and_type(config, meal)
    days = _fetch_all_halls(config, menu_type, date.today())

    goals = {"protein": Goal(target=config.protein_target_g)}
    if config.calorie_cap is not None:
        goals["calories"] = Goal(max=config.calorie_cap)
    picks = PicksConfig(
        exclude_allergens=list(config.excluded_allergens),
        unknown_allergens=UnknownAllergenPolicy(config.unknown_allergen_policy),
    )
    lines = build_picks_section(
        list(days.items()), None, MacrosConfig(goals=goals), picks, meal_period
    )
    return meal_period, lines or ["No items met the goals."]


def _format_plans(meal_period: str, lines: list[str]) -> str:
    return f"Meal plan ({meal_period}):\n" + "\n".join(lines)


def cmd_plan(args: argparse.Namespace) -> int:
    config = load_config()
    if not config.dining_halls:
        print("No dining halls configured -- see config.example.toml", file=sys.stderr)
        return 1
    meal_period, lines = _build_today_picks(config, args.meal)
    print(_format_plans(meal_period, lines))
    return 0


def cmd_notify(args: argparse.Namespace) -> int:
    config = load_config()
    if not config.dining_halls:
        print("No dining halls configured -- see config.example.toml", file=sys.stderr)
        return 1
    meal_period, lines = _build_today_picks(config, args.meal)
    message = _format_plans(meal_period, lines)

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


def _build_message(user: UserConfig, meal: str, local_date: date) -> list[str]:
    """Meal picks (if configured) followed by each hall's stations.

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
    if user.macros is not None:
        picks = build_picks_section(halls, user.stations, user.macros, user.picks, meal)
        if picks:
            blocks = [picks, *station_blocks]

    lines: list[str] = []
    for block in blocks:
        if lines:
            lines.append("")
        lines.extend(block)
    return lines


def cmd_dispatch(args: argparse.Namespace) -> int:
    """Send each subscriber any meal that came due within the window.

    With --supabase and a real send, each meal is claimed in the
    sent_meals table before sending, so the several runs that can see
    the same meal (see menu/schedule.py) deliver it once.
    """
    credentials = supabase_users.credentials_from_env() if args.supabase else None
    users = (
        supabase_users.load_users_from_supabase(*credentials)
        if credentials
        else load_users(Path(args.users))
    )
    now_utc = _resolve_now(args.now, args.tz)
    claiming = credentials is not None and not args.dry_run

    sent = 0
    problems: list[str] = []

    for user in users:
        for due in due_meals(user, now_utc, args.window):
            label = f"{user.name}/{due.meal} on {due.local_date.isoformat()}"
            claim = (user.id, due.meal, due.local_date)
            if claiming:
                try:
                    if not supabase_users.claim_send(*credentials, *claim):
                        continue  # an earlier run already sent it
                except Exception as exc:  # noqa: BLE001 - one user must not break the rest
                    problems.append(f"{label}: could not record the send: {exc}")
                    continue

            try:
                sections = _build_message(user, due.meal, due.local_date)
            except Exception as exc:  # noqa: BLE001
                problems.append(f"{label}: fetch failed: {exc}")
                _release(credentials, claim, claiming, problems, label)
                continue

            if not sections:
                # The claim stays: an unpublished menu won't appear on a
                # retry, and reporting it once per meal is enough.
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
                _release(credentials, claim, claiming, problems, label)

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


def _release(credentials, claim, claiming: bool, problems: list[str], label: str) -> None:
    """Free a claim after a failure so the next run inside the window retries."""
    if not claiming:
        return
    try:
        supabase_users.release_send(*credentials, *claim)
    except Exception as exc:  # noqa: BLE001
        problems.append(f"{label}: could not release the claim, so it won't retry: {exc}")


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
        goals = (
            ", ".join(describe_goal(n, g) for n, g in user.macros.goals.items())
            if user.macros
            else "no picks"
        )
        if user.macros and user.macros.meals:
            goals += f" (+ overrides for {', '.join(user.macros.meals)})"
        print(f"{user.name}: {len(user.stations)} stations, {meals} scheduled meals/week, {goals}")
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
        "--window",
        "--interval",  # the pre-2026-09-25 slot flag, kept so old workflows still run
        dest="window",
        type=int,
        default=DEFAULT_WINDOW_MINUTES,
        help="Send meals whose time passed within this many minutes",
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
