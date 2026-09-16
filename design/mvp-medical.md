# Digital Brain — MVP Scope: Doctor (Medical Field)

> Status: scope draft (build not yet started — awaiting go-ahead) · Last updated: 2026-09-14
> Companions: [data-model.md](./data-model.md), [plasticity-engine.md](./plasticity-engine.md), [thought-cycle-protocol.md](./thought-cycle-protocol.md)

## Goal

The thinnest end-to-end vertical that proves the full thought cycle for **one doctor, one
complaint class**, running **entirely locally**. Success = the loop demonstrably works and a
model can be swapped without changing how the brain reasons.

## Safety framing (read first — this is medical)

This MVP is **clinical decision *support*, not a diagnostic device**. Non-negotiable:

- It augments a physician's reasoning; a licensed clinician is always in the loop.
- It never outputs a definitive diagnosis or a directive to act — it produces the doctor's
  *reasoning approach* (differential-building method, workup structure) for the doctor to judge.
- Autonomy is fixed at **`gated`** for the MVP (Constitution is always gated regardless). No
  auto-applied memory changes in a medical context.
- No real PHI: the demo uses synthetic vignettes only. No EHR integration in v1.

These constraints live *in the brain itself* as Constitution (below), so the system enforces
them, not just the docs.

## Domain choice: chest-pain workup

One region — **`chest_pain_workup`** — in one individual doctor's brain (optionally inheriting a
thin `domain:emergency_medicine` layer). Chest pain is ideal: high-stakes reasoning with clear
can't-miss diagnoses (great for Constitution), a strongly personal workup style (great for
procedural memory), and repetitive enough that consolidation has something to abstract.

## Local storage decision (local Postgres + pgvector — not Neon)

Per direction: **provision locally on the laptop, not Neon.**

- **Postgres + `pgvector`, running locally** (Homebrew `postgresql@16` + the `pgvector`
  extension, or a local Docker container). Matches the general data-model recommendation exactly
  — vectors, relational plasticity counters, association-graph traversal via recursive CTEs, and
  the append-only event log all in one engine, no adapter divergence.
- Local instance: database `digital_brain` on `localhost:5432`; connection via `DATABASE_URL`
  (defaults to the local instance). No hosted/Neon dependency.
- Keep storage behind a thin interface anyway, so a later move to hosted Postgres/Neon for
  multi-user is a config change, not a rewrite.

## Seed engrams (hand-authored for the demo)

- **1 procedural** — *"Approach to chest pain"*: `steps` = [structured history (OPQRST + cardiac
  risk factors), targeted exam, ECG within 10 min, risk-stratify (HEART score), serial troponin,
  build differential can't-miss-first].
- **~4 semantic** — condition notes for ACS, PE, aortic dissection, GERD (features that
  discriminate them).
- **3 value / hard (Constitution)** — see below.
- **2 value / soft (Instinct)** — see below.
- **2–3 episodic** — synthetic past cases, seeded so consolidation has raw material.

### Constitution (hard — enforced by `brain.check`)

1. Never present output as a definitive diagnosis; frame as decision support requiring physician
   judgment (must include the disclaimer).
2. For chest pain, always include the can't-miss differentials: **ACS, PE, aortic dissection,
   tension pneumothorax, esophageal rupture**.
3. Never suggest ruling out ACS without **ECG + serial troponin**.

### Instinct (soft — always-on defaults)

1. Take a structured history first (OPQRST).
2. Surface red-flag findings prominently and document the reasoning.

## Interface

- **Core as a local library** with a thin storage adapter (SQLite now, Postgres later).
- **CLI** to demonstrate the loop directly (`brain think`, `brain reflect`, `brain consolidate`,
  `brain recall`) — fastest way to prove it, mirrors the design-context-engine pattern.
- **Local MCP server** exposing the tool surface so a real model (e.g. Claude) can drive the
  loop end-to-end and prove model-agnosticism.

## Scope

**In (v1):** one brain, one region, the 3 core calls (`think`/`check`/`reflect`) + `recall`,
local SQLite store, seed engrams, inline reinforcement, a **manual** `consolidate` command,
prompt-injection integration mode, MCP server.

**Out (v1):** multi-user, hosted DB, EHR/PHI, autonomy levels above `gated`, the trust ramp,
background cron jobs, rewind UI, spreading-activation tuning, the domain-layer marketplace.

## Demo / success criteria

1. **`think`** on *"45yo male, chest pain radiating to left arm, diaphoretic"* returns a
   CognitionPacket with the doctor's workup playbook + can't-miss constraints (slow path).
2. The model drafts a structured differential following the scaffold. **`check`** *blocks* an
   output that omits a can't-miss dx or lacks the disclaimer, and *passes* a compliant one.
3. **`reflect`** with a positive outcome visibly raises the fired engrams' `salience` and
   strengthens the procedural↔episodic edge.
4. Feed 5 similar synthetic episodes, run **`consolidate`** → a refined *"Approach to chest
   pain"* playbook appears as a **draft** for the doctor to approve (never auto-applied).
5. **Swap the model** (different provider) → `think` returns the *same packet* → same reasoning.
   *(The money demo — proves the thesis.)*

## Build milestones (checklist — to start after go-ahead)

- [ ] Scaffold project + local Postgres (`pgvector`) store behind a storage interface
- [ ] Engram/association/event schema + migrations
- [ ] Seed loader (the hand-authored chest-pain engrams above)
- [ ] Retrieval: embedding + activation-score recall (LLM-free)
- [ ] `brain.think` → CognitionPacket (fast/slow routing)
- [ ] `brain.check` → Constitution enforcement
- [ ] `brain.reflect` → reinforcement + episodic write + event-log append
- [ ] `brain.recall` (introspection)
- [ ] Manual `consolidate` (cluster episodes → draft procedural)
- [ ] CLI wrapper
- [ ] Local MCP server exposing the tool surface
- [ ] Demo script running all 5 success criteria

## Tech stack (proposed)

Python (Homebrew); local **Postgres + pgvector** for the store; embeddings via a **local**
embedding model (e.g. `fastembed` / `sentence-transformers` — retrieval only, not an LLM, no API
key). MCP server via the Python MCP SDK. Model access for the demo/consolidation is
bring-your-own — the brain core never hardcodes a provider.
