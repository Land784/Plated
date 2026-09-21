# Fixtures

- `real_north_lunch_2026-09-21.json` -- a **real** (trimmed) response
  from `GET https://nd.api.nutrislice.com/menu/api/weeks/school/north-dining-hall/menu-type/lunch/2026/09/22/`,
  captured 2026-09-20. Trimmed down to one station-header row and four
  representative food items (one with allergen-ish icon tags, one with
  no icon data at all, one plain) across an empty day and a populated
  day, to keep the file small. Field names and values inside the kept
  items are exactly as returned -- nothing was renamed or corrected,
  including the upstream data-quality quirks (e.g. some items report
  `serving_size_unit: "z"` instead of `"oz"`).
- `real_schools_2026-09-20.json` -- the real, full response from
  `GET https://nd.api.nutrislice.com/menu/api/schools/`, listing both
  dining halls and their confirmed `menu_type` slugs. Not currently
  parsed by any model/test, but kept as evidence for the values in
  `config.example.toml`.
- `sample_week.json` -- an older **synthetic** fixture, hand-written
  before the real API host/shape were confirmed. Still used by
  `tests/test_client.py` for basic day-lookup/caching checks that
  don't depend on the exact real schema.

Nutrislice is unofficial and undocumented, so this can drift. If
something looks off:

1. Open `https://nd.nutrislice.com/menu/north-dining-hall/` (or
   `.../south-dining-hall/`) in a browser with DevTools' Network tab
   open, and watch for a request to
   `nd.api.nutrislice.com/menu/api/weeks/school/.../menu-type/.../YYYY/MM/DD/`.
   Note: the request does NOT go to the page's own host
   (`nd.nutrislice.com`) -- that host is a static SPA shell with no
   backend of its own. See `menu/client.py`'s module docstring for how
   this was worked out.
2. Save the full JSON response body as a new fixture file here.
3. Compare its shape against `menu/models.py` and adjust field names,
   aliases, and optionality as needed.
4. Add a test in `tests/test_models.py` / `tests/test_client.py` that
   parses the real fixture, so future upstream schema changes get
   caught by the test suite instead of silently breaking in
   production.

Tests must never hit the live API -- always fetch through fixtures.
