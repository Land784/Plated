-- Wake the GitHub runner when a meal is due, instead of relying on
-- GitHub's own schedule. In September 2026 a */30 GitHub cron ran only
-- 5-6 times a day, so meals that needed a run inside their 30-minute
-- slot were never sent.
--
-- Every 5 minutes pg_cron asks whether any active subscriber has a meal
-- scheduled in the last 5 minutes of their own local time. Only then
-- does pg_net call GitHub's workflow_dispatch API, which starts a run
-- within seconds. The run itself decides what to send and claims it in
-- sent_meals, so a duplicate trigger is harmless.
--
-- The GitHub token lives in Vault as 'github_dispatch_token': a
-- fine-grained token limited to Land784/plated-runner with Actions
-- read/write. It is added by hand in the SQL editor, never in a
-- migration. Until it exists the check logs and does nothing.

create extension if not exists pg_net with schema extensions;
create extension if not exists pg_cron;

-- Not exposed through the REST API, unlike public.
create schema if not exists plated_private;
revoke all on schema plated_private from public, anon, authenticated;

create function plated_private.meal_due(window_minutes integer default 5)
returns boolean
language sql
stable
set search_path = ''
as $$
  select exists (
    select 1
    from public.subscribers as s
    cross join lateral (select now() at time zone s.timezone as local_now) as l
    cross join lateral jsonb_each_text(
      s.schedule -> lower(to_char(l.local_now, 'FMDay'))
    ) as m (meal, at)
    where s.active
      and l.local_now::date + m.at::time > l.local_now - make_interval(mins => window_minutes)
      and l.local_now::date + m.at::time <= l.local_now
  );
$$;

create function plated_private.dispatch_if_due()
returns bigint
language plpgsql
set search_path = ''
as $$
declare
  token text;
begin
  if not plated_private.meal_due() then
    return null;
  end if;

  select decrypted_secret into token
  from vault.decrypted_secrets
  where name = 'github_dispatch_token';

  if token is null then
    raise log 'plated: a meal is due but github_dispatch_token is missing from Vault';
    return null;
  end if;

  return net.http_post(
    url := 'https://api.github.com/repos/Land784/plated-runner/actions/workflows/notify.yml/dispatches',
    body := jsonb_build_object('ref', 'main'),
    headers := jsonb_build_object(
      'Authorization', 'Bearer ' || token,
      'Accept', 'application/vnd.github+json',
      'X-GitHub-Api-Version', '2022-11-28',
      'User-Agent', 'plated-supabase-scheduler',
      'Content-Type', 'application/json'
    ),
    timeout_milliseconds := 10000
  );
end;
$$;

revoke all on function plated_private.meal_due(integer) from public, anon, authenticated;
revoke all on function plated_private.dispatch_if_due() from public, anon, authenticated;

select cron.schedule(
  'plated-dispatch',
  '*/5 * * * *',
  $$ select plated_private.dispatch_if_due() $$
);

-- pg_cron logs every run; 288 rows a day adds up, so keep a week.
select cron.schedule(
  'plated-cron-log-cleanup',
  '23 4 * * *',
  $$ delete from cron.job_run_details where end_time < now() - interval '7 days' $$
);
