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

Needs Node 20.9 or newer (`engines` in package.json; Next.js 16's minimum).

```bash
cd web
cp .env.example .env.local   # fill in the two NEXT_PUBLIC_ values
npm i && npm run dev         # http://localhost:3000
npm test                     # vitest: schedule, stations, preview request
npm run lint && npm run build
```

Open it at `http://localhost:3000`, not `127.0.0.1:3000`: Next.js dev
blocks cross-origin dev requests from hosts other than localhost, so the
page loads but stays unhydrated on 127.0.0.1.

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

- Import the Plated repo; Root Directory: `web`
- Framework Preset: Next.js (install `npm install`, build `npm run build`)
- Node.js Version: 20.x or newer (`engines` asks for 20.9+)
- Environment variables: the four above, for Production and Preview.
  Never the secret key.
- `api/preview.py` becomes a Python function (3.12 by default) with no
  extra configuration. It installs `plated` from GitHub `main`
  (`api/requirements.txt`), so a Python change reaches the preview on
  the next Vercel deploy after it is merged. The git-URL install is
  unproven until the first deploy; the tarball URL in that file is the
  fallback.

## Supabase Auth settings (dashboard)

None of these are in migrations; set them by hand before the first
invite.

- **Sign-ups:** turn off "Allow new users to sign up". The sign-in page
  also asks with `shouldCreateUser: false`, but only the dashboard
  setting enforces it. `menu subscribers invite` is the only way in.
- **URLs:** Site URL = the Vercel URL. Redirect allow list: that URL
  (the invite command's `redirect_to`, from `PLATED_SITE_URL`, which
  must be the same URL) and `<site>/auth/confirm` (the sign-in link's
  redirect).
- **Email templates** must link to `/auth/confirm` with a token hash
  (not the default `{{ .ConfirmationURL }}`, which uses a flow the app
  doesn't handle), and include `{{ .Token }}`, the 6-digit code, because
  mail link scanners can use up a link before the person taps it:
  - Magic link: `{{ .SiteURL }}/auth/confirm?token_hash={{ .TokenHash }}&type=email`
  - Invite: `{{ .SiteURL }}/auth/confirm?token_hash={{ .TokenHash }}&type=invite`

  The sign-in page's code box verifies with `type: "email"`, which is
  right for magic-link codes. Whether it accepts the code from an
  invite email is untested; check that with the first invite.
- **SMTP:** Supabase's built-in sender only reaches the project's team
  members, at 2 emails an hour. Set custom SMTP (the owner's Gmail with
  an app password, `smtp.gmail.com`, about 500 a day) before inviting
  anyone else.

## Preview function (owned by the backend)

`web/api/preview.py` is a Vercel Python function maintained with the
Python package, not here. The app calls `POST /api/preview` with
`{"halls": [...], "stations": [...], "meal": "dinner", "date": "YYYY-MM-DD"}`,
built from the unsaved form (`lib/plated/preview.ts`), debounced 350 ms. It
answers `{title, tags, body, bytes, sent: true}` or `{sent: false, reason}`.
Menus are stored for the current Sunday-to-Saturday week only, so the date
picker runs from today (the subscriber's zone) to the coming Saturday, and
"no menu published" reads "Nothing stored yet for that day; menus appear
the morning of."

Names are unique and at most 60 characters: the Name field trims and caps
input, and a unique violation (23505) shows "That name is taken" by it.

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
