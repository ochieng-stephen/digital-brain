export type Autonomy = "gated" | "guarded" | "autonomous";
export const AUTONOMY: Autonomy[] = ["gated", "guarded", "autonomous"];

const NOTE: Record<Autonomy, string> = {
  gated: "every write waits for you",
  guarded: "auto within guardrails",
  autonomous: "acts on its own",
};

interface Props {
  level: Autonomy; // earned, reported by the live brain
  reviews: number;
  acceptRate: number; // 0..1
  suggestedLevel: string | null; // non-null when the brain says a promotion is earned
  onPromote: () => void;
}

export default function AutonomyDial({ level, reviews, acceptRate, suggestedLevel, onPromote }: Props) {
  // the path to more autonomy, spelled out so it isn't a mystery button (thresholds match config.py)
  let hint: string | null = null;
  if (level !== "autonomous" && !suggestedLevel) {
    hint = reviews < 5 ? `${reviews}/5 reviews to earn the next level` : `${Math.round(acceptRate * 100)}% accepted · need 80%`;
  }

  return (
    <div className="dial">
      <div className="dial-label">
        <span className="tick">autonomy · earned</span>
        <span className="lvl">{NOTE[level]}</span>
        <span className="trust-note">
          {reviews} review{reviews === 1 ? "" : "s"} · {Math.round(acceptRate * 100)}% accepted
        </span>
        {hint && <span className="promote-hint">{hint}</span>}
      </div>
      <div className="dial-track" role="group" aria-label="Earned autonomy level">
        {AUTONOMY.map((l) => (
          <span key={l} className="dial-opt" data-on={level === l} data-locked={AUTONOMY.indexOf(l) > AUTONOMY.indexOf(level)}>
            {l}
          </span>
        ))}
      </div>
      {suggestedLevel && (
        <button className="btn promote" onClick={onPromote}>
          Promote →
        </button>
      )}
    </div>
  );
}
