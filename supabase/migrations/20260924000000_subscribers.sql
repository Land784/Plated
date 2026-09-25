-- Subscribers: one row per person receiving notifications.
--
-- Columns mirror the keys of a users/*.toml subscriber file exactly, so
-- menu.users.parse_user() validates rows from either source through one
-- code path. `schedule` and `protein` are jsonb for the same reason:
-- they hold the same nested tables the TOML file does.
--
-- ntfy_topic is effectively a password (anyone who knows it can read and
-- publish to that person's phone), so this table must never be readable
-- with the publishable key. RLS is enabled with no policies: only the
-- secret key, which bypasses RLS, can read or write it.

create table public.subscribers (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  ntfy_topic text not null unique,
  timezone text not null default 'America/New_York',
  halls text[] not null default array['north-dining-hall', 'south-dining-hall'],
  stations text[] not null default '{}',
  max_items_per_station integer not null default 4 check (max_items_per_station > 0),
  schedule jsonb not null default '{}'::jsonb,
  protein jsonb,
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.subscribers enable row level security;

create function public.touch_updated_at() returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger subscribers_touch_updated_at
before update on public.subscribers
for each row execute function public.touch_updated_at();
