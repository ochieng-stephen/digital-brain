# Restore per-domain reset (regression from the sandbox refactor)

## Problem
`/reset` was rewritten in the sandbox refactor (`36c9d5e`) to wipe+re-clone the WHOLE session and
stopped reading the request body. So "Reset this brain (Dr. Demo)" and "Reset all brains" became
identical — "this brain" misleadingly wipes the visitor's legal sandbox too. Pre-sandbox, `scope`
was honored ("brain" kept the other domain; "all" reset both).

## Fix (backend only; UI/api already send {scope, brain})
- [x] Factor the sandbox clone/wipe to take a brain list: `_clone_brains(conn, sid, brains)` +
      `_wipe_brains(conn, sid, brains)`; keep `_clone_template`/`_wipe_session` as full-set wrappers
      (middleware provisioning path unchanged).
- [x] `_domain_chain(brain)` → the two template brains for one domain's chain (domain + individual),
      EXCLUDING the shared base (base is shared by both chains and users only ever write to the
      individual layer, so a single-domain reset must leave base + the other domain intact).
- [x] Rewrite the `reset` endpoint: read `scope` (default "brain") + `brain`; reset `TEMPLATE_BRAINS`
      when "all", else `_domain_chain(brain)`. Keep the sessions row alive (bump last_seen), don't
      touch the rate counter.
- [x] Verify against local Postgres: teach medical + legal, reset "brain" (medical) → medical clean,
      legal memories kept, base intact; reset "all" → both clean. Cross-session isolation unaffected.

## Review
Backend-only fix (`src/digital_brain/http_server.py`); UI/api untouched since they already POST
`{scope, brain}`.

- Split the sandbox clone/wipe into brain-list-parameterized primitives `_clone_brains` /
  `_wipe_brains`; `_clone_template` / `_wipe_session` now delegate with the full `TEMPLATE_BRAINS`
  set + the sessions-row handling, so the middleware provisioning path is byte-for-byte unchanged.
  `_wipe_brains` deletes events/cycles/trust by exact scoped brain_id (all logged under the acting
  brain) instead of a `%#sid` LIKE — equivalent over the full set, precise for a subset.
- `_domain_chain(brain)` returns the domain+individual template pair for the selected brain (substring
  match, medical default), deliberately EXCLUDING the shared `base` — users only ever write to the
  individual layer, and base is shared by both chains, so a single-domain reset leaves it alone.
- `reset` now honors `scope`: `all` → both domains; `brain` (default) → only the selected chain,
  keeping the other domain's memories and the shared base. Session stays live (bump `last_seen`);
  the rate counter is left intact (only the TTL sweep drops it).
- Verified at the function level against local Postgres (16/16 checks): full provision (26 engrams,
  both domains); after a medical `scope='brain'` reset the medical taught memory + its event are
  gone while the legal memory + event and `base#sid` remain, the medical chain is re-cloned with a
  correct parent link, and the session stays live; `scope='all'` then wipes the legal memory too and
  restores the pristine 26-engram baseline; teardown removed the throwaway sandbox cleanly.
- Deploy note: backward-compatible standalone backend change (old UI without the params defaults to a
  medical-chain reset), so it doesn't trip the X-Session deploy-coupling rule — but not yet committed.

---

# Per-visitor sandbox brains (public LinkedIn launch)

## Goal
Make the deployed `digital-brain` demo safe to hand to the public. Today it's one shared brain
with open, unauthenticated write/reset endpoints — anyone can reset or vandalize what everyone
sees. Fix: **each visitor gets their own isolated copy of the demo brains**, so nobody can affect
anyone else, and full interactivity (think → reflect → consolidate → reset) stays safe.

## Approach (minimal, within the existing Postgres store)
- A visitor gets a random **session id** (`sid`, hex). The browser mints it once, stores it in
  `localStorage`, and sends it as an `X-Session` header on every request.
- Server namespaces brains by suffix: `base#<sid>`, `domain:emergency_medicine#<sid>`,
  `individual:dr_demo#<sid>`, `domain:legal_contract_review#<sid>`, `individual:lawyer_demo#<sid>`.
- **Lazy provisioning**: first request carrying a new `sid` clones the pristine template brains
  into that namespace. Clone = `INSERT ... SELECT` of the template engrams with fresh uuids and
  plasticity counters reset (`salience := base_salience`, counts := 0) so every session starts
  identical and clean — regardless of any drift on the template. No associations/events exist on a
  pristine template, so **no uuid-remapping is needed**.
- **Forced scoping (the isolation guarantee)**: the server ignores whatever brain the client sends,
  takes only its canonical part, and re-appends the caller's `sid`. A visitor therefore can never
  address another session's brains or the unsuffixed template — every think/remember/consolidate/
  reset/promote/sleep/rewind/audit/memories/graph/trust acts only inside their own sandbox.
- **TTL cleanup**: a `sessions(sid, created_at, last_seen)` table; on each request, lazily sweep a
  few sessions older than 6h — delete their brains (cascades engrams → associations) plus their
  events/cycles/trust rows (reuse the existing `_wipe_brains` pattern). Keeps Postgres bounded.

## Plan
- [ ] **schema.sql**: add `sessions(sid TEXT PK, created_at, last_seen)`.
- [ ] **http_server.py**:
  - [ ] `_valid_sid(sid)` strict regex (`^[a-f0-9]{8,64}$`) — guards all SQL id/LIKE building.
  - [ ] `ensure_session(sid)`: if unprovisioned, clone template → `#sid`; upsert `sessions.last_seen`.
  - [ ] `_scope(brain_or_none, sid)`: canonical-part + `#sid` (forced scoping helper).
  - [ ] `_sweep_expired(limit)`: delete a few sessions past TTL (brains + events/cycles/trust).
  - [ ] Middleware (or per-endpoint first line): read+validate `X-Session`, `ensure_session`,
        `_sweep_expired`, stash `sid` on `request.state`; reject requests with a missing/invalid sid.
  - [ ] Apply `_scope(...)` to every endpoint's `brain` (replaces the `individual:dr_demo` defaults).
  - [ ] `/brains`: list only this session's individuals (labels/theming still work — suffix keeps
        the `lawyer`/`dr` substring the UI themes on).
  - [ ] `reset`: reset only the caller's session (re-clone its namespace); drop global reset.
  - [ ] `_ensure_seeded`: unchanged (seeds the template once when the DB is empty).
- [ ] **Rate limiting** (rolled in): in-process sliding-window limiter in `http_server.py`.
  - [ ] Per-session cap on heavy endpoints (think/recall/remember/consolidate/reflect/sleep/rewind):
        ~25 / 60s → HTTP 429 + `Retry-After`.
  - [ ] Global heavy cap (~90 / 60s) to protect the shared Railway CPU during a traffic spike.
  - [ ] Global new-session/provision cap (~40 / 60s) so rotating sids can't force a clone flood.
  - [ ] Cheap reads (health/brains/memories/graph/audit) stay unthrottled.
- [ ] **ui/src/lib/api.ts**: mint/store `sid` in `localStorage`; inject `X-Session` in `req()`;
      surface a friendly message on 429.
- [ ] **ui/src/App.tsx**: no logic change expected (brain ids come from `/brains`, already scoped);
      verify theming + domain switch still key off the returned ids.
- [ ] **Railway uptime (rolled in)**:
  - [ ] `railway status` / plan + credits check via CLI; report whether the service will stay up.
  - [ ] Harden `railway.json` restart policy for a public post (raise retries / ALWAYS).
- [ ] **Verify**: two different `sid`s see independent state (reset in one doesn't touch the other);
      a request with no/garbage `sid` is rejected; TTL sweep removes an aged session; UI loads,
      Think/Reflect/Consolidate/Reset all operate on the visitor's own sandbox; 0 console errors.
- [ ] **Deploy**: commit + push (Railway backend + Vercel frontend redeploy from git).
- [ ] Security pass on deps (CVEs) per workflow rule 11.

## Residual (noted, negligible for a demo)
- Cycle/engram-id endpoints (`check/reflect/edit/forget/explain`) key off unguessable random uuids
  created inside the caller's session. Cross-session tampering would require guessing another
  visitor's uuid (not enumerable, never exposed cross-session), so brain-scoping covers the real
  vandalism vector. Full per-request engram-ownership checks are deferred as over-engineering.

## Review
Made the deployed demo safe to launch publicly by giving **every visitor their own isolated
brain sandbox**, plus rate limiting and Railway uptime hardening.

- **Isolation**: a browser-minted `X-Session` id namespaces each visitor's brains as
  `<canonical>#<sid>`; first request clones the pristine template (INSERT…SELECT, fresh uuids,
  counters reset). The server **forces every request into the caller's own namespace**, so a
  visitor can never touch another sandbox or the template — verified: session A writing via
  session B's brain id left B untouched.
- **Cleanup**: `sessions` table + a lazy 6h TTL sweep (deleting brains cascades engrams →
  associations; events/cycles/trust removed by suffix). Verified an aged sandbox is fully removed
  and a live one is spared. Keeps Postgres bounded.
- **Rate limiting**: sliding-window, per-session 25/60s + global 90/60s on heavy endpoints, plus a
  40/60s provisioning cap against sid-rotation clone floods → HTTP 429. Verified 25 pass / 5 reject.
- **Reset** now resets only the caller's own sandbox (wipe + re-clone), never global.
- **Frontend**: `lib/api.ts` mints/persists the sid and sends `X-Session` on every request (one
  place), with a friendly 429 message; bootstrap reordered so provisioning precedes the count read.
- **Railway**: confirmed service up (latest deploy SUCCESS, /health 200); raised restart retries 3→10.
- Verified end-to-end against a local Postgres: session validation (400), provisioning, cross-session
  isolation, forced-scope security, reset-to-pristine, rate limiting, TTL sweep. UI builds clean.

### Deploy + live verification (DONE)
- Backend: `railway up` (Railway is NOT git-connected — manual deploy each time). Deploy
  `6b677ca2` SUCCESS; live `/brains` without a session → 400 = new code confirmed.
- Frontend: git push auto-built on Vercel, but the custom aliases were **pinned to the old
  deployment** and didn't follow — briefly served "Brain offline" until re-aliased. Re-pointed
  `digital-brain-app` + `digital-brain-ai` to the new deployment with `vercel alias set`.
- Live end-to-end (Playwright on digital-brain-app.vercel.app): fresh visitor mints a session,
  provisions a pristine 26-engram sandbox (6 medical memories), runs the full think cycle
  (SLOW · SYSTEM 2 · conf 0.679, 6-step playbook, 4 hard rules), logs to audit, subtitle is clean
  ("individual:dr_demo", no #sid leak) — **0 console errors**.
- Security review: no dependency manifests touched → runtime dep surface unchanged; the change
  itself is a hardening (session isolation + forced scoping + rate limiting + strict sid validation).

### Operational gotchas for future updates (owner)
- **Vercel custom aliases do NOT auto-follow git deploys** — every frontend redeploy needs
  `vercel alias set <new-deployment> digital-brain-app.vercel.app` (and `-ai`), or set them as the
  project's Production Domains in the dashboard so they auto-update.
- **Railway is git-connected** — pushes to `main` auto-deploy the backend (watch paths limit rebuilds
  to backend files: `/Dockerfile`, `/railway.json`, `/pyproject.toml`, `/uv.lock`, `/src/**`);
  `railway up` still works for a manual deploy. `/health` returns the live commit sha.
- **Deploy order matters**: the backend now REQUIRES X-Session, so always get the new frontend live
  (and aliased) right after a backend deploy, or the site shows "Brain offline" in the gap.
- Railway **plan/credits**: CLI exposes no billing — confirm in the dashboard the service has enough
  credit to stay up for the launch (a dead backend = a broken link).
