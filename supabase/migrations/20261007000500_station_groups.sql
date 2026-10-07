-- Station groups: one counter published under a different name each day.
--
-- South's bowl counter appears as "Athenian Rice Bowl", "Jerusalem Rice
-- Bowl" or "Harvest Bowl", each with its own station_id, so the picker
-- showed several stations where there is one. menu.digest.STATION_GROUPS
-- now normalizes any food station whose name has the word bowl/bowls to
-- the token 'bowls' (the push and allowlists match on it), and the
-- notify job writes that into menu_stations.normalized for new rows.
--
-- This migration backfills existing rows the same way (food stations
-- only, as in Python: a "Bowl Toppings" bar would otherwise make the
-- whole group non-food) and makes the `stations` view show a group by
-- its label ("Bowls") instead of the day's most common spelling. The
-- view's columns are unchanged, so the web app needs no change to read
-- it.
--
-- Additive; apply any time. Before it, grouped rows written by the new
-- code simply show under their most common spelling.

update public.menu_stations
set normalized = 'bowls'
where station ~* '\mbowls?\M'
  and is_food;

create or replace view public.stations with (security_invoker = true) as
with recent as (
  select *
  from public.menu_stations
  where date > current_date - 14
),
-- Keep in step with menu.digest.STATION_GROUPS.
group_labels (normalized, label) as (
  values ('bowls'::text, 'Bowls'::text)
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
  coalesce(
    (select l.label from group_labels as l where l.normalized = g.normalized),
    (
      select s.station
      from spellings as s
      where s.normalized = g.normalized
      order by s.seen desc, s.station
      limit 1
    )
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
