// Typed client for the live Brain engine, over the local HTTP bridge (src/digital_brain/
// http_server.py). Every call drives the real Postgres+pgvector store — this is not a
// simulation. Dev requests go through the Vite proxy at /api → 127.0.0.1:8787.

const BASE = "/api";

export interface BrainInfo {
  id: string;
  label: string;
  region: string;
}

export interface RuleBrief {
  id: string;
  rule: string;
  scope?: string;
  source_layer: string; // base | domain:* | individual:*
}

export interface RecalledEngram {
  id: string;
  type: "semantic" | "episodic" | "procedural";
  region: string;
  salience: number;
  sim: number;
  content: Record<string, unknown>;
}

export interface Packet {
  cycle_id: string;
  intent: { classification: string; confidence: number };
  path: "fast" | "slow";
  scaffold: {
    playbook: { name: string; steps: string[]; preconditions: string[] } | null;
    recalled: RecalledEngram[];
    constraints: { hard: RuleBrief[]; soft: RuleBrief[] };
  };
  meta: Record<string, unknown>;
}

export type MemKind = "semantic" | "episodic" | "procedural";
export type MemStatus = "active" | "draft" | "pruned";

export interface Memory {
  id: string;
  type: MemKind;
  region: string;
  status: MemStatus;
  source: string; // human | model_proposed | consolidated
  salience: number;
  activationCount: number;
  successCount: number; // judged "went well" outcomes when this memory was recalled
  failureCount: number; // judged "didn't land" outcomes — together they form its recall track record
  label: string;
  detail: string;
  content: Record<string, unknown>;
  createdAt: string;
}

export interface CheckResult {
  pass: boolean;
  violations: RuleBrief[];
}

export interface TrustInfo {
  brain_id: string;
  region: string;
  level: "gated" | "guarded" | "autonomous";
  reviews: number;
  accept_rate: number;
  suggested_level: string | null;
  reason: string;
}

export interface GraphNode {
  id: string;
  type: MemKind;
  label: string;
  salience: number;
  region: string;
}
export interface GraphEdge {
  from: string;
  to: string;
  weight: number;
  kind: string;
}
export interface Graph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface AuditItem {
  event: number;
  when: string;
  summary: string;
}

export interface ExplainInfo {
  id: string;
  type: string;
  status: string;
  region: string;
  summary: string;
  salience: number;
  activation_count: number;
  success_count: number;
  created_at: string;
  provenance: { origin: string; from_cases?: string[] };
  associations: { to: string; kind: string; weight: number }[];
  timeline: { event: number; kind: string; when: string; note: string }[];
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    ...init,
    headers: init?.body ? { "content-type": "application/json" } : undefined,
  });
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return res.json() as Promise<T>;
}
const post = <T>(path: string, body: unknown) => req<T>(path, { method: "POST", body: JSON.stringify(body) });

export const api = {
  health: () => req<{ ok: boolean; engrams: number }>("/health"),
  brains: () => req<BrainInfo[]>("/brains"),
  memories: (brain: string) => req<Memory[]>(`/memories?brain=${encodeURIComponent(brain)}`),
  graph: (brain: string) => req<Graph>(`/graph?brain=${encodeURIComponent(brain)}`),
  audit: (brain: string) => req<AuditItem[]>(`/audit?brain=${encodeURIComponent(brain)}&limit=40`),
  trust: (brain: string, region: string) =>
    req<TrustInfo>(`/trust?brain=${encodeURIComponent(brain)}&region=${encodeURIComponent(region)}`),
  explain: (id: string) => req<ExplainInfo>(`/explain/${encodeURIComponent(id)}`),

  // fast/slow is decided automatically by the brain (instinct), not passed in
  think: (stimulus: string, brain: string) => post<Packet>("/think", { stimulus, brain }),
  check: (cycle_id: string, draft: string) => post<CheckResult>("/check", { cycle_id, draft }),
  // action_steps: the concrete steps the user actually took. Optional — when omitted/empty the
  // engine records the applied playbook's steps instead, so consolidation still has content.
  reflect: (cycle_id: string, success: boolean, action_steps: string[] = []) =>
    post<{ reinforced: string[]; edges_strengthened: number; episode_id: string }>("/reflect", {
      cycle_id,
      success,
      valence: success ? 0.6 : 0.3,
      action: action_steps.length ? "took the recorded steps" : "applied the recalled scaffold",
      action_steps,
      outcome_text: success ? "resolved well" : "did not land",
    }),
  remember: (brain: string, region: string, content: Record<string, unknown>) =>
    post<{ id: string; status: string }>("/remember", { brain, region, type: "semantic", content }),
  edit: (engram_id: string, patch: Record<string, unknown>) => post<unknown>("/edit", { engram_id, patch }),
  forget: (engram_id: string) => post<unknown>("/forget", { engram_id }),
  review: (engram_id: string, accepted: boolean) => post<unknown>("/review", { engram_id, accepted }),
  promote: (brain: string, region: string) => post<unknown>("/promote", { brain, region }),
  consolidate: (brain: string, region: string) => post<unknown>("/consolidate", { brain, region }),
  rewind: (brain: string, steps = 1) => post<unknown>("/rewind", { brain, steps }),
  sleep: (brain: string) =>
    post<{ decayed: number; pruned_count: number; edges_pruned: number }>("/sleep", { brain }),
  reset: (scope: "brain" | "all", brain?: string) =>
    post<{ ok: boolean; scope: string; engrams: number }>("/reset", { scope, brain }),
};
