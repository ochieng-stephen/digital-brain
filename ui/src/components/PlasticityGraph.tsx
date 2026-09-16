// The plasticity graph, drawn: memory nodes + the Hebbian association edges among them, laid out
// by a tiny deterministic force simulation so wired memories cluster ("fire together, wire
// together"). Edge thickness ∝ weight; a node pulses when it fires (is recalled) during a think.
// Hovering a node instantly shows its label and highlights its wiring. Data: live GET /graph.
//
// It lives in the swappable centre slot (interchangeable with the brain art), so the SVG scales to
// fit that slot via preserveAspectRatio. A single, near-square viewBox is used for both states so
// the framing stays put whether or not any wiring exists yet.

import { useMemo, useState } from "react";
import type { Graph } from "../lib/api";

interface Props {
  graph: Graph;
  firing: Set<string>; // engram ids recalled in the current cycle
}

const W = 560;
const H_WIRED = 430; // near-square viewBox; the SVG scales to fit the centre slot
const H_EMPTY = 430; // same as wired so the framing doesn't jump when the first wiring appears
const GLYPH: Record<string, string> = { semantic: "S", episodic: "E", procedural: "P" };
const nodeR = (salience: number) => 10 + salience * 6.5; // refined (10–16.5px at 1:1)

interface Pos {
  id: string;
  x: number;
  y: number;
}

function layout(graph: Graph, H: number): Pos[] {
  const n = graph.nodes.length;
  if (n === 0) return [];
  // Unwired (no edges yet): a tidy, evenly-spaced centered row — never a scattered soup, so the
  // empty-state caption below it stays clean and legible.
  if (graph.edges.length === 0) {
    const span = Math.min(W - 160, (n - 1) * 90);
    const x0 = W / 2 - span / 2;
    return graph.nodes.map((nd, i) => ({ id: nd.id, x: n === 1 ? W / 2 : x0 + (span * i) / (n - 1), y: H / 2 }));
  }
  const pos = graph.nodes.map((nd, i) => {
    const a = (i / n) * Math.PI * 2;
    return { id: nd.id, x: W / 2 + Math.cos(a) * W * 0.3, y: H / 2 + Math.sin(a) * H * 0.32 };
  });
  const idx = new Map(pos.map((p, i) => [p.id, i]));
  const edges = graph.edges
    .map((e) => ({ a: idx.get(e.from), b: idx.get(e.to), w: e.weight }))
    .filter((e) => e.a != null && e.b != null) as { a: number; b: number; w: number }[];

  for (let iter = 0; iter < 260; iter++) {
    const fx = new Array(n).fill(0);
    const fy = new Array(n).fill(0);
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        let dx = pos[i].x - pos[j].x;
        let dy = pos[i].y - pos[j].y;
        const d2 = dx * dx + dy * dy || 0.01;
        const rep = 5000 / d2;
        const d = Math.sqrt(d2);
        dx /= d;
        dy /= d;
        fx[i] += dx * rep;
        fy[i] += dy * rep;
        fx[j] -= dx * rep;
        fy[j] -= dy * rep;
      }
    }
    for (const e of edges) {
      const dx = pos[e.b].x - pos[e.a].x;
      const dy = pos[e.b].y - pos[e.a].y;
      const d = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const k = 0.028 * (0.5 + e.w);
      const f = (d - 82) * k;
      const ux = (dx / d) * f;
      const uy = (dy / d) * f;
      fx[e.a] += ux;
      fy[e.a] += uy;
      fx[e.b] -= ux;
      fy[e.b] -= uy;
    }
    for (let i = 0; i < n; i++) {
      fx[i] += (W / 2 - pos[i].x) * 0.011;
      fy[i] += (H / 2 - pos[i].y) * 0.011;
      pos[i].x = Math.max(24, Math.min(W - 24, pos[i].x + fx[i] * 0.5));
      pos[i].y = Math.max(22, Math.min(H - 22, pos[i].y + fy[i] * 0.5));
    }
  }
  return pos;
}

export default function PlasticityGraph({ graph, firing }: Props) {
  const [hover, setHover] = useState<string | null>(null);
  const H = graph.edges.length === 0 ? H_EMPTY : H_WIRED;
  const sig = graph.nodes.map((n) => n.id).join(",") + "|" + graph.edges.map((e) => `${e.from}-${e.to}:${e.weight}`).join(",");
  const pos = useMemo(() => layout(graph, H), [sig, H]); // eslint-disable-line react-hooks/exhaustive-deps
  const at = useMemo(() => new Map(pos.map((p) => [p.id, p])), [pos]);

  const hoverNode = hover ? graph.nodes.find((n) => n.id === hover) : null;
  const hoverPos = hover ? at.get(hover) : null;

  return (
    <svg className="pgraph" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Plasticity graph of memory associations">
      <defs>
        <linearGradient id="pnodeBase" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#ffffff" />
          <stop offset="1" stopColor="#e7ebf0" />
        </linearGradient>
        <linearGradient id="pnodeAccent" x1="0" y1="0" x2="0.9" y2="1">
          <stop offset="0" stopColor="var(--accent-a)" />
          <stop offset="1" stopColor="var(--accent-b)" />
        </linearGradient>
        <filter id="pnodeShadow" x="-70%" y="-70%" width="240%" height="240%">
          <feDropShadow dx="0" dy="1.6" stdDeviation="1.7" floodColor="#0b0d12" floodOpacity="0.18" />
        </filter>
      </defs>
      {graph.edges.map((e, i) => {
        const a = at.get(e.from);
        const b = at.get(e.to);
        if (!a || !b) return null;
        const lit = firing.has(e.from) && firing.has(e.to);
        const touchesHover = hover != null && (e.from === hover || e.to === hover);
        return (
          <line
            key={i}
            x1={a.x}
            y1={a.y}
            x2={b.x}
            y2={b.y}
            className={"pedge" + (lit ? " lit" : "") + (touchesHover ? " hovered" : "")}
            strokeWidth={1.5 + e.weight * 4}
            style={{ opacity: touchesHover ? 0.95 : 0.2 + e.weight * 0.6 }}
          />
        );
      })}
      {graph.nodes.map((nd) => {
        const p = at.get(nd.id);
        if (!p) return null;
        const on = firing.has(nd.id);
        return (
          <g
            key={nd.id}
            className={"pnode" + (on ? " on" : "") + (hover === nd.id ? " hovered" : "")}
            transform={`translate(${p.x},${p.y})`}
            onMouseEnter={() => setHover(nd.id)}
            onMouseLeave={() => setHover((h) => (h === nd.id ? null : h))}
          >
            {/* inner group carries the hover-lift / firing-pulse so it never fights the translate */}
            <g className="pnode-inner">
              <circle
                className="pnode-dot"
                r={nodeR(nd.salience)}
                fill={on ? "url(#pnodeAccent)" : "url(#pnodeBase)"}
                filter="url(#pnodeShadow)"
              />
              <text className="pnode-glyph" y={0.5} textAnchor="middle" dominantBaseline="central">
                {GLYPH[nd.type] ?? "?"}
              </text>
            </g>
          </g>
        );
      })}

      {/* instant tooltip for the hovered node (SVG-native — no browser `title` delay) */}
      {hoverNode &&
        hoverPos &&
        (() => {
          const raw = hoverNode.label;
          const label = raw.length > 42 ? raw.slice(0, 42) + "…" : raw;
          // padding tuned to match the Explain-button tooltip (~3px vertical, ~7px horizontal)
          const th = 17;
          const w = Math.min(320, label.length * 6.0 + 14);
          const r = nodeR(hoverNode.salience);
          const cx = Math.max(w / 2 + 3, Math.min(W - w / 2 - 3, hoverPos.x));
          const top = hoverPos.y - r - th - 7;
          const y = top < 2 ? hoverPos.y + r + 7 : top; // flip below if it would clip the top
          return (
            <g className="ptip" pointerEvents="none">
              <rect x={cx - w / 2} y={y} width={w} height={th} rx={6} />
              <text x={cx} y={y + th / 2} textAnchor="middle" dominantBaseline="central">
                {label}
              </text>
            </g>
          );
        })()}
    </svg>
  );
}
