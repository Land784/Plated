-- Link subscribers to Supabase Auth users and let the database pick
-- their ntfy topics, for the invite-only web app.
--
-- favorites: stations starred in the web app. `stations` stays the
--   ordered list the push renders (favorites first); this only tells
--   the app which ones are starred.
-- user_id: the auth user who may read and edit this row (policies in
--   the next migration). Set by `menu subscribers invite`, never by the
--   user. Deleting the auth user deletes the row.
-- ntfy_topic default: `plated-` + 16 characters from the same
--   unambiguous alphabet as users.example.toml (no 0/o, 1/l/i), so an
--   invited person gets an unguessable topic without anyone choosing
--   one. Bytes come from pgcrypto; values >= 248 are rejected so each
--   of the 31 letters is equally likely.
--
-- APPLY BEFORE merging the code that names `favorites` to main. The
-- runner installs from main, so merging is deploying, and that code
-- selects and writes `favorites`; PostgREST rejects an unknown column,
-- so code merged first fails every run. Additive with defaults, so the
-- code on main today is unaffected and applying early is safe.

create extension if not exists pgcrypto with schema extensions;

alter table public.subscribers
  add column favorites text[] not null default '{}',
  add column user_id uuid unique references auth.users (id) on delete cascade;

create function public.new_ntfy_topic() returns text
language plpgsql
volatile
set search_path = ''
as $$
declare
  alphabet constant text := 'abcdefghjkmnpqrstuvwxyz23456789';
  suffix text := '';
  bytes bytea;
  b integer;
begin
  while length(suffix) < 16 loop
    bytes := extensions.gen_random_bytes(32);
    for i in 0 .. 31 loop
      b := get_byte(bytes, i);
      if b < 248 then  -- 248 = 8 * 31; higher values would favor early letters
        suffix := suffix || substr(alphabet, b % 31 + 1, 1);
        exit when length(suffix) = 16;
      end if;
    end loop;
  end loop;
  return 'plated-' || suffix;
end;
$$;

-- Not callable over the REST API's rpc endpoint. The secret key's role
-- inserts rows, so it needs to run the default.
revoke all on function public.new_ntfy_topic() from public, anon, authenticated;
grant execute on function public.new_ntfy_topic() to service_role;

alter table public.subscribers
  alter column ntfy_topic set default public.new_ntfy_topic();
