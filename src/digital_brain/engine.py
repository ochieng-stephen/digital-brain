"""The Brain engine — the thought cycle (design/thought-cycle-protocol.md).

The brain owns no reasoning model. think() returns a CognitionPacket (the
scaffold); the caller's model does the reasoning; reflect() fires the plasticity
engine; check() enforces the hard Constitution deterministically.
"""
from __future__ import annotations

import math
import uuid
from collections import Counter
from typing import Any, Optional

import numpy as np

from . import config
from .embeddings import embed
from .models import CognitionPacket, Engram, Outcome
from .store import Store

_CORE_TYPES = ("procedural", "episodic", "semantic")


def _recency(age_sec: float, half_life_days: float = 30.0) -> float:
    return math.exp(-(age_sec / 86400.0) / half_life_days)


class Brain:
    def __init__(self, store: Optional[Store] = None):
        self.store = store or Store()

    def close(self) -> None:
        self.store.close()

    # ---------------------------------------------------------------- helpers
    def _chain_ids(self, brain_id: str) -> list[str]:
        return [b["id"] for b in self.store.brain_chain(brain_id)]

    @staticmethod
    def _engram_brief(e: Engram) -> dict[str, Any]:
        return {"id": e.id, "type": e.type, "region": e.region,
                "salience": round(e.salience, 3), "sim": round(e.sim, 3),
                "content": e.content}

    @staticmethod
    def _rule_brief(e: Engram) -> dict[str, Any]:
        return {"id": e.id, "rule": e.content.get("rule"),
                "scope": e.content.get("scope"), "source_layer": e.brain_id}

    # ------------------------------------------------------------------ think
    def think(self, stimulus: str, brain_id: str, *, stakes: str = "high",
              region: Optional[str] = None, app_context: Optional[dict] = None) -> CognitionPacket:
        """Perceive + Recall + Constrain + Deliberate → CognitionPacket."""
        chain_ids = self._chain_ids(brain_id)
        q = embed(stimulus)

        # Recall (LLM-free vector search over the layer chain)
        recalled = self.store.search(chain_ids, q, top_k=config.RECALL_TOP_K,
                                     types=list(_CORE_TYPES))

        # Spreading activation: boost engrams associated with what already lit up
        boost: dict[str, float] = {}
        for a in self.store.associations_from([e.id for e in recalled]):
            boost[a["to_id"]] = boost.get(a["to_id"], 0.0) + a["weight"]

        # Activation score = attention (data-model.md)
        for e in recalled:
            val = abs(float(e.content.get("valence", 0.0))) if e.type == "episodic" else 0.0
            e.score = (config.W_SIM * e.sim
                       + config.W_SALIENCE * e.salience
                       + config.W_ASSOC * boost.get(e.id, 0.0)
                       + config.W_RECENCY * _recency(e.age_sec)
                       + config.W_VALENCE * val)
        recalled.sort(key=lambda e: e.score, reverse=True)

        # Deliberate: select the applicable playbook explicitly (a dedicated
        # procedural lookup), so it can't be crowded out of a mixed top-k recall.
        best_proc = self.store.search(chain_ids, q, top_k=1, types=["procedural"])
        playbook = best_proc[0] if best_proc else None

        region_eff = region or (playbook.region if playbook else REGION_DEFAULT)
        hard = self.store.values(chain_ids, "hard", region=region_eff)
        soft = self.store.values(chain_ids, "soft", region=region_eff)

        # Fast vs slow path (System 1 vs System 2), decided automatically. The fast path is an
        # *instinct*: it fires only when a well-practiced (high-salience) procedure matches with
        # enough confidence — repetition through successful reflection is what makes a task routine
        # (design/thought-cycle-protocol.md). `stakes` is retained for the audit record but no
        # longer routes: whether to short-circuit deliberation is the brain's call, not the caller's.
        top_sim = playbook.sim if playbook else (recalled[0].sim if recalled else 0.0)
        instinctual = bool(playbook and playbook.salience >= config.FAST_PATH_SALIENCE)
        path = "fast" if (instinctual and top_sim >= config.FAST_PATH_SIM) else "slow"

        cycle_id = "c_" + uuid.uuid4().hex[:8]
        recall_ids = [e.id for e in recalled]
        if playbook and playbook.id not in recall_ids:
            recall_ids.append(playbook.id)
        activated = list(dict.fromkeys(recall_ids + [r.id for r in hard] + [r.id for r in soft]))
        self.store.mark_activated(recall_ids)
        self.store.create_cycle(cycle_id, brain_id, stimulus, activated, path)

        pb = None
        if playbook:
            pb = {"name": playbook.content["name"], "steps": playbook.content["steps"],
                  "preconditions": playbook.content.get("preconditions", [])}
        recalled_out = [self._engram_brief(e) for e in recalled if e.type != "procedural"][:5]
        scaffold = {"playbook": pb, "recalled": recalled_out,
                    "constraints": {"hard": [self._rule_brief(r) for r in hard],
                                    "soft": [self._rule_brief(r) for r in soft]}}
        packet = CognitionPacket(
            cycle_id=cycle_id,
            intent={"classification": playbook.content["name"] if playbook else "general reasoning",
                    "confidence": round(float(top_sim), 3)},
            path=path, scaffold=scaffold,
            meta={"brain_id": brain_id, "layers_used": chain_ids,
                  "token_estimate": _estimate_tokens(scaffold)},
        )
        self.store.append_event(brain_id, cycle_id, "think",
                                {"path": path, "playbook": pb["name"] if pb else None,
                                 "recalled": recall_ids, "stakes": stakes})
        return packet

    # ------------------------------------------------------------------ check
    def check(self, cycle_id: str, draft_output: str) -> dict[str, Any]:
        """Validate a draft against every hard Constitution rule in the chain."""
        cyc = self.store.get_cycle(cycle_id)
        if not cyc:
            return {"pass": False, "violations": [{"rule": f"unknown cycle {cycle_id}"}]}
        chain_ids = self._chain_ids(cyc["brain_id"])
        text = draft_output.lower()
        violations = []
        for r in self.store.values(chain_ids, "hard"):
            chk = r.content.get("check")
            if chk and not _satisfies(chk, text):
                violations.append(self._rule_brief(r))
        result = {"pass": len(violations) == 0, "violations": violations}
        self.store.append_event(cyc["brain_id"], cycle_id, "check", result)
        return result

    # ---------------------------------------------------------------- reflect
    def reflect(self, cycle_id: str, outcome: Outcome) -> dict[str, Any]:
        """Fire the plasticity engine: reinforce, wire (Hebbian), write episode."""
        cyc = self.store.get_cycle(cycle_id)
        if not cyc:
            raise ValueError(f"unknown cycle {cycle_id}")
        brain_id = cyc["brain_id"]

        # Reflection is once per cognitive cycle — reinforcing the same activated set again would
        # inflate salience and write duplicate episodes. If this cycle was already reflected, no-op.
        if any(e["kind"] == "reflect" for e in self.store.events_for_cycle(cycle_id)):
            return {"reinforced": [], "edges_strengthened": 0, "episode_id": None,
                    "already_reflected": True}

        signal = 1.0 if outcome.success else 0.0

        engs = [e for e in (self.store.get_engram(i) for i in cyc["activated"]) if e]
        core = [e for e in engs if e.type in _CORE_TYPES]

        reinforced = []
        for e in core:  # values are constraints, not reinforced-by-use in the MVP
            self.store.reinforce(e.id, config.LEARNING_RATE, signal, outcome.success)
            reinforced.append(e.id)

        edges = 0
        if outcome.success:  # "fire together, wire together" only on good outcomes
            ids = [e.id for e in core]
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    self.store.reinforce_association(ids[i], ids[j])
                    edges += 1

        region = core[0].region if core else REGION_DEFAULT
        valence = outcome.valence if outcome.success else -abs(outcome.valence)
        # If the caller didn't spell out the concrete steps taken, record the steps of the playbook
        # that was applied this cycle (the recalled procedural). A "went well" reflection means that
        # playbook worked, so its steps become this episode's action_steps — this is what gives
        # consolidation real, majority-votable content to distill (the UI's plain "Went well" sends
        # no explicit steps, so without this every episode would be step-less and consolidation empty).
        action_steps = outcome.action_steps
        if not action_steps:
            pb = next((e for e in engs if e and e.type == "procedural"), None)
            if pb:
                action_steps = list(pb.content.get("steps", []))
        ep = {"kind": "episodic", "situation": cyc["stimulus"],
              "action": outcome.action or "applied recalled playbook",
              "action_steps": action_steps,
              "outcome": outcome.outcome_text or outcome.feedback
                         or ("resolved" if outcome.success else "poor outcome"),
              "valence": valence, "refs": [e.id for e in core]}
        ep_id = self.store.add_engram(
            brain_id, "episodic", region, ep,
            embed(f"{ep['situation']} {ep['action']} {ep['outcome']}"),
            salience=0.5, base_salience=0.4, layer_priority=2)

        summary = {"reinforced": reinforced, "edges_strengthened": edges, "episode_id": ep_id}
        self.store.append_event(brain_id, cycle_id, "reflect", {**summary, "success": outcome.success})
        return summary

    # ----------------------------------------------------------------- recall
    def recall(self, query: str, brain_id: str, top_k: int = 6) -> list[dict[str, Any]]:
        """Introspection: 'what do I know about X' (read-only)."""
        chain_ids = self._chain_ids(brain_id)
        res = self.store.search(chain_ids, embed(query), top_k=top_k,
                                types=["semantic", "episodic", "procedural", "value"])
        return [self._engram_brief(e) for e in res]

    # ------------------------------------------------------------ consolidate
    def consolidate(self, brain_id: str, region: str = "chest_pain_workup") -> dict[str, Any]:
        """Cluster positive-valence episodes → draft a refined procedural (gated)."""
        chain_ids = self._chain_ids(brain_id)
        eps = self.store.episodes(chain_ids, region, min_valence=0.1)
        if len(eps) < config.CONSOLIDATION_MIN_CLUSTER:
            return {"created": [], "reason":
                    f"only {len(eps)} positive episodes (<{config.CONSOLIDATION_MIN_CLUSTER})"}

        clusters = _cluster([emb for _, emb in eps], config.CONSOLIDATION_SIM)
        level = self.store.autonomy_level(brain_id, region)
        status = "active" if level in ("guarded", "autonomous") else "draft"

        created = []
        for idxs in clusters:
            if len(idxs) < config.CONSOLIDATION_MIN_CLUSTER:
                continue
            members = [eps[i][0] for i in idxs]
            counts: Counter[str] = Counter()
            for m in members:
                for s in m.content.get("action_steps", []):
                    counts[s] += 1
            majority = len(members) / 2.0
            steps = [s for s, c in counts.most_common() if c >= majority] \
                or [s for s, _ in counts.most_common(6)]
            if not steps:
                continue  # no step content to abstract — don't write a hollow playbook
            name = f"Consolidated approach ({region}) — from {len(members)} cases"
            content = {"kind": "procedural", "name": name, "preconditions": [],
                       "steps": steps, "expected_outcome": "",
                       "examples": [m.content["situation"] for m in members[:3]]}
            eid = self.store.add_engram(
                brain_id, "procedural", region, content,
                embed(f"{name}. Steps: {'; '.join(steps)}"),
                salience=0.55, base_salience=0.5, source="consolidated",
                status=status, layer_priority=2)
            for m in members:
                self.store.reinforce_association(eid, m.id, kind="example_of", delta=0.3)
            self.store.append_event(brain_id, None, "consolidate",
                                    {"engram": eid, "status": status,
                                     "cluster_size": len(members), "steps": steps})
            created.append({"id": eid, "status": status, "name": name,
                            "steps": steps, "cluster_size": len(members)})
        return {"created": created, "autonomy": level}

    # ------------------------------------------------- write verbs (protocol)
    _WRITABLE = ("semantic", "episodic", "procedural")  # models never author 'value'

    @staticmethod
    def _embed_for(type_: str, content: dict) -> np.ndarray:
        """Build the retrieval text for a writable engram, mirroring the seed loader."""
        if type_ == "semantic":
            return embed(f"{content.get('concept','')}. {content.get('definition','')}")
        if type_ == "episodic":
            return embed(f"{content.get('situation','')} {content.get('action','')} "
                         f"{content.get('outcome','')}")
        if type_ == "procedural":
            return embed(f"{content.get('name','')}. Steps: {'; '.join(content.get('steps', []))}")
        return embed(str(content))

    def remember(self, brain_id: str, type_: str, region: str, content: dict,
                 salience: float = 0.5) -> dict[str, Any]:
        """A model proposes a NEW memory. Write-gated (draft unless the region has earned
        guarded/autonomous). Never authors Constitution/Instinct."""
        if type_ not in self._WRITABLE:
            raise ValueError(f"cannot remember type '{type_}'; models never author 'value' engrams")
        level = self.store.autonomy_level(brain_id, region)
        status = "active" if level in ("guarded", "autonomous") else "draft"
        content = {"kind": type_, **content}
        eid = self.store.add_engram(
            brain_id, type_, region, content, self._embed_for(type_, content),
            salience=salience, base_salience=0.4, source="model_proposed",
            status=status, layer_priority=2)
        self.store.append_event(brain_id, None, "remember",
                                {"engram": eid, "type": type_, "status": status})
        return {"id": eid, "status": status, "autonomy": level}

    def edit(self, engram_id: str, patch: dict) -> dict[str, Any]:
        """Refine an existing memory's content (shallow merge) and re-embed. Records the
        exact before/after so it is reversible. Constitution/Instinct are not editable here."""
        e = self.store.get_engram(engram_id)
        if not e:
            raise ValueError(f"unknown engram {engram_id}")
        if e.type == "value":
            raise ValueError("Constitution/Instinct are human-owned; edit blocked")
        before = e.content
        after = {**before, **patch}
        self.store.update_content(engram_id, after, self._embed_for(e.type, after))
        self.store.append_event(e.brain_id, None, "edit",
                                {"engram": engram_id, "before": before, "after": after})
        return {"id": engram_id, "content": after}

    def forget(self, engram_id: str) -> dict[str, Any]:
        """Retract a memory (soft-delete → 'pruned'). Values are never forgotten
        (mirrors the sleep-prune invariant). Reversible via rewind."""
        e = self.store.get_engram(engram_id)
        if not e:
            raise ValueError(f"unknown engram {engram_id}")
        if e.type == "value":
            raise ValueError("values (Constitution/Instinct) are never forgotten")
        self.store.set_status(engram_id, "pruned")
        self.store.append_event(e.brain_id, None, "forget",
                                {"engram": engram_id, "before_status": e.status})
        return {"id": engram_id, "status": "pruned"}

    # ---------------------------------------------------------------- sleep
    def sleep(self, brain_id: str) -> dict[str, Any]:
        """Background 'sleep' consolidation: decay salience + edges, prune what faded.
        Constitution/Instinct (value engrams) are never pruned."""
        chain_ids = self._chain_ids(brain_id)
        decayed = self.store.decay_all(chain_ids)
        self.store.decay_edges(chain_ids, config.EDGE_DECAY_HALF_LIFE_DAYS)
        pruned = self.store.prune(chain_ids, config.PRUNE_THRESHOLD)
        edges_pruned = self.store.prune_edges(chain_ids, config.EDGE_PRUNE_THRESHOLD)
        summary = {"decayed": decayed, "pruned": pruned, "pruned_count": len(pruned),
                   "edges_pruned": edges_pruned}
        self.store.append_event(brain_id, None, "sleep", summary)
        return summary

    # ----------------------------------------------------------- trust ramp
    @staticmethod
    def _accept_rate(reviews: int, accepts: int) -> float:
        return accepts / reviews if reviews else 0.0

    def _suggest(self, level: str, reviews: int, rate: float) -> tuple[Optional[str], str]:
        order = config.AUTONOMY_ORDER
        i = order.index(level)
        if (i < len(order) - 1 and reviews >= config.TRUST_PROMOTE_MIN_REVIEWS
                and rate >= config.TRUST_PROMOTE_RATE):
            return order[i + 1], f"{reviews} reviews at {rate:.0%} accept — eligible to promote"
        return None, "no change"

    def trust(self, brain_id: str, region: str) -> dict[str, Any]:
        t = self.store.get_trust(brain_id, region)
        reviews, accepts = t["reviews"], t["accepts"]
        rate = self._accept_rate(reviews, accepts)
        level = self.store.autonomy_level(brain_id, region)
        suggested, reason = self._suggest(level, reviews, rate)
        return {"brain_id": brain_id, "region": region, "level": level,
                "reviews": reviews, "accept_rate": round(rate, 3),
                "suggested_level": suggested, "reason": reason}

    def _maybe_demote(self, brain_id: str, region: str) -> Optional[dict]:
        flags = self.store.recent_review_flags(brain_id, region, config.TRUST_DEMOTE_WINDOW)
        rejects = sum(1 for f in flags if not f)
        if len(flags) >= config.TRUST_DEMOTE_WINDOW and rejects >= config.TRUST_DEMOTE_REJECTS:
            level = self.store.autonomy_level(brain_id, region)
            i = config.AUTONOMY_ORDER.index(level)
            if i > 0:
                new = config.AUTONOMY_ORDER[i - 1]
                self.store.set_region_autonomy(brain_id, region, new)
                self.store.append_event(brain_id, None, "autonomy_demote",
                                        {"region": region, "from": level, "to": new,
                                         "recent_rejects": rejects})
                return {"from": level, "to": new}
        return None

    def review(self, engram_id: str, accepted: bool) -> dict[str, Any]:
        """Approve/reject a draft (or quarantined) engram; accrues trust and may auto-demote."""
        e = self.store.get_engram(engram_id)
        if not e:
            raise ValueError(f"unknown engram {engram_id}")
        if e.status not in ("draft", "quarantined"):
            raise ValueError(f"{engram_id} is '{e.status}', not reviewable")
        new_status = "active" if accepted else "pruned"
        self.store.set_status(engram_id, new_status)
        self.store.record_review(e.brain_id, e.region, accepted, engram_id)
        demoted = self._maybe_demote(e.brain_id, e.region)
        return {"engram_id": engram_id, "status": new_status, "demoted": demoted,
                "trust": self.trust(e.brain_id, e.region)}

    def promote(self, brain_id: str, region: str) -> dict[str, Any]:
        """Apply the suggested promotion for a region (earned autonomy)."""
        info = self.trust(brain_id, region)
        if not info["suggested_level"]:
            return {"promoted": False, **info}
        self.store.set_region_autonomy(brain_id, region, info["suggested_level"])
        self.store.append_event(brain_id, None, "autonomy_promote",
                                {"region": region, "from": info["level"],
                                 "to": info["suggested_level"]})
        return {"promoted": True, "from": info["level"],
                "to": info["suggested_level"], "region": region}

    # ----------------------------------------------------- explain / audit
    @staticmethod
    def _label(content: dict) -> str:
        return (content.get("concept") or content.get("name")
                or content.get("rule") or content.get("situation") or "")

    @staticmethod
    def _refs(payload: dict, eid: str) -> bool:
        if payload.get("engram") == eid or payload.get("episode_id") == eid:
            return True
        return eid in (payload.get("reinforced") or []) or eid in (payload.get("pruned") or [])

    def explain(self, engram_id: str) -> dict[str, Any]:
        """Provenance + history for one engram: why it exists and how it got here."""
        row = self.store.get_engram_raw(engram_id)
        if not row:
            raise ValueError(f"unknown engram {engram_id}")
        content = row["content"]

        # Provenance
        if row["source"] == "consolidated":
            members = [a["to_id"] for a in self.store.associations_from([engram_id])
                       if a["kind"] == "example_of"]
            situations = []
            for mid in members:
                m = self.store.get_engram(mid)
                if m:
                    situations.append(m.content.get("situation", mid))
            provenance = {"origin": "consolidated", "from_cases": situations}
        elif row["source"] == "model_proposed":
            provenance = {"origin": "proposed by a model"}
        else:
            provenance = {"origin": "authored by human"}

        # Strongest associations
        assoc = sorted(self.store.associations_from([engram_id]),
                       key=lambda a: a["weight"], reverse=True)[:5]
        associations = []
        for a in assoc:
            other = self.store.get_engram(a["to_id"])
            associations.append({"to": self._label(other.content) if other else a["to_id"],
                                 "kind": a["kind"], "weight": round(a["weight"], 3)})

        # Timeline: every logged event that touched this engram. Scanned across brains,
        # since a lower-layer engram is touched by events logged under the acting brain.
        timeline = []
        for e in reversed(self.store.recent_events(limit=1000)):
            if not self._refs(e["payload"], engram_id):
                continue
            note = {"consolidate": "created by consolidation",
                    "reflect": "reinforced" if engram_id in (e["payload"].get("reinforced") or [])
                               else "written as episode",
                    "review": f"reviewed: {'approved' if e['payload'].get('accepted') else 'rejected'}",
                    "sleep": "pruned during sleep",
                    "remember": "proposed by a model",
                    "edit": "content edited",
                    "forget": "retracted (forget)",
                    "rewind": "affected by rewind"}.get(e["kind"], e["kind"])
            timeline.append({"event": e["id"], "kind": e["kind"],
                             "when": str(e["created_at"]), "note": note})

        return {"id": engram_id, "type": row["type"], "status": row["status"],
                "region": row["region"], "summary": self._label(content),
                "salience": round(row["salience"], 3),
                "activation_count": row["activation_count"],
                "success_count": row["success_count"], "created_at": str(row["created_at"]),
                "provenance": provenance, "associations": associations, "timeline": timeline}

    def audit(self, brain_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """The recent event journal (human-readable), newest first."""
        out = []
        for e in self.store.events_for_brain(brain_id, limit=limit):
            p = e["payload"]
            brief = {
                "think": lambda: f"think ({p.get('path')}): {p.get('playbook')}",
                "check": lambda: f"check: {'pass' if p.get('pass') else str(len(p.get('violations', []))) + ' violations'}",
                "reflect": lambda: f"reflect: reinforced {len(p.get('reinforced', []))}, +{p.get('edges_strengthened', 0)} edges",
                "consolidate": lambda: f"consolidate: draft {str(p.get('engram'))[:8]} from {p.get('cluster_size')} cases",
                "sleep": lambda: f"sleep: decayed {p.get('decayed')}, pruned {p.get('pruned_count')}",
                "review": lambda: f"review: {'approved' if p.get('accepted') else 'rejected'} {str(p.get('engram'))[:8]}",
                "remember": lambda: f"remember: {p.get('type')} {str(p.get('engram'))[:8]} ({p.get('status')})",
                "edit": lambda: f"edit: {str(p.get('engram'))[:8]}",
                "forget": lambda: f"forget: {str(p.get('engram'))[:8]}",
                "autonomy_promote": lambda: f"promote {p.get('region')}: {p.get('from')} -> {p.get('to')}",
                "autonomy_demote": lambda: f"demote {p.get('region')}: {p.get('from')} -> {p.get('to')}",
                "rewind": lambda: f"rewind: undid {p.get('count')} event(s)",
            }.get(e["kind"], lambda: e["kind"])
            out.append({"event": e["id"], "when": str(e["created_at"]), "summary": brief()})
        return out

    # ---------------------------------------------------------------- rewind
    def _undo_event(self, brain_id: str, e: dict, dry_run: bool = False) -> Optional[dict]:
        p, k = e["payload"], e["kind"]
        if k == "consolidate" and p.get("engram") and self.store.get_engram(p["engram"]):
            if not dry_run:
                self.store.set_status(p["engram"], "pruned")
            return {"event": e["id"], "kind": k, "action": f"prune consolidated {p['engram'][:8]}"}
        if k == "reflect" and p.get("episode_id") and self.store.get_engram(p["episode_id"]):
            if not dry_run:
                self.store.set_status(p["episode_id"], "pruned")
            return {"event": e["id"], "kind": k, "action": f"prune episode {p['episode_id'][:8]}"}
        if k == "review" and p.get("engram"):
            er = self.store.get_engram(p["engram"])
            if er:
                if not dry_run:
                    self.store.set_status(p["engram"], "draft")
                    self.store.adjust_trust(brain_id, er.region, -1, -1 if p.get("accepted") else 0)
                return {"event": e["id"], "kind": k, "action": f"restore {p['engram'][:8]} to draft"}
        if k in ("autonomy_promote", "autonomy_demote") and p.get("region") and p.get("from"):
            if not dry_run:
                self.store.set_region_autonomy(brain_id, p["region"], p["from"])
            return {"event": e["id"], "kind": k, "action": f"{p['region']} autonomy -> {p['from']}"}
        if k == "sleep":
            restored = [i for i in (p.get("pruned") or []) if self.store.get_engram(i)]
            if restored:
                if not dry_run:
                    for i in restored:
                        self.store.set_status(i, "active")
                return {"event": e["id"], "kind": k, "action": f"un-prune {len(restored)} engram(s)"}
        if k == "remember" and p.get("engram") and self.store.get_engram(p["engram"]):
            if not dry_run:
                self.store.set_status(p["engram"], "pruned")
            return {"event": e["id"], "kind": k, "action": f"prune remembered {p['engram'][:8]}"}
        if k == "edit" and p.get("engram") and p.get("before"):
            er = self.store.get_engram(p["engram"])
            if er:
                if not dry_run:
                    self.store.update_content(p["engram"], p["before"],
                                              self._embed_for(er.type, p["before"]))
                return {"event": e["id"], "kind": k, "action": f"revert edit {p['engram'][:8]}"}
        if k == "forget" and p.get("engram"):
            fr = self.store.get_engram(p["engram"])
            if fr:
                if not dry_run:
                    self.store.set_status(p["engram"], p.get("before_status", "active"))
                return {"event": e["id"], "kind": k, "action": f"restore forgotten {p['engram'][:8]}"}
        return None

    def rewind(self, brain_id: str, steps: int = 1, to_event_id: Optional[int] = None,
               cycle_id: Optional[str] = None, dry_run: bool = False) -> dict[str, Any]:
        """Undo structural changes (newest first). Scope by --steps, --to <event_id>, or a whole
        --cycle. dry_run previews without mutating. Does not restore continuous salience/edge
        weights (they self-heal). Applied rewinds are themselves logged."""
        undoable = {"consolidate", "reflect", "review", "autonomy_promote",
                    "autonomy_demote", "sleep", "remember", "edit", "forget"}
        if cycle_id is not None:
            candidates = list(reversed(self.store.events_for_cycle(cycle_id)))  # newest first
        else:
            candidates = self.store.events_for_brain(brain_id, limit=1000)
        undone: list[dict] = []
        for e in candidates:
            if cycle_id is None:
                if to_event_id is not None:
                    if e["id"] <= to_event_id:
                        break
                elif len(undone) >= steps:
                    break
            if e["kind"] not in undoable:
                continue
            action = self._undo_event(brain_id, e, dry_run=dry_run)
            if action:
                undone.append(action)
        summary = {"brain_id": brain_id, "count": len(undone), "undone": undone, "dry_run": dry_run}
        if cycle_id is not None:
            summary["cycle_id"] = cycle_id
        if not dry_run:
            self.store.append_event(brain_id, None, "rewind", summary)
        return summary


REGION_DEFAULT = "chest_pain_workup"


# --------------------------------------------------------------- module utils
def _estimate_tokens(scaffold: dict) -> int:
    import json
    return int(len(json.dumps(scaffold)) / 4)


def _satisfies(chk: dict, text: str) -> bool:
    mode = chk.get("mode")
    terms = [t.lower() for t in chk.get("terms", [])]
    if mode == "require_all":
        return all(t in text for t in terms)
    if mode == "require_any":
        return any(t in text for t in terms)
    if mode == "forbid_any":
        return not any(t in text for t in terms)
    if mode == "require_if":
        ifs = [t.lower() for t in chk.get("if_terms", [])]
        thens = [t.lower() for t in chk.get("then_terms", [])]
        if any(t in text for t in ifs):
            return all(t in text for t in thens)
        return True
    return True


def _cluster(embs: list[np.ndarray], thresh: float) -> list[list[int]]:
    """Greedy single-pass clustering by cosine similarity to a running centroid."""
    norm = [v / (np.linalg.norm(v) + 1e-9) for v in embs]
    clusters: list[tuple[list[int], np.ndarray]] = []
    for i, v in enumerate(norm):
        best, best_sim = None, -1.0
        for ci, (_, cen) in enumerate(clusters):
            sim = float(np.dot(v, cen))
            if sim > best_sim:
                best_sim, best = sim, ci
        if best is not None and best_sim >= thresh:
            idxs, cen = clusters[best]
            idxs.append(i)
            new_cen = (cen * (len(idxs) - 1) + v) / len(idxs)
            clusters[best] = (idxs, new_cen / (np.linalg.norm(new_cen) + 1e-9))
        else:
            clusters.append(([i], v))
    return [idxs for idxs, _ in clusters]
