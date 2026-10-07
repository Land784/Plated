-- Per-subscriber protein floor for a notification's "mains": an item is
-- listed as a station's main at this much protein per listed serving
-- (menu/digest.py). Display only; it never changes what picks rank.
--
-- Additive, with a default, so existing rows read as 10. Apply it before
-- deploying the code that selects the column, since PostgREST rejects a
-- select naming a column that doesn't exist. The deployed code never
-- selects it, so applying early is safe.

alter table public.subscribers
  add column main_protein_g numeric not null default 10 check (main_protein_g >= 0);
