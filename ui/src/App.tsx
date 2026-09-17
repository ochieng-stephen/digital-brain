import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import BrainCore, { type SeamState, type MemoryNode, type MemoryEdge } from "./components/BrainCore";
import PlasticityGraph from "./components/PlasticityGraph";
import DomainSwitcher from "./components/DomainSwitcher";
import AutonomyDial, { type Autonomy } from "./components/AutonomyDial";
import Walkthrough, { TOUR_FLAG } from "./components/Walkthrough";
import SettingsDrawer from "./components/SettingsDrawer";
import BrandMark from "./components/BrandMark";
import {
  api,
  type AuditItem,
  type BrainInfo,
  type CheckResult,
  type ExplainInfo,
  type Graph,
  type Memory,
  type Packet,
  type RuleBrief,
  type TrustInfo,
} from "./lib/api";

const ENERGY: Record<Autonomy, number> = { gated: 0.28, guarded: 0.55, autonomous: 0.85 };

function layerOf(sourceLayer: string): string {
  if (sourceLayer.startsWith("individual")) return "individual";
  if (sourceLayer.startsWith("domain")) return "domain";
  return "base";
}

// Example drafts so the Constitution check is usable without an external model handy. These stand
// in for "what your model wrote after reading the scaffold" — one that obeys the hard rules and one
// that doesn't — so a first-time user can see a pass and a block immediately.
function sampleDrafts(brainId: string): { compliant: string; weak: string } {
  if (brainId.includes("lawyer")) {
    return {
      compliant:
        "This is informational, not legal advice; attorney review required. The agreement has uncapped " +
        "liability and a one-sided indemnification favoring the vendor. Confirm the governing law and " +
        "termination / auto-renewal terms. Both clauses are high risk; recommend a mutual, capped redline.",
      weak: "Looks standard to me — you're good to sign.",
    };
  }
  return {
    compliant:
      "This is clinical decision support, not a diagnosis; a clinician must confirm. Keep the can't-miss " +
      "differentials in view: ACS, PE, aortic dissection, tension pneumothorax, esophageal rupture. Obtain a " +
      "12-lead ECG and serial troponin; do not rule out ACS without them. Document the HEART score.",
    weak: "This looks fine overall — probably just reflux, send them home.",
  };
}

export default function App() {
  // ---- live connection + selected brain ----
  const [online, setOnline] = useState<boolean | null>(null);
  const [engrams, setEngrams] = useState(0);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [brains, setBrains] = useState<BrainInfo[]>([]);
  const [brainId, setBrainId] = useState<string>("");
  const brain = brains.find((b) => b.id === brainId) ?? null;
  const region = brain?.region ?? "";

  // ---- live brain state (fetched) ----
  const [memories, setMemories] = useState<Memory[]>([]);
  const [graph, setGraph] = useState<Graph>({ nodes: [], edges: [] });
  const [audit, setAudit] = useState<AuditItem[]>([]);
  const [trust, setTrust] = useState<TrustInfo | null>(null);

  // ---- cycle / view state ----
  const [centerView, setCenterView] = useState<"brain" | "wiring">("brain"); // the center slot: art or plasticity
  const [stimulus, setStimulus] = useState("");
  const [packet, setPacket] = useState<Packet | null>(null);
  const [thinking, setThinking] = useState(false);
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [reflected, setReflected] = useState(false);
  const [stepsTaken, setStepsTaken] = useState(""); // optional "steps you actually took" for reflect
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [tour, setTour] = useState(false);

  const [draft, setDraft] = useState("");
  const [verdict, setVerdict] = useState<CheckResult | null>(null);
  const [seam, setSeam] = useState<SeamState>("idle");

  const [newMemory, setNewMemory] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [explainId, setExplainId] = useState<string | null>(null);
  const [explainData, setExplainData] = useState<ExplainInfo | null>(null);
  const [recallQuery, setRecallQuery] = useState("");

  const verdictRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (verdict) verdictRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [verdict]);

  // ---- initial connect ----
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const bs = await api.brains(); // provisions this visitor's sandbox on first call
        const h = await api.health();  // now reports this sandbox's own engram count
        if (!alive) return;
        setEngrams(h.engrams);
        setBrains(bs);
        setBrainId(bs[0]?.id ?? "");
        setOnline(true);
      } catch {
        if (alive) setOnline(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  const loadData = useCallback(async (id: string, reg: string) => {
    const [mem, g, a, t] = await Promise.all([
      api.memories(id),
      api.graph(id),
      api.audit(id),
      reg ? api.trust(id, reg) : Promise.resolve(null),
    ]);
    setMemories(mem);
    setGraph(g);
    setAudit(a);
    setTrust(t);
  }, []);

  useEffect(() => {
    if (online && brainId && region) loadData(brainId, region).catch(() => setOnline(false));
  }, [online, brainId, region, loadData]);

  // first-run walkthrough (once; re-openable from the header "guide" button)
  useEffect(() => {
    if (online && brainId) {
      try {
        if (!localStorage.getItem(TOUR_FLAG)) setTour(true);
      } catch {
        /* ignore */
      }
    }
  }, [online, brainId]);

  const refresh = useCallback(() => {
    if (brainId && region) loadData(brainId, region).catch(() => {});
  }, [brainId, region, loadData]);

  // ---- derived ----
  const activeMemories = memories.filter((m) => m.status === "active");
  const draftMemories = memories.filter((m) => m.status === "draft");
  const level: Autonomy = (trust?.level as Autonomy) ?? "gated";
  const energy = ENERGY[level];

  const firingIds = useMemo(
    () => new Set((packet?.scaffold.recalled ?? []).map((r) => r.id)),
    [packet]
  );
  // Each memory's intrinsic "wiring strength" from the plasticity graph — summed weight of its
  // associations, normalised 0..1 across the brain. Hub memories (many strong links) fire brighter.
  const wiring = useMemo(() => {
    const strength = new Map<string, number>();
    for (const e of graph.edges) {
      strength.set(e.from, (strength.get(e.from) ?? 0) + e.weight);
      strength.set(e.to, (strength.get(e.to) ?? 0) + e.weight);
    }
    const max = Math.max(1e-6, ...Array.from(strength.values()));
    const norm = new Map<string, number>();
    strength.forEach((v, k) => norm.set(k, v / max));
    return norm;
  }, [graph]);

  const memById = useMemo(() => new Map(memories.map((m) => [m.id, m])), [memories]);
  // intrinsic firing intensity of a memory: its salience blended with how well-wired it is (0..1)
  const combo = useCallback(
    (id: string) => 0.45 * (memById.get(id)?.salience ?? 0.4) + 0.55 * (wiring.get(id) ?? 0),
    [memById, wiring]
  );

  // The current activation ("fire", 0..1) each memory gets on the art = its recall + hover level, on
  // TOP of its resting baseline (which BrainCore derives from wiring). During a think the hot/cool
  // structure comes from task-relevance (sim) normalised WITHIN this recall — the most on-point
  // memory is the bright focus, also-rans stay cool (fMRI-style) — plus a wiring boost. Hover lifts a
  // memory to its intrinsic level (salience × wiring). Everything not firing simply stays at 0 (rest).
  const fireById = useMemo(() => {
    const rec = packet?.scaffold.recalled ?? [];
    const lo = rec.length ? Math.min(...rec.map((r) => r.sim)) : 0;
    const hi = rec.length ? Math.max(...rec.map((r) => r.sim)) : 1;
    const span = hi - lo || 1;
    const map = new Map<string, number>();
    for (const r of rec) {
      const simRel = (r.sim - lo) / span;
      map.set(r.id, Math.min(1, 0.34 + 0.46 * simRel + 0.2 * (wiring.get(r.id) ?? 0)));
    }
    if (hoverId) {
      const hoverInt = Math.min(1, 0.45 + 0.55 * combo(hoverId));
      map.set(hoverId, Math.max(hoverInt, map.get(hoverId) ?? 0));
    }
    return map;
  }, [packet, hoverId, wiring, combo]);

  // Everything BrainCore needs to draw the living map: every active memory with its live metrics, and
  // the association graph that clusters them. Layout re-flows only when membership/wiring changes.
  const brainNodes = useMemo<MemoryNode[]>(
    () =>
      activeMemories.map((m) => ({
        id: m.id,
        kind: m.type,
        wiring: wiring.get(m.id) ?? 0,
        salience: m.salience,
        fire: fireById.get(m.id) ?? 0,
      })),
    [activeMemories, wiring, fireById]
  );
  const brainEdges = useMemo<MemoryEdge[]>(
    () => graph.edges.map((e) => ({ from: e.from, to: e.to, weight: e.weight })),
    [graph]
  );

  const shownMemories = useMemo(() => {
    const q = recallQuery.trim().toLowerCase();
    if (!q) return activeMemories;
    const terms = q.split(/\s+/).filter(Boolean);
    const rank = (m: Memory) => {
      const hay = `${m.label} ${m.detail}`.toLowerCase();
      return terms.reduce((n, t) => n + (hay.includes(t) ? 1 : 0), 0);
    };
    return activeMemories.map((m) => ({ m, s: rank(m) })).filter((x) => x.s > 0).sort((a, b) => b.s - a.s).map((x) => x.m);
  }, [activeMemories, recallQuery]);

  const consolidateReady = activeMemories.filter(
    (m) => m.type === "episodic" && (Number((m.content as { valence?: number }).valence) || 0) > 0
  ).length;

  const rootStyle = {
    "--accent-a": brain?.id.includes("lawyer") ? "#b45309" : "#0891b2",
    "--accent-b": brain?.id.includes("lawyer") ? "#a16207" : "#0e7490",
    "--energy": energy,
  } as React.CSSProperties;

  // ---- actions ----
  function clearCycleView() {
    setPacket(null);
    setDraft("");
    setVerdict(null);
    setSeam("idle");
    setStimulus("");
    setReflected(false);
    setEditingId(null);
    setExplainId(null);
    setRecallQuery("");
  }

  function switchDomain(id: string) {
    setBrainId(id);
    clearCycleView();
  }

  async function doThink(text?: string) {
    const s = (text ?? stimulus).trim();
    if (!s || !brainId) return;
    setStimulus(s);
    setBusy(true);
    setThinking(true);
    try {
      const p = await api.think(s, brainId);
      setPacket(p);
      setDraft("");
      setVerdict(null);
      setSeam("idle");
      setReflected(false);
      refresh();
    } catch {
      setOnline(false);
    } finally {
      setBusy(false);
      window.setTimeout(() => setThinking(false), 900);
    }
  }

  async function doCheck() {
    if (!packet) return;
    setBusy(true);
    try {
      const res = await api.check(packet.cycle_id, draft);
      setVerdict(res);
      setSeam(res.pass ? "pass" : "violation");
      // note: do NOT reset `reflected` here — reflection is once per cognitive cycle (per think),
      // not per check. Re-checking a draft must not re-open the reflect step on the same cycle.
      window.setTimeout(() => setSeam("idle"), 2600);
      refresh();
    } finally {
      setBusy(false);
    }
  }

  async function doReflect(success: boolean) {
    if (!packet || reflected) return;
    setBusy(true);
    try {
      // one step per line; blank lines dropped. Empty → engine records the applied playbook's steps.
      const steps = stepsTaken.split("\n").map((s) => s.trim()).filter(Boolean);
      await api.reflect(packet.cycle_id, success, steps);
      setReflected(true);
      setStepsTaken("");
      refresh();
    } finally {
      setBusy(false);
    }
  }

  async function doRemember() {
    const text = newMemory.trim();
    if (!text || !brainId) return;
    const concept = text.length > 42 ? text.slice(0, 42) + "…" : text;
    setBusy(true);
    try {
      await api.remember(brainId, region, { concept, definition: text, facts: [] });
      setNewMemory("");
      refresh();
    } finally {
      setBusy(false);
    }
  }

  function startEdit(m: Memory) {
    setEditingId(m.id);
    setEditText(m.detail);
    setExplainId(null);
  }
  async function saveEdit() {
    if (!editingId) return;
    const m = memories.find((x) => x.id === editingId);
    if (!m) return;
    const patch = m.type === "semantic" ? { definition: editText } : { outcome: editText };
    setBusy(true);
    try {
      await api.edit(editingId, patch);
      setEditingId(null);
      refresh();
    } finally {
      setBusy(false);
    }
  }

  async function doForget(id: string) {
    setBusy(true);
    try {
      await api.forget(id);
      if (editingId === id) setEditingId(null);
      if (explainId === id) setExplainId(null);
      refresh();
    } finally {
      setBusy(false);
    }
  }

  async function toggleExplain(id: string) {
    if (explainId === id) {
      setExplainId(null);
      return;
    }
    setEditingId(null);
    setExplainId(id);
    setExplainData(null);
    try {
      setExplainData(await api.explain(id));
    } catch {
      /* leave null */
    }
  }

  async function doReview(id: string, accepted: boolean) {
    setBusy(true);
    try {
      await api.review(id, accepted);
      refresh();
    } finally {
      setBusy(false);
    }
  }

  async function doPromote() {
    setBusy(true);
    try {
      await api.promote(brainId, region);
      refresh();
    } finally {
      setBusy(false);
    }
  }

  async function doConsolidate() {
    setBusy(true);
    try {
      await api.consolidate(brainId, region);
      refresh();
    } finally {
      setBusy(false);
    }
  }

  async function doRewind() {
    setBusy(true);
    try {
      await api.rewind(brainId, 1);
      refresh();
    } finally {
      setBusy(false);
    }
  }

  async function resync() {
    try {
      const h = await api.health();
      setEngrams(h.engrams);
      refresh();
    } catch {
      setOnline(false);
    }
  }

  async function doSleep() {
    setBusy(true);
    try {
      const r = await api.sleep(brainId);
      const h = await api.health();
      setEngrams(h.engrams);
      refresh();
      return r;
    } finally {
      setBusy(false);
    }
  }

  async function doReset(scope: "brain" | "all") {
    setBusy(true);
    try {
      await api.reset(scope, scope === "brain" ? brainId : undefined);
      const h = await api.health();
      setEngrams(h.engrams);
      clearCycleView();
      refresh();
      setSettingsOpen(false);
    } finally {
      setBusy(false);
    }
  }

  function copyScaffold() {
    if (!packet) return;
    const s = packet.scaffold;
    const L: string[] = [];
    L.push(`# Reasoning scaffold — ${packet.intent.classification} (${packet.path} path, confidence ${packet.intent.confidence})`);
    if (s.playbook) {
      L.push("", `## Playbook: ${s.playbook.name}`);
      s.playbook.steps.forEach((st, i) => L.push(`${i + 1}. ${st}`));
    }
    L.push("", "## Recalled memory");
    s.recalled.forEach((m) => {
      const c = m.content as { concept?: string; definition?: string; situation?: string; outcome?: string };
      L.push(`- ${c.concept ?? c.situation ?? m.type}: ${c.definition ?? c.outcome ?? ""}`);
    });
    L.push("", "## Constitution — hard rules, must not be violated");
    s.constraints.hard.forEach((r) => L.push(`- ${r.rule} [${layerOf(r.source_layer)}]`));
    L.push("", "## Instinct — soft defaults");
    s.constraints.soft.forEach((r) => L.push(`- ${r.rule} [${layerOf(r.source_layer)}]`));
    L.push("", "— Reason within this scaffold. Do not cross the Constitution.");
    navigator.clipboard?.writeText(L.join("\n")).then(
      () => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1600);
      },
      () => {}
    );
  }

  // ---- render gates ----
  if (online === false) {
    return (
      <div className="app offline" style={rootStyle}>
        <div className="offline-card">
          <BrandMark live={false} />
          <h2>Brain offline</h2>
          <p>
            This UI is a client of the live Brain engine, not a simulation. Start the local bridge, then reload:
          </p>
          <pre>uv run digital-brain-http</pre>
          <p className="offline-sub">Needs Postgres running with the seeded <code>digital_brain</code> database.</p>
          <button className="btn" onClick={() => window.location.reload()}>
            Retry
          </button>
        </div>
      </div>
    );
  }
  if (online === null || !brain) {
    return (
      <div className="app loading" style={rootStyle}>
        <div className="loading-card">
          <BrandMark live={false} connecting />
          <span className="tick">connecting to the live brain…</span>
        </div>
      </div>
    );
  }

  return (
    <div className="app" style={rootStyle} data-domain={brainId}>
      {/* ------------------------------------------------------------ top bar */}
      <header className="topbar">
        <div className="topbar-lead">
          <div className="brandmark">
            <BrandMark live={online === true} />
            <div>
              <div className="brand-name">Digital Brain</div>
              <div className="brand-sub">live cognition layer · {brainId.split("#")[0]}</div>
            </div>
          </div>
          <DomainSwitcher brains={brains} active={brainId} onChange={switchDomain} />
          <button className="guide-btn" onClick={() => setTour(true)} data-tip="Show the getting-started guide" data-tip-pos="bottom">
            ? guide
          </button>
          <button
            className="icon-btn"
            onClick={() => setSettingsOpen(true)}
            data-tip="Settings"
            data-tip-pos="bottom"
            aria-label="Settings"
          >
            <svg
              className="gear"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <circle cx="12" cy="12" r="6.6" />
              <circle cx="12" cy="12" r="2.7" />
              <path d="M18.6 12 L21.4 12 M16.67 16.67 L18.65 18.65 M12 18.6 L12 21.4 M7.33 16.67 L5.35 18.65 M5.4 12 L2.6 12 M7.33 7.33 L5.35 5.35 M12 5.4 L12 2.6 M16.67 7.33 L18.65 5.35" />
            </svg>
          </button>
        </div>
        <AutonomyDial
          level={level}
          reviews={trust?.reviews ?? 0}
          acceptRate={trust?.accept_rate ?? 0}
          suggestedLevel={trust?.suggested_level ?? null}
          onPromote={doPromote}
        />
      </header>

      {/* ---------------------------------------------------------- workspace */}
      <div className="workspace">
        {/* LEFT — the enduring self, a full-height rail */}
        <aside className="col rail">
          <section className="panel">
            <div className="panel-head">
              <div className="panel-title">
                <h3>Recall</h3>
                <span className="tick">organic side</span>
              </div>
              <span className="pill">{activeMemories.length}</span>
            </div>

            <div className="mem-add">
              <input
                value={newMemory}
                placeholder="Teach it something…"
                onChange={(e) => setNewMemory(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && doRemember()}
              />
              <button className="btn ghost small" onClick={doRemember} disabled={!newMemory.trim() || busy}>
                Remember
              </button>
            </div>

            <div className="mem-search">
              <input
                value={recallQuery}
                placeholder="🔍 Recall — what do I know about…"
                aria-label="Search memory"
                onChange={(e) => setRecallQuery(e.target.value)}
              />
              {recallQuery && (
                <span className="mem-search-count">
                  {shownMemories.length} of {activeMemories.length}
                </span>
              )}
            </div>

            {!packet && !recallQuery && <p className="hint">Send a thought below and the relevant ones light up.</p>}

            <div className="mem-list">
              {shownMemories.map((m, i) => {
                const isLit = firingIds.has(m.id); // recalled memories are highlighted in the list
                // only the top card's action tooltips would clip above the scroll edge → drop those below;
                // every other card's upward tooltip renders fine over the card above it
                const tipPos = i === 0 ? "bottom" : undefined;
                const isEditing = editingId === m.id;
                const isExplaining = explainId === m.id;
                const viaAssoc = firingIds.has(m.id) && (packet?.scaffold.recalled.find((r) => r.id === m.id)?.sim ?? 1) < 0.35;
                return (
                  <div key={m.id} className={"mem" + (isLit ? " lit" : "")}>
                    <div
                      className="mem-body"
                      onMouseEnter={() => setHoverId(m.id)}
                      onMouseLeave={() => setHoverId(null)}
                    >
                      <div className="mem-row">
                        <div className="mem-label">
                          {m.label}
                          {viaAssoc && <span className="via-assoc">linked</span>}
                        </div>
                        <div className="mem-actions">
                          <button className="mem-btn" data-tip="Explain" data-tip-pos={tipPos} aria-label={`Explain "${m.label}"`} onClick={() => toggleExplain(m.id)}>
                            ?
                          </button>
                          {m.type !== "procedural" && (
                            <button className="mem-btn" data-tip="Edit" data-tip-pos={tipPos} aria-label={`Edit "${m.label}"`} onClick={() => startEdit(m)}>
                              ✎
                            </button>
                          )}
                          <button className="mem-btn" data-tip="Forget" data-tip-pos={tipPos} aria-label={`Forget "${m.label}"`} onClick={() => doForget(m.id)}>
                            ✕
                          </button>
                        </div>
                      </div>
                      {isEditing ? (
                        <div className="mem-edit">
                          <textarea value={editText} onChange={(e) => setEditText(e.target.value)} rows={2} />
                          <div className="mem-edit-actions">
                            <button className="btn small" onClick={saveEdit} disabled={busy}>
                              Save
                            </button>
                            <button className="btn ghost small" onClick={() => setEditingId(null)}>
                              Cancel
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div className="mem-detail">{m.detail}</div>
                      )}
                      <div className="mem-kind">
                        <span className="mem-kind-label">
                          <span className="kind-cap">{m.type.charAt(0)}</span>
                          {m.type.slice(1)} · {m.region}
                        </span>
                        {(() => {
                          const judged = m.successCount + m.failureCount;
                          if (judged < 3) return null; // evidence gate — shown exactly when recall starts weighting it
                          const rate = m.successCount / judged;
                          return (
                            <span
                              className="mem-rel"
                              data-lo={rate < 0.5 ? "true" : "false"}
                              data-tip={`Helpful in ${m.successCount} of ${judged} judged recalls — the brain weights this in recall`}
                              data-tip-align="right"
                              style={{ "--rel": rate } as React.CSSProperties}
                            >
                              <span className="mem-rel-track">
                                <span className="mem-rel-fill" />
                              </span>
                              <span className="mem-rel-n">
                                {m.successCount}/{judged}
                              </span>
                            </span>
                          );
                        })()}
                      </div>
                      {isExplaining && (
                        <div className="mem-explain">
                          {!explainData ? (
                            <div>loading…</div>
                          ) : (
                            <>
                              <div>
                                {explainData.provenance.origin} · salience {Math.round(explainData.salience * 100)}% · activated{" "}
                                {explainData.activation_count}×
                              </div>
                              {explainData.associations.length > 0 && (
                                <div className="mem-assoc">
                                  wired to:{" "}
                                  {explainData.associations.map((a, i) => (
                                    <span key={i} className="assoc-chip">
                                      {a.to}
                                      <span className="assoc-w">{a.weight.toFixed(1)}</span>
                                    </span>
                                  ))}
                                </div>
                              )}
                              <ul>
                                {explainData.timeline.slice(0, 6).map((h, i) => (
                                  <li key={i}>{h.note}</li>
                                ))}
                              </ul>
                            </>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>

            {draftMemories.length > 0 && (
              <div className="review-queue">
                <div className="panel-head" style={{ marginTop: 14 }}>
                  <div className="panel-title">
                    <h3>Pending review</h3>
                    <span className="tick">earn trust</span>
                  </div>
                  <span className="pill">{draftMemories.length}</span>
                </div>
                <p className="queue-hint">
                  Approve what you trust. {trust?.reviews ?? 0}/5 reviews at ≥80% accepted earns the next autonomy level.
                </p>
                <div className="review-list">
                  {draftMemories.map((d) => (
                    <div key={d.id} className="review-row">
                      <div>
                        <div className="mem-label">{d.label}</div>
                        <div className="mem-detail">{d.detail}</div>
                      </div>
                      <div className="review-actions">
                        <button className="btn small" onClick={() => doReview(d.id, true)} disabled={busy}>
                          Approve
                        </button>
                        <button className="btn ghost small" onClick={() => doReview(d.id, false)} disabled={busy}>
                          Reject
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </section>
        </aside>

        {/* RIGHT REGION — everything else stacks beside the rail */}
        <div className="workspace-main">
          <main className="stage">
            {/* CENTER — swappable: the brain art, or the plasticity (memory-wiring) graph */}
            <div className="brain-stage" data-view={centerView}>
              <div className="center-toggle" role="tablist" aria-label="Center view">
                <button
                  role="tab"
                  aria-selected={centerView === "brain"}
                  data-on={centerView === "brain"}
                  onClick={() => setCenterView("brain")}
                >
                  Brain
                </button>
                <button
                  role="tab"
                  aria-selected={centerView === "wiring"}
                  data-on={centerView === "wiring"}
                  onClick={() => setCenterView("wiring")}
                >
                  Wiring
                </button>
              </div>

              <div className="center-view">
                {centerView === "brain" ? (
                  <BrainCore nodes={brainNodes} edges={brainEdges} thinking={thinking} seamState={seam} energy={energy} />
                ) : (
                  <PlasticityGraph graph={graph} firing={firingIds} />
                )}
              </div>

              <div className="brain-caption">
                {centerView === "wiring" ? (
                  <div className="big" style={{ color: "var(--ink-3)" }}>
                    {graph.nodes.length} memories · {graph.edges.length} associations
                    {graph.edges.length === 0 && <span className="path-novel"> · reflect “Went well” to wire them</span>}
                  </div>
                ) : packet ? (
                  <>
                    <div className={"path path-" + packet.path}>
                      {packet.path === "fast" ? "fast · System 1 · instinct" : "slow · System 2 · deliberation"} · conf{" "}
                      {packet.intent.confidence}
                      {packet.intent.confidence < 0.5 && <span className="path-novel"> · novel</span>}
                    </div>
                    <div className="big">{packet.intent.classification}</div>
                  </>
                ) : (
                  <div className="big" style={{ color: "var(--ink-3)" }}>
                    organic memory ⟶ silicon processor
                  </div>
                )}
              </div>
            </div>

        {/* RIGHT — the scaffold + constitution check */}
        <div className="col col-right">
          {!packet ? (
            <section className="panel">
              <div className="panel-head">
                <div className="panel-title">
                  <h3>Scaffold</h3>
                  <span className="tick">silicon side</span>
                </div>
              </div>
              <p className="empty">
                A request enters through the chip. The live brain returns a reasoning scaffold for any model to reason within —
                three things:
              </p>
              <ul className="scaffold-legend">
                <li>
                  <span className="leg-glyph">P</span>
                  <span>
                    <b>Playbook</b> — the steps it follows for this kind of problem
                  </span>
                </li>
                <li>
                  <span className="leg-glyph">M</span>
                  <span>
                    <b>Recalled memory</b> — the facts and past cases it surfaced (real vector recall)
                  </span>
                </li>
                <li>
                  <span className="leg-glyph">§</span>
                  <span>
                    <b>Constitution</b> — the hard rules it must not cross
                  </span>
                </li>
              </ul>
            </section>
          ) : (
            <section className="panel reveal">
              <div className="panel-head">
                <div className="panel-title">
                  <h3>Scaffold</h3>
                  <span className="tick">{brainId.split("#")[0]}</span>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0, marginLeft: "auto" }}>
                  <button className="btn ghost small" onClick={copyScaffold} data-tip="Copy this scaffold to hand to any model" data-tip-pos="bottom">
                    {copied ? "Copied ✓" : "Copy for your model"}
                  </button>
                  <span className="pill">{packet.cycle_id}</span>
                </div>
              </div>

              {packet.intent.confidence < 0.5 && (
                <div className="novel-note">
                  Low confidence — this looks novel for this brain. The scaffold is a best effort; treat it with extra care.
                </div>
              )}

              {packet.scaffold.playbook && (
                <>
                  <div className="panel-head" style={{ marginBottom: 4 }}>
                    <div className="playbook-name" style={{ marginBottom: 0 }}>
                      {packet.scaffold.playbook.name}
                    </div>
                    {consolidateReady >= 5 && (
                      <button className="btn ghost small" onClick={doConsolidate} disabled={busy}>
                        Consolidate ({consolidateReady}) →
                      </button>
                    )}
                  </div>
                  {packet.scaffold.playbook.steps.map((s, i) => (
                    <div className="step" key={i}>
                      <span className="step-n">{String(i + 1).padStart(2, "0")}</span>
                      <span>{s}</span>
                    </div>
                  ))}
                </>
              )}

              <div className="panel-head" style={{ marginTop: 16 }}>
                <div className="panel-title">
                  <h3>Constitution & instinct</h3>
                </div>
                <span className="pill">{packet.scaffold.constraints.hard.length} hard</span>
              </div>
              {packet.scaffold.constraints.hard.map((r: RuleBrief) => (
                <div className="rule" key={r.id}>
                  <span className="rule-dot" />
                  <span>
                    {r.rule}
                    <span className="rule-layer">{layerOf(r.source_layer)}</span>
                  </span>
                </div>
              ))}
              {packet.scaffold.constraints.soft.map((r: RuleBrief) => (
                <div className="rule soft" key={r.id}>
                  <span className="rule-dot" />
                  <span>
                    {r.rule}
                    <span className="rule-layer">{layerOf(r.source_layer)}</span>
                  </span>
                </div>
              ))}

              <div className="panel-head" style={{ marginTop: 16 }}>
                <div className="panel-title">
                  <h3>Check a draft</h3>
                  <span className="tick">at the seam</span>
                </div>
              </div>
              <p className="draft-help">
                This is <b>your model's answer</b> — use <b>“Copy for your model”</b> above, let your model respond within the
                scaffold, then paste it back here. No model handy? Load an example:
                <button className="chip-suggest" onClick={() => setDraft(sampleDrafts(brainId).compliant)}>
                  compliant
                </button>
                <button className="chip-suggest" onClick={() => setDraft(sampleDrafts(brainId).weak)}>
                  weak
                </button>
              </p>
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                rows={4}
                placeholder="Paste your model's answer here — the live Constitution check runs against it."
                style={{
                  width: "100%",
                  resize: "vertical",
                  background: "var(--bg-1)",
                  color: "var(--ink)",
                  border: "1px solid var(--hair)",
                  borderRadius: "12px",
                  padding: "10px 12px",
                  fontSize: "12.5px",
                  lineHeight: 1.45,
                  outline: "none",
                }}
              />
              <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
                <button className="btn" onClick={doCheck} disabled={busy || !draft.trim()}>
                  Check against constitution
                </button>
              </div>

              <div ref={verdictRef}>
                {verdict && (
                  <div className={"verdict " + (verdict.pass ? "pass" : "fail")}>
                    <span className="rule-dot" style={{ background: verdict.pass ? "var(--ok)" : "var(--bad)", marginTop: 6 }} />
                    <div>
                      {verdict.pass ? (
                        <b>Passes the Constitution.</b>
                      ) : (
                        <>
                          <b>Blocked — {verdict.violations.length} violation(s).</b>
                          <ul className="verdict-list">
                            {verdict.violations.map((v) => (
                              <li key={v.id}>{v.rule}</li>
                            ))}
                          </ul>
                        </>
                      )}
                    </div>
                  </div>
                )}

                {verdict?.pass && !reflected && (
                  <div className="reflect-callout">
                    <div className="reflect-copy">
                      <b>Once you use this, how did it go?</b>
                      <span>Teaches the brain — reinforces what it recalled and writes an episode.</span>
                    </div>
                    <textarea
                      className="reflect-steps"
                      value={stepsTaken}
                      onChange={(e) => setStepsTaken(e.target.value)}
                      placeholder="Steps you actually took — one per line (optional; blank keeps the playbook's steps)"
                      rows={2}
                    />
                    <div className="reflect-actions">
                      <button className="btn small" onClick={() => doReflect(true)} disabled={busy}>
                        Went well
                      </button>
                      <button className="btn ghost small" onClick={() => doReflect(false)} disabled={busy}>
                        Didn't land
                      </button>
                    </div>
                  </div>
                )}
                {reflected && <p className="reflect-done">Reflected — memories reinforced, episode + associations written to the live brain.</p>}
              </div>
            </section>
          )}
        </div>
      </main>

      {/* ------------------------------------------------------------ think console */}
      <div className="dock">
        <div className="console">
          <span className="console-glyph">▸ THINK</span>
          <input
            value={stimulus}
            placeholder="Describe the situation…"
            onChange={(e) => setStimulus(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && doThink()}
          />
          <button className="btn ghost" onClick={() => setStimulus("")} disabled={!stimulus}>
            Clear
          </button>
          <button className="btn" onClick={() => doThink()} disabled={!stimulus.trim() || busy}>
            Think
          </button>
        </div>
        <div className="console-hint">
          <span>try:</span>
          <button className="chip-suggest" onClick={() => doThink(brain.id.includes("lawyer") ? "SaaS MSA: uncapped liability, one-sided indemnity, 3-yr auto-renew" : "45yo male, chest pain radiating to left arm, diaphoretic")}>
            {brain.id.includes("lawyer") ? "SaaS MSA: uncapped liability, one-sided indemnity, 3-yr auto-renew" : "45yo male, chest pain radiating to left arm, diaphoretic"}
          </button>
          <span className="stakes-note">fast vs slow is automatic — the brain takes a System-1 shortcut only on well-practiced instincts</span>
        </div>
      </div>

      {/* ------------------------------------------------------------ audit ribbon */}
      <div className="audit">
        <div className="audit-label">
          <span className="tick">audit</span>
        </div>
        <div className="audit-line">
          {audit.length === 0 ? (
            <span className="audit-empty">the brain's record of its own actions appears here — every think and check is logged.</span>
          ) : (
            audit.map((e) => (
              <div className="event" key={e.event}>
                <span className="dotk" />
                <span>{e.summary}</span>
              </div>
            ))
          )}
        </div>
        <button
          className="reset-btn"
          onClick={doRewind}
          data-tip="Undo the most recent structural change on the live brain"
          data-tip-align="right"
          disabled={busy}
        >
          ↺ rewind last
        </button>
      </div>
        </div>
      </div>

      {tour && <Walkthrough onDone={() => setTour(false)} />}

      {settingsOpen && (
        <SettingsDrawer
          onClose={() => setSettingsOpen(false)}
          brain={brain}
          online={online === true}
          engrams={engrams}
          memCount={activeMemories.length}
          assocCount={graph.edges.length}
          auditCount={audit.length}
          level={level}
          busy={busy}
          onReset={doReset}
          onSleep={doSleep}
          onReplayGuide={() => {
            setSettingsOpen(false);
            setTour(true);
          }}
          onResync={resync}
        />
      )}
    </div>
  );
}
