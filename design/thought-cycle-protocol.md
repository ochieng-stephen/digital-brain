# Digital Brain — Thought-Cycle Protocol

> Status: design draft · Last updated: 2026-09-14 · Companion to [data-model.md](./data-model.md) and [plasticity-engine.md](./plasticity-engine.md)

The model-facing interface: how *any* model plugs in and reasons like the brain. This is the
product — get it right and the thesis (swap models, keep identity) becomes real.

## The one non-negotiable principle

**The brain never owns a reasoning model.** If the brain called a specific LLM internally,
you'd just re-centralize cognition in whatever the brain picked. Instead:

- The **model orchestrates**; the brain **serves scaffolding**.
- The brain owns only an **embedding model** locally (retrieval, not reasoning — same class of
  tool as `sqlite-vec` in the existing design-context-engine). The hot path (recall + constrain)
  is therefore **LLM-free and instant**.
- Any *reasoning-level* work (consolidation abstraction, conflict resolution) is delegated back
  to the **caller's model**. The brain stays bring-your-own-model — which *is* decentralization.

Brain = OS + memory. Model = swappable processor. The protocol is the syscall interface.

## Transport: the brain is an MCP server

Any MCP-capable model or app connects, names a `brain_id`, and calls tools. An "app" (literal
app *or* field domain) is just a client pointing at a brain.

## Tool surface

The 6-step cycle collapses into **3 core calls** plus editing/introspection. We deliberately do
*not* expose 6 separate step-tools — that would push orchestration onto every client and make the
Constitution check optional.

```ts
// ── CORE CYCLE ──
brain.think(stimulus, { brain_id, app_context, stakes? })  → CognitionPacket
  // = Perceive + Recall + Constrain + Deliberate. The workhorse.

brain.check(cycle_id, draft_output)  → { pass: boolean, violations: Rule[] }
  // post-output guard against hard Constitution. Recommended for high-stakes.

brain.reflect(cycle_id, outcome)  → { writes: WriteSummary }
  // fires the plasticity engine: reinforcement + episodic write.
  // outcome = { success, feedback?, used_output?, edits? }

// ── EDIT ("models can edit it when prompted") ──
brain.remember(engram)          // propose new engram → draft per autonomy
brain.edit(engram_id, changes)  // propose edit
brain.forget(engram_id)         // propose prune

// ── INTROSPECT ──
brain.recall(query)             // raw retrieval — "what do I know about X"
brain.explain(engram_id)        // "why do I think this" — traces the event log
```

## The CognitionPacket (the key artifact)

`brain.think` returns this — the reasoning scaffold injected into the model's context:

```ts
type CognitionPacket = {
  cycle_id: string;
  intent: { classification: string; confidence: number };
  path: 'fast' | 'slow';              // did instinct short-circuit deliberation?
  scaffold: {
    playbook?: { name: string; steps: string[]; preconditions: string[] };  // procedural
    recalled: Engram[];               // relevant semantic/episodic memories
    constraints: {
      hard: Rule[];                   // Constitution — MUST NOT violate
      soft: Rule[];                   // Instinct — default behaviors
    };
  };
  meta: { brain_id: string; layers_used: string[]; token_estimate: number };
};
```

The model reads it and knows: *what you know* (recalled), *how you approach this* (playbook),
*the lines you can't cross* (constraints). It then generates the output. `cycle_id` threads
`think → check → reflect` so `reflect` knows exactly which engrams fired (the activation set) —
which is what reinforcement writes back to.

## Fast vs. slow path — decided inside `think`

- **Fast path**: stimulus matches a high-salience instinct/procedure with high confidence →
  minimal packet (one playbook + constraints), skip heavy recall. Cheap, near-instant.
- **Slow path**: novel / low-confidence / high-`stakes` → full recall, spreading activation,
  deliberation.

System 1 vs System 2 realized as a routing decision — and where cost/latency savings come from.

## Two integration modes (works with any model)

1. **Prompt injection** — serialize the packet into a system/context block. Works with *any*
   model, even non-tool-using ones. The lowest common denominator that guarantees portability
   and makes the "any model, forever" promise literally true.
2. **Agentic tool loop** — a tool-using agent calls `brain.think` first, gets the packet,
   proceeds, then calls `brain.check` / `brain.reflect`. Richer, self-correcting.

Both hit the same MCP surface.

## Worked exchange (litigator brain)

```
→ brain.think("opposing counsel missed the discovery deadline",
              { brain_id: "litigator/individual:jane", stakes: "high" })

← { cycle_id: "c_91",
    intent: { classification: "deadline_response", confidence: 0.93 },
    path: "slow",
    scaffold: {
      playbook: { name: "Respond to missed deadline",
                  steps: ["Confirm the deadline + service record",
                          "Meet-and-confer letter first",
                          "Draft motion to compel if no cure in 7d"] },
      recalled: [ /* episodic: Ramirez v. Doe motion granted */ ],
      constraints: {
        hard: [{ rule: "Never threaten sanctions without partner sign-off" }],
        soft: [{ rule: "Default to cooperative tone before escalation" }] } },
    meta: { brain_id, layers_used: ["individual:jane","domain:litigation","base"] } }

// model drafts the letter using the steps + constraints
→ brain.check("c_91", "<draft letter>")   ← { pass: true, violations: [] }
→ brain.reflect("c_91", { success: true, used_output: true })
   ← { writes: { reinforced: ["proc:missed_deadline","ep:ramirez"],
                 edges_strengthened: 1 } }
```

Swap the model next month — the brain returns the *same packet*, so the reasoning stays the
user's. That is the whole thesis in one exchange.

## Requirement coverage

| Requirement | How the protocol delivers it |
|---|---|
| Decentralized reasoning | brain owns no reasoning model; caller brings any model |
| Guides reasoning rules | `scaffold.playbook.steps` = the how-to handed over |
| Instinct as strategy | `path: 'fast'` + `constraints.soft`, always-on, no recall needed |
| Constitution of laws | `constraints.hard` + `brain.check` enforcement |
| Models can edit when prompted | `remember` / `edit` / `forget`, gated by autonomy |
| Portable across apps/domains | MCP + `brain_id` + layer resolution |
| Feeds the plasticity engine | `reflect` closes the loop with the outcome signal |

## Next

- **MVP domain slice** — see [mvp-medical.md](./mvp-medical.md).
