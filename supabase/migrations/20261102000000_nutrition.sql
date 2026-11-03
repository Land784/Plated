-- Nutrition settings in the web app, and same-day pick history.
--
-- 1. sent_meals.picked: names of the items sent as picks for that meal,
--    so a later meal the same day doesn't pick them again (written by
--    dispatch after a send; null for meals sent without picks).
-- 2. Signed-in users may now edit macros, picks and main_protein_g on
--    their own row (the Nutrition tab), so those columns get checks.
--
-- Rows keep their current picks object: the code on main rejects the
-- new keys, and the new code ignores the three retired ones
-- (min_item_protein_g, max_servings_per_item, max_total_servings), so
-- the checks allow them too. Every existing row satisfies the checks.
--
-- APPLY BEFORE merging the planner rebuild (it reads and writes
-- sent_meals.picked, and the web app PATCHes the newly granted columns).
-- Safe to apply before any code: nothing on main names `picked`, and
-- the extra grants and checks only matter once the web app writes them.

alter table public.sent_meals add column picked text[];

create function public.valid_macros(macros jsonb) returns boolean
language plpgsql
immutable
set search_path = ''
as $$
declare
  t record;
begin
  if macros is null then
    return true;
  end if;
  if jsonb_typeof(macros) <> 'object' then
    return false;
  end if;
  for t in select key, value from jsonb_each(macros) loop
    if t.key not in ('protein', 'carbs', 'fat', 'calories') then
      return false;
    end if;
    if jsonb_typeof(t.value) = 'null' then
      continue;
    end if;
    if jsonb_typeof(t.value) <> 'number'
      or (t.value #>> '{}')::numeric <= 0
      or (t.value #>> '{}')::numeric > 10000 then
      return false;
    end if;
  end loop;
  return true;
end;
$$;

create function public.valid_picks(picks jsonb) returns boolean
language plpgsql
immutable
set search_path = ''
as $$
declare
  t record;
  n numeric;
begin
  if picks is null then
    return true;
  end if;
  if jsonb_typeof(picks) <> 'object' then
    return false;
  end if;
  for t in select key, value from jsonb_each(picks) loop
    if t.key = 'enabled' then
      if jsonb_typeof(t.value) <> 'boolean' then return false; end if;
    elsif t.key = 'unknown_allergens' then
      if (t.value #>> '{}') not in ('flag', 'exclude') or jsonb_typeof(t.value) <> 'string' then
        return false;
      end if;
    elsif t.key = 'exclude_allergens' then
      if jsonb_typeof(t.value) <> 'array' or jsonb_array_length(t.value) > 30
        or exists (
          select 1 from jsonb_array_elements(t.value) a
          where jsonb_typeof(a) <> 'string' or length(a #>> '{}') > 40
        ) then
        return false;
      end if;
    elsif t.key = 'max_item_calories' and jsonb_typeof(t.value) = 'null' then
      continue;
    elsif t.key in (
      'tolerance_pct', 'side_min_calories', 'max_main_servings', 'max_item_calories',
      -- Retired keys, still on rows saved before the planner rebuild.
      'min_item_protein_g', 'max_servings_per_item', 'max_total_servings'
    ) then
      if jsonb_typeof(t.value) <> 'number' then return false; end if;
      n := (t.value #>> '{}')::numeric;
      if (t.key = 'tolerance_pct' and (n <= 0 or n > 100))
        or (t.key = 'side_min_calories' and (n < 0 or n > 5000))
        or (t.key = 'max_main_servings' and n not in (1, 2, 3))
        or (t.key = 'max_item_calories' and (n <= 0 or n > 20000))
        or n < 0 then
        return false;
      end if;
    else
      return false;
    end if;
  end loop;
  return true;
end;
$$;

grant execute on function public.valid_macros(jsonb) to anon, authenticated, service_role;
grant execute on function public.valid_picks(jsonb) to anon, authenticated, service_role;

alter table public.subscribers
  add constraint subscribers_macros_valid check (public.valid_macros(macros)),
  add constraint subscribers_picks_valid check (public.valid_picks(picks)),
  add constraint subscribers_main_protein_range check (main_protein_g between 0 and 200);

grant update (macros, picks, main_protein_g) on public.subscribers to authenticated;
