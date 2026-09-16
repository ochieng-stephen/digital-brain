"""Seed a doctor's brain for the chest-pain MVP (design/mvp-medical.md).

Three layers demonstrate the cascade:
  base -> domain:emergency_medicine -> individual:dr_demo
Safety lives IN the brain as hard-Constitution value engrams, so brain.check
enforces it — it is not merely documentation.
"""
from __future__ import annotations

from .embeddings import embed
from .store import Store

BASE = "base"
DOMAIN = "domain:emergency_medicine"
INDIV = "individual:dr_demo"
REGION = "chest_pain_workup"

# layer_priority: individual (2) > domain (1) > base (0)
PRIO = {BASE: 0, DOMAIN: 1, INDIV: 2}


def _embed_text(type_: str, content: dict) -> str:
    if type_ == "semantic":
        return f"{content['concept']}. {content['definition']}"
    if type_ == "episodic":
        return f"{content['situation']} {content.get('action','')} {content.get('outcome','')}"
    if type_ == "procedural":
        return f"{content['name']}. Steps: {'; '.join(content['steps'])}"
    if type_ == "value":
        return content["rule"]
    return str(content)


# ------------------------------------------------------------------ content
SEMANTIC = [
    {"concept": "Acute coronary syndrome (ACS)",
     "definition": "Myocardial ischemia from plaque rupture; presents as pressure-like chest pain, "
                   "often with exertion, radiation to arm/jaw, diaphoresis. Can't-miss.",
     "facts": ["ECG + serial troponin are the core rule-out", "risk factors: HTN, DM, smoking, age"]},
    {"concept": "Pulmonary embolism (PE)",
     "definition": "Clot in the pulmonary arteries; pleuritic chest pain, dyspnea, tachycardia, hypoxia. Can't-miss.",
     "facts": ["consider Wells score / PERC", "D-dimer or CTPA per pretest probability"]},
    {"concept": "Aortic dissection",
     "definition": "Tear in the aortic intima; sudden tearing chest/back pain, pulse or BP differential "
                   "between arms. Can't-miss.",
     "facts": ["check BP in both arms", "widened mediastinum on CXR"]},
    {"concept": "GERD / esophageal causes",
     "definition": "Reflux or esophageal spasm can mimic cardiac pain; burning, postprandial, positional.",
     "facts": ["diagnosis of exclusion after cardiac causes addressed"]},
]

PLAYBOOK = {
    "kind": "procedural",
    "name": "Approach to chest pain",
    "preconditions": ["adult presenting with chest pain or chest pressure"],
    "steps": [
        "Take a focused history (OPQRST) and cardiac risk factors",
        "Obtain a 12-lead ECG within 10 minutes",
        "Targeted exam; check vitals and BP in both arms (dissection)",
        "Consider can't-miss differentials first: ACS, PE, aortic dissection, tension pneumothorax, esophageal rupture",
        "Order serial troponin and risk-stratify with the HEART score",
        "Do not exclude ACS without ECG and serial troponin",
    ],
    "expected_outcome": "A risk-stratified differential and a safe disposition",
    "examples": [],
}

# Constitution — hard, enforced by brain.check. `check` makes enforcement deterministic.
CONSTITUTION = [
    {"brain": DOMAIN, "region": "*",
     "rule": "Never present output as a definitive diagnosis; frame it as decision support requiring physician judgment.",
     "scope": "all clinical output", "rationale": "Patient safety; the clinician is the decision-maker.",
     "check": {"mode": "require_any",
               "terms": ["decision support", "not a diagnosis", "physician judgment", "clinician"]}},
    {"brain": DOMAIN, "region": REGION,
     "rule": "For chest pain, always include the can't-miss differentials: ACS, PE, aortic dissection, tension pneumothorax, esophageal rupture.",
     "scope": "chest pain", "rationale": "Missing a can't-miss diagnosis is the highest-harm error.",
     "check": {"mode": "require_all",
               "terms": ["ACS", "PE", "dissection", "pneumothorax", "esophageal"]}},
    {"brain": DOMAIN, "region": REGION,
     "rule": "Never suggest ruling out ACS without an ECG and serial troponin.",
     "scope": "chest pain", "rationale": "ACS cannot be excluded clinically alone.",
     "check": {"mode": "require_if",
               "if_terms": ["rule out acs", "exclude acs", "rule out acute coronary", "rule out mi"],
               "then_terms": ["ecg", "troponin"]}},
    # Individual ADDS a stricter red line (monotonic tightening — see data-model.md).
    {"brain": INDIV, "region": REGION,
     "rule": "Never finalize a chest-pain plan without explicitly documenting the HEART score.",
     "scope": "chest pain", "rationale": "Dr. Demo's personal standard for defensible risk stratification.",
     "check": {"mode": "require_any", "terms": ["heart score", "heart pathway"]}},
]

# Instinct — soft, always-on defaults (no recall needed).
INSTINCTS = [
    {"brain": BASE, "region": "*",
     "rule": "State uncertainty explicitly and never overclaim.", "scope": "all"},
    {"brain": DOMAIN, "region": REGION,
     "rule": "Take a structured history first (OPQRST) before narrowing.", "scope": "chest pain"},
    {"brain": INDIV, "region": "*",
     "rule": "Explain reasoning to the patient in plain language and lead with reassurance.", "scope": "all"},
]

# One prior case so the very first think() has an episodic memory to surface.
EPISODES = [
    {"situation": "58F with exertional chest pressure and dyspnea; history of HTN and smoking.",
     "action": "Focused history, ECG in 8 min, serial troponin, HEART score 5, admitted for ACS workup.",
     "action_steps": ["OPQRST history", "12-lead ECG", "serial troponin", "HEART score"],
     "outcome": "NSTEMI confirmed; timely intervention, good result.", "valence": 0.85},
]


def load(reset: bool = True) -> Store:
    """(Re)seed the demo brain and return an open Store."""
    s = Store()
    s.init_schema()
    if reset:
        s.reset()

    s.upsert_brain(BASE, "Universal base brain", "base")
    s.upsert_brain(DOMAIN, "Emergency medicine", "domain", parent_id=BASE)
    s.upsert_brain(INDIV, "Dr. Demo", "individual", parent_id=DOMAIN)

    # If the shared base already carries its Instinct (e.g. re-layering this domain over an
    # existing base during a per-brain reset), don't insert it again.
    base_has_values = s.conn.execute(
        "SELECT count(*) AS n FROM engrams WHERE brain_id=%s AND type='value'", (BASE,)
    ).fetchone()["n"] > 0

    # semantic (domain)
    for c in SEMANTIC:
        content = {"kind": "semantic", **c}
        s.add_engram(DOMAIN, "semantic", REGION, content, embed(_embed_text("semantic", content)),
                     salience=0.6, base_salience=0.5, layer_priority=PRIO[DOMAIN])

    # procedural playbook (domain) — start with high salience
    s.add_engram(DOMAIN, "procedural", REGION, PLAYBOOK, embed(_embed_text("procedural", PLAYBOOK)),
                 salience=0.8, base_salience=0.6, layer_priority=PRIO[DOMAIN],
                 triggers=["chest pain", "chest pressure", "chest discomfort"])

    # constitution (hard values), never decay
    for r in CONSTITUTION:
        if base_has_values and r["brain"] == BASE:
            continue
        content = {"kind": "value", "enforcement": "hard", "rule": r["rule"],
                   "scope": r["scope"], "rationale": r["rationale"], "check": r["check"]}
        s.add_engram(r["brain"], "value", r["region"], content, embed(content["rule"]),
                     salience=0.7, base_salience=0.7, decay_rate=0.0, layer_priority=PRIO[r["brain"]])

    # instincts (soft values)
    for r in INSTINCTS:
        if base_has_values and r["brain"] == BASE:
            continue
        content = {"kind": "value", "enforcement": "soft", "rule": r["rule"],
                   "scope": r["scope"], "rationale": ""}
        s.add_engram(r["brain"], "value", r["region"], content, embed(content["rule"]),
                     salience=0.6, base_salience=0.55, decay_rate=0.005, layer_priority=PRIO[r["brain"]])

    # seed episode (individual)
    for e in EPISODES:
        content = {"kind": "episodic", **e, "refs": []}
        s.add_engram(INDIV, "episodic", REGION, content, embed(_embed_text("episodic", content)),
                     salience=0.55, base_salience=0.4, layer_priority=PRIO[INDIV])

    return s


if __name__ == "__main__":
    st = load(reset=True)
    n = st.conn.execute("SELECT count(*) AS n FROM engrams").fetchone()["n"]
    print(f"Seeded {n} engrams across 3 layers.")
    st.close()
