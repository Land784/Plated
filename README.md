# Plated

A personal tool that pulls daily Notre Dame dining hall menus, filters
items by allergen and protein/macro criteria, builds high-protein meal
suggestions, and sends notifications.

See [CLAUDE.md](./CLAUDE.md) for the full project spec, data source
details, and conventions.

## Quick start

```bash
uv sync
cp config.example.toml config.toml   # then edit it
uv run python -m menu fetch          # print today's menu
uv run python -m menu plan           # build a protein-focused meal plan
uv run python -m menu notify         # run the full pipeline and notify
uv run pytest
uv run ruff check . && uv run ruff format .
```

## Status

Early scaffold (roadmap step 1-2 in CLAUDE.md). The Nutrislice
`school_slug` and `menu_type` values in `config.example.toml` are
**unverified placeholders** -- confirm them in your browser's DevTools
Network tab against `nd.nutrislice.com` before trusting any output.
