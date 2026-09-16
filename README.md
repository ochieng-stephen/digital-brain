# Digital Brain

A portable, **model-agnostic cognition layer**: the identity and *method of reasoning*
lives with the person/domain, not the AI model. Any model plugs in and reasons *like the
entity* — swap the model, keep the reasoning.

Full architecture in [`design/`](./design):
[data model](./design/data-model.md) ·
[plasticity engine](./design/plasticity-engine.md) ·
[thought-cycle protocol](./design/thought-cycle-protocol.md) ·
[MVP scope](./design/mvp-medical.md).

## What this repo contains

An MVP vertical: a **doctor's brain for chest-pain workup** (clinical decision *support*,
not a diagnostic device — a clinician is always in the loop; synthetic data only).

- **Store** — local Postgres + pgvector. Typed *engrams* (semantic / episodic / procedural /
  value) with plasticity fields, a Hebbian association graph, and an append-only event log.
- **Engine** — the thought cycle: `think` (→ CognitionPacket scaffold), `check` (hard
  Constitution enforcement), `reflect` (reinforcement + episodic write), `recall`,
  `consolidate` (episodes → draft playbook); memory-write verbs **`remember`/`edit`/`forget`**
  (write-gated, so a model can propose or refine a memory before a human approves it); plus
  background **`sleep`** (decay + prune) and a **trust ramp** (`review`/`trust`/`promote`) for
  earned per-region autonomy; plus **audit/undo** (`explain`/`audit`/`rewind`) over the
  append-only event log.
- **Interfaces** — a `brain` CLI and a local **MCP server** (15 tools) so any model can drive the loop.
- **Portable across fields** — the same `base` brain sits under multiple domains. Ships with two:
  a doctor's **chest-pain workup** and a lawyer's **commercial-contract review**, each adding its
  own Constitution + playbook while sharing the base Instinct (`brain seed --domain all`).
- **Safety-as-Constitution** — the disclaimer, the can't-miss differentials, and "no ruling
  out ACS without ECG + troponin" are enforced by `check`, not just documented.

## Prerequisites

- Local **Postgres** with **pgvector** (this repo built it against Homebrew `postgresql@14`).
- Python ≥ 3.13 and [`uv`](https://docs.astral.sh/uv/).
- `DATABASE_URL` (default `postgresql:///digital_brain`).

## Setup

```bash
uv sync                                   # install deps
uv run python -c "from digital_brain.store import Store; Store().init_schema()"
uv run brain seed --reset                 # seed the chest-pain demo brain (downloads embedder once)
uv run brain seed --domain all            # or: seed BOTH domains (medical + legal) under one base
```

Domains: `--domain medical` (default), `legal`, or `all`. To drive the lawyer's brain, pass
`--brain individual:lawyer_demo` to `think`/`recall`/etc.

## Usage

```bash
# CLI — state persists in Postgres, so cycle_id is shared across invocations
uv run brain think "45yo male, chest pain radiating to left arm, diaphoretic"
uv run brain check <cycle_id> "<draft output>"
uv run brain reflect <cycle_id> --step "12-lead ECG" --step "serial troponin"
uv run brain recall "clot in the lungs"
uv run brain consolidate

# Memory-write verbs — a model proposes/refines memory; write-gated (draft unless earned autonomy)
uv run brain remember semantic '{"concept":"Takotsubo","definition":"Stress-induced ACS mimic."}'
uv run brain edit <engram_id> '{"steps":["OPQRST history","12-lead ECG","serial troponin"]}'
uv run brain forget <engram_id>         # soft-delete (values are never forgotten); reversible via rewind

# Background plasticity + earned autonomy
uv run brain sleep                       # decay salience + edges, prune what faded (values kept)
uv run brain review <engram_id> --approve   # or --reject; accrues per-region trust
uv run brain trust                       # region level, review stats, promotion suggestion
uv run brain promote                     # apply a suggested promotion (gated -> guarded -> autonomous)

# Audit + undo (why the brain changed, and reverting drift)
uv run brain explain <engram_id>         # provenance + associations + event timeline
uv run brain audit                       # the recent event journal
uv run brain rewind --steps 1            # undo last structural change; also --to <event_id>,
                                         #   --cycle <cycle_id>, or --dry-run to preview

# Full end-to-end demo (all 5 success criteria)
uv run python demo.py

# MCP server (stdio) — point any MCP client at this command
uv run digital-brain-mcp

# End-to-end agent: drives all 12 tools over a real stdio MCP session
uv run python examples/mcp_agent.py
```

The agent's reasoning step is a pluggable `Model`. It uses a **real LLM automatically** if
`ANTHROPIC_API_KEY` is set and the SDK is installed (`uv add anthropic`); otherwise it falls back
to a deterministic scaffold-follower. Either way the MCP transport, tool dispatch, cognitive loop,
and guardrail retry are real.

### Use it live from Claude Code / Claude Desktop (recommended)

`.mcp.json` (project root) registers the server, so a real Claude drives the brain directly — no
API key needed:

```json
{
  "mcpServers": {
    "digital-brain": {
      "command": "uv",
      "args": ["run", "--directory", "<abs-path-to-repo>", "digital-brain-mcp"],
      "env": { "DATABASE_URL": "postgresql:///digital_brain" }
    }
  }
}
```

Then in Claude Code: run `/mcp` to approve/connect the `digital-brain` server (project MCP servers
require approval; restart Claude Code if it doesn't appear). The tools show up as
`mcp__digital-brain__brain_think`, `…_check`, `…_reflect`, `…_recall`, `…_consolidate`,
`…_remember`, `…_edit`, `…_forget`, `…_review`, `…_trust`, `…_promote`, `…_sleep`, `…_explain`,
`…_audit`, `…_rewind` (15). Optionally reseed first for a clean brain: `uv run brain seed --reset`
(or `--domain all` for both domains). Example prompt:

> Using the digital-brain tools, *think* about "68yo woman, sudden tearing chest pain to the back,
> BP differential between arms", *check* your draft against the constitution, then *reflect* the outcome.

### Scheduling the sleep job

`brain sleep` is idempotent and safe to run on a timer. Example cron entry (nightly):

```cron
0 3 * * *  cd /path/to/digital-brain && /path/to/uv run brain sleep >> ~/.digital-brain-sleep.log 2>&1
```

## Layout

```
src/digital_brain/
  config.py        # temperament knobs + retrieval weights
  models.py        # Engram, CognitionPacket, Outcome
  embeddings.py    # local fastembed (retrieval only — no LLM, no API key)
  schema.sql       # Postgres + pgvector schema
  store.py         # thin storage interface (Postgres today, hosted later)
  engine.py        # the thought cycle: think/check/reflect/recall/consolidate
  seed.py          # 3-layer chest-pain brain (base -> domain -> individual)
  seed_legal.py    # 2nd domain: contract-review brain, sharing the same base
  cli.py           # `brain` CLI
  mcp_server.py    # MCP tool surface (15 tools)
demo.py            # runs all 5 MVP success criteria
examples/
  mcp_agent.py     # drives all 12 tools over a real stdio MCP session (pluggable model)
```

## Status

MVP complete and verified: all five success criteria pass (`uv run python demo.py`).
This is decision *support* on synthetic data — not for clinical use.
