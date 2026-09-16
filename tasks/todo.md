# Deploy: backend → Railway, frontend → Vercel (git-connected)

## Architecture
- **Backend** (`src/digital_brain`, uvicorn + Postgres/pgvector, fastembed ONNX embeddings) → Railway.
- **Frontend** (`ui/`, Vite SPA) → Vercel. `/api/*` rewritten to the Railway backend (same-origin, no CORS).
- Both connected to GitHub repo `ochieng-stephen/digital-brain` for push-to-deploy.

## Production-readiness code changes (local, committed)
- [ ] `http_server.py`: bind `0.0.0.0` and read `$PORT` (Railway); keep `127.0.0.1` locally.
- [ ] `http_server.py`: idempotent `_ensure_seeded()` on boot — init schema + seed both demo brains only when the DB is empty.
- [ ] `Dockerfile` (python:3.13-slim + uv, `uv sync --frozen`, CMD `digital-brain-http`).
- [ ] `.dockerignore` (exclude ui/, .venv, caches, screenshots).
- [ ] `railway.json` — Dockerfile builder + `/health` healthcheck.
- [ ] `ui/vercel.json` — SPA + rewrite `/api/:path*` → `https://<railway-domain>/:path*`.

## Railway (backend)
- [ ] `railway init` (project: digital-brain).
- [ ] Provision Postgres **with pgvector** (verify `CREATE EXTENSION vector`; fall back to pgvector image if absent).
- [ ] Backend service var `DATABASE_URL = ${{Postgres.DATABASE_URL}}`.
- [ ] `railway up` (build Dockerfile) → `railway domain` (public URL).
- [ ] Verify `/health` returns `{ok:true, engrams:N}` (seed ran).
- [ ] Connect GitHub repo for push-to-deploy (dashboard step if not CLI-able).

## Vercel (frontend)
- [ ] Put the Railway domain into `ui/vercel.json` rewrite; commit.
- [ ] `vercel link` (root dir `ui`, framework Vite) + `vercel git connect`.
- [ ] `vercel --prod` deploy; verify the live app loads brains from the backend.

## Verify end-to-end
- [ ] Live Vercel URL: think / recall / memories all hit the Railway backend.
- [ ] Push a trivial commit → both auto-deploy.

## Review
(to fill in)
