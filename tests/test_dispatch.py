from datetime import date, datetime
from zoneinfo import ZoneInfo

from menu import cli
from menu.config import DiningHallConfig, PlatedConfig
from menu.models import DayMenu
from menu.notifier import DISCLAIMER, SEPARATOR
from menu.users import parse_user

MENU = DayMenu.model_validate(
    {
        "date": "2026-09-24",
        "menu_items": [
            {"is_station_header": True, "text": "Grill", "station_id": 1},
            {
                "station_id": 1,
                "food": {
                    "name": "Grilled Chicken",
                    "rounded_nutrition_info": {
                        "g_protein": 40,
                        "calories": 300,
                        "g_carbs": 0,
                        "g_fat": 5,
                    },
                },
            },
        ],
    }
)

USER = {
    "name": "Wes",
    "ntfy_topic": "topic-abc",
    "halls": ["north-dining-hall"],
    "stations": ["Grill"],
}


def _serve(monkeypatch, day: DayMenu | None) -> None:
    monkeypatch.setattr(cli.client, "fetch_day", lambda hall, meal, d: day)


def test_picks_follow_the_glance(monkeypatch):
    _serve(monkeypatch, MENU)
    user = parse_user({**USER, "macros": {"protein": {"target": 40}}}, "test")

    lines = cli._build_message(user, "dinner", date(2026, 9, 24))

    assert lines == [
        "North: Grilled Chicken",
        "",
        "PICKS · North · 40P 0C 5F · 300 cal",
        "Grilled Chicken · 40P · 300 cal",
        "",
        SEPARATOR,
        "NORTH FULL MENU",
        "• Grill: Grilled Chicken",
    ]


def test_subscriber_without_macros_gets_the_plain_digest(monkeypatch):
    _serve(monkeypatch, MENU)
    user = parse_user(USER, "test")

    lines = cli._build_message(user, "dinner", date(2026, 9, 24))

    assert lines == [
        "North: Grilled Chicken",
        "",
        SEPARATOR,
        "NORTH FULL MENU",
        "• Grill: Grilled Chicken",
    ]


def test_no_published_menu_means_no_message(monkeypatch):
    _serve(monkeypatch, None)
    user = parse_user({**USER, "macros": {"protein": {"target": 40}}}, "test")

    assert cli._build_message(user, "dinner", date(2026, 9, 24)) == []


class _Recorder:
    """Stands in for Supabase claims and ntfy sends during a dispatch."""

    def __init__(
        self,
        monkeypatch,
        *,
        claimed=True,
        send_fails=False,
        menu=MENU,
        menus_stored=True,
        store_problems=(),
    ):
        self.claims: list[tuple] = []
        self.releases: list[tuple] = []
        self.sent: list[dict] = []
        self.stored: list[date] = []
        user = parse_user(
            {**USER, "id": "3f1c", "schedule": {"friday": {"lunch": "11:15"}}}, "test"
        )
        monkeypatch.setattr(cli.supabase_users, "credentials_from_env", lambda: ("url", "key"))
        monkeypatch.setattr(cli.supabase_users, "load_users_from_supabase", lambda u, k: [user])

        def claim(url, key, *key_parts):
            self.claims.append(key_parts)
            return claimed

        monkeypatch.setattr(cli.supabase_users, "claim_send", claim)
        monkeypatch.setattr(
            cli.supabase_users, "release_send", lambda url, key, *k: self.releases.append(k)
        )
        _serve(monkeypatch, menu)

        def send(notifier, title, message, **headers):
            if send_fails:
                raise RuntimeError("ntfy down")
            self.sent.append({"title": title, **headers})

        monkeypatch.setattr(cli.NtfyNotifier, "send", send)

        def has_menus_for(url, key, d):
            if isinstance(menus_stored, Exception):
                raise menus_stored
            return menus_stored

        def store_day(url, key, d, *, now):
            # Sends come first, so a slow Nutrislice can't delay them.
            self.stored.append((d, len(self.sent)))
            return list(store_problems)

        monkeypatch.setattr(cli.menus_store, "has_menus_for", has_menus_for)
        monkeypatch.setattr(cli.menus_store, "store_day", store_day)

    def run(self, now="2026-09-25T11:40") -> int:
        return cli.main(["dispatch", "--supabase", "--now", now])


def test_a_claimed_meal_is_sent_once(monkeypatch):
    rec = _Recorder(monkeypatch)
    assert rec.run() == 0
    assert rec.claims == [("3f1c", "lunch", date(2026, 9, 25))]
    assert rec.sent == [
        {
            "title": "Lunch · Fri Sep 25",
            "tags": ["sandwich"],
            "link": "https://nd.nutrislice.com/menu/north-dining-hall/",
        }
    ]


def test_a_meal_already_claimed_by_an_earlier_run_is_skipped(monkeypatch):
    rec = _Recorder(monkeypatch, claimed=False)
    assert rec.run() == 0
    assert rec.sent == []


def test_a_failed_send_releases_the_claim_for_a_retry(monkeypatch):
    rec = _Recorder(monkeypatch, send_fails=True)
    assert rec.run() == 1
    assert rec.releases == [("3f1c", "lunch", date(2026, 9, 25))]


def test_no_published_menu_keeps_the_claim_so_it_is_reported_once(monkeypatch):
    rec = _Recorder(monkeypatch, menu=None)
    assert rec.run() == 1
    assert rec.releases == []


def test_dry_run_never_claims(monkeypatch):
    rec = _Recorder(monkeypatch)
    assert cli.main(["dispatch", "--supabase", "--dry-run", "--now", "2026-09-25T11:40"]) == 0
    assert rec.claims == []


def test_a_meal_past_the_window_is_not_sent(monkeypatch):
    rec = _Recorder(monkeypatch)
    assert rec.run(now="2026-09-25T12:30") == 0
    assert rec.claims == []


def test_the_first_run_after_5am_stores_todays_menus_after_sending(monkeypatch):
    rec = _Recorder(monkeypatch, menus_stored=False)
    assert rec.run() == 0
    assert rec.stored == [(date(2026, 9, 25), 1)]


def test_menus_already_stored_today_are_not_stored_again(monkeypatch):
    rec = _Recorder(monkeypatch, menus_stored=True)
    assert rec.run() == 0
    assert rec.stored == []


def test_menus_are_not_stored_before_5am_eastern(monkeypatch):
    rec = _Recorder(monkeypatch, menus_stored=False)
    assert rec.run(now="2026-09-25T04:59") == 0
    assert rec.stored == []
    assert rec.run(now="2026-09-25T05:00") == 0
    assert rec.stored == [(date(2026, 9, 25), 0)]


def test_a_dry_run_never_stores_menus(monkeypatch):
    rec = _Recorder(monkeypatch, menus_stored=False)
    assert cli.main(["dispatch", "--supabase", "--dry-run", "--now", "2026-09-25T11:40"]) == 0
    assert rec.stored == []


def test_store_problems_fail_the_run_but_never_block_sends(monkeypatch, capsys):
    rec = _Recorder(monkeypatch, menus_stored=False, store_problems=["menus store: boom"])
    assert rec.run() == 1
    assert len(rec.sent) == 1
    assert "dispatch: menus store: boom" in capsys.readouterr().err


def test_a_failed_menus_check_is_reported_and_sends_still_go(monkeypatch, capsys):
    rec = _Recorder(monkeypatch, menus_stored=RuntimeError("supabase down"))
    assert rec.run() == 1
    assert len(rec.sent) == 1
    assert rec.stored == []
    assert "dispatch: menus store: supabase down" in capsys.readouterr().err


def _store_command(monkeypatch, problems=()):
    calls = []
    monkeypatch.setattr(cli.supabase_users, "credentials_from_env", lambda: ("url", "key"))

    def store_day(url, key, d, *, now):
        calls.append(d)
        return list(problems)

    monkeypatch.setattr(cli.menus_store, "store_day", store_day)
    return calls


def test_menus_store_command_stores_the_given_date(monkeypatch):
    calls = _store_command(monkeypatch)
    assert cli.main(["menus", "store", "--date", "2026-09-24"]) == 0
    assert calls == [date(2026, 9, 24)]


def test_menus_store_command_defaults_to_today_in_eastern_time(monkeypatch):
    calls = _store_command(monkeypatch)
    assert cli.main(["menus", "store"]) == 0
    assert calls == [datetime.now(ZoneInfo("America/New_York")).date()]


def test_menus_store_command_fails_on_problems(monkeypatch, capsys):
    _store_command(monkeypatch, problems=["menus store: boom"])
    assert cli.main(["menus", "store", "--date", "2026-09-24"]) == 1
    assert "menus store: boom" in capsys.readouterr().err


def _dev_config(monkeypatch) -> None:
    """config.toml for the plan/notify dev commands, without a topic so nothing is sent."""
    config = PlatedConfig(
        dining_halls=[DiningHallConfig(slug="north-dining-hall", name="North Dining Hall")],
        meal_types={"dinner": "dinner"},
    )
    monkeypatch.setattr(cli, "load_config", lambda: config)
    _serve(monkeypatch, MENU)


def test_plan_command_prints_the_picks_block(monkeypatch, capsys):
    _dev_config(monkeypatch)
    assert cli.main(["plan", "--meal", "dinner"]) == 0
    assert capsys.readouterr().out == (
        "Meal plan (dinner):\n"
        "PICKS · North Dining Hall · 40P 0C 5F · 300 cal\n"
        "Grilled Chicken · 40P · 300 cal\n"
    )


def test_notify_command_without_a_topic_prints_to_the_console(monkeypatch, capsys):
    _dev_config(monkeypatch)
    assert cli.main(["notify", "--meal", "dinner"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("=== Dinner · ")
    assert "\ntags: plate_with_cutlery\n" in out
    assert out.endswith(f"\n\n{SEPARATOR}\n{DISCLAIMER}\n")
