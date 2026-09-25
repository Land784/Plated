-- Replace the single-purpose `protein` settings with per-nutrient goals.
--
-- `macros` holds the [macros] table: nutrient -> {target, min, max,
-- tolerance}, plus per-meal overrides keyed by meal slug. `picks` holds
-- the [picks] table: item eligibility limits, repeat servings and
-- allergen handling. Both mirror the subscriber-file tables exactly, so
-- rows keep going through parse_user().
--
-- Additive on purpose: the deployed code still reads `protein` until the
-- code that reads these columns ships. `protein` is dropped in a
-- follow-up migration after that.

alter table public.subscribers
  add column macros jsonb,
  add column picks jsonb;
