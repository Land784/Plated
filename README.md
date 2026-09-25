# Plated

Pushes the Notre Dame dining hall menus to your phone, at the times you
actually eat, filtered down to the stations you care about, led by a
combo from each hall built for your own macro goals.

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

One TOML file per person, loaded from a `users/` directory. Copy the
commented template to get started:

```bash
cp users.example.toml users/wes.toml
```

It documents the full format: ntfy topic, timezone, halls, station
allowlist, per-station cap, and per-weekday send times.

The template lives *outside* `users/` on purpose. `dispatch` notifies
every file in that directory, so a placeholder left sitting there would
push real notifications to a guessable public topic. `users/` itself is
gitignored in this repo.

Station matching ignores case and a leading "The", so `Global Compass`
also matches North's spelling, `The Global Compass`.

Meal keys are Nutrislice `menu_type` slugs. The confirmed set is
`breakfast`, `lunch`, `late-lunch`, `dinner`, `brunch` and `special`.
Only the weekdays you list get notifications, so omitting a meal is how
you handle days a hall doesn't serve it. Sundays serve brunch, not lunch.

## Meal picks

A subscriber with a `[macros]` table gets one combo per hall at the top
of each notification, built for their own nutrient goals:

```toml
[macros]
protein = { target = 70 }   # within 15%, or set tolerance = 10
carbs   = { max = 60 }
fiber   = { min = 8 }

[macros.brunch]             # per-meal override, merged per nutrient
protein = { target = 50 }
```

Goals can be set on protein, carbs, fat, calories, fiber, sugar and
sodium: every item at the tracked stations reports all seven. Each goal
is any mix of `target`, `min` and `max`, and at least one target or min
is required, since limits alone are met by eating nothing.

```
PICKS: protein 60-80g
North Dining Hall: 78P 12C 16F · 513 cal
  2× Garden Herb Grilled Chicken
     21P 0C 0F · 89 cal (1 tender) · allergens unknown
  Pork Tenderloin Agrodolce
     36P 12C 16F · 335 cal (6 oz portion) · Dairy, Fish, Soy
```

Items come only from the subscriber's stations, and each hall is
planned on its own, since nobody eats at both in one meal. The planner
searches every combo of up to 4 servings, with at most 2 of any item,
and of those meeting every goal picks the one supplying the most of
what was asked for per calorie; for a lone protein goal, protein per
calorie. If nothing meets every goal, the closest combo is shown with a
line naming what it misses.

Ranking by fewest calories was tried first and rejected: it always
landed at the bottom of a target's range, choosing 62g protein for 507
cal over 78g for 513.

Three per-item rules keep the search honest against the real data, set
in the optional `[picks]` table:

- **Missing values are never guessed.** An item that doesn't report a
  nutrient you have a goal on isn't ranked. A reported 0 is used as 0.
- **A protein floor** (default 15g), applied when you have a protein
  goal. Pure protein-per-calorie ranking once made a single lettuce
  leaf the top pick for a 40g target.
- **A calorie ceiling** (default 1200). Some rows are whole recipes
  listed as one serving: a 2473 cal "Cheese Pizza", serving "1 pizza".
  The serving unit can't tell them apart, so calories are the only
  signal. These rows are skipped, never corrected.

Numbers are one serving exactly as listed (`4 z` and all), because
nutrients are only comparable per listed serving. Tags that are dietary
labels rather than allergens ("Vegan", "High Performance") are hidden,
and an item with no allergen tags reads "allergens unknown", never safe.

## Subscribers in Supabase

In production, subscribers live in a Supabase table rather than files,
so onboarding someone doesn't mean committing to a repo, and a future
signup form has somewhere to write. The schema is in
`supabase/migrations/`; its columns are the subscriber-file keys, and
rows go through the same validation as a TOML file.

`ntfy_topic` works like a password, so the table has row level security
on and no policies: only the secret key can read it. Keep that key in
`.env` locally (gitignored) and in the runner repo's secrets.

```bash
# .env: SUPABASE_URL=https://<ref>.supabase.co, SUPABASE_SECRET_KEY=sb_secret_...

# Add or update someone: the file is validated, then upserted by topic
uv run --env-file .env python -m menu subscribers push users/wes.toml

# Who's subscribed (topics are never printed)
uv run --env-file .env python -m menu subscribers list

# Render what Supabase subscribers would get, without sending
uv run --env-file .env python -m menu dispatch --supabase --dry-run --now 2026-09-24T17:30
```

Pushing writes every column from the validated file, so a key deleted
from the file is cleared in the database too. `dispatch --users` still
works for local testing.

## Deployment: two repos

This repo is public and holds code only. A **separate private repo**
holds real subscriber files and runs the cron.

An ntfy topic is open pub/sub: anyone who knows the name can both read a
subscriber's notifications and publish fake ones to their phone. Topics
therefore never appear in this repo.

```
Plated (public, this repo)        plated-runner (private)
  menu/                             .github/workflows/notify.yml
  users.example.toml                secrets: SUPABASE_URL,
  supabase/migrations/                       SUPABASE_SECRET_KEY
  tests/
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
      - run: uv run python -m menu dispatch --supabase --interval 30
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SECRET_KEY: ${{ secrets.SUPABASE_SECRET_KEY }}
```

Scheduled GitHub runs are regularly delayed several minutes, so each run
owns a time slot rather than an exact minute: it floors its own clock to
`--interval` and sends any meal falling inside that slot. A run delayed
by less than one interval still lands in the right slot. GitHub's rule
that disables scheduled workflows after 60 days without repo activity
applies only to public repositories, so it can't stop the cron in the
private runner.

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

Menu history, watchlist alerts, and a signup frontend. History belongs
in Supabase too: GitHub Actions runners start with an empty disk every
run, so the SQLite history in `menu/db.py` could never persist there.

## Roadmap

1. Fetch and print one day's menu with protein and allergen info for each item
2. Pydantic models and fixture-based tests
3. Allergen filtering and protein ranking
4. Meal planner
5. ntfy notifications and a GitHub Actions daily run
6. SQLite history and simple stats (e.g., which days have the best high-protein options)
7. (Stretch) multi-user subscriptions via a Discord bot or small web UI
