// The living centerpiece — the supplied pen-and-ink brain⇄chip illustration embedded as the base
// layer (its fine hatching/stippling can't be vectorised without losing the detail), with a
// restrained interactive layer composited on top: soft recall glows that warm the lit regions from
// within (clipped to the traced silhouette), a chip pulse while thinking, a seam flare on a
// Constitution check, and the circuit terminals softly firing. All overlay coordinates were
// measured off the artwork itself (silhouette trace + chip/seam/terminal detection), in the
// image's own 749×853 space, so nothing drifts from the drawing.
//
// The recall layer is a living MAP of the memory store, not a set of pegs. Every active memory is a
// soft glow whose POSITION comes from a force-directed layout of the real association graph
// (constrained to the organic hemisphere, seeded by memory kind): memories wired together pull into
// clusters, isolated ones drift apart — so the picture reflects how the store is actually wired and
// how it clusters, and it re-flows (gliding smoothly) as wiring grows over time, like a real brain.
// Each glow's RESTING warmth + size scale with the memory's wiring strength and salience — so at
// idle the cortex faintly shimmers, denser-wired areas glowing warmer — and RECALL/hover lifts the
// relevant memories above that baseline (fading gently back down when they stop firing). Glows are
// large and overlap on purpose, merging into continuous organic areas rather than dots.

import { useMemo } from "react";
import type { MemKind } from "../lib/api";

export type SeamState = "idle" | "pass" | "violation";

export interface MemoryNode {
  id: string;
  kind: MemKind; // seeds the layout toward a functional region
  wiring: number; // 0..1 normalised association strength (degree-weighted) → resting warmth + size
  salience: number; // 0..1 importance → area size
  fire: number; // 0..1 current activation from recall/hover (0 = resting)
}

export interface MemoryEdge {
  from: string;
  to: string;
  weight: number;
}

interface Props {
  nodes: MemoryNode[]; // every active memory, with its live metrics
  edges: MemoryEdge[]; // the association graph — drives the clustering layout
  thinking: boolean; // pulse the chip while a thought is in flight
  seamState: SeamState;
  energy: number; // 0..1 autonomy → firing speed
}

const VIEW = { w: 749, h: 853 };
const SEAM_X = 366;
const SEAM_Y1 = 44;
const SEAM_Y2 = 812;
const CHIP = { x: 370, y: 291, w: 146, h: 274, rx: 26 };

// outer brain silhouette, traced off the drawing — clips the recall glow so it reads as the
// material lighting up, never spilling onto the page.
const SILHOUETTE =
  "M364,0 L364,56 L361,60 L349,61 L323,50 L253,58 L225,75 L191,86 L161,116 L135,135 L121,159 L116,179 L95,212 L87,252 L65,288 L57,329 L44,354 L41,382 L27,415 L32,464 L25,485 L25,504 L33,539 L55,582 L59,619 L49,628 L74,662 L71,676 L74,680 L85,682 L116,708 L143,749 L158,750 L199,780 L242,791 L250,801 L249,811 L283,814 L312,807 L322,810 L348,781 L355,763 L362,762 L366,852 Z";

// functional zones on the organic hemisphere (749×853 art space, all left of the seam) — used only
// to SEED the layout and gently anchor a memory toward the region for its kind (semantic→frontal,
// procedural→central, episodic→temporal); the association graph then pulls wired memories together.
const ZONES: Record<MemKind, { cx: number; cy: number }> = {
  semantic: { cx: 214, cy: 260 }, // frontal — knowledge / reasoning
  procedural: { cx: 206, cy: 452 }, // central, motor strip — skills
  episodic: { cx: 202, cy: 636 }, // temporal / occipital — events
};

// the field the map lives in — an ellipse tucked inside the silhouette; positions are clamped here
// so clusters never drift off the organic hemisphere (the glow is clipped to the silhouette anyway).
const FIELD = { cx: 198, cy: 436, rx: 158, ry: 330 };

// FNV-1a: a fast, well-mixed hash → a stable per-memory seed (layout start, shimmer phase).
function hashId(id: string): number {
  let h = 2166136261 >>> 0;
  for (let k = 0; k < id.length; k++) {
    h ^= id.charCodeAt(k);
    h = Math.imul(h, 16777619) >>> 0;
  }
  return h >>> 0;
}

interface Pt {
  x: number;
  y: number;
}

function clampField({ x, y }: Pt): Pt {
  const dx = (x - FIELD.cx) / FIELD.rx;
  const dy = (y - FIELD.cy) / FIELD.ry;
  const d = Math.hypot(dx, dy);
  if (d <= 1) return { x, y };
  return { x: FIELD.cx + (dx / d) * FIELD.rx, y: FIELD.cy + (dy / d) * FIELD.ry };
}

// Deterministic force-directed layout of the association graph, constrained to the field. Wired
// memories attract (∝ weight) into clusters; everything repels so clusters stay legible; a soft pull
// to each memory's kind-zone keeps the map anatomically grounded and stable. Seeded from the id so
// the same store always lays out the same way (and re-flows smoothly when wiring changes).
function layoutMap(nodes: MemoryNode[], edges: MemoryEdge[]): Map<string, Pt> {
  const n = nodes.length;
  const pos: Pt[] = nodes.map((nd) => {
    const z = ZONES[nd.kind] ?? ZONES.semantic;
    const h = hashId(nd.id);
    const a = ((h & 2047) / 2048) * Math.PI * 2;
    const rf = Math.sqrt(((h >>> 11) & 2047) / 2048);
    return { x: z.cx + Math.cos(a) * 96 * rf, y: z.cy + Math.sin(a) * 96 * rf };
  });
  const idx = new Map(nodes.map((nd, i) => [nd.id, i]));
  const E = edges
    .map((e) => ({ a: idx.get(e.from), b: idx.get(e.to), w: e.weight }))
    .filter((e) => e.a != null && e.b != null) as { a: number; b: number; w: number }[];

  for (let it = 0; it < 300; it++) {
    const fx = new Array(n).fill(0);
    const fy = new Array(n).fill(0);
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        let dx = pos[i].x - pos[j].x;
        let dy = pos[i].y - pos[j].y;
        const d2 = dx * dx + dy * dy || 0.01;
        const d = Math.sqrt(d2);
        const rep = 2200 / d2;
        dx /= d;
        dy /= d;
        fx[i] += dx * rep;
        fy[i] += dy * rep;
        fx[j] -= dx * rep;
        fy[j] -= dy * rep;
      }
    }
    for (const e of E) {
      const dx = pos[e.b].x - pos[e.a].x;
      const dy = pos[e.b].y - pos[e.a].y;
      const d = Math.hypot(dx, dy) || 0.01;
      const f = (d - 40) * 0.03 * (0.5 + e.w); // wired memories settle ~40px apart → tight clusters
      const ux = (dx / d) * f;
      const uy = (dy / d) * f;
      fx[e.a] += ux;
      fy[e.a] += uy;
      fx[e.b] -= ux;
      fy[e.b] -= uy;
    }
    for (let i = 0; i < n; i++) {
      const z = ZONES[nodes[i].kind] ?? ZONES.semantic;
      fx[i] += (z.cx - pos[i].x) * 0.006; // gentle anatomical anchoring
      fy[i] += (z.cy - pos[i].y) * 0.006;
      pos[i].x += fx[i] * 0.5;
      pos[i].y += fy[i] * 0.5;
      const c = clampField(pos[i]);
      pos[i].x = c.x;
      pos[i].y = c.y;
    }
  }
  return new Map(nodes.map((nd, i) => [nd.id, pos[i]]));
}

// the drawn circuit-lead terminals — they fire as the chip's outputs (on-geometry, no invented paths)
const TERMINALS: Array<[number, number]> = [
  [499, 128],
  [616, 196],
  [545, 220],
  [631, 317],
  [715, 421],
  [650, 621],
  [553, 686],
];

export default function BrainCore({ nodes, edges, thinking, seamState, energy }: Props) {
  const fireDur = (3.6 - energy * 1.6).toFixed(2) + "s";
  // layout depends only on the graph STRUCTURE (which memories, which wiring), not on live fire/
  // salience — so the map is stable while recalling and only re-flows when the wiring itself changes.
  const sig = nodes.map((n) => n.id).join(",") + "|" + edges.map((e) => `${e.from}~${e.to}:${e.weight}`).join(",");
  const at = useMemo(() => layoutMap(nodes, edges), [sig]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <svg
      className={"brain-svg" + (thinking ? " chip-active" : "")}
      viewBox={`0 0 ${VIEW.w} ${VIEW.h}`}
      role="img"
      aria-label="Digital brain: organic memory fused with a silicon processor"
    >
      <defs>
        <radialGradient id="regionGlow" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="var(--accent-a)" stopOpacity="0.9" />
          <stop offset="55%" stopColor="var(--accent-b)" stopOpacity="0.45" />
          <stop offset="100%" stopColor="var(--accent-b)" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="accentGrad" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="var(--accent-a)" />
          <stop offset="1" stopColor="var(--accent-b)" />
        </linearGradient>
        <linearGradient id="seamGrad" gradientUnits="userSpaceOnUse" x1="0" y1={SEAM_Y1} x2="0" y2={SEAM_Y2}>
          <stop offset="0" stopColor="var(--ink-3)" stopOpacity="0.0" />
          <stop offset="0.5" stopColor="var(--ink)" stopOpacity="0.35" />
          <stop offset="1" stopColor="var(--ink-3)" stopOpacity="0.0" />
        </linearGradient>
        <filter id="softBlur" x="-80%" y="-80%" width="260%" height="260%">
          <feGaussianBlur stdDeviation="16" />
        </filter>
        <clipPath id="brainClip">
          <path d={SILHOUETTE} />
        </clipPath>
      </defs>

      <g className="brain-breathe">
        {/* base: the hand-drawn illustration */}
        <image href="/brain-art.png" x="0" y="0" width={VIEW.w} height={VIEW.h} />

        {/* the living memory map — every memory is a soft area at its clustered position; it shimmers
            faintly at rest (warmth ∝ wiring) and lifts when recalled/hovered, then fades gently back.
            Large + overlapping on purpose, so clusters read as continuous organic areas, not dots. */}
        <g clipPath="url(#brainClip)" className="recall-layer">
          {nodes.map((nd) => {
            const p = at.get(nd.id);
            if (!p) return null;
            const rest = 0.15 + 0.3 * nd.wiring + 0.05 * nd.salience; // hubs glow clearly warmer than leaves
            const level = Math.max(rest, nd.fire); // recall/hover lifts above the resting baseline
            const r = 44 + 20 * nd.salience + 44 * nd.wiring; // hubs are markedly larger areas → dense core
            const h = hashId(nd.id);
            const delay = (((h >>> 15) & 255) / 256) * 6; // desync the resting shimmer
            const dur = (4.8 + ((h >>> 7) & 7) * 0.45).toFixed(2); // varied shimmer period
            return (
              <g key={nd.id} className="mem-region" transform={`translate(${p.x.toFixed(1)},${p.y.toFixed(1)})`}>
                <circle
                  className="mem-glow"
                  r={r.toFixed(1)}
                  fill="url(#regionGlow)"
                  filter="url(#softBlur)"
                  style={{ opacity: level, animationDelay: `${delay.toFixed(2)}s`, animationDuration: `${dur}s` }}
                />
              </g>
            );
          })}
        </g>

        {/* chip pulse halo — glows behind the chip while a thought is being scaffolded */}
        <rect
          className="chip-pulse"
          x={CHIP.x}
          y={CHIP.y}
          width={CHIP.w}
          height={CHIP.h}
          rx={CHIP.rx}
          fill="url(#accentGrad)"
          filter="url(#softBlur)"
        />

        {/* the Constitution seam — a flare on the drawn divider on a check */}
        <line
          className={"seam " + seamState}
          x1={SEAM_X}
          y1={SEAM_Y1}
          x2={SEAM_X}
          y2={SEAM_Y2}
          stroke="url(#seamGrad)"
          strokeWidth={4}
          strokeLinecap="round"
        />

        {/* circuit terminals firing — subtle idle life, quicker with autonomy */}
        {TERMINALS.map(([cx, cy], i) => (
          <circle
            key={i}
            className="terminal"
            cx={cx}
            cy={cy}
            r={5}
            fill="url(#accentGrad)"
            style={{ animationDuration: fireDur, animationDelay: `${(i * 0.32).toFixed(2)}s` }}
          />
        ))}
      </g>
    </svg>
  );
}
