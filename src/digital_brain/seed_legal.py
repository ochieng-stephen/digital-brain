"""Second domain: a lawyer's brain for commercial-contract review.

Exists to exercise the layering cascade across unrelated fields — it hangs the
SAME `base` brain (and the shared base Instinct) under a new domain + individual:

  base -> domain:legal_contract_review -> individual:lawyer_demo

Safety lives IN the brain as hard-Constitution value engrams (structurally identical
to the medical MVP), so brain.check enforces it. Synthetic, illustrative content only.

Seeded via:  brain seed --domain legal   (or --domain all, alongside medical)
"""
from __future__ import annotations

from .embeddings import embed
from .seed import BASE, _embed_text
from .store import Store

DOMAIN = "domain:legal_contract_review"
INDIV = "individual:lawyer_demo"
REGION = "contract_review"

PRIO = {BASE: 0, DOMAIN: 1, INDIV: 2}

# The shared base Instinct (same text the medical seed uses). Inserted here only if
# the base layer has no values yet, so legal-only seeding still gets it — and there is
# no duplication when medical has already seeded base.
BASE_INSTINCT = "State uncertainty explicitly and never overclaim."

SEMANTIC = [
    {"concept": "Unlimited / uncapped liability",
     "definition": "No ceiling on damages a party may owe; exposure can exceed the contract value. "
                   "High-risk unless capped by a limitation-of-liability clause.",
     "facts": ["look for a liability cap (e.g. fees paid in 12 months)", "watch for carve-outs that reopen the cap"]},
    {"concept": "Indemnification",
     "definition": "A promise to cover another party's losses/claims. One-sided or broad indemnities "
                   "shift disproportionate risk; mutual, scoped indemnities are more balanced.",
     "facts": ["check scope, triggers, and caps", "note whether it is mutual or one-sided"]},
    {"concept": "Auto-renewal (evergreen) clause",
     "definition": "The term renews automatically unless notice is given within a window; easy to miss "
                   "and can lock in unwanted obligations.",
     "facts": ["find the notice window and method", "diarize the non-renewal deadline"]},
    {"concept": "Governing law & jurisdiction",
     "definition": "Which jurisdiction's law applies and where disputes are heard. Drives enforceability, "
                   "cost, and forum convenience.",
     "facts": ["confirm venue and dispute-resolution (litigation vs arbitration)"]},
    {"concept": "Intellectual property assignment",
     "definition": "Whether IP created or shared under the contract is assigned, licensed, or retained. "
                   "Broad assignments can transfer more than intended.",
     "facts": ["distinguish assignment vs license", "check background vs foreground IP"]},
]

PLAYBOOK = {
    "kind": "procedural",
    "name": "Review a commercial contract",
    "preconditions": ["a commercial contract or agreement to review"],
    "steps": [
        "Identify the parties, effective date, and term",
        "Read the defined terms; map each party's obligations",
        "Flag liability: check for unlimited/uncapped liability and any limitation-of-liability cap",
        "Flag indemnification: scope, triggers, mutual vs one-sided, and carve-outs",
        "Check termination, notice periods, and auto-renewal/evergreen terms",
        "Confirm governing law, jurisdiction, and dispute resolution",
        "Assign a risk rating (low/medium/high) to each flagged clause and summarize",
    ],
    "expected_outcome": "A clause-by-clause risk summary and clear redline recommendations",
    "examples": [],
}

# Constitution — hard, enforced deterministically by brain.check.
CONSTITUTION = [
    {"brain": DOMAIN, "region": "*",
     "rule": "Never present output as legal advice; frame it as informational and requiring attorney review.",
     "scope": "all legal output", "rationale": "Unauthorized-practice risk; the attorney is the decision-maker.",
     "check": {"mode": "require_any",
               "terms": ["not legal advice", "informational", "attorney review", "consult a lawyer", "attorney"]}},
    {"brain": DOMAIN, "region": REGION,
     "rule": "Always flag uncapped/unlimited liability and broad or one-sided indemnification.",
     "scope": "contract review", "rationale": "These clauses carry the highest downside risk.",
     "check": {"mode": "require_all", "terms": ["liability", "indemnif"]}},
    {"brain": DOMAIN, "region": REGION,
     "rule": "Never advise signing without identifying the governing law and termination terms.",
     "scope": "contract review", "rationale": "Enforceability and exit rights are non-negotiable basics.",
     "check": {"mode": "require_if",
               "if_terms": ["ok to sign", "safe to sign", "advise signing", "recommend signing", "proceed to sign"],
               "then_terms": ["governing law", "termination"]}},
    # Individual ADDS a stricter red line (monotonic tightening — see data-model.md).
    {"brain": INDIV, "region": REGION,
     "rule": "Never finalize a contract review without a risk rating (low/medium/high) for each flagged clause.",
     "scope": "contract review", "rationale": "Counsel's personal standard for actionable, defensible reviews.",
     "check": {"mode": "require_any",
               "terms": ["risk rating", "high risk", "medium risk", "low risk"]}},
]

# Instinct — soft, always-on defaults.
INSTINCTS = [
    {"brain": DOMAIN, "region": REGION,
     "rule": "Read the whole document and its defined terms before opining.", "scope": "contract review"},
    {"brain": INDIV, "region": "*",
     "rule": "Explain clauses in plain language a non-lawyer client can act on.", "scope": "all"},
]

EPISODES = [
    {"situation": "SaaS vendor MSA with uncapped liability and a one-sided indemnity in the vendor's favor.",
     "action": "Flagged the missing liability cap and one-sided indemnification; confirmed governing law and "
               "termination; rated both clauses high risk and proposed a mutual, capped redline.",
     "action_steps": ["map obligations", "flag liability cap", "flag indemnification",
                      "check termination + governing law", "assign risk rating"],
     "outcome": "Vendor accepted a mutual cap; risk materially reduced.", "valence": 0.85},
]


def _ensure_base(s: Store) -> None:
    """Base brain node + the shared base Instinct (insert only if base has no values yet)."""
    s.upsert_brain(BASE, "Universal base brain", "base")
    n = s.conn.execute("SELECT count(*) AS n FROM engrams WHERE brain_id=%s AND type='value'",
                       (BASE,)).fetchone()["n"]
    if n == 0:
        content = {"kind": "value", "enforcement": "soft", "rule": BASE_INSTINCT, "scope": "*", "rationale": ""}
        s.add_engram(BASE, "value", "*", content, embed(BASE_INSTINCT),
                     salience=0.6, base_salience=0.55, decay_rate=0.005, layer_priority=PRIO[BASE])


def load(reset: bool = False) -> Store:
    """Seed the legal domain under the shared base. Default reset=False so it can be layered
    alongside the medical seed (see `brain seed --domain all`)."""
    s = Store()
    s.init_schema()
    if reset:
        s.reset()

    _ensure_base(s)
    s.upsert_brain(DOMAIN, "Commercial contract review", "domain", parent_id=BASE)
    s.upsert_brain(INDIV, "Counsel Demo", "individual", parent_id=DOMAIN)

    for c in SEMANTIC:
        content = {"kind": "semantic", **c}
        s.add_engram(DOMAIN, "semantic", REGION, content, embed(_embed_text("semantic", content)),
                     salience=0.6, base_salience=0.5, layer_priority=PRIO[DOMAIN])

    s.add_engram(DOMAIN, "procedural", REGION, PLAYBOOK, embed(_embed_text("procedural", PLAYBOOK)),
                 salience=0.8, base_salience=0.6, layer_priority=PRIO[DOMAIN],
                 triggers=["contract", "agreement", "MSA", "terms"])

    for r in CONSTITUTION:
        content = {"kind": "value", "enforcement": "hard", "rule": r["rule"],
                   "scope": r["scope"], "rationale": r["rationale"], "check": r["check"]}
        s.add_engram(r["brain"], "value", r["region"], content, embed(content["rule"]),
                     salience=0.7, base_salience=0.7, decay_rate=0.0, layer_priority=PRIO[r["brain"]])

    for r in INSTINCTS:
        content = {"kind": "value", "enforcement": "soft", "rule": r["rule"],
                   "scope": r["scope"], "rationale": ""}
        s.add_engram(r["brain"], "value", r["region"], content, embed(content["rule"]),
                     salience=0.6, base_salience=0.55, decay_rate=0.005, layer_priority=PRIO[r["brain"]])

    for e in EPISODES:
        content = {"kind": "episodic", **e, "refs": []}
        s.add_engram(INDIV, "episodic", REGION, content, embed(_embed_text("episodic", content)),
                     salience=0.55, base_salience=0.4, layer_priority=PRIO[INDIV])

    return s


if __name__ == "__main__":
    st = load(reset=False)
    n = st.conn.execute("SELECT count(*) AS n FROM engrams WHERE brain_id=%s", (DOMAIN,)).fetchone()["n"]
    print(f"Seeded legal domain ({n} domain engrams) under {BASE}.")
    st.close()
