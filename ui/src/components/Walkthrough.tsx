// A light, one-time first-run tour. Spotlights real UI elements one at a time with a short caption
// so a first-time user learns the loop by seeing it — no video, no long modal. Shown once
// (localStorage flag); re-openable from the "guide" button in the header.

import { useLayoutEffect, useState } from "react";

export const TOUR_FLAG = "db-tour-done:v1";

interface Step {
  sel: string;
  title: string;
  body: string;
}

const STEPS: Step[] = [
  {
    sel: ".console",
    title: "① Start here",
    body: "Describe a situation and press Think — or tap the example chip. The brain returns a reasoning scaffold for any model to use.",
  },
  {
    sel: ".rail .panel",
    title: "② Its memory",
    body: "What the brain knows. Relevant memories light up when it thinks; teach it new ones with “Remember”, and hover a memory for Explain / Edit / Forget.",
  },
  {
    sel: ".brain-stage",
    title: "③ The live brain",
    body: "The centerpiece is real. Regions glow as memory is recalled, and the seam between mind and machine flares green or red when you check a draft against its Constitution.",
  },
  {
    sel: ".col-right .panel",
    title: "④ Scaffold & check",
    body: "After a Think, this shows the playbook, recalled memories, and the hard rules it can’t cross. Paste a draft to check it — then mark the outcome so the brain learns.",
  },
  {
    sel: ".center-toggle",
    title: "⑤ It rewires as you use it",
    body: "Swap the centre to “Wiring” to watch the memory graph. Reflecting “Went well” after a check wires co-recalled memories together — and autonomy is earned as you approve its suggestions.",
  },
];

interface Props {
  onDone: () => void;
}

export default function Walkthrough({ onDone }: Props) {
  const [i, setI] = useState(0);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const step = STEPS[i];

  // Keep the spotlight locked to the target. Memories load asynchronously from the live brain, so
  // the layout grows after the tour mounts — re-center + re-measure across several frames so the
  // spotlight always lands on the settled position, and track any scroll live.
  useLayoutEffect(() => {
    let cancelled = false;
    const measure = () => {
      const el = document.querySelector(step.sel);
      if (el) setRect(el.getBoundingClientRect());
    };
    const center = () => {
      if (cancelled) return;
      const el = document.querySelector(step.sel);
      if (el) {
        el.scrollIntoView({ behavior: "auto", block: "center" });
        setRect(el.getBoundingClientRect());
      }
    };
    center();
    const timers = [60, 180, 380, 680].map((d) => window.setTimeout(center, d));
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      cancelled = true;
      timers.forEach(clearTimeout);
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [step.sel]);

  const finish = () => {
    try {
      localStorage.setItem(TOUR_FLAG, "1");
    } catch {
      /* ignore */
    }
    onDone();
  };

  const last = i === STEPS.length - 1;
  const pad = 8;

  // Place the caption card in the first spot with room: below → above → right → left → center.
  // A target taller than the viewport (the Recall panel) has no room above/below, so it lands to
  // the side (never off-screen / cropped). Always clamped fully inside the viewport.
  const cardStyle: React.CSSProperties = (() => {
    const winW = window.innerWidth;
    const winH = window.innerHeight;
    const cardW = 320;
    const cardH = 190;
    const gap = 12;
    const margin = 16;
    if (!rect) return { top: (winH - cardH) / 2, left: (winW - cardW) / 2 };
    const clampX = (x: number) => Math.max(margin, Math.min(winW - cardW - margin, x));
    const clampY = (y: number) => Math.max(margin, Math.min(winH - cardH - margin, y));
    const alignX = clampX(rect.left + rect.width / 2 - cardW / 2);
    const sideY = clampY((Math.max(0, rect.top) + Math.min(winH, rect.bottom)) / 2 - cardH / 2);
    if (winH - rect.bottom >= cardH + gap) return { top: rect.bottom + gap, left: alignX };
    if (rect.top >= cardH + gap) return { top: rect.top - gap - cardH, left: alignX };
    if (winW - rect.right >= cardW + gap) return { top: sideY, left: rect.right + gap };
    if (rect.left >= cardW + gap) return { top: sideY, left: rect.left - gap - cardW };
    return { top: sideY, left: alignX };
  })();

  return (
    <div className="tour" role="dialog" aria-modal="true" aria-label="Getting started">
      {rect && (
        <div
          className="tour-spot"
          style={{
            top: rect.top - pad,
            left: rect.left - pad,
            width: rect.width + pad * 2,
            height: rect.height + pad * 2,
          }}
        />
      )}
      <div className="tour-card" style={cardStyle}>
        <div className="tour-title">{step.title}</div>
        <div className="tour-body">{step.body}</div>
        <div className="tour-foot">
          <button className="tour-skip" onClick={finish}>
            Skip
          </button>
          <div className="tour-nav">
            <span className="tour-dots">
              {STEPS.map((_, k) => (
                <span key={k} className={"tour-dot" + (k === i ? " on" : "")} />
              ))}
            </span>
            {i > 0 && (
              <button className="btn ghost small" onClick={() => setI((n) => n - 1)}>
                Back
              </button>
            )}
            <button className="btn small" onClick={() => (last ? finish() : setI((n) => n + 1))}>
              {last ? "Got it" : "Next"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
