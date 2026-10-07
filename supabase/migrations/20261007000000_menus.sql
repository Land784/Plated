-- Menus saved for the web app, so its preview and station picker read
-- Supabase and never Nutrislice.
--
-- Written by the notify job (menu/menus_store.py) with the secret key:
-- on the first run after 05:00 Eastern each day, one `menus` row per
-- (date, hall, meal) that serves food, and one `menu_stations` row per
-- station in it. Rows older than 60 days are deleted by the same job;
-- station rows go with their menu.
--
-- `items` is the day's Nutrislice menu_items trimmed to the fields the
-- pydantic models read, in menu order, values exactly as reported
-- (nulls, bulk recipe rows and duplicate rows kept), so
-- DayMenu.model_validate({"date": ..., "menu_items": items}) rebuilds it.
--
-- `menu_stations.mains` holds the names the push would list for that
-- station (menu/digest.py's mains rule), computed in Python because the
-- rule lives there. The `stations` view only counts them.
--
-- Menus are public information, so anyone may read these; nobody but
-- the secret key may write them (RLS on, select-only policies).
--
-- APPLY BEFORE merging the code that writes these tables to main. The
-- runner installs from main, so merging is deploying, and the new
-- dispatch step reports a missing table as a failed run. Nothing on
-- main today names these tables, so applying early is safe.

create table public.menus (
  date date not null,
  hall text not null,
  meal text not null,
  fetched_at timestamptz not null default now(),
  items jsonb not null,
  primary key (date, hall, meal)
);

alter table public.menus enable row level security;
revoke all on public.menus from anon, authenticated;
grant select on public.menus to anon, authenticated;
create policy "menus are public" on public.menus
  for select to anon, authenticated using (true);

create table public.menu_stations (
  date date not null,
  hall text not null,
  meal text not null,
  -- As published, e.g. "The Global Compass" at North.
  station text not null,
  -- menu.digest.normalize_station: lower case, no leading "the".
  normalized text not null,
  -- False when the name is in menu.digest.NON_FOOD_STATIONS.
  is_food boolean not null,
  mains text[] not null default '{}',
  primary key (date, hall, meal, station),
  foreign key (date, hall, meal) references public.menus (date, hall, meal) on delete cascade
);

create index menu_stations_normalized_idx on public.menu_stations (normalized, date);

alter table public.menu_stations enable row level security;
revoke all on public.menu_stations from anon, authenticated;
grant select on public.menu_stations to anon, authenticated;
create policy "menu stations are public" on public.menu_stations
  for select to anon, authenticated using (true);

-- The station picker's catalog: one row per normalized station seen in
-- the last 14 days. Shared stations merge across halls ("The Global
-- Compass" at North, "Global Compass" at South). example_dishes are the
-- three names listed most often, ties broken by how high they were
-- listed. security_invoker so the caller's RLS applies, not the owner's.
create view public.stations with (security_invoker = true) as
with recent as (
  select *
  from public.menu_stations
  where date > current_date - 14
),
spellings as (
  select normalized, station, count(*) as seen
  from recent
  group by normalized, station
),
dishes as (
  select r.normalized, m.dish, count(*) as seen, min(m.pos) as best_position
  from recent as r
  cross join lateral unnest(r.mains) with ordinality as m (dish, pos)
  group by r.normalized, m.dish
),
grouped as (
  select
    normalized,
    array_agg(distinct hall order by hall) as halls,
    array_agg(distinct meal order by meal) as meals,
    max(date) as last_seen,
    bool_and(is_food) as is_food
  from recent
  group by normalized
)
select
  (
    select s.station
    from spellings as s
    where s.normalized = g.normalized
    order by s.seen desc, s.station
    limit 1
  ) as station,
  g.normalized,
  g.halls,
  g.meals,
  g.last_seen,
  g.is_food,
  coalesce(
    (
      select array_agg(top.dish order by top.seen desc, top.best_position, top.dish)
      from (
        select d.dish, d.seen, d.best_position
        from dishes as d
        where d.normalized = g.normalized
        order by d.seen desc, d.best_position, d.dish
        limit 3
      ) as top
    ),
    '{}'
  ) as example_dishes
from grouped as g;

revoke all on public.stations from anon, authenticated;
grant select on public.stations to anon, authenticated;
