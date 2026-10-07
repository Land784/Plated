-- Database-side checks on what a signed-in user may save.
--
-- Once the web app can update rows (20261007000200), a malformed row no
-- longer comes only from a validated TOML file. The runner now skips and
-- reports a row parse_user rejects, but these checks stop the common
-- shapes from being saved at all: a schedule that isn't
-- weekday -> meal -> "HH:MM", an unknown or empty hall list, a blank or
-- huge name, runaway station lists, and two subscribers with one name
-- (`menu subscribers invite --link` finds rows by name).
--
-- Also sets the max_items_per_station default to 3, matching
-- menu.users.DEFAULT_MAX_ITEMS (existing rows keep their value), and
-- adds menu_store_runs, the menus store's success marker (bottom).
--
-- Additive; every existing row (written by `subscribers push`, which
-- formats times as zero-padded HH:MM) satisfies these checks, and a row
-- that didn't would make this migration fail rather than change data.
--
-- APPLY BEFORE deploying the web app, and BEFORE merging the runner
-- code that reads menu_store_runs (without it the daily menus store
-- reports a failed run; sends are unaffected). Safe to apply before any
-- code: nothing on main names menu_store_runs, and the runner never
-- writes subscriber columns in a shape the checks reject.

create function public.valid_schedule(schedule jsonb) returns boolean
language plpgsql
immutable
set search_path = ''
as $$
declare
  day record;
  meal record;
begin
  if schedule is null or jsonb_typeof(schedule) <> 'object' then
    return false;
  end if;
  for day in select key, value from jsonb_each(schedule) loop
    if day.key not in (
      'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'
    ) or jsonb_typeof(day.value) <> 'object' then
      return false;
    end if;
    for meal in select key, value from jsonb_each(day.value) loop
      -- Meal slugs as Nutrislice spells them: breakfast, late-lunch, ...
      if meal.key !~ '^[a-z][a-z-]{0,39}$'
        or jsonb_typeof(meal.value) <> 'string'
        or (meal.value #>> '{}') !~ '^([01]\d|2[0-3]):[0-5]\d$' then
        return false;
      end if;
    end loop;
  end loop;
  return true;
end;
$$;

-- Callable by anyone: a CHECK runs it as the role doing the write, and
-- it only inspects its argument.
grant execute on function public.valid_schedule(jsonb) to anon, authenticated, service_role;

alter table public.subscribers
  add constraint subscribers_schedule_valid check (public.valid_schedule(schedule)),
  add constraint subscribers_halls_valid check (
    halls <@ array['north-dining-hall', 'south-dining-hall']::text[]
    and cardinality(halls) between 1 and 2
    and (cardinality(halls) = 1 or halls[1] <> halls[2])
  ),
  add constraint subscribers_name_length check (length(btrim(name)) between 1 and 60),
  add constraint subscribers_stations_count check (cardinality(stations) <= 200),
  add constraint subscribers_favorites_count check (cardinality(favorites) <= 200),
  add constraint subscribers_name_key unique (name);

alter table public.subscribers alter column max_items_per_station set default 3;

-- One row per Eastern local date whose menus store (menu/menus_store.py)
-- finished with no problems. The notify job stores the week's menus on
-- its first run after 05:00 that finds no row for today; a store that
-- hit a problem writes none, so the next run retries. Pruned with the
-- menus after 60 days. Only the secret key touches it: RLS on, no
-- policies, no grants.
create table public.menu_store_runs (
  local_date date primary key,
  stored_at timestamptz not null default now()
);

alter table public.menu_store_runs enable row level security;
revoke all on public.menu_store_runs from anon, authenticated;
