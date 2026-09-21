# Fixtures

`sample_week.json` is a **synthetic** fixture, hand-written to match
the best-guess Nutrislice schema in `menu/models.py`. It is NOT a real
captured API response.

Before trusting the models in production:

1. Open `https://nd.nutrislice.com/menu/north-dining-hall/` in a
   browser, open DevTools -> Network, and find the request to
   `menu/api/weeks/school/.../menu-type/.../YYYY/MM/DD/`.
2. Save the full JSON response body as a new fixture file here (e.g.
   `real_north_lunch_2026-09-20.json`).
3. Compare its shape against `menu/models.py` and adjust field names,
   aliases, and optionality as needed.
4. Add a test in `tests/test_models.py` / `tests/test_client.py` that
   parses the real fixture, so future upstream schema changes get
   caught by the test suite instead of silently breaking in
   production.

Tests must never hit the live API -- always fetch through fixtures.
