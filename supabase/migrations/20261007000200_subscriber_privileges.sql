-- Let a signed-in web user read and edit their own subscriber row, and
-- nothing else.
--
-- Until now both tables had RLS on and no policies, so only the secret
-- key could touch them. Supabase also grants anon and authenticated
-- every privilege on new public tables by default; RLS made that
-- harmless, but this tightens the grants too, so a future policy can't
-- accidentally open more than intended.
--
-- Column privileges: revoking UPDATE on one column does nothing while
-- the table-level UPDATE grant stands, so table-level UPDATE is revoked
-- and granted back on the editable columns only. ntfy_topic, user_id,
-- timezone, max_items_per_station, main_protein_g, macros and picks are
-- not editable by users; PostgREST answers 403 to a PATCH naming one.
-- Users can read every column of their own row, ntfy_topic included
-- (the Connect page shows it). No insert or delete: rows are created by
-- `menu subscribers invite` with the secret key.
--
-- APPLY AFTER 20261007000100 (it names favorites and user_id) and
-- BEFORE deploying the web app. The runner is unaffected either way: it
-- uses the secret key, whose role these grants and policies don't
-- touch.

revoke all on public.subscribers from anon;
revoke all on public.sent_meals from anon;
-- The send log is the runner's alone; the web app never reads it.
revoke all on public.sent_meals from authenticated;

revoke all on public.subscribers from authenticated;
grant select on public.subscribers to authenticated;
grant update (name, halls, stations, favorites, schedule, active)
  on public.subscribers to authenticated;

create policy "subscribers: read own row" on public.subscribers
  for select to authenticated
  using ((select auth.uid()) = user_id);

create policy "subscribers: update own row" on public.subscribers
  for update to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);
