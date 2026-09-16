"""Thin storage interface over local Postgres + pgvector.

All DB access goes through Store, so moving to hosted Postgres/Neon later is a
connection-string change, not a rewrite (see design/mvp-medical.md).
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Optional, Sequence

import numpy as np
import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from . import config
from .config import DATABASE_URL
from .models import Engram

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def _to_np(v: Any) -> np.ndarray:
    """Coerce a fetched embedding (ndarray or pgvector Vector) to float32 ndarray."""
    if isinstance(v, np.ndarray):
        return v.astype(np.float32)
    if hasattr(v, "to_numpy"):
        return v.to_numpy().astype(np.float32)
    return np.asarray(list(v), dtype=np.float32)


class Store:
    def __init__(self, url: str = DATABASE_URL):
        self.conn = psycopg.connect(url, autocommit=True, row_factory=dict_row)
        register_vector(self.conn)

    def close(self) -> None:
        self.conn.close()

    def init_schema(self) -> None:
        self.conn.execute(SCHEMA_PATH.read_text())

    def reset(self) -> None:
        """Drop brain data (keeps schema). Used by the seed loader for a clean demo."""
        self.conn.execute("TRUNCATE trust, events, cycles, associations, engrams, brains CASCADE;")

    # ---------------------------------------------------------------- brains
    def upsert_brain(self, id: str, name: str, kind: str,
                     parent_id: Optional[str] = None,
                     autonomy: Optional[dict] = None) -> None:
        autonomy = autonomy or {"default_level": "gated", "region_overrides": {}}
        self.conn.execute(
            """INSERT INTO brains(id,name,kind,parent_id,autonomy)
               VALUES(%s,%s,%s,%s,%s)
               ON CONFLICT(id) DO UPDATE SET
                 name=EXCLUDED.name, kind=EXCLUDED.kind,
                 parent_id=EXCLUDED.parent_id, autonomy=EXCLUDED.autonomy""",
            (id, name, kind, parent_id, Jsonb(autonomy)),
        )

    def brain_chain(self, brain_id: str) -> list[dict]:
        """Walk parent links: returns [individual, domain, base]."""
        chain: list[dict] = []
        cur_id: Optional[str] = brain_id
        seen: set[str] = set()
        while cur_id and cur_id not in seen:
            seen.add(cur_id)
            row = self.conn.execute("SELECT * FROM brains WHERE id=%s", (cur_id,)).fetchone()
            if not row:
                break
            chain.append(row)
            cur_id = row["parent_id"]
        return chain

    def autonomy_level(self, brain_id: str, region: str) -> str:
        row = self.conn.execute("SELECT autonomy FROM brains WHERE id=%s", (brain_id,)).fetchone()
        if not row:
            return "gated"
        a = row["autonomy"]
        return a.get("region_overrides", {}).get(region, a.get("default_level", "gated"))

    # --------------------------------------------------------------- engrams
    def add_engram(self, brain_id: str, type: str, region: str, content: dict,
                   embedding: np.ndarray, *, salience: float = 0.5,
                   base_salience: float = 0.5, decay_rate: float = 0.02,
                   source: str = "human", status: str = "active",
                   confidence: float = 0.8, triggers: Optional[list[str]] = None,
                   layer_priority: int = 0, id: Optional[str] = None) -> str:
        row = self.conn.execute(
            """INSERT INTO engrams(id,brain_id,type,region,content,embedding,salience,
                   base_salience,decay_rate,source,status,confidence,triggers,layer_priority)
               VALUES(COALESCE(%s, gen_random_uuid()::text),%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               RETURNING id""",
            (id, brain_id, type, region, Jsonb(content), embedding, salience,
             base_salience, decay_rate, source, status, confidence,
             triggers or [], layer_priority),
        ).fetchone()
        return row["id"]

    def get_engram(self, engram_id: str) -> Optional[Engram]:
        row = self.conn.execute("SELECT * FROM engrams WHERE id=%s", (engram_id,)).fetchone()
        return Engram.from_row(row) if row else None

    def search(self, brain_ids: Sequence[str], query_emb: np.ndarray, *,
               types: Optional[Sequence[str]] = None, top_k: int = 6,
               statuses: Sequence[str] = ("active",),
               region: Optional[str] = None) -> list[Engram]:
        """Vector recall ranked by cosine similarity (sim = 1 - cosine distance)."""
        clauses = ["brain_id = ANY(%s)", "status = ANY(%s)", "embedding IS NOT NULL"]
        params: list[Any] = [list(brain_ids), list(statuses)]
        if types:
            clauses.append("type = ANY(%s)"); params.append(list(types))
        if region:
            clauses.append("region = %s"); params.append(region)
        where = " AND ".join(clauses)
        # Reliability factor: once a memory has ≥ RECALL_EVIDENCE_MIN judged outcomes, scale its recall
        # score by its success rate — a chronically-unhelpful memory ranks lower, bounded so it can
        # never fall below (1 - penalty) and is never removed (non-destructive; reversible as it recovers).
        rel = (f"(CASE WHEN (success_count + failure_count) >= {config.RECALL_EVIDENCE_MIN} "
               f"THEN 1 - {config.RECALL_UNRELIABLE_PENALTY} * "
               f"(1 - success_count::float / NULLIF(success_count + failure_count, 0)) "
               f"ELSE 1 END)")
        sql = (f"SELECT *, 1 - (embedding <=> %s) AS sim, "
               f"EXTRACT(EPOCH FROM (now() - COALESCE(last_activated_at, created_at))) AS age_sec "
               f"FROM engrams WHERE {where} "
               f"ORDER BY (1 - (embedding <=> %s)) * {rel} DESC LIMIT %s")
        rows = self.conn.execute(sql, [query_emb, *params, query_emb, top_k]).fetchall()
        return [Engram.from_row(r) for r in rows]

    def values(self, brain_ids: Sequence[str], enforcement: str,
               region: Optional[str] = None) -> list[Engram]:
        """Fetch value engrams (hard=Constitution, soft=Instinct) across a layer chain."""
        clauses = ["brain_id = ANY(%s)", "type='value'", "status='active'",
                   "content->>'enforcement' = %s"]
        params: list[Any] = [list(brain_ids), enforcement]
        if region:
            clauses.append("(region=%s OR region='*')"); params.append(region)
        rows = self.conn.execute(
            f"SELECT * FROM engrams WHERE {' AND '.join(clauses)} "
            f"ORDER BY layer_priority DESC", params).fetchall()
        return [Engram.from_row(r) for r in rows]

    def episodes(self, brain_ids: Sequence[str], region: str,
                 min_valence: float = 0.0) -> list[tuple[Engram, np.ndarray]]:
        rows = self.conn.execute(
            """SELECT *, embedding AS emb FROM engrams
               WHERE brain_id = ANY(%s) AND type='episodic' AND status='active'
                 AND region=%s AND (content->>'valence')::float >= %s""",
            (list(brain_ids), region, min_valence)).fetchall()
        return [(Engram.from_row(r), _to_np(r["emb"])) for r in rows]

    # ---------------------------------------------------------- associations
    def associations_from(self, engram_ids: Sequence[str]) -> list[dict]:
        if not engram_ids:
            return []
        return self.conn.execute(
            "SELECT * FROM associations WHERE from_id = ANY(%s)", (list(engram_ids),)
        ).fetchall()

    def reinforce_association(self, a: str, b: str, kind: str = "co_activated",
                              delta: float = 0.15) -> None:
        """Symmetric Hebbian strengthening between two engrams."""
        for x, y in ((a, b), (b, a)):
            self.conn.execute(
                """INSERT INTO associations(from_id,to_id,kind,weight)
                   VALUES(%s,%s,%s,%s)
                   ON CONFLICT(from_id,to_id,kind) DO UPDATE SET
                     weight = LEAST(1.0, associations.weight + %s),
                     last_reinforced_at = now()""",
                (x, y, kind, min(1.0, delta), delta))

    # ------------------------------------------------------------ plasticity
    def mark_activated(self, engram_ids: Sequence[str]) -> None:
        if not engram_ids:
            return
        self.conn.execute(
            """UPDATE engrams SET activation_count = activation_count + 1,
                   last_activated_at = now() WHERE id = ANY(%s)""", (list(engram_ids),))

    def reinforce(self, engram_id: str, learning_rate: float, signal: float,
                  success: bool) -> float:
        """salience += lr*(1-salience)*signal, bounded to 1. Tallies the judged outcome
        (success/failure) so recall can down-weight chronically-unhelpful memories. Returns salience."""
        row = self.conn.execute(
            """UPDATE engrams
               SET salience = LEAST(1.0, salience + %s * (1.0 - salience) * %s),
                   success_count = success_count + %s,
                   failure_count = failure_count + %s
               WHERE id=%s RETURNING salience""",
            (learning_rate, signal, 1 if success else 0, 0 if success else 1, engram_id)).fetchone()
        return row["salience"] if row else 0.0

    def decay_all(self, brain_ids: Sequence[str]) -> int:
        """Exponential relaxation of salience toward base over days since activation."""
        rows = self.conn.execute(
            """UPDATE engrams SET salience = base_salience
                   + (salience - base_salience)
                   * exp(-decay_rate * GREATEST(0, EXTRACT(EPOCH FROM (now() - COALESCE(last_activated_at, created_at)))/86400.0))
               WHERE brain_id = ANY(%s) AND decay_rate > 0 AND status='active'
               RETURNING id""", (list(brain_ids),)).fetchall()
        return len(rows)

    def set_status(self, engram_id: str, status: str) -> None:
        self.conn.execute("UPDATE engrams SET status=%s WHERE id=%s", (status, engram_id))

    def update_content(self, engram_id: str, content: dict, embedding: np.ndarray) -> None:
        """Replace an engram's content and re-embed it (used by edit / edit-rewind)."""
        self.conn.execute("UPDATE engrams SET content=%s, embedding=%s WHERE id=%s",
                          (Jsonb(content), embedding, engram_id))

    def prune(self, brain_ids: Sequence[str], threshold: float) -> list[str]:
        """Soft-delete faded engrams. Never prunes value engrams (Constitution/Instinct).
        Reversible: status -> 'pruned', preserved in the event log."""
        rows = self.conn.execute(
            """UPDATE engrams SET status='pruned'
               WHERE brain_id = ANY(%s) AND status='active' AND type <> 'value'
                 AND salience < %s
               RETURNING id""", (list(brain_ids), threshold)).fetchall()
        return [r["id"] for r in rows]

    def decay_edges(self, brain_ids: Sequence[str], half_life_days: float) -> None:
        """Association weight halves every `half_life_days` of no reinforcement."""
        self.conn.execute(
            """UPDATE associations a SET weight = weight
                   * exp(-0.6931471805599453
                         * (EXTRACT(EPOCH FROM (now() - a.last_reinforced_at))/86400.0)
                         / %s)
               FROM engrams e
               WHERE a.from_id = e.id AND e.brain_id = ANY(%s)""",
            (half_life_days, list(brain_ids)))

    def prune_edges(self, brain_ids: Sequence[str], threshold: float) -> int:
        cur = self.conn.execute(
            """DELETE FROM associations a USING engrams e
               WHERE a.from_id = e.id AND e.brain_id = ANY(%s) AND a.weight < %s""",
            (list(brain_ids), threshold))
        return cur.rowcount

    # ------------------------------------------------------------------ trust
    def record_review(self, brain_id: str, region: str, accepted: bool,
                      engram_id: str) -> None:
        self.conn.execute(
            """INSERT INTO trust(brain_id,region,reviews,accepts) VALUES(%s,%s,1,%s)
               ON CONFLICT(brain_id,region) DO UPDATE SET
                 reviews = trust.reviews + 1,
                 accepts = trust.accepts + %s, updated_at = now()""",
            (brain_id, region, 1 if accepted else 0, 1 if accepted else 0))
        self.append_event(brain_id, None, "review",
                          {"region": region, "accepted": accepted, "engram": engram_id})

    def get_trust(self, brain_id: str, region: str) -> dict:
        row = self.conn.execute(
            "SELECT reviews, accepts FROM trust WHERE brain_id=%s AND region=%s",
            (brain_id, region)).fetchone()
        return row or {"reviews": 0, "accepts": 0}

    def recent_review_flags(self, brain_id: str, region: str, window: int) -> list[bool]:
        rows = self.conn.execute(
            """SELECT (payload->>'accepted')::boolean AS accepted FROM events
               WHERE brain_id=%s AND kind='review' AND payload->>'region'=%s
               ORDER BY id DESC LIMIT %s""", (brain_id, region, window)).fetchall()
        return [r["accepted"] for r in rows]

    def set_region_autonomy(self, brain_id: str, region: str, level: str) -> None:
        self.conn.execute(
            """UPDATE brains
               SET autonomy = jsonb_set(autonomy, ARRAY['region_overrides', %s],
                                        to_jsonb(%s::text), true)
               WHERE id=%s""", (region, level, brain_id))

    # ---------------------------------------------------------------- cycles
    def create_cycle(self, cycle_id: str, brain_id: str, stimulus: str,
                     activated: Sequence[str], path: str) -> None:
        self.conn.execute(
            """INSERT INTO cycles(cycle_id,brain_id,stimulus,activated,path)
               VALUES(%s,%s,%s,%s,%s)""",
            (cycle_id, brain_id, stimulus, list(activated), path))

    def get_cycle(self, cycle_id: str) -> Optional[dict]:
        return self.conn.execute("SELECT * FROM cycles WHERE cycle_id=%s", (cycle_id,)).fetchone()

    # ----------------------------------------------------------------- events
    def append_event(self, brain_id: str, cycle_id: Optional[str], kind: str,
                     payload: Optional[dict] = None) -> None:
        self.conn.execute(
            "INSERT INTO events(brain_id,cycle_id,kind,payload) VALUES(%s,%s,%s,%s)",
            (brain_id, cycle_id, kind, Jsonb(payload or {})))

    def events_for_cycle(self, cycle_id: str) -> list[dict]:
        return self.conn.execute(
            "SELECT * FROM events WHERE cycle_id=%s ORDER BY id", (cycle_id,)).fetchall()

    def events_for_brain(self, brain_id: str, limit: int = 100) -> list[dict]:
        """Recent events, newest first."""
        return self.conn.execute(
            "SELECT * FROM events WHERE brain_id=%s ORDER BY id DESC LIMIT %s",
            (brain_id, limit)).fetchall()

    def recent_events(self, limit: int = 500) -> list[dict]:
        """Recent events across all brains (newest first). Used by explain(), since an
        engram in a lower layer is touched by events logged under the acting brain."""
        return self.conn.execute(
            "SELECT * FROM events ORDER BY id DESC LIMIT %s", (limit,)).fetchall()

    def get_engram_raw(self, engram_id: str) -> Optional[dict]:
        """Full row (incl. timestamps/source) for provenance display."""
        return self.conn.execute("SELECT * FROM engrams WHERE id=%s", (engram_id,)).fetchone()

    def adjust_trust(self, brain_id: str, region: str, d_reviews: int, d_accepts: int) -> None:
        self.conn.execute(
            """UPDATE trust SET reviews = GREATEST(0, reviews + %s),
                   accepts = GREATEST(0, accepts + %s), updated_at = now()
               WHERE brain_id=%s AND region=%s""",
            (d_reviews, d_accepts, brain_id, region))
