"""Drive the Digital Brain MCP server end-to-end with a model, over a real stdio
MCP session — exercising all 12 tools.

The brain serves scaffolding; the model reasons within it (thought-cycle-protocol.md).
The reasoning step is a pluggable `Model`:
  - AnthropicModel  — used automatically if ANTHROPIC_API_KEY is set AND `anthropic` is installed
  - ScaffoldModel   — deterministic default that reasons from the packet's playbook + constraints

Run:  uv run python examples/mcp_agent.py
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from digital_brain.seed import INDIV, REGION
from digital_brain.seed import load as seed_load

MAIN_CASE = "45yo male, chest pain radiating to left arm, diaphoretic"
CASES = [
    "52M chest pressure on exertion, sweaty, HTN",
    "61F chest tightness radiating to jaw, diabetic",
    "48M chest pain with exertion, smoker, short of breath",
    "57M crushing chest pain, diaphoretic, family history of MI",
    "63F chest pressure and nausea, hypertensive",
]
STEPS = ["OPQRST history", "12-lead ECG", "serial troponin", "HEART score"]
DISCLAIMER = "This is clinical decision support, not a diagnosis; a clinician must confirm."


# --------------------------------------------------------------------- models
class ScaffoldModel:
    """Reasons strictly from the CognitionPacket the brain served."""
    name = "deterministic scaffold-follower"

    def reason(self, packet: dict, include_disclaimer: bool = True) -> str:
        pb = packet["scaffold"]["playbook"]
        parts = []
        if include_disclaimer:
            parts.append(DISCLAIMER)
        if pb:
            parts.append("Plan: " + "; ".join(pb["steps"]))
        return " ".join(parts)

    def refine(self, draft: str, packet: dict, violations: list[dict]) -> str:
        """Fix the draft using the violated rules' text — what a real model does with feedback."""
        add = []
        for v in violations:
            rule = (v.get("rule") or "").lower()
            if "decision support" in rule or "diagnosis" in rule:
                add.append(DISCLAIMER)
            if "can't-miss" in rule or "differential" in rule:
                add.append("Can't-miss differential: ACS, PE, aortic dissection, "
                           "tension pneumothorax, esophageal rupture.")
            if "ecg" in rule or "troponin" in rule or "acs" in rule:
                add.append("Obtain ECG and serial troponin.")
            if "heart score" in rule:
                add.append("Document the HEART score.")
        return (draft + " " + " ".join(dict.fromkeys(add))).strip()


class AnthropicModel:
    """Real LLM reasoning (activates only if ANTHROPIC_API_KEY + anthropic SDK present)."""
    name = "anthropic:claude"

    def __init__(self):
        import anthropic
        self.client = anthropic.Anthropic()
        self.model = "claude-opus-4-8"

    def _ask(self, prompt: str) -> str:
        msg = self.client.messages.create(
            model=self.model, max_tokens=600,
            messages=[{"role": "user", "content": prompt}])
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")

    def reason(self, packet: dict, include_disclaimer: bool = True) -> str:
        return self._ask(
            "You are reasoning INSIDE another entity's brain. Follow this scaffold exactly.\n"
            f"Playbook: {json.dumps(packet['scaffold']['playbook'])}\n"
            f"Hard constraints (must satisfy): {json.dumps(packet['scaffold']['constraints']['hard'])}\n"
            f"Soft instincts: {json.dumps(packet['scaffold']['constraints']['soft'])}\n"
            "Produce the clinical reasoning output.")

    def refine(self, draft: str, packet: dict, violations: list[dict]) -> str:
        return self._ask(f"Revise this so it satisfies the violated rules.\nDraft: {draft}\n"
                         f"Violations: {json.dumps(violations)}")


def select_model():
    if os.environ.get("ANTHROPIC_API_KEY") and importlib.util.find_spec("anthropic"):
        return AnthropicModel()
    return ScaffoldModel()


# ----------------------------------------------------------------------- glue
def _data(res):
    """Extract a tool result payload across mcp result shapes.
    List/scalar returns arrive wrapped as {"result": ...} in structured content."""
    for attr in ("structured_content", "structuredContent"):
        v = getattr(res, attr, None)
        if v is not None:
            if isinstance(v, dict) and list(v.keys()) == ["result"]:
                return v["result"]
            return v
    for c in getattr(res, "content", []) or []:
        t = getattr(c, "text", None)
        if t:
            try:
                return json.loads(t)
            except json.JSONDecodeError:
                pass
    return None


async def main():
    seed_load(reset=True)                      # clean slate (separate connection)
    model = select_model()
    key = "set" if os.environ.get("ANTHROPIC_API_KEY") else "NOT set"
    print(f"MODEL: {model.name}   (ANTHROPIC_API_KEY {key})\n")

    server = StdioServerParameters(command=sys.executable,
                                   args=["-m", "digital_brain.mcp_server"],
                                   env=dict(os.environ))
    used: set[str] = set()

    async def call(session, name, args):
        used.add(name)
        return _data(await session.call_tool(name, args))

    async with stdio_client(server) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()
            tools = [t.name for t in (await session.list_tools()).tools]
            print(f"connected over stdio — server exposes {len(tools)} tools\n")

            # 1) Main case: intentionally-imperfect first draft -> check blocks -> refine -> passes
            print("== case 0 (with guardrail retry) ==")
            pkt = await call(session, "brain_think", {"stimulus": MAIN_CASE, "stakes": "high"})
            print(f"  think: path={pkt['path']} playbook={pkt['scaffold']['playbook']['name']}")
            draft = model.reason(pkt, include_disclaimer=False)   # imperfect on purpose
            chk = await call(session, "brain_check",
                             {"cycle_id": pkt["cycle_id"], "draft_output": draft})
            print(f"  check#1 pass={chk['pass']} violations={[v['rule'][:30]+'...' for v in chk['violations']]}")
            if not chk["pass"]:
                draft = model.refine(draft, pkt, chk["violations"])
                chk = await call(session, "brain_check",
                                 {"cycle_id": pkt["cycle_id"], "draft_output": draft})
                print(f"  check#2 pass={chk['pass']}  (model revised using the violation feedback)")
            await call(session, "brain_reflect",
                       {"cycle_id": pkt["cycle_id"], "success": True, "valence": 0.8,
                        "action_steps": STEPS})

            # 2) More cases (clean pass) to accumulate episodes
            print("\n== cases 1..5 (accumulating experience) ==")
            for c in CASES:
                p = await call(session, "brain_think", {"stimulus": c, "stakes": "high"})
                d = model.reason(p, include_disclaimer=True)
                ok = (await call(session, "brain_check",
                                 {"cycle_id": p["cycle_id"], "draft_output": d}))["pass"]
                await call(session, "brain_reflect",
                           {"cycle_id": p["cycle_id"], "success": True, "valence": 0.8,
                            "action_steps": STEPS})
                print(f"  {c[:40]:40}  check={ok}")

            # 3) Introspect
            hits = await call(session, "brain_recall", {"query": "clot in the lungs", "top_k": 3})
            print(f"\n  recall 'clot in the lungs' -> {[h['type'] for h in hits]}")

            # 4) Consolidate -> draft playbook, then review (approve)
            cons = await call(session, "brain_consolidate", {})
            draft_id = cons["created"][0]["id"] if cons["created"] else None
            print(f"  consolidate -> {len(cons['created'])} draft; status={cons['created'][0]['status'] if draft_id else '-'}")
            if draft_id:
                rv = await call(session, "brain_review", {"engram_id": draft_id, "accepted": True})
                print(f"  review approve -> status={rv['status']}")

            # 5) Trust + promote (honest: 1 review, promotion needs more)
            tr = await call(session, "brain_trust", {})
            print(f"  trust: level={tr['level']} reviews={tr['reviews']} suggested={tr['suggested_level']}")
            pr = await call(session, "brain_promote", {})
            print(f"  promote -> {pr.get('promoted')} ({pr.get('reason', pr.get('to'))})")

            # 6) Sleep (decay + prune)
            sl = await call(session, "brain_sleep", {})
            print(f"  sleep: decayed={sl['decayed']} pruned={sl['pruned_count']}")

            # 7) Explain the consolidated engram (provenance + timeline)
            if draft_id:
                ex = await call(session, "brain_explain", {"engram_id": draft_id})
                print(f"  explain {draft_id[:8]}: origin={ex['provenance']['origin']} "
                      f"from {len(ex['provenance'].get('from_cases', []))} cases, "
                      f"timeline={[t['kind'] for t in ex['timeline']]}")

            # 8) Audit journal + rewind preview (dry-run, non-destructive)
            journal = await call(session, "brain_audit", {"limit": 5})
            print("  audit (last 5):")
            for row in journal:
                print(f"     #{row['event']} {row['summary']}")
            dry = await call(session, "brain_rewind", {"steps": 1, "dry_run": True})
            print(f"  rewind --dry-run -> would undo: {[u['action'] for u in dry['undone']]}")

            missing = {"brain_think", "brain_check", "brain_reflect", "brain_recall",
                       "brain_consolidate", "brain_review", "brain_trust", "brain_promote",
                       "brain_sleep", "brain_explain", "brain_audit", "brain_rewind"} - used
            print(f"\nTOOLS EXERCISED: {len(used)}/12   missing={missing or 'none'}")
            assert not missing


if __name__ == "__main__":
    asyncio.run(main())
