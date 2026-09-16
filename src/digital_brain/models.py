"""Typed in-memory shapes for engrams and the CognitionPacket.

Storage rows are plain dicts (psycopg dict_row); these dataclasses are the
convenient, typed surface used by the engine and returned to callers.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass
class Engram:
    id: str
    brain_id: str
    type: str            # semantic | episodic | procedural | value
    region: str
    content: dict[str, Any]
    salience: float = 0.5
    base_salience: float = 0.5
    decay_rate: float = 0.02
    activation_count: int = 0
    success_count: int = 0
    source: str = "human"          # human | consolidated | model_proposed
    status: str = "active"         # active | draft | quarantined | pruned
    confidence: float = 0.8
    triggers: list[str] = field(default_factory=list)
    layer_priority: int = 0
    # transient scoring fields (populated during recall, not persisted)
    sim: float = 0.0
    score: float = 0.0
    age_sec: float = 0.0

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Engram":
        return cls(
            id=row["id"], brain_id=row["brain_id"], type=row["type"],
            region=row["region"], content=row["content"],
            salience=row["salience"], base_salience=row["base_salience"],
            decay_rate=row["decay_rate"], activation_count=row["activation_count"],
            success_count=row["success_count"], source=row["source"],
            status=row["status"], confidence=row["confidence"],
            triggers=list(row.get("triggers") or []),
            layer_priority=row["layer_priority"],
            sim=float(row.get("sim", 0.0) or 0.0),
            age_sec=float(row.get("age_sec", 0.0) or 0.0),
        )


@dataclass
class CognitionPacket:
    cycle_id: str
    intent: dict[str, Any]     # {classification, confidence}
    path: str                  # 'fast' | 'slow'
    scaffold: dict[str, Any]   # {playbook?, recalled[], constraints:{hard[],soft[]}}
    meta: dict[str, Any]       # {brain_id, layers_used[], token_estimate}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Outcome:
    success: bool = True
    feedback: Optional[str] = None
    used_output: Optional[bool] = None
    edits: Optional[str] = None
    valence: float = 0.6       # emotional tag written onto the episodic memory
    action: str = ""           # short summary of what was done
    action_steps: list[str] = field(default_factory=list)  # steps actually taken (consolidation fuel)
    outcome_text: str = ""     # how it turned out
