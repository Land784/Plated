-- Superseded by the macros and picks columns (20260925000000). Dropped
-- only after the code reading those columns was deployed and verified
-- by a runner dry run, so no deployed version still selects `protein`.

alter table public.subscribers drop column protein;
