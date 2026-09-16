# Digital Brain — MVP Build (chest-pain vertical)

Design locked in `design/` (data model, plasticity engine, thought-cycle protocol, MVP scope).

## Plan / checklist

- [x] Provision local Postgres + pgvector, create `digital_brain` DB
- [x] Scaffold uv project + thin storage interface
- [x] Engram / association / event schema + init
- [x] Seed loader (3-layer chest-pain brain)
- [x] Retrieval: local embeddings + activation-score recall
- [x] `brain.think` → CognitionPacket (fast/slow routing)
- [x] `brain.check` → hard-Constitution enforcement
- [x] `brain.reflect` → reinforcement + Hebbian edges + episodic write + event log
- [x] `brain.recall` (introspection)
- [x] `brain.consolidate` (episodes → draft procedural, gated)
- [x] CLI wrapper (`brain`)
- [x] Local MCP server (5 tools)
- [x] Demo script (all 5 success criteria pass)

## Review

**What was built.** A working, local, model-agnostic cognition layer for one doctor's
chest-pain workup. Postgres+pgvector store of typed *engrams* with plasticity fields and a
Hebbian graph; an engine implementing the 6-step thought cycle; a CLI and an MCP server as
interfaces. Safety is encoded as hard-Constitution value engrams that `check` enforces.

**Verified behavior (demo.py, all pass):**
1. `think` → slow path, "Approach to chest pain" playbook + 4 hard rules across 3 layers.
2. `check` blocks a non-compliant draft (3 violations incl. the individual's HEART-score rule)
   and passes a compliant one.
3. `reflect` raises the playbook salience (0.80 → 0.85), strengthens 15 edges, writes an episode.
4. 5 repeated cases → `consolidate` drafts a refined playbook (`status=draft`, gated).
5. Model-swap parity: one packet, two "models", both compliant — identity independent of model.

**Notable decisions / fixes.**
- Local store = **Postgres + pgvector** (per direction, not Neon). pgvector's Homebrew bottle
  only ships @17/@18, so it was **compiled from source against the running @14** (leaves the
  user's 9 existing DBs untouched).
- `mcp` 2.x renamed `FastMCP` → `MCPServer`; updated import (decorators/`run` unchanged).
- pgvector 0.5.0 returns a `Vector` object on read → added a `_to_np` coercion.
- Deliberate step now selects the playbook via a **dedicated procedural lookup** so it can't
  be crowded out of a mixed top-k recall once many episodes exist.
- Constitution `check` is **deterministic** (require_all / require_any / require_if term specs)
  — fast, free, reliable; an LLM judge could augment it later.

**Security check (2026-09-14).** Starlette CVE-2026-48710 → patched (have 1.6.0 ≥ 1.0.1;
server also runs stdio). pydantic CVE-2026-25580 → affects `pydantic-ai`, not `pydantic`;
not affected. urllib3 CVE-2026-21441 (DoS) → transitive, only during one-time model download;
low risk, monitor. **No critical action required.**

## Iteration 2 — sleep jobs + trust ramp

- [x] Sleep job: engram salience decay, edge decay, prune faded engrams + weak edges (values never pruned)
- [x] Trust ramp: `trust` table, `review` (approve/reject drafts), `promote` (apply suggestion), auto-demote on reject burst
- [x] Earned autonomy flips the `consolidate` gate (guarded/autonomous → drafts auto-activate)
- [x] CLI (`sleep`/`review`/`trust`/`promote`) + 4 matching MCP tools (9 total)
- [x] Verified end-to-end + demo regression still green

**Review.** `Brain.sleep()` runs decay (salience → base, edges by half-life) then pruning
(`salience < 0.05`, never `value` engrams; soft-deletes to `status=pruned`, reversible via the
event log). The trust ramp records per-region review stats; 5 reviews at ≥80% accept suggests a
promotion, `promote` applies it, and a 2-of-last-3 reject burst auto-demotes one level. Promotion
lifts the gate so `consolidate` writes `active` instead of `draft`. Verified: decay 0.6→0.168,
junk pruned while a low-salience Constitution rule survived, gated→guarded→(auto-apply)→gated.
No new dependencies added, so no new CVE surface beyond iteration 1's scan.

## Iteration 3 — explain + audit + rewind (audit/undo)

- [x] `explain(engram)`: provenance (source, consolidated-from cases), top associations, event timeline
- [x] `audit(brain)`: recent human-readable event journal
- [x] `rewind(brain, steps|to_event_id)`: per-event structural undo, itself logged
- [x] CLI (`explain`/`audit`/`rewind`) + 3 MCP tools (12 total)
- [x] Verified: undo of consolidate/review(+trust)/promote/sleep-prune; explain timeline; demo regression green

**Review.** `explain` traces one engram's provenance and every event that touched it (scanning
across brains, since a lower-layer engram is reinforced by events logged under the acting brain —
fixed a bug where a brain-scoped scan missed these). `rewind` applies per-event inverses for the
**structural** events (prune created engrams/episodes, restore reviewed status + trust, revert
autonomy level, un-prune sleep-pruned engrams), newest-first, by `--steps` or `--to <event_id>`.
It deliberately does **not** restore continuous salience/edge weights (not snapshotted; they
self-heal via decay/reinforcement), and it is itself logged — history is append-only and never
lost. This is the audit/undo story that makes autonomous mode defensible.

## Iteration 4 — rewind niceties + end-to-end MCP agent

- [x] `rewind` by `--cycle <cycle_id>` (undo a whole cycle) and `--dry-run` preview (no mutation, not logged)
- [x] CLI `--cycle`/`--dry-run` + MCP `cycle_id`/`dry_run` params
- [x] `examples/mcp_agent.py`: real stdio MCP client driving all 12 tools with a pluggable model
- [x] Verified: cycle rewind prunes only that cycle's episode; dry-run mutates nothing; agent exercises 12/12 tools

**Review.** rewind now scopes by steps / to_event_id / whole cycle, and previews with dry_run
(returns the would-undo actions without mutating or logging). `examples/mcp_agent.py` connects to
the server over a genuine stdio MCP session and runs the full loop: think → check (with a real
guardrail retry — first draft omits the disclaimer, check blocks, the model revises from the
violation feedback, re-check passes) → reflect across 6 cases, then recall, consolidate, review,
trust, promote, sleep, explain, audit, and a dry-run rewind — 12/12 tools. The reasoning step is a
pluggable `Model`: `AnthropicModel` auto-activates when `ANTHROPIC_API_KEY` + the SDK are present,
else a deterministic scaffold-follower. No model credentials exist in this environment, so the
run used the stand-in; the MCP transport, tool dispatch, and cognitive loop are all real. No new
runtime dependencies (anthropic is optional/on-demand) → no new CVE surface.

## Iteration 5 — write tools (remember/edit/forget) + second domain (PLAN — awaiting approval)

Goal: close the two scoped next steps. Keep every change minimal and additive; do not
touch existing entrypoints (`seed.load`, demo.py, mcp_agent.py) so nothing regresses.

### WP-A — `remember` / `edit` / `forget` (a model refines memory before approval)
Today the model can only approve/reject a consolidated draft. These add the missing verbs
from the protocol, all write-gated and audit/rewind-able.

- [x] `Store.update_content(engram_id, content, embedding)` — the one new DB method.
- [x] `Brain.remember(brain_id, type, region, content, salience=0.5)` — propose a NEW engram.
      Blocks `type='value'` (models never author Constitution/Instinct). `source='model_proposed'`.
      Write gate: `draft` when region is `gated`, else `active`. Logs a `remember` event.
- [x] `Brain.edit(engram_id, patch)` — shallow-merge patch into content + re-embed.
      Blocks `value` engrams. Logs `edit` with `{before, after}` for exact revert.
- [x] `Brain.forget(engram_id)` — soft-delete (`status='pruned'`). Blocks `value` engrams
      (mirrors the prune invariant). Logs `forget` with `{before_status}`.
- [x] Wire into `rewind`: add the 3 kinds to `undoable` + `_undo_event`
      (remember→prune, edit→restore before-content+re-embed, forget→restore before-status).
- [x] `audit` briefs + `explain` timeline notes for the 3 new kinds (`_refs` already covers
      the `engram` key, so no change needed there).
- [x] CLI: `brain remember <type> <json>`, `brain edit <id> <json-patch>`, `brain forget <id>`.
- [x] MCP: 3 wrappers → **15 tools**.
- [x] Verify: remember a draft → edit its steps → review-approve; forget a semantic then
      rewind to restore it; edit then rewind restores content; value-write attempts are refused.
      **All 20 checks PASS** (`verify_writetools.py`).

### WP-B — second domain (exercise the base→domain→individual cascade across fields)
Proves portability: the SAME `base` brain + base Instinct sit under two unrelated domains,
each adding its own Constitution + playbook. **Chosen field: TBD (see check-in below).**

- [x] `src/digital_brain/seed_legal.py` — **legal contract review** (chosen). `load(reset=False)`
      seeds `domain:legal_contract_review` + `individual:lawyer_demo`, sharing `base`; `_ensure_base`
      inserts the base Instinct only if absent (insert-if-zero) — no duplication when seeded with medical.
- [x] CLI: `brain seed --domain medical|legal|all` (`all` = `seed.load(reset)` then
      `seed_legal.load(reset=False)`; `medical` stays the default → existing behavior unchanged).
- [x] Verify: `think`/`check` on a contract case builds the legal scaffold + enforces the legal
      Constitution (incl. the individual's stricter risk-rating red line), while the medical brain
      still recalls medical memories — both domains coexist under one base, base Instinct shared
      (exactly one base value engram). **All 12 checks PASS** (`verify_legal.py`).

### Wrap-up
- [x] README: documented the 3 new tools + `--domain` seeding; count updated 12 → 15; second-domain note.
- [x] Security recheck (2026-09-14): no new runtime deps → no new surface. Verified stdio-only usage
      dodges the new MCP transport CVEs; starlette 1.6.0 and urllib3 2.7.0 are both at patched versions.
- [x] Review section below.

## Iteration 6 — React UI (brain-centerpiece cockpit) — DONE

Build a premium, responsive React UI whose organizing principle is the supplied brain⇄chip
motif, recreated as an interactive inline SVG (raster can't light up / theme / animate).

- [x] Scaffold Vite + React + TS under `ui/` (minimal deps: react, react-dom, vite, typescript).
- [x] Design tokens + global CSS: light canvas, glass panels, neural accent, status colors,
      mono+sans roles, tabular-nums. (My own intentional palette; no store.)
- [x] `BrainCore.tsx` — bespoke interactive SVG, pixel-traced from the reference icon: organic
      hemisphere (LEFT) + chip & radiating circuit leads (RIGHT) + central SEAM. Breathing pulse,
      traveling synapse sparks (each on its own real lead), region glow clipped to the silhouette
      (no dot markers), seam flare. Energy scales with autonomy.
- [x] Data faithful to the real brain: port medical + legal seed memories + constraint `check`
      specs; port `_satisfies` (require_all/any/if/forbid) to TS so the Constitution check is REAL.
- [x] Panels mapped to anatomy: Think console (right/chip), Recall/Memories (left/organic),
      Constitution (seam), Autonomy dial (3-stop), Audit timeline (bottom), Domain switcher (top).
- [x] Wire the flow: think → signal into chip → brain regions light → Scaffold panel (playbook +
      recalled + hard/soft) → check draft → seam flares pass/violation → audit entry appended.
- [x] Responsive: works from wide desktop down to narrow; brain stays the star (now sized calmer,
      not dense — separate caption from art, no overlap).
- [x] `npm install` + `npm run build` clean; dev server verified.

**Review.** Delivered the brain⇄chip centerpiece as a real pixel trace of the user's reference
icon (potrace over a thresholded raster, not hand-drawn geometry), with every interactive overlay
— 6 recall regions, 8 synapse-spark leads, the Constitution seam — anchored to coordinates measured
directly off the traced silhouette (distance-transform + contour analysis), not eyeballed. Recall
activation reads as the gyrus fold itself glowing (clip-path'd to the brain shape, `mix-blend-mode:
screen`) rather than a marker sitting on top. Iterated down from a dense, large, harsh-shadowed icon
to a smaller, softer-shadowed, slower-animating one after user feedback that it felt too busy —
size, shadow spread, and animation cadence were all reduced together to read as calmer without
losing the "alive" quality. No new deps; build stays clean throughout.

## Iteration 7 — full lifecycle features — DONE

**Why.** The UI (Iteration 6) is a client-side simulation, faithful to `engine.py`'s `think`/`check`
only. But the real engine — and the whole point of a "digital brain" — is the *rest* of the
protocol: a brain you can correct, that learns from outcomes, that earns autonomy rather than
having it toggled for free, and whose every consequential action is reviewable and undoable. Right
now none of that is reachable: Recall is a read-only list, the Autonomy dial is a free 3-way
toggle unconnected to any trust signal, and the audit ribbon is a dead log. For the target users —
**the domain expert** (Dr. Demo / counsel_demo) teaching and correcting their own brain, and
**an evaluator** trying to understand the trust/safety story — that gap is exactly where the
product's value lives. This plan closes it, still client-side (same architecture as Iteration 6:
faithful TS port of the engine's logic, no backend wiring), faithful to `engine.py` /
`config.py`'s actual constants (`CONSOLIDATION_MIN_CLUSTER=5`, `TRUST_PROMOTE_MIN_REVIEWS=5` @
`TRUST_PROMOTE_RATE=0.8`, `TRUST_DEMOTE_WINDOW=3` / `TRUST_DEMOTE_REJECTS=2`) so the sim behaves
like the real thing, not an invented approximation.

### Tier 1 — close the loop; make memory real (highest value)
- [x] **Reflect**: after a passing `check`, a "mark outcome" affordance (succeeded / didn't) in
      the Scaffold panel → bumps recalled memories' salience, strengthens their pairwise edges on
      success, and writes a new episodic memory into Recall. Logs a `reflect` audit event.
- [x] **Editable memory** — the Recall panel stops being read-only:
      - Add memory (`remember`): short concept + detail + cues → lands `active` if the region's
        autonomy is `guarded`/`autonomous`, else `draft` (into the Tier-2 review queue).
      - Edit (`edit`): inline patch to a memory's detail/cues, re-embeds (recomputes cues),
        logged before/after for exact revert.
      - Forget (`forget`): soft-delete (recoverable via rewind), never available on Constitution/
        Instinct rules (those stay in the separate Constitution panel, untouchable — mirrors the
        backend's hard `value`-type invariant).
- [x] **Explain**: click any memory or rule → small popover with provenance (human-authored /
      model-proposed / consolidated) + the event timeline that touched it.

### Tier 2 — earned autonomy, not a free toggle
- [x] **Trust meter**: replace the Autonomy dial's free click-to-any-level with a readout of the
      region's actual reviews/accept-rate, plus a **Promote** button that only appears once
      `reviews ≥ 5` at `≥80%` accept (exact `trust()` logic) — clicking calls `promote()`.
- [x] **Review queue**: a small panel listing `draft` engrams (from remember/consolidate) with
      Approve/Reject; approving feeds the trust meter, 2-of-last-3 rejects auto-demotes a level
      (mirrors `_maybe_demote`).
- [x] **Consolidate**: once ≥5 successful reflected episodes exist for the region, a "Consolidate"
      action drafts a refined playbook into the review queue.

### Tier 3 — audit as a safety instrument, not a log
- [x] **Rewind**: each undoable audit entry (reflect/remember/edit/forget/review/consolidate/
      promote/demote — the real `undoable` set) gets a "↺ undo" action that reverts exactly that
      event's effect (mirrors `_undo_event`) and logs a `rewind` event.

**Out of scope:** `sleep` (decay/prune maintenance) and a real backend/HTTP bridge — staying
consistent with Iteration 6's architecture (a faithful client-side port, same as `_satisfies`).

**Review.** New `ui/src/lib/brainState.ts` ports the rest of the protocol as pure functions —
`remember`/`edit`/`forget`, `reflect`, `consolidate`, `review`/`promote` (trust ramp), `rewind` —
using config.py's real constants (5 reviews @ 80% to promote, 5 episodes to consolidate, 2-of-3
rejects to demote) so the sim earns/behaves like the real engine, not an invented approximation.
`App.tsx` now holds one `RuntimeState` per domain (medical/legal), isolated and persistent across
domain switches — memory, trust, and audit history no longer reset when you tab away and back.

Recall is no longer read-only or gated behind a `think()` call: it always shows the domain's full
active memory set (highlighting whichever were just recalled), with a "Teach it something" input,
per-memory Edit/Forget, and a click-to-expand provenance/timeline ("Explain"). New/pending writes
land in a "Pending review" queue exactly where the backend would gate them (`draft` while
`gated`, `active` once `guarded`/`autonomous` is earned). The Autonomy dial is no longer a free
3-way toggle — it's a readout of actually-earned trust (reviews · accept-rate) with a **Promote**
button that only appears when the real threshold is hit; the same energy that drives the brain's
animation now reflects *earned*, not clicked, autonomy. Every consequential audit entry gets a
↺ rewind affordance that reverses exactly that action (including restoring the correct trust
counters and autonomy level), matching `_undo_event`'s per-kind semantics.

Fixed one small bug found while building this: `think()`'s procedural-playbook lookup picked the
*first* procedural memory rather than the best-scoring one — harmless with a single seed playbook,
but wrong once `consolidate` can add a second, competing procedural. Now picks the top-ranked one,
mirroring the backend's dedicated `best_proc` search.

Verified end-to-end via a scripted Playwright run: 5×(think→check→reflect success) → Consolidate
enabled at exactly 5 → 5×(remember→approve) reaches 5 reviews/100% → Promote appears and advances
gated→guarded → a post-promotion `remember` lands `active` immediately (gate flipped correctly) →
forget removes a memory from Recall → rewind restores it, with a "rewound: restored" entry
appended to its own explain timeline → edit updates content in place → switching to Law and back
confirmed each domain's runtime state (memories/trust/audit) is fully isolated and persists.

**Security check (2026-09-14).** No new dependencies added (`package.json` untouched) — pure
additions to existing TS files. `npm audit`: 0 vulnerabilities.

## Iteration 8 — UI review: accessibility, layout, discoverability (IN PROGRESS)

A UI review turned up concrete gaps. Fixing A + B + C (approved full pass).

### A — accessibility & touch correctness (bugs)
- [ ] Per-memory Edit/Forget/Explain are `opacity:0` until hover → unreachable on touch and don't
      reveal on keyboard focus. Make always-visible on touch (`@media (hover:hover)` gates the
      hide) and reveal on `:focus-within`.
- [ ] No visible focus ring anywhere → add a branded `:focus-visible` outline for all interactives.
- [ ] Icon buttons (✎ ✕ ?, ↺) expose only `title`, no `aria-label` → add explicit labels.
- [ ] `--ink-3 (#8a919c)` ≈3.4:1 on white (fails AA) → darken to ~4.5:1.

### B — layout & visual polish
- [ ] Desktop panels don't align (Recall top≈264 vs Scaffold top≈96) — `.stage` centers each
      column independently → top-align the flanking panels, keep the brain centered.
- [ ] The reflect step (the learning-loop payoff) sits below the fold after a check, with a cryptic
      "outcome, once used" label → relabel, style as a callout, and scroll the verdict into view.
- [ ] Stale `theme-color #05060a` (dark) on a light app + missing favicon (404) → fix both.

### C — discoverability opportunities
- [x] Trust path is invisible → AutonomyDial shows progress-to-promote ("N/5 reviews…"), and the
      review queue carries a one-line explainer of how approvals earn autonomy.
- [x] Empty Scaffold panel is a bare stub → add a compact legend of what a scaffold delivers
      (playbook · recalled memories · constitution).

## Iteration 9 — usability + full-capability coverage (Tier 1 + 2) — DONE

A capability review found the UI embodied the human-facing lifecycle but omitted things that
block real value / undersell the thesis. Approved Tier 1 + 2 (client-side; Tier 3 model-in-loop
deferred).

### Tier 1 — unblock practitioner value
- [x] **Persistence**: serialize per-domain `RuntimeState` to localStorage; hydrate on load; a
      taught brain survives refresh (today it's wiped). Guard bad/old payloads.
- [x] **Reset**: a per-domain "reset to seed" control (persistence makes this necessary).
- [x] **Copy scaffold**: serialize the CognitionPacket (playbook + recalled + hard/soft) to text →
      realizes the protocol's prompt-injection mode (hand the scaffold to any model).

### Tier 2 — embody the hidden capabilities (still client-side, faithful to engine.py)
- [x] **Fast vs slow path**: stop hardcoding `path:"slow"`. Add a stakes control (routine/high);
      route fast when a playbook matches at high confidence AND stakes=routine (mirrors
      `FAST_PATH_SIM=0.80` / `FAST_PATH_STAKES={low}`); fast path shows a trimmed scaffold + a
      System-1 indicator.
- [x] **Association graph / spreading activation**: add Hebbian `edges` to `RuntimeState`;
      `reflect(success)` wires co-recalled pairs; `think` boosts recall from those edges (a memory
      wired to a hit can surface without a keyword match); mark association-surfaced memories.
- [x] **Standalone recall**: a read-only "search what I know" query in the Recall panel (the
      `recall` introspection verb), separate from `remember`.
- [x] **Explain associations**: the Explain popover lists a memory's strongest wired associations
      (mirrors `engine.explain`), not just provenance + timeline.
- [x] **Richer rewind**: a dry-run preview — the rewind control states the exact effect it will
      apply before you commit (mirrors `--dry-run`).

**Review.** Two files did the heavy lifting: `brainState.ts` gained a Hebbian `edges` graph
(wired by `reflect` on success, `associationsFor` for readback, `pairKey` helper) and a
non-mutating `rewindPreview` (the `--dry-run` analogue); `cognition.ts`'s `think` now takes
`{stakes, edges}` and does real fast/slow routing (`FAST_PATH_SIM=0.8`, low-stakes only, fast
path trims recall to 2) plus spreading activation (a memory wired to a hit surfaces without its
own keyword match, tagged `via:"assoc"`). `App.tsx` persists per-domain runtime to localStorage
(hydrate-on-load with a shape guard; a taught brain now survives refresh), adds a reset, a
"Copy for your model" button that serializes the CognitionPacket to text (prompt-injection mode),
a stakes toggle, a standalone recall search, association chips in Explain, a "linked" marker on
association-surfaced memories, and a dry-run title on every rewind.

Verified in-browser (scripted): stakes high→slow (4 recalled) vs routine→fast (2 recalled) at
conf 0.85; `reflect` reports `+1 edges` and Explain shows "wired to: Playbook · chest pain 0.3";
recall search "clot lungs" → 1 of 7, top = Pulmonary embolism; Copy produced a full scaffold with
a `## Constitution` section; rewind title read "will delete the written episode"; and a taught
episode **survived a full page reload** (Recall 6→7 persisted) — the gap that previously wiped
everything. Build clean; `npm audit` 0 vulns; no new dependencies.

**Honest boundary (Tier 3, deferred).** The UI still has no model in the loop — the draft is
canned and "Copy for your model" is the bridge to prompt-injection mode, but true bring-your-own-
model / model-swap parity and connection to the real Postgres/MCP backend remain the architectural
next step, not built here.

## Iteration 10 — live client + visual plasticity graph — DONE

The React UI has been a faithful client-side *simulation*, not a client of the live brain. Make it
a real client of the running engine (Postgres+pgvector, 26 engrams, both domains seeded), and
build an actual node-link plasticity graph (not the current text list).

Feasibility confirmed: Postgres up; `digital_brain` DB has `individual:dr_demo` (emergency
medicine) + `individual:lawyer_demo` (legal) over a shared `base`; `store.associations_from()`
exists; associations table currently empty (graph grows as you reflect).

### A — HTTP bridge over the engine (browser can't speak stdio MCP)
- [ ] `src/digital_brain/http_server.py` — a thin Starlette (already a dep) app importing `Brain`,
      exposing JSON endpoints mirroring the tools: `GET /brains`, `POST /think`, `/check`,
      `/reflect`, `/recall`, `/remember`, `/edit`, `/forget`, `/review`, `/promote`, `/trust`,
      `/consolidate`, `/sleep`, `GET /explain/{id}`, `GET /audit`, `POST /rewind`, and a new
      `GET /graph?brain=` (nodes = active engrams, edges from `associations_from`). CORS on.
- [ ] `digital-brain-http` script in pyproject; document `uv run digital-brain-http`.
- [ ] Vite dev proxy `/api → http://127.0.0.1:8787` (no CORS pain in dev).

### B — UI becomes a live client
- [ ] `ui/src/lib/api.ts` — typed fetch client for the endpoints above; live engram/packet types
      matching the real JSON (UUID ids, typed `content`).
- [ ] Refactor `App.tsx` off the in-browser `brainState`/`cognition` sim onto async API calls;
      loading + error states; a clear **brain-online / offline** status indicator.
- [ ] Discover domains from `GET /brains` (reconcile `dr_demo` / `lawyer_demo`), don't hardcode.
- [ ] Map the real engram shapes into the Recall panel / editing / Explain (provenance from the
      live event log + real associations).
- [ ] Fallback behavior per the decision below.

### C — visual plasticity graph
- [ ] `ui/src/components/PlasticityGraph.tsx` — SVG node-link graph: nodes = memories (typed
      glyphs), edges = associations with **thickness ∝ weight**; nodes **light up / pulse** as
      they fire during a `think`; hover a node → highlight its edges. Fed by `GET /graph`.
- [ ] Placement per the decision below; keep it legible and on-brand (calm, not busy).

### D — verify end-to-end against the live brain
- [x] think→check→reflect on the real DB persists (edges appear in Postgres, graph grows);
      remember/edit/forget/review/promote/rewind hit the store; domain switch = real brains.
- [x] Security recheck (new dep surface from the HTTP server), build clean.

**Review.** The UI is now a real client of the live engine, not a simulation.
- `src/digital_brain/http_server.py` — a Starlette bridge (new `digital-brain-http` script) wrapping
  the real `Brain`: `/think /check /reflect /recall /remember /edit /forget /review /promote /trust
  /consolidate /sleep /explain /audit /rewind` plus `/brains`, `/memories`, and a new `/graph`
  (nodes = active engrams, edges from `associations_from`). One Brain per request; binds 127.0.0.1.
- `ui/src/lib/api.ts` — typed fetch client; `App.tsx` fully rewritten as an async live client
  (loading/offline gates, discovers brains from `/brains`, refreshes after every mutation). The
  in-browser sim (`cognition.ts`, `brainState.ts`, `data/brains.ts`) was **deleted** — single source
  of truth is the engine. Bundle shrank (176→168kB js).
- `ui/src/components/PlasticityGraph.tsx` — the visual graph the user asked for: a dedicated panel,
  a small deterministic force layout so wired memories cluster, edge thickness ∝ weight, nodes
  firing (accent + pulse) when recalled during a think. Fed by `GET /graph`.
- New brain art: the supplied pen-and-ink illustration embedded as the base image (its hatching/
  stippling can't be vectorised faithfully), with the interactive layer re-anchored to geometry
  measured off the drawing (silhouette clip-path trace, chip box, seam, terminals). Overlays kept
  restrained to suit the delicate art. Asset at `ui/public/brain-art.png`.

Verified against the running DB: think returns real packets (real pgvector `sim`); the medical +
legal brains load from `/brains`; a UI-driven check passed the live Constitution (seam flare); a
UI-driven reflect wrote a new episode (Recall 7→8) and 5 edges (graph 15→20), and the associations
table in Postgres grew 0→30 — real persistence. `npm run build` clean; `tsc` clean.

**Security (2026-09-14).** New Python deps starlette 1.6.0 (≥ patched CVE-2026-48710) + uvicorn
0.52.4. Bridge binds 127.0.0.1 only (not network-exposed), so the permissive dev CORS is local-only.
No new npm deps (net removal of the sim modules).

## Iteration 11 — fast/slow becomes instinct-driven (automatic), stakes toggle removed

Found a design↔code gap: the design (thought-cycle-protocol.md) intended the fast path to be an
*instinct* — a **high-salience, well-practiced procedure** matched with confidence — but the code
gated it on `top_sim ≥ 0.80` + a caller-set `stakes` flag, ignoring salience, and the 0.80 sim bar
made the live toggle effectively inert (real embeddings match at ~0.68, so it never went fast).

- `config.py`: `FAST_PATH_SIM 0.80 → 0.62` (reachable confidence floor); removed `FAST_PATH_STAKES`;
  added `FAST_PATH_SALIENCE = 0.85` (a procedure must be practiced past this to become instinctual;
  seed playbooks start at 0.80 so they deliberate until reinforced).
- `engine.py` `think`: path is now decided automatically — `fast` iff the matched playbook is
  instinctual (`salience ≥ FAST_PATH_SALIENCE`) AND `top_sim ≥ FAST_PATH_SIM`. `stakes` stays in the
  signature for the audit record but no longer routes.
- UI: removed the `routine/high` toggle (api.think drops the param); console shows "fast vs slow is
  automatic…". The path badge (`fast · System 1 · instinct`) is now meaningful.

Verified: practiced playbook (salience 0.888) → **fast**; fresh (0.80) → **slow** (so demo.py's
`assert path=='slow'` on a fresh seed still holds — no regression). UI shows the fast badge and the
toggle is gone. Build clean.
Possible follow-up: the fast path doesn't yet *trim* the recalled set (design says it should return
a minimal packet) — currently it's a routing label with the same recall.

## Iteration 12 — bug: multiple reflections on the same cycle

Reported: after reflecting ("Went well"), clicking "Check against constitution" again re-surfaced the
reflect button, allowing repeated reflection on one cycle (which would inflate salience + write
duplicate episodes). Two-layer fix:
- **UI** (`App.tsx` `doCheck`): removed `setReflected(false)` — reflection is once per *think* (cycle),
  not per *check*, so re-checking no longer re-opens the reflect step. `reflected` resets only on a
  new think / domain switch.
- **Backend** (`engine.py` `reflect`, defense-in-depth): made it idempotent per cycle — if a `reflect`
  event already exists for the cycle, it no-ops and returns `already_reflected: true` (no reinforce,
  no duplicate episode). Guards the CLI/MCP paths too, not just the UI.
Verified: UI re-check no longer resurfaces "Went well"; a second `/reflect` on a cycle returns
`reinforced 0, already_reflected true`.

## Iteration 13 — Settings drawer + per-brain reset + plasticity empty-state

- **Settings drawer** (`SettingsDrawer.tsx`, header ⚙): Connection (live status, engram count,
  Re-sync), This brain (label/id, base→domain→individual chain, live stats: memories / associations
  / audit / autonomy, region), Maintenance (**Run sleep** — first UI exposure of the decay/prune
  job), Replay walkthrough, and a red Danger zone with two-step-confirm **Reset this brain** /
  **Reset all brains**.
- **Per-brain reset** (bridge `POST /reset {scope:'brain'|'all', brain}`): deletes the target
  domain's events/cycles/trust then its `domain:`/`individual:` brains (cascades engrams→
  associations) and re-seeds that domain with `reset=False`, preserving the other domain and the
  shared base. Required hardening `seed.py` with a base-skip guard (insert base value engrams only
  if base has none) so re-layering doesn't duplicate the base Instinct — mirrors `seed_legal._ensure_base`.
  Verified: resetting medical left legal (playbook 0.850, its episode + edges) and base (1 value)
  intact; reset-all returns both to clean seed.
- **Plasticity empty-state fix**: the "no wiring yet" caption was absolutely positioned over the
  force-scattered nodes (overlap + poor legibility). Now the unwired graph lays nodes in a tidy
  centered row with the caption cleanly beneath (`.pgraph-hint`).

**Operational.** Two processes: `uv run digital-brain-http` (the bridge, needs Postgres +
seeded `digital_brain`) and `npm run dev` in `ui/` (Vite proxies `/api` → 127.0.0.1:8787). If the
bridge is down the UI shows a "Brain offline" card with the command to start it.

**Follow-ups (not done):** README/design-doc note for the HTTP bridge; wire `remember` to choose
memory type (currently always semantic); optional live `/recall` for the introspection search
(currently a client-side filter over the loaded set); a real model-in-the-loop is still external
(Copy-for-your-model + the MCP path remain the bring-your-own-model story).

## Iteration 5 — Review

**What was built.** Two additive changes, no existing entrypoint touched.

- **Write verbs `remember`/`edit`/`forget`** (`engine.py`, +`Store.update_content`). A model can now
  *propose* a new memory, *refine* an existing one (e.g. fix a consolidated draft's steps), or *retract*
  one — the protocol verbs the MVP was missing. All three are **write-gated** (a proposal lands as
  `draft` unless the region has earned `guarded`/`autonomous`), **audit-logged**, and **rewind-able**
  (`edit` snapshots before/after for an exact revert; `forget` records the prior status; `remember`
  un-does by pruning). Hard safety invariant: models **cannot author, edit, or forget `value` engrams**
  — the Constitution and Instinct stay human-owned. Surfaced as 3 CLI commands + 3 MCP tools (→ 15).
  Verified by `verify_writetools.py` (20/20), including all value-write refusals and dry-run non-mutation.
- **Second domain — legal contract review** (`seed_legal.py`). A lawyer's brain hung under the *same*
  `base` as the doctor's, proving the cognition layer is portable across unrelated fields. It adds its own
  hard Constitution ("informational, not legal advice; attorney review required"; "always flag uncapped
  liability + broad indemnification"; "don't advise signing without governing law + termination"), a
  contract-review playbook, and the individual's stricter risk-rating red line — while sharing the base
  Instinct (seeded once, not duplicated). `brain seed --domain medical|legal|all`. Verified by
  `verify_legal.py` (12/12): cascade, scaffold, Constitution enforcement, coexistence, shared base.

**Regression.** `demo.py` (all 5 medical criteria) and `examples/mcp_agent.py` (12/12 tools over stdio,
now against a 15-tool server) both remain green.

**Simplicity.** One new store method, three engine methods, one new seed module, thin CLI/MCP wrappers.
No schema change, no new dependency, no edit to `seed.load` / `demo.py` / `mcp_agent.py`.
