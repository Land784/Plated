# Plated

Pushes the Notre Dame dining hall menus to your phone, at the times you
actually eat, filtered down to the stations you care about, led by
each hall's best mains and a combo built for your own macro goals.

Menus come from Nutrislice's unofficial JSON API. Notifications go out
over [ntfy.sh](https://ntfy.sh). Invited subscribers set up and edit
their own notifications in a small [web app](#web-app).

## What a notification looks like

Real output for the 2026-09-24 dinner, a 70g protein target and 3 mains
per station:

```
Dinner · Thu Sep 24
North: Cantina Sandwich, Southwest Salad, Pork Tenderloin Agrodolce

South: Pork Tenderloin Agrodolce, Mushroom Florentine Pork Chops, Pepperoni & Cheese French Bread Pizza

PICKS · both halls · 78P 12C 16F · 513 cal
2× Garden Herb Grilled Chicken · 42P · 178 cal
Pork Tenderloin Agrodolce · 36P · 335 cal

──────────
NORTH FULL MENU
• Domer Diner: Cantina Sandwich, Smash Burger, Garden Herb Grilled Chicken
• La Mesa: Cochinita Pibil
• Mezze: Pork Tenderloin Agrodolce, Quinoa, Pork Osso Buco
• Crust & Co: Pepperoni Pizza, Elote Pizza, Cheese Pizza
• Green & Grains: Southwest Salad
• Comfort Kitchen: Fried Catfish, Dirty Rice
• The Global Compass: Beef Pad See Ew, Pork Potsticker

──────────
SOUTH FULL MENU
• Domer Diner: Garden Herb Grilled Chicken, Smash Beef Patty, Black Bean Veggie Burger
• La Mesa: Tacos Al Pastor
• Mezze: Pork Tenderloin Agrodolce
• Crust & Co: Pepperoni & Cheese French Bread Pizza, Meatball Pizza, Pepperoni Pizza
• Comfort Kitchen: Mushroom Florentine Pork Chops, Beef Au Poivre
• Global Compass: Beef Pad See Ew
• Pastaria: Halal Chicken & Beef Pepperoni, Elbow Macaroni, Penne Pasta
• Pasta Stir Fry: Pasta Stir-Fry Station

──────────
Full menu: https://nd.nutrislice.com/menu/north-dining-hall/
Data may be incomplete; confirm allergens with staff.
```

The push answers "what's good today", so the first lines carry it: a
lock screen shows the title and two to four lines. Then come the
[meal picks](#meal-picks), each hall's full menu (one bulleted line per
station, set off by a `──────────` separator), and a footer under the
last separator: a plain-text link to your preferred hall's Nutrislice
page, which the phone makes tappable, and the disclaimer, which ends
every push. Each glance line is its own paragraph, so the second hall
isn't buried under the first line's wrap.

One meal serves 175 items across 40 stations, most of them condiments,
drinks and toppings, so each subscriber declares an allowlist of the
stations they actually visit, and stations print in that order. Each
station line names only its **mains**:

- An item is a main if it reports at least `main_protein_g` of protein
  per listed serving (default 10), or its serving unit names a dish
  or a per-piece main (`1 taco`, `1 sandwich`, `1 potsticker`, `1 egg
  roll`). Tacos Al Pastor has 3g per taco but is still dinner. Weights
  (`4 oz portion`) and a bare `1 roll` (dinner rolls) don't count.
- Rows over the `[picks]` calorie ceiling are whole recipes (a 2473 cal
  "Cheese Pizza"), so they are skipped for display.
- Mains are listed highest protein first, up to `max_items_per_station`
  per line (default 3, in files, the database and the web app alike).
- A station with nothing qualifying, like a build-your-own pasta bar,
  lists its items highest protein first instead (up to the same cap,
  bulk rows included) rather than disappearing.
- The glance lines at the top are each hall's top 3 mains by protein,
  at most one per station.

This is a display rule only. It never changes what the planner may pick
or any reported value.

ntfy puts a meal emoji before the title (the `tags`). Tapping the push
itself opens nothing; the menu link is in the body. The body is kept
to 3,000 bytes: every iPhone push goes through ntfy's Firebase path,
which caps the serialized message at 4,000 bytes and cuts the end off
to fit. Over budget, station lines are dropped from the end and replaced
with `+N stations` under the hall's header; the glance, picks, link and
disclaimer are never cut. The sample above is about 1,400 bytes. There
is no Markdown: Android renders it, but iOS shows the asterisks.

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
allowlist, starred stations (`favorites`), mains per station
(`max_items_per_station`, default 3), the mains protein floor
(`main_protein_g`, default 10g), macro goals, and per-weekday send
times.

The template lives *outside* `users/` on purpose. `dispatch` notifies
every file in that directory, so a placeholder left sitting there would
push real notifications to a guessable public topic. `users/` itself is
gitignored in this repo.

Station matching ignores case and a leading "The", so `Global Compass`
also matches North's spelling, `The Global Compass`. Nothing else is
forgiven, so a name must be spelled the way Nutrislice publishes it:
the halls publish one station as "Homestyle 2", and an allowlist entry
of "Homestyle" never matches it. The `stations` view (see
[Stored menus](#stored-menus)) lists every name exactly as published.

`favorites` is the web app's list of starred stations. On its own it
reorders nothing: the push follows `stations`, and the web app writes
the favorites at the front of that list when it saves. In a file, list
your favorites first in `stations` too.

Your preferred hall is the first entry of `halls`: it leads the glance,
its full menu comes first, and the push's "Full menu:" link points to
its Nutrislice page.

Meal keys are Nutrislice `menu_type` slugs. The confirmed set is
`breakfast`, `lunch`, `late-lunch`, `dinner`, `brunch` and `special`.
Only the weekdays you list get notifications, so omitting a meal is how
you handle days a hall doesn't serve it. Sundays serve brunch, not lunch.

Breakfast is served at its own stations: North's "Sunrise Kitchen" and
"Bar, MYOO", South's "Breakfast" and "Omelets" (checked live
2026-10-06). One allowlist covers every meal, so if you schedule
breakfast, list those stations too; otherwise nothing is sent and the
run fails as if no menu were published.

## Meal picks

A subscriber with a `[macros]` table gets one combo per hall, right
after the glance lines, built for their own nutrient goals:

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
PICKS · both halls · 78P 12C 16F · 513 cal
2× Garden Herb Grilled Chicken · 42P · 178 cal
Pork Tenderloin Agrodolce · 36P · 335 cal
```

The header carries the combo's totals. Each line gives an item's
protein and calories for all its servings (`2×` doubles the reported
per-serving numbers; that is arithmetic, not an estimate). When both
halls land on the same combo, it prints once as `both halls`; otherwise each hall gets its own
`PICKS · North · ...` block. A combo that misses a goal ends with a
line such as `closest: protein 57g (want 60-80g)`.

Per-item carbs and fat, serving sizes and allergen names are not in the
push, to keep it short. The one exception: if you set
`exclude_allergens`, an item with no allergen data gets
` · allergens unknown`, since you asked to avoid something it can't be
checked for. The disclaimer covers everyone else.

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

The planner compares one serving exactly as listed (`4 z` and all),
because nutrients are only comparable per listed serving. Tags that are
dietary labels rather than allergens ("Vegan", "High Performance") are
not allergen data, so an item tagged only with them is unknown exactly
like an untagged one: never safe, and dropped under
`unknown_allergens = "exclude"`.

## Subscribers in Supabase

In production, subscribers live in a Supabase table rather than files,
so onboarding someone doesn't mean committing to a repo, and the web
app has somewhere to write. The schema is in `supabase/migrations/`;
its columns are the subscriber-file keys, and rows go through the same
validation as a TOML file.

`ntfy_topic` works like a password. The table has row level security
on, and its only policies let a signed-in web user read and update
their own row ([Web app](#web-app)); anonymous callers have no access
at all. The runner and the commands below use the secret key. Keep that
key in `.env` locally (gitignored) and in the runner repo's secrets.

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

A row linked to a web account (its `user_id` is set) belongs to that
person, who edits it in the app, so `push` refuses to overwrite it and
says which row it is. `--force` pushes anyway, undoing whatever they
last saved.

Each row is validated on its own. Now that people can save their own
rows, a bad one is possible despite the database's checks, so it is
skipped and reported rather than allowed to stop everyone else's
notifications, and the run then exits non-zero so GitHub emails the
owner. `subscribers list` reports bad rows the same way.

## Web app

`web/` is an invite-only site where a subscriber sets up and edits
their own notifications without a TOML file: where they eat, when, and
which stations (cards showing dishes each one served recently, with a
star for favorites), plus a pause switch, a live preview of their own
push for any meal this week, and ntfy phone setup with a "send a test"
button. There is no public sign-up and no macros section (picks are off
for everyone until the planner is rebuilt); admin stays in the CLI.
It's Next.js, Tailwind and shadcn/ui; [web/README.md](web/README.md)
covers its routes, local dev, and the Supabase dashboard settings it
needs.

The browser talks to Supabase directly, with the publishable key and
the person's session. Row level security and column grants let a
signed-in user select and update only their own `subscribers` row, and
update only `name`, `halls`, `stations`, `favorites`, `schedule` and
`active`. They can read `ntfy_topic` (the Connect page shows it) but
not change it: the database generates it, so nobody can point their row
at someone else's phone. Only `subscribers invite` creates rows. Check
constraints reject a malformed schedule, an unknown hall, a blank or
over-long name, and a duplicate name: `name` is unique and works as a
username.

### The preview

The preview has to match the real push exactly, so the renderer is
never ported to TypeScript. `web/api/preview.py` is a Vercel Python
function that installs this package from `main`
(`web/api/requirements.txt`) and calls the same functions `dispatch`
does (`menu/preview.py`). One renderer, at the cost of a preview that
lags `main` by one Vercel deploy.

`POST /api/preview` takes the unsaved form (halls, stations in order, a
meal and a date), reads that day's stored menus with the publishable
key, and answers with the push's title, tags, body and byte count, or
`{"sent": false, "reason": ...}` when there's nothing to send. It needs
no secret and no sign-in, and allows 30 requests a minute per IP per
function instance.

### Stored menus

The web app never calls Nutrislice; only the notify job does. So
`dispatch --supabase` also copies menus into Supabase, after the sends,
so a slow Nutrislice can never delay a notification:

- On the first real run after 05:00 Eastern each day (dry runs never
  store), it fetches the whole week containing today for both halls and
  every meal type that serves food: breakfast, brunch, lunch,
  late-lunch, dinner. Nutrislice's endpoint returns a week per request,
  so that's 10 requests a day, cached by the week's Sunday, and the
  preview can show the rest of the week.
- `menus` gets one row per (date, hall, meal): the day's items trimmed
  to the fields the models read, in menu order, values as reported
  (nulls, bulk rows and duplicates kept). About 25 KB a row instead of
  100 KB.
- `menu_stations` gets one row per station in each menu, with whether
  it's a food station (`NON_FOOD_STATIONS` in `menu/digest.py`) and the
  mains the push would list for it. The mains rule is Python, so it
  runs here and SQL only counts.
- `stations` is a view over the last 14 days of `menu_stations`, one
  row per station with spellings merged ("The Global Compass" and
  "Global Compass"): its most common published name, halls, meals, last
  seen, whether it's food, and its three most frequent mains as example
  dishes. It is the web app's station catalog.
- Rows older than 60 days are deleted in the same step.
- `menu_store_runs` is the success marker: one row per Eastern date
  whose store had no problems. A store with any problem records none,
  so the next run retries; the problem is reported and the run exits
  non-zero, but sends are never affected.

Menus are public information, so the three tables and the view are
readable by anyone; only the secret key writes them. To fill them by
hand, for example before the first invite:

```bash
uv run --env-file .env python -m menu menus store              # this week
uv run --env-file .env python -m menu menus store --date 2026-10-12
```

### Inviting someone

Public signups are off in Supabase, so an invite is the only way in:

```bash
# .env also needs PLATED_SITE_URL=https://<the Vercel site>
uv run --env-file .env python -m menu subscribers invite friend@nd.edu --name jdoe

# Give a subscriber who predates the web app an account for their row
uv run --env-file .env python -m menu subscribers invite wes@nd.edu --name wschmidt --link wschmidt
```

It checks what it can before anything is created (the name is free, or
with `--link` the named row exists and has no account yet; the station
catalog isn't empty), then creates the auth user with Supabase's admin
invite, which emails a sign-in link, and inserts their row with the web
app's defaults: both halls, North first; every food station in the
app's catalog order; lunch 12:00 and dinner 17:30 on weekdays, brunch
11:00 and dinner 17:30 at weekends; 3 mains per station; no picks. The
database generates the topic, and the command never prints it.

`--link` attaches the account to the existing row and changes nothing
else in it. From then on that person edits it on the web, and
`subscribers push` refuses to overwrite it. If the row can't be saved
after the invite has gone out, the command says which auth user to
delete before trying again.

### Rolling out schema changes

Merging to `main` is deploying: the runner installs from it, and so
does the preview on Vercel's next build. So a migration is applied to
the live database **before** the code that needs it is merged, never
after; each file in `supabase/migrations/` says in its header what it
must precede. Additive migrations are safe to apply early because the
code on `main` doesn't name the new columns yet.

## Deployment: three parts

This repo is public and holds code only, the web app included. A
**separate private repo** holds the Supabase secrets and runs the cron.
**Vercel** builds and hosts the web app and its preview function from
this repo's `web/` directory.

An ntfy topic is open pub/sub: anyone who knows the name can both read a
subscriber's notifications and publish fake ones to their phone. Topics
therefore never appear in this repo.

```
Plated (public, this repo)          plated-runner (private)          Vercel (root: web/)
  menu/                               .github/workflows/notify.yml     the Next.js app
  web/  (app + api/preview.py)        installs Plated from main         api/preview.py, installs
  users.example.toml                                                    Plated from main
  supabase/migrations/
  tests/
```

| Part | Environment |
|---|---|
| Plated, on your machine | `.env`: `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, and `PLATED_SITE_URL` for `subscribers invite` |
| plated-runner | repo secrets `SUPABASE_URL`, `SUPABASE_SECRET_KEY` |
| Vercel | `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` (Next.js), `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY` (the preview function) |

**Never put the secret key on Vercel.** Everything there is public by
design: `NEXT_PUBLIC_` values ship to every browser, and the preview
only reads public menus. What a signed-in person may do comes from
their session and row level security, not from a key.

Vercel project settings: Root Directory `web`, Framework Preset
Next.js, Node.js 20 or newer (`web/package.json` asks for 20.9+), and
the four variables above for Production and Preview. Vercel turns the
Python file in `web/api/` into a function with no extra configuration.
Its git-URL install of this package is unproven until the first deploy;
`web/api/requirements.txt` has the tarball URL to switch to if Vercel
rejects it.

The private repo installs this package straight from `main`, so changes
here reach subscribers on the next run with no release step. The
dependency points private -> public, and public repos are readable
anonymously, so no access token is needed in either direction.

Do not copy `menu/` into the private repo. It holds config and a
workflow, nothing else. The web app needed no runner change: storing
menus is a step inside the same `dispatch --supabase` run, with the
same two secrets.

The private repo's workflow:

```yaml
name: Notify
on:
  schedule:
    - cron: "17 */3 * * *"   # heartbeat only; Supabase starts runs on time
  workflow_dispatch: {}

jobs:
  notify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv venv
      - run: uv pip install git+https://github.com/Land784/Plated.git@main
      - run: uv run python -m menu dispatch --supabase
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SECRET_KEY: ${{ secrets.SUPABASE_SECRET_KEY }}
```

## Scheduling: who starts a run

GitHub's own schedule can't be trusted for meal times. It is best
effort, and in September 2026 a `*/30` cron ran only 5-6 times a day;
since each meal needed a run inside its 30-minute slot, nothing was sent
for four days.

Runs are now started by the database. Every 5 minutes, `pg_cron` in
Supabase checks whether any active subscriber has a meal scheduled in
the last 5 minutes of their local time, and only then calls GitHub's
`workflow_dispatch` API, which starts a run within seconds. That is
about one run per scheduled meal, instead of 48 a day. The check and
its schedule are in `supabase/migrations/`.

Each run sends every meal whose time passed within the last 45 minutes
(`--window`), so a late run still delivers, and never sends a meal
before its time. Several runs can see the same meal, so a run first
claims it in the `sent_meals` table; the primary key lets only one claim
succeed. A failed send releases its claim so the next run retries.

GitHub's schedule stays as a heartbeat every 3 hours: a catch-up sweep,
and regular reads that keep the free Supabase project from being paused
for inactivity. GitHub's rule that disables scheduled workflows after 60
days without repo activity applies only to public repositories, so it
can't stop the private runner.

The database needs a GitHub token to start runs: a fine-grained token
limited to `plated-runner` with Actions read and write, stored in Vault
as `github_dispatch_token` (added in the SQL editor, never committed).
When it expires, on-time runs stop and only the heartbeat remains, so
renew it before then; GitHub emails a reminder.

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

Watchlist alerts, a public menu page, macros and account deletion in
the web app, and menu history beyond 60 days. History belongs in
Supabase (the `menus` table is its start): GitHub Actions runners start
with an empty disk every run, so the SQLite history in `menu/db.py`
could never persist there.

## Roadmap

1. Fetch and print one day's menu with protein and allergen info for each item
2. Pydantic models and fixture-based tests
3. Allergen filtering and protein ranking
4. Meal planner
5. ntfy notifications and a GitHub Actions daily run
6. SQLite history and simple stats (e.g., which days have the best high-protein options)
7. Multi-user subscriptions: Supabase subscribers and the invite-only web app (done)
