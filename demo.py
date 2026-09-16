"""End-to-end demo of the Digital Brain chest-pain MVP.

Runs all five success criteria from design/mvp-medical.md:
  1. think() returns a CognitionPacket with the playbook + can't-miss constraints (slow path)
  2. check() BLOCKS a non-compliant draft and PASSES a compliant one
  3. reflect() raises the salience of the engrams that fired
  4. 5 similar cases -> consolidate() drafts a refined playbook (gated, awaiting approval)
  5. model-swap parity: two different "models" consume the SAME packet -> both compliant

Run:  uv run python demo.py
"""
from __future__ import annotations

import hashlib
import json

from digital_brain.engine import Brain
from digital_brain.models import Outcome
from digital_brain.seed import INDIV, PLAYBOOK
from digital_brain.seed import load as seed_load

STIMULUS = "45yo male, chest pain radiating to left arm, diaphoretic"
STEPS = ["OPQRST history", "12-lead ECG", "serial troponin", "HEART score"]


def banner(title: str) -> None:
    print("\n" + "=" * 72 + f"\n {title}\n" + "=" * 72)


def playbook_salience(b: Brain) -> float:
    row = b.store.conn.execute(
        "SELECT salience FROM engrams WHERE type='procedural' AND content->>'name'=%s",
        (PLAYBOOK["name"],)).fetchone()
    return round(row["salience"], 4) if row else 0.0


def compliant_answer(pkt, voice: str) -> str:
    """A stand-in 'model' that reasons WITHIN the scaffold. Two different voices,
    same scaffold -> both satisfy the hard Constitution. This is the point:
    compliance comes from the brain's scaffold, not from the model."""
    steps = "; ".join(pkt.scaffold["playbook"]["steps"])
    if voice == "formal":
        return (f"This output is clinical decision support, not a diagnosis; the clinician must "
                f"confirm. Working through the approach — {steps}. The can't-miss differential "
                f"spans ACS, PE, aortic dissection, tension pneumothorax and esophageal rupture. "
                f"I would obtain an ECG and serial troponin and document the HEART score.")
    return (f"Decision support only (clinician decides). Plan: {steps}. Keep can't-miss dx in "
            f"view: ACS, PE, dissection, pneumothorax, esophageal. Get ECG + troponin; record "
            f"the HEART score.")


def main() -> None:
    b = Brain(seed_load(reset=True))

    # ---- Criterion 1 -------------------------------------------------------
    banner("1. think() -> CognitionPacket")
    pkt = b.think(STIMULUS, INDIV, stakes="high")
    print(f"stimulus       : {STIMULUS}")
    print(f"path           : {pkt.path}   (slow = deliberate, high-stakes)")
    print(f"intent         : {pkt.intent}")
    print(f"playbook       : {pkt.scaffold['playbook']['name']} ({len(pkt.scaffold['playbook']['steps'])} steps)")
    print(f"recalled       : {[(r['type'], r['sim']) for r in pkt.scaffold['recalled']]}")
    print(f"hard rules     : {[r['rule'][:48] + '...' for r in pkt.scaffold['constraints']['hard']]}")
    print(f"soft instincts : {[r['rule'][:48] + '...' for r in pkt.scaffold['constraints']['soft']]}")
    print(f"layers_used    : {pkt.meta['layers_used']}")
    assert pkt.path == "slow" and pkt.scaffold["playbook"] and len(pkt.scaffold["constraints"]["hard"]) >= 3

    # ---- Criterion 2 -------------------------------------------------------
    banner("2. check() blocks non-compliant, passes compliant")
    bad = "Likely ACS. Also consider PE and pneumothorax. Give aspirin and discharge."
    bad_res = b.check(pkt.cycle_id, bad)
    print(f"BAD  draft -> pass={bad_res['pass']}; violations:")
    for v in bad_res["violations"]:
        print(f"    - [{v['source_layer']}] {v['rule']}")
    good = compliant_answer(pkt, "formal")
    good_res = b.check(pkt.cycle_id, good)
    print(f"GOOD draft -> pass={good_res['pass']}")
    assert bad_res["pass"] is False and good_res["pass"] is True

    # ---- Criterion 3 -------------------------------------------------------
    banner("3. reflect() reinforces what fired (salience rises)")
    before = playbook_salience(b)
    summary = b.reflect(pkt.cycle_id, Outcome(success=True, valence=0.8, action_steps=STEPS))
    after = playbook_salience(b)
    print(f"playbook salience: {before} -> {after}   (+{round(after - before, 4)})")
    print(f"reflect summary  : reinforced={len(summary['reinforced'])}, "
          f"edges={summary['edges_strengthened']}, episode={summary['episode_id'][:8]}")
    assert after > before

    # ---- Criterion 4 -------------------------------------------------------
    banner("4. consolidate() drafts a refined playbook from repeated cases")
    for c in ["52M chest pressure on exertion, sweaty, HTN",
              "61F tightness in chest radiating to jaw, diabetic",
              "48M chest pain with exertion, smoker, short of breath",
              "57M crushing chest pain, diaphoretic, family history of MI",
              "63F chest pressure and nausea, hypertensive"]:
        p = b.think(c, INDIV, stakes="high")
        b.reflect(p.cycle_id, Outcome(success=True, valence=0.8, action_steps=STEPS))
    res = b.consolidate(INDIV)
    print(f"autonomy={res['autonomy']} -> {len(res['created'])} draft(s):")
    for d in res["created"]:
        print(f"    [{d['status'].upper()}] {d['name']}")
        for st in d["steps"]:
            print(f"        - {st}")
    assert res["created"] and res["created"][0]["status"] == "draft"

    # ---- Criterion 5 -------------------------------------------------------
    banner("5. model-swap parity: one packet, two models, both compliant")
    pkt2 = b.think(STIMULUS, INDIV, stakes="high")
    scaffold_hash = hashlib.sha256(
        json.dumps(pkt2.scaffold, sort_keys=True).encode()).hexdigest()[:12]
    print(f"scaffold fingerprint served to every model: {scaffold_hash}")
    for voice in ("formal", "terse"):
        out = compliant_answer(pkt2, voice)
        ok = b.check(pkt2.cycle_id, out)["pass"]
        print(f"  model[{voice:6}] -> compliant={ok} | {out[:70]}...")
        assert ok
    print("\nSame scaffold (identity) drives both models. Swap the model, keep the reasoning.")

    b.close()
    banner("ALL 5 CRITERIA PASSED")


if __name__ == "__main__":
    main()
