# Digital Brain — Plasticity Engine

> Status: design draft · Last updated: 2026-09-14 · Companion to [data-model.md](./data-model.md)

The machinery that turns the fields defined in the data model — what makes the store *warp and
evolve* instead of being a static pile. Every mechanic is a **write-back** to `salience`,
`success_count`, edge `weight`, or engram `status`, and each write is gated by the brain's
`AutonomyPolicy`.

## Two clocks: reflex vs. sleep

Plasticity runs on two schedules, like a real brain:

| | Reflex (inline) | Sleep (background) |
|---|---|---|
| When | during/right after each thought cycle | on a schedule / when idle (cron) |
| Ops | reinforcement, Hebbian edge strengthening, episodic write | decay, consolidation, pruning, conflict detection |
| Cost | cheap, synchronous | batched, can use a model pass |
| Brain analog | synaptic potentiation | memory consolidation during sleep (DMN) |

The split keeps the live cycle fast and cheap; expensive model-assisted work (consolidation)
happens offline.

## The five mechanics

### 1. Reinforcement (myelination)
On a *successful* cycle, boost each activated engram toward 1 with bounded, diminishing growth:

```
salience += learning_rate · (1 − salience) · outcome_signal
success_count++
```

The `(1 − salience)` term prevents any single engram from running away to dominate. Failure
gives no boost (or a small penalty). Makes "what worked before" surface faster next time.

### 2. Decay (forgetting)
Background job; salience relaxes toward its floor over elapsed time:

```
salience = base_salience + (salience − base_salience) · e^(−decay_rate · Δt)
```

`base_salience` is a floor so nothing important vanishes; Constitution has `decay_rate = 0`.
Decay is essential, not a nuisance — without it the store flattens and recall loses signal.
**Forgetting is a feature.**

### 3. Association (Hebbian — "fire together, wire together")
Engrams co-activated in a successful cycle get an edge created (or its weight strengthened), so
next time recalling one spreads activation to the other. Edges decay too if never reinforced.
This is how the brain grows *structure* from experience.

### 4. Consolidation (episodic → procedural/semantic) — the crown jewel
The background job that literally replaces re-prompting:

- Cluster `episodic` engrams by similarity (embedding + situation/action).
- When a cluster crosses a threshold (≥ N similar episodes with **positive valence**), run a
  model abstraction pass: summarize the recurring `steps[]` into a new `procedural` engram.
- Emit it as `source: 'consolidated'`, `status: 'draft'` (or auto-apply per autonomy).

The core thesis made mechanical: **the brain notices "you keep doing X in situation Y" and
codifies it as a playbook, so you stop hand-writing that instruction as a prompt.** The model
is *used* here, but its output becomes portable brain content, not vendor-locked reasoning.
Repeated *facts* consolidate into `semantic` engrams the same way.

### 5. Pruning (synaptic pruning)
Background job soft-deletes engrams where `salience < prune_threshold` **and** low
`activation_count`, excluding Constitution. Soft-delete (`status → pruned`) stays reversible via
the event log. Weak edges get pruned too. Keeps recall sharp and storage bounded.

### (6) Conflict detection (cognitive dissonance)
Guard mechanic from the data model: when a new/edited engram contradicts an existing one
(semantic contradiction, or explicit `contradicts` edge), flag both `→ quarantined` and queue
for resolution (keep-newer / keep-higher-confidence / merge / human decides).

## Where the reinforcement signal comes from

Reinforcement needs an `outcome_signal`. Three sources, ascending in trust and latency:

- **Implicit** (free, noisy): was the output used unchanged? Heavy edits = weak negative signal.
- **Explicit** (clean, needs UI): human accept / reject / edit on the output.
- **Downstream** (best, delayed): did the real task succeed — deal closed, test passed, PR
  merged? Attributed back to the engrams that fired.

Start with implicit + explicit; wire downstream where the host app can report it.

## Temperament knobs = cognitive personality

The engine's constants define the brain's temperament, and they're per-brain:

- `learning_rate` — how fast it adapts (impulsive vs. deliberate).
- `decay_rate` — how fast it forgets (fluid vs. stable).
- `prune_threshold` — how ruthlessly it discards (minimalist vs. pack-rat).
- `consolidation_threshold` — how much evidence before it codifies a habit (cautious vs. quick
  to generalize).

A conservative expert's brain and a fast-moving generalist's brain differ *only* in these
numbers — a clean, portable notion of personality.

## Failure modes the design prevents

| Pathology | Prevention |
|---|---|
| Runaway reinforcement (one engram dominates) | bounded growth `(1−salience)` + counteracting decay + salience cap |
| Catastrophic forgetting | `base_salience` floor + Constitution never decays/prunes |
| Consolidating *bad* habits | positive-valence filter on clusters + draft/review gate |
| Silent drift into a different "personality" | event-sourced log + rewind + trust-ramp demotion on rejection bursts |
| Contradictory beliefs coexisting | conflict detection → quarantine → resolution |

## Next

- **Thought-cycle protocol** — the model-facing API/MCP contract that invokes recall, delivers
  the scaffold, and calls `reflect` to fire this engine.
- **MVP domain slice** — thin end-to-end vertical to prove the loop.
