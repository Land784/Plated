from datetime import date

from menu import cli
from menu.models import DayMenu
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


def test_picks_lead_the_message(monkeypatch):
    _serve(monkeypatch, MENU)
    user = parse_user({**USER, "macros": {"protein": {"target": 40}}}, "test")

    lines = cli._build_message(user, "dinner", date(2026, 9, 24))

    assert lines == [
        "PICKS: protein 34-46g",
        "North Dining Hall: 40P 0C 5F · 300 cal",
        "  Grilled Chicken",
        "     40P 0C 5F · 300 cal · allergens unknown",
        "",
        "NORTH DINING HALL",
        "Grill",
        "  Grilled Chicken",
    ]


def test_subscriber_without_macros_gets_the_plain_digest(monkeypatch):
    _serve(monkeypatch, MENU)
    user = parse_user(USER, "test")

    lines = cli._build_message(user, "dinner", date(2026, 9, 24))

    assert lines == ["NORTH DINING HALL", "Grill", "  Grilled Chicken"]


def test_no_published_menu_means_no_message(monkeypatch):
    _serve(monkeypatch, None)
    user = parse_user({**USER, "macros": {"protein": {"target": 40}}}, "test")

    assert cli._build_message(user, "dinner", date(2026, 9, 24)) == []


class _Recorder:
    """Stands in for Supabase claims and ntfy sends during a dispatch."""

    def __init__(self, monkeypatch, *, claimed=True, send_fails=False, menu=MENU):
        self.claims: list[tuple] = []
        self.releases: list[tuple] = []
        self.sent: list[str] = []
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

        def send(notifier, title, message):
            if send_fails:
                raise RuntimeError("ntfy down")
            self.sent.append(title)

        monkeypatch.setattr(cli.NtfyNotifier, "send", send)

    def run(self, now="2026-09-25T11:40") -> int:
        return cli.main(["dispatch", "--supabase", "--now", now])


def test_a_claimed_meal_is_sent_once(monkeypatch):
    rec = _Recorder(monkeypatch)
    assert rec.run() == 0
    assert rec.claims == [("3f1c", "lunch", date(2026, 9, 25))]
    assert rec.sent == ["Lunch - Fri Sep 25"]


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
