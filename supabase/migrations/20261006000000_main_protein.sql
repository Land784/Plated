-- Per-subscriber protein floor for a notification's "mains": an item is
-- listed as a station's main at this much protein per listed serving
-- (menu/digest.py). Display only; it never changes what picks rank.
--
-- Additive, with a default, so existing rows read as 10.
--
-- Apply before merging to main; the runner installs from main, so
-- merging is deploying. The new code names this column when it loads
-- and when `subscribers push` writes, and PostgREST rejects a column
-- that doesn't exist, so code merged first fails every run. The code on
-- main today never names it, so applying early is safe.

alter table public.subscribers
  add column main_protein_g numeric not null default 10 check (main_protein_g >= 0);
