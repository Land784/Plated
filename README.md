# Plated

Pushes the Notre Dame dining hall menus to your phone, at the times you
actually eat, filtered down to the stations you care about.

Menus come from Nutrislice's unofficial JSON API. Notifications go out
over [ntfy.sh](https://ntfy.sh).

## What a notification looks like

```
Lunch - Mon Sep 21

NORTH DINING HALL
Domer Diner
  Smash Burger
  Garden Herb Grilled Chicken
  Hand Breaded Chicken Tenders
La Mesa
  Steak Pepito
  Tortilla Chips
The Global Compass
  Butter Chicken

SOUTH DINING HALL
Crust & Co
  Prosciutto Pizza
  Cheese Pizza
Athenian Rice Bowl
  Mini Pita Chips
  Jerusalem Garbanzo
  +11 more
```

One meal serves 175 items across 40 stations, most of them condiments,
drinks and toppings, so each subscriber declares an allowlist of the
stations they actually visit. Build-your-own stations list individual
ingredients rather than dishes, so items are capped per station and the
remainder collapses into `+N more`.

## Quick start

```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format .

# Print today's menu / build a protein-focused plan (local dev commands)
cp config.example.toml config.toml
uv run python -m menu fetch
uv run python -m menu plan

# Render what would be sent, without sending anything
uv run python -m menu dispatch --users ./users --dry-run --now 2026-09-21T11:15
```

`--now` accepts a naive local time and `--dry-run` prints to the console
instead of pushing, which together let you test a schedule without
waiting for the clock.

## Subscribers

One TOML file per person. See [`users/example.toml`](./users/example.toml)
for the fully commented format: ntfy topic, timezone, halls, station
allowlist, per-station cap, and per-weekday send times.

Station matching ignores case and a leading "The", so `Global Compass`
also matches North's spelling, `The Global Compass`.

Meal keys are Nutrislice `menu_type` slugs. The confirmed set is
`breakfast`, `lunch`, `late-lunch`, `dinner`, `brunch` and `special`.
Only the weekdays you list get notifications, so omitting a meal is how
you handle days a hall doesn't serve it. Sundays serve brunch, not lunch.

## Deployment: two repos

This repo is public and holds code only. A **separate private repo**
holds real subscriber files and runs the cron.

An ntfy topic is open pub/sub: anyone who knows the name can both read a
subscriber's notifications and publish fake ones to their phone. Topics
therefore never appear in this repo.

```
Plated (public, this repo)        plated-runner (private)
  menu/                             users/wes.toml
  users/example.toml                users/<friend>.toml
  tests/                            .github/workflows/notify.yml
```

The private repo installs this package straight from `main`, so changes
here reach subscribers on the next run with no release step. The
dependency points private -> public, and public repos are readable
anonymously, so no access token is needed in either direction.

Do not copy `menu/` into the private repo. It holds config and a
workflow, nothing else.

The private repo's workflow:

```yaml
name: Notify
on:
  schedule:
    - cron: "*/30 * * * *"   # must match --interval below
  workflow_dispatch: {}

jobs:
  notify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv venv
      - run: uv pip install git+https://github.com/Land784/Plated.git@main
      - run: uv run python -m menu dispatch --users ./users --interval 30
```

Scheduled GitHub runs are regularly delayed several minutes, so each run
owns a time slot rather than an exact minute: it floors its own clock to
`--interval` and sends any meal falling inside that slot. A run delayed
by less than one interval still lands in the right slot. Note also that
GitHub disables scheduled workflows after 60 days without repo activity.

When a scheduled meal has no published menu, subscribers get nothing and
the run exits non-zero, so GitHub emails the repo owner rather than
pushing a useless "nothing here" notification.

## Data source notes

Verified live on 2026-09-20:

- The API is at `nd.api.nutrislice.com`, **not** the `nd.nutrislice.com`
  host the site is served from. That host is a static S3/CloudFront app
  shell where every path returns the same `index.html`. See
  `menu/client.py` for how this was determined.
- Hall slugs are `north-dining-hall` and `south-dining-hall`.
- The two halls do **not** serve the same menu. On the same day their
  lunch menus shared only 90 of 323 items, about 28%, so both are
  fetched and rendered separately.

The API is unofficial and undocumented. Responses are cached by date,
requests use a descriptive user agent with timeouts and backoff, and the
test suite runs entirely against saved fixtures and never touches the
live API.

## Not yet built

Allergen filtering, nutrition in the digest, menu history, watchlist
alerts, and any web or Discord frontend. The allergen and planner
modules exist but are not wired into notifications.
