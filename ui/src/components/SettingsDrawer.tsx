// A right-side settings/manage drawer for the current brain: connection status, brain info,
// a maintenance action (sleep — decay & prune), replaying the guide, and a danger zone that
// resets this brain (or all) to a clean seed. Opened from the header gear.

import { useEffect, useState } from "react";
import type { BrainInfo } from "../lib/api";

interface Props {
  onClose: () => void;
  brain: BrainInfo;
  online: boolean;
  engrams: number; // total engrams in the store
  memCount: number; // active memories, current brain
  assocCount: number; // associations, current brain
  auditCount: number;
  level: string; // autonomy
  busy: boolean;
  onReset: (scope: "brain" | "all") => void;
  onSleep: () => Promise<{ decayed: number; pruned_count: number; edges_pruned: number } | void>;
  onReplayGuide: () => void;
  onResync: () => void;
}

export default function SettingsDrawer(p: Props) {
  const [confirm, setConfirm] = useState<"brain" | "all" | null>(null);
  const [sleepMsg, setSleepMsg] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && p.onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [p]);

  async function runSleep() {
    setSleepMsg(null);
    const r = await p.onSleep();
    if (r) setSleepMsg(`Decayed ${r.decayed} · pruned ${r.pruned_count} memories, ${r.edges_pruned} edges.`);
  }

  return (
    <div className="drawer-scrim" onClick={p.onClose}>
      <aside className="drawer" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Settings">
        <div className="drawer-head">
          <h3>Settings</h3>
          <button className="drawer-x" onClick={p.onClose} aria-label="Close settings">
            ✕
          </button>
        </div>

        {/* connection */}
        <section className="drawer-sec">
          <div className="drawer-sec-title">Connection</div>
          <div className="drawer-row">
            <span className={"conn-dot" + (p.online ? " on" : "")} />
            <span>{p.online ? "Live — driving the real engine" : "Offline"}</span>
          </div>
          <div className="drawer-sub">{p.engrams} engrams in store · bridge 127.0.0.1:8787</div>
          <button className="btn ghost small" onClick={p.onResync} disabled={p.busy}>
            Re-sync
          </button>
        </section>

        {/* current brain */}
        <section className="drawer-sec">
          <div className="drawer-sec-title">This brain</div>
          <div className="drawer-brain">{p.brain.label}</div>
          <div className="drawer-sub">{p.brain.id}</div>
          <div className="layer-chain">
            <span className="layer-chip">base</span>
            <span className="layer-arrow">→</span>
            <span className="layer-chip">domain</span>
            <span className="layer-arrow">→</span>
            <span className="layer-chip on">individual</span>
          </div>
          <div className="drawer-stats">
            <div>
              <b>{p.memCount}</b>
              <span>memories</span>
            </div>
            <div>
              <b>{p.assocCount}</b>
              <span>associations</span>
            </div>
            <div>
              <b>{p.auditCount}</b>
              <span>audit events</span>
            </div>
            <div>
              <b>{p.level}</b>
              <span>autonomy</span>
            </div>
          </div>
          <div className="drawer-sub">region · {p.brain.region}</div>
        </section>

        {/* maintenance */}
        <section className="drawer-sec">
          <div className="drawer-sec-title">Maintenance</div>
          <p className="drawer-note">
            <b>Sleep</b> — decays salience toward each memory's floor and prunes what has faded (weak
            memories &amp; edges). The Constitution never decays.
          </p>
          <button className="btn ghost small" onClick={runSleep} disabled={p.busy}>
            Run sleep
          </button>
          {sleepMsg && <div className="drawer-result">{sleepMsg}</div>}
        </section>

        {/* guide */}
        <section className="drawer-sec">
          <div className="drawer-sec-title">Guide</div>
          <button className="btn ghost small" onClick={p.onReplayGuide}>
            Replay the walkthrough
          </button>
        </section>

        {/* danger zone */}
        <section className="drawer-sec danger">
          <div className="drawer-sec-title">Danger zone</div>
          <p className="drawer-note">
            Resetting wipes taught memories, associations, trust and audit back to the clean seed. This
            cannot be undone.
          </p>

          {confirm !== "brain" ? (
            <button className="btn danger-btn" onClick={() => setConfirm("brain")} disabled={p.busy}>
              Reset this brain ({p.brain.label})
            </button>
          ) : (
            <div className="confirm-row">
              <span>Reset {p.brain.label}?</span>
              <button className="btn danger-solid" onClick={() => p.onReset("brain")} disabled={p.busy}>
                Confirm
              </button>
              <button className="btn ghost small" onClick={() => setConfirm(null)}>
                Cancel
              </button>
            </div>
          )}

          {confirm !== "all" ? (
            <button className="btn danger-btn" onClick={() => setConfirm("all")} disabled={p.busy}>
              Reset all brains
            </button>
          ) : (
            <div className="confirm-row">
              <span>Reset both brains?</span>
              <button className="btn danger-solid" onClick={() => p.onReset("all")} disabled={p.busy}>
                Confirm
              </button>
              <button className="btn ghost small" onClick={() => setConfirm(null)}>
                Cancel
              </button>
            </div>
          )}
        </section>
      </aside>
    </div>
  );
}
