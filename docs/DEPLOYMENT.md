# Production deployment

This describes the actual live deployment, not a hypothetical one — both
pieces are already running and auto-deploy from `main`:

| Component | Host | URL | Deploys on |
|---|---|---|---|
| Backend API | [Railway](https://railway.app) | `https://specledger-production.up.railway.app` | Push to `main` (Railway's GitHub integration, no workflow file in this repo) |
| Frontend | GitHub Pages | `https://yashasm18.github.io/specledger/` | Push to `main` touching `frontend/**` ([`.github/workflows/gh-pages.yml`](../.github/workflows/gh-pages.yml)) |
| Database + object storage | [Supabase](https://supabase.com) (Postgres + Storage) | — | Not deployed from this repo; managed separately |
| Search API | [Serper.dev](https://serper.dev) | — | Third-party, `live_fetch`-only |

The frontend is a static site (Vite build, no server-side code) — it must
never attempt to run catalogue operations without the backend reachable.
An earlier version of this document described deploying the frontend to
Vercel and the backend to Render via a `render.yaml` blueprint; neither is
used. Those configs (`vercel.json`, `render.yaml`, `worker.js`,
`wrangler.toml`) were dead leftovers from abandoned deploy attempts and
have been removed from the repo.

## Backend (Railway)

The repository's [`Dockerfile`](../Dockerfile) is what Railway builds —
there is no `railway.json`/`railway.toml`/`Procfile` in this repo; the
service and its GitHub-integration auto-deploy are configured directly in
the Railway dashboard (project `protective-vibrancy`, service
`specledger`). The container runs:

```
uvicorn backend.specledger.http_api:app --host 0.0.0.0 --port ${PORT}
```

Railway sets `PORT` itself; nothing else in the Dockerfile needs editing to
redeploy.

**Required Railway service variables** (see [README § Environment
variables](../README.md#environment-variables) for what each one does):

```text
DATABASE_URL=<Supabase Postgres connection string>
SPECLEDGER_API_KEY=<random secret — gates write endpoints>
SUPABASE_URL=<Supabase project URL>
SUPABASE_SERVICE_ROLE_KEY=<Supabase service-role key>
SUPABASE_STORAGE_BUCKET=specledger-artifacts
SERPER_API_KEY=<optional — enables live_fetch search fallback>
CORS_ORIGINS=https://yashasm18.github.io
ENVIRONMENT=production
```

All of `DATABASE_URL`, `SUPABASE_*`, and `SERPER_API_KEY` are optional at
the code level — the backend falls back to local SQLite / local disk /
skipped search when unset (see [Running locally](../README.md#running-locally)).
They're listed as required *here* because a production deployment without
them silently loses persistence, object storage, and live source
discovery rather than failing loudly.

**To deploy a change:** push to `main`. Railway's GitHub integration picks
it up automatically — no manual trigger needed. Confirm it landed:

```bash
curl -s https://specledger-production.up.railway.app/health
```

**If Railway's GitHub auto-deploy stops working** (this happened once
during development due to a real, external Railway/Google Cloud
infrastructure incident — check https://status.railway.com first), deploy
directly from local code instead:

```bash
railway link   # select project protective-vibrancy, service specledger
railway up --detach
```

## Frontend (GitHub Pages)

Deploys automatically via [`.github/workflows/gh-pages.yml`](../.github/workflows/gh-pages.yml)
on every push to `main` that touches `frontend/**`. The workflow builds
with Vite and publishes `frontend/dist` to GitHub Pages — there is no
separate hosting account or CLI step to run.

The build needs two values, set as **repository variables/secrets** in
GitHub (Settings → Secrets and variables → Actions), not as local `.env`
files:

```text
VITE_API_URL   (variable) = https://specledger-production.up.railway.app
VITE_API_KEY   (secret)   = <same value as backend SPECLEDGER_API_KEY>
```

`VITE_API_KEY` is baked into the shipped JS bundle at build time — GitHub
Pages is a static host, so this is readable by anyone who opens dev tools.
It is not a real secret in the security sense; it deters casual/scripted
abuse of the write endpoints, not a determined reader of the bundle. See
[SECURITY.md](../SECURITY.md) for the full note.

**To deploy a change:** push to `main` with frontend changes. Watch it in
GitHub Actions, then confirm:

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://yashasm18.github.io/specledger/
```

## Post-deploy verification

After either side redeploys, verify the same things a judge running their
own data through the app would hit:

- `GET https://specledger-production.up.railway.app/health` returns `200`
- `GET .../catalogue/batches` returns JSON
- Uploading a spreadsheet via the dashboard creates a batch
- Review decisions (approve/reject) persist after a page refresh
- CSV/252-column exports download correctly
- Load the site fresh and click around within the first 2–3 seconds —
  this is the Railway cold-start window and has surfaced real bugs before
  (see the main README's disclosed-limitations notes)

If the API is unreachable, the frontend reports the failure — it does not
fall back to generating substitute product specifications, evidence,
approvals, or exports.
