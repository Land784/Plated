-- Restrict schedule meal keys to the confirmed Nutrislice menu types
-- (breakfast, brunch, lunch, late-lunch, dinner, special) instead of any
-- slug-shaped word. A typo such as "diner" would otherwise be saved and
-- produce an empty send every week. Same function, same checks
-- (20261007000300's subscribers_schedule_valid calls it), tighter rule.
--
-- Additive and safe to apply any time after 20261007000300: every
-- existing schedule uses only these meal slugs, and the runner's code is
-- unaffected. If a row ever didn't, `create or replace` would not
-- recheck it; only later writes to that row would be rejected.

create or replace function public.valid_schedule(schedule jsonb) returns boolean
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
      if meal.key not in ('breakfast', 'brunch', 'lunch', 'late-lunch', 'dinner', 'special')
        or jsonb_typeof(meal.value) <> 'string'
        or (meal.value #>> '{}') !~ '^([01]\d|2[0-3]):[0-5]\d$' then
        return false;
      end if;
    end loop;
  end loop;
  return true;
end;
$$;
