-- rls_auto_enable() is Supabase's event trigger that turns on RLS for
-- every new table in public. It is created with the project and granted
-- to anon and authenticated, which puts it on the REST API's rpc
-- endpoint. An event_trigger function can't be invoked that way, but the
-- grant has no purpose, so revoke it. Revoking EXECUTE does not stop the
-- event trigger from firing on DDL.

revoke execute on function public.rls_auto_enable() from public, anon, authenticated;
