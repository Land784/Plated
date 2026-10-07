# Plated web

Invite-only sign-in, a three-step setup, settings, a live preview of your
own text, and phone setup for ntfy. Next.js (App Router) + Tailwind +
shadcn/ui, mobile-first, light/dark from the system setting.

| Route | What it does |
|---|---|
| `/` | Sign in: email magic link (plus the 6-digit code from the same email) |
| `/auth/confirm` | Route handler: `verifyOtp({ token_hash, type })` for `email` and `invite`, then Setup on first run, else Settings |
| `/setup` | Where you eat / When / What you like, then Finish |
| `/settings` | Summary with an Edit per section, pause, name |
| `/preview` | Your text for a meal and date, from the current (unsaved) form |
| `/connect` | Your ntfy topic, iPhone and Android steps, send a test |

The browser talks to Supabase directly with the publishable key and the
person's session. It reads its own `subscribers` row and the `stations`
view, and updates only `name, halls, stations, favorites, schedule,
active` (never `ntfy_topic`). RLS and column grants enforce this.

## Local dev

```bash
cd web
cp .env.example .env.local   # fill in the two NEXT_PUBLIC_ values
npm i && npm run dev         # http://localhost:3000
npm test                     # vitest: schedule, stations, preview request
npm run lint && npm run build
```

`npm run dev` serves only the Next.js app. `/api/preview` is a Python
function, so in plain `next dev` the Preview page shows "The preview
isn't available right now." Run `vercel dev` from `web/` to serve both.

## Environment

| Variable | Used by |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | Next.js (browser, proxy, `/auth/confirm`) |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | Next.js; the `sb_publishable_...` key |
| `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY` | The Python preview function |

No secret key is used anywhere in `web/`.

## Vercel

- Root Directory: `web`
- Framework Preset: Next.js (install `npm install`, build `npm run build`)
- Environment variables: the four above, for Production and Preview.

## Supabase Auth settings (dashboard)

- Public signups off; Site URL = the Vercel URL; add `<site>/auth/confirm`
  to the redirect allow list.
- Email templates must link to `/auth/confirm` with a token hash (not the
  default `{{ .ConfirmationURL }}`), and include `{{ .Token }}` for the
  code entry on the sign-in page:
  - Magic link: `{{ .SiteURL }}/auth/confirm?token_hash={{ .TokenHash }}&type=email`
  - Invite: `{{ .SiteURL }}/auth/confirm?token_hash={{ .TokenHash }}&type=invite`

## Preview function (owned by the backend)

`web/api/preview.py` is a Vercel Python function maintained with the
Python package, not here. The app calls `POST /api/preview` with
`{"halls": [...], "stations": [...], "meal": "dinner", "date": "YYYY-MM-DD"}`,
built from the unsaved form (`lib/plated/preview.ts`), debounced 350 ms. It
answers `{title, tags, body, bytes, sent: true}` or `{sent: false, reason}`.

"Send a test" on Connect posts that body from the browser straight to
`https://ntfy.sh/<topic>?title=...&tags=...` as plain text (a CORS simple
request, no preflight), at most once per 5 seconds. It never goes through
Vercel, whose shared egress IPs would share ntfy's per-IP limit.

## Notes

- First run is detected from the row: `updated_at == created_at` means
  the invite's defaults were never saved, so `/auth/confirm` sends the
  person to `/setup`. Finish (or any save) bumps `updated_at`.
- `stations` is written as favorites, then the other included stations,
  both in catalog order: not breakfast-only first, then stations at both
  halls, North-only, South-only, then by name. Names in the row the
  catalog doesn't know (not seen in 14 days) are kept at the end.
- Schedule entries the editor can't show (late-lunch, lunch on a
  weekend) are kept and written back unchanged.
