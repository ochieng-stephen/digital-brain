"""A thin local HTTP bridge over the live Brain engine.

The React UI runs in a browser and cannot speak stdio MCP, so this exposes the same
operations as JSON over HTTP. Every endpoint drives the *real* engine (Postgres + pgvector,
real embeddings) — this is not the in-browser simulation. A fresh Brain (one DB connection)
is created per request, mirroring the MCP server's "one connection per call" approach; the
embedding model is process-cached, so per-request cost is just the connect.

Run:  uv run digital-brain-http   (defaults to 127.0.0.1:8787)
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from . import seed, seed_legal
from .engine import Brain
from .models import Outcome

# child → parent order matters for the FK on brains.parent_id when deleting
MEDICAL_BRAINS = ["individual:dr_demo", "domain:emergency_medicine"]
LEGAL_BRAINS = ["individual:lawyer_demo", "domain:legal_contract_review"]

# ---------------------------------------------------------------- helpers

def J(obj: Any, status: int = 200) -> Response:
    return Response(json.dumps(obj, default=str), status_code=status, media_type="application/json")


def _label(content: dict, type_: str) -> str:
    c = content or {}
    return c.get("concept") or c.get("name") or c.get("situation") or c.get("rule") or c.get("label") or type_


def _detail(content: dict, type_: str) -> str:
    c = content or {}
    if type_ == "semantic":
        return c.get("definition", "")
    if type_ == "episodic":
        sit, out = c.get("situation", ""), c.get("outcome", "")
        return f"{sit} → {out}".strip(" →")
    if type_ == "procedural":
        return "; ".join(c.get("steps", [])[:3])
    return c.get("definition", "") or c.get("rule", "")


def _chain_ids(brain: Brain, brain_id: str) -> list[str]:
    return [b["id"] for b in brain.store.brain_chain(brain_id)]


def _primary_region(brain: Brain, brain_id: str) -> str:
    """The region of the chain's playbook (procedural) — what remember/consolidate act on."""
    chain = _chain_ids(brain, brain_id)
    row = brain.store.conn.execute(
        "SELECT region FROM engrams WHERE brain_id = ANY(%s) AND type='procedural' "
        "AND status='active' ORDER BY layer_priority DESC LIMIT 1",
        (chain,),
    ).fetchone()
    return row["region"] if row else "general"


def _memory_rows(brain: Brain, brain_id: str, statuses=("active", "draft")) -> list[dict]:
    """The teachable memory set (semantic/episodic/procedural) across the layer chain —
    what the Recall panel shows. Constitution/Instinct (value) are returned separately."""
    chain = _chain_ids(brain, brain_id)
    rows = brain.store.conn.execute(
        """SELECT id, type, region, status, source, salience, activation_count,
                  success_count, failure_count, content, created_at, layer_priority
           FROM engrams
           WHERE brain_id = ANY(%s) AND status = ANY(%s) AND type <> 'value'
           ORDER BY layer_priority DESC, created_at ASC""",
        (chain, list(statuses)),
    ).fetchall()
    out = []
    for r in rows:
        out.append({
            "id": r["id"], "type": r["type"], "region": r["region"], "status": r["status"],
            "source": r["source"], "salience": round(r["salience"], 3),
            "activationCount": r["activation_count"],
            "successCount": r["success_count"], "failureCount": r["failure_count"],
            "label": _label(r["content"], r["type"]), "detail": _detail(r["content"], r["type"]),
            "content": r["content"], "createdAt": str(r["created_at"]),
        })
    return out


# ---------------------------------------------------------------- endpoints

async def health(_req: Request) -> Response:
    b = Brain()
    try:
        n = b.store.conn.execute("SELECT count(*) AS n FROM engrams").fetchone()["n"]
        return J({"ok": True, "engrams": n})
    finally:
        b.close()


async def brains(_req: Request) -> Response:
    """Selectable brains = the individuals; each resolves its own layer chain. Includes the
    friendly label + primary region the UI needs for remember/consolidate/trust."""
    b = Brain()
    try:
        rows = b.store.conn.execute(
            "SELECT id, name, kind FROM brains WHERE kind='individual' ORDER BY id"
        ).fetchall()
        out = []
        for r in rows:
            region = _primary_region(b, r["id"])
            out.append({"id": r["id"], "label": r["name"] or r["id"], "region": region})
        return J(out)
    finally:
        b.close()


async def think(req: Request) -> Response:
    body = await req.json()
    b = Brain()
    try:
        packet = b.think(body["stimulus"], body.get("brain", "individual:dr_demo"),
                         stakes=body.get("stakes", "high"))
        return J(packet.to_dict())
    finally:
        b.close()


async def check(req: Request) -> Response:
    body = await req.json()
    b = Brain()
    try:
        return J(b.check(body["cycle_id"], body["draft"]))
    finally:
        b.close()


async def reflect(req: Request) -> Response:
    body = await req.json()
    b = Brain()
    try:
        outcome = Outcome(
            success=bool(body.get("success", True)),
            valence=float(body.get("valence", 0.6)),
            action=body.get("action", ""),
            action_steps=body.get("action_steps", []),
            outcome_text=body.get("outcome_text", ""),
            feedback=body.get("feedback"),
        )
        return J(b.reflect(body["cycle_id"], outcome))
    finally:
        b.close()


async def recall(req: Request) -> Response:
    body = await req.json()
    b = Brain()
    try:
        return J(b.recall(body["query"], body.get("brain", "individual:dr_demo"),
                          top_k=int(body.get("top_k", 6))))
    finally:
        b.close()


async def remember(req: Request) -> Response:
    body = await req.json()
    b = Brain()
    try:
        return J(b.remember(body["brain"], body.get("type", "semantic"), body["region"],
                            body["content"], salience=float(body.get("salience", 0.5))))
    finally:
        b.close()


async def edit(req: Request) -> Response:
    body = await req.json()
    b = Brain()
    try:
        return J(b.edit(body["engram_id"], body["patch"]))
    finally:
        b.close()


async def forget(req: Request) -> Response:
    body = await req.json()
    b = Brain()
    try:
        return J(b.forget(body["engram_id"]))
    finally:
        b.close()


async def review(req: Request) -> Response:
    body = await req.json()
    b = Brain()
    try:
        return J(b.review(body["engram_id"], bool(body["accepted"])))
    finally:
        b.close()


async def promote(req: Request) -> Response:
    body = await req.json()
    b = Brain()
    try:
        return J(b.promote(body["brain"], body["region"]))
    finally:
        b.close()


async def trust(req: Request) -> Response:
    b = Brain()
    try:
        return J(b.trust(req.query_params["brain"], req.query_params["region"]))
    finally:
        b.close()


async def consolidate(req: Request) -> Response:
    body = await req.json()
    b = Brain()
    try:
        return J(b.consolidate(body["brain"], body.get("region", "chest_pain_workup")))
    finally:
        b.close()


async def sleep(req: Request) -> Response:
    body = await req.json()
    b = Brain()
    try:
        return J(b.sleep(body["brain"]))
    finally:
        b.close()


async def explain(req: Request) -> Response:
    b = Brain()
    try:
        return J(b.explain(req.path_params["engram_id"]))
    finally:
        b.close()


async def audit(req: Request) -> Response:
    b = Brain()
    try:
        return J(b.audit(req.query_params.get("brain", "individual:dr_demo"),
                         limit=int(req.query_params.get("limit", 30))))
    finally:
        b.close()


async def rewind(req: Request) -> Response:
    body = await req.json()
    b = Brain()
    try:
        return J(b.rewind(body["brain"], steps=int(body.get("steps", 1)),
                          to_event_id=body.get("to_event_id"),
                          cycle_id=body.get("cycle_id"), dry_run=bool(body.get("dry_run", False))))
    finally:
        b.close()


async def memories(req: Request) -> Response:
    b = Brain()
    try:
        return J(_memory_rows(b, req.query_params.get("brain", "individual:dr_demo")))
    finally:
        b.close()


async def graph(req: Request) -> Response:
    """The plasticity graph: memory nodes + the Hebbian association edges among them."""
    brain_id = req.query_params.get("brain", "individual:dr_demo")
    b = Brain()
    try:
        nodes = _memory_rows(b, brain_id, statuses=("active",))
        ids = [n["id"] for n in nodes]
        idset = set(ids)
        raw = b.store.associations_from(ids)
        seen: set[tuple[str, str]] = set()
        edges = []
        for a in raw:
            f, t, w = a["from_id"], a["to_id"], float(a["weight"])
            if t not in idset:
                continue
            key = (f, t) if f < t else (t, f)
            if key in seen:
                continue
            seen.add(key)
            edges.append({"from": key[0], "to": key[1], "weight": round(w, 3), "kind": a.get("kind", "co_activated")})
        slim = [{"id": n["id"], "type": n["type"], "label": n["label"],
                 "salience": n["salience"], "region": n["region"]} for n in nodes]
        return J({"nodes": slim, "edges": edges})
    finally:
        b.close()


def _wipe_brains(brain_ids: list[str]) -> None:
    """Remove a brain's non-cascading state (events/cycles/trust) then the brains themselves —
    deleting the brain rows cascades their engrams, which cascades their associations. Child→parent
    order for the brains.parent_id FK."""
    b = Brain()
    try:
        for tbl in ("events", "cycles", "trust"):
            b.store.conn.execute(f"DELETE FROM {tbl} WHERE brain_id = ANY(%s)", (brain_ids,))
        for bid in brain_ids:  # already child→parent ordered
            b.store.conn.execute("DELETE FROM brains WHERE id = %s", (bid,))
    finally:
        b.close()


async def reset(req: Request) -> Response:
    """Reset a brain (or all) to its clean seed. scope: 'brain' (default, keeps the other domain) or
    'all'."""
    body = await req.json()
    scope = body.get("scope", "brain")
    if scope == "all":
        seed.load(reset=True).close()
        seed_legal.load(reset=False).close()
    else:
        brain_id = body.get("brain", "")
        if "lawyer" in brain_id or "legal" in brain_id:
            _wipe_brains(LEGAL_BRAINS)
            seed_legal.load(reset=False).close()  # _ensure_base keeps the shared base intact
        else:
            _wipe_brains(MEDICAL_BRAINS)
            seed.load(reset=False).close()  # base-skip guard keeps the shared base intact
    b = Brain()
    try:
        n = b.store.conn.execute("SELECT count(*) AS n FROM engrams").fetchone()["n"]
        return J({"ok": True, "scope": scope, "engrams": n})
    finally:
        b.close()


routes = [
    Route("/health", health),
    Route("/brains", brains),
    Route("/think", think, methods=["POST"]),
    Route("/check", check, methods=["POST"]),
    Route("/reflect", reflect, methods=["POST"]),
    Route("/recall", recall, methods=["POST"]),
    Route("/remember", remember, methods=["POST"]),
    Route("/edit", edit, methods=["POST"]),
    Route("/forget", forget, methods=["POST"]),
    Route("/review", review, methods=["POST"]),
    Route("/promote", promote, methods=["POST"]),
    Route("/trust", trust),
    Route("/consolidate", consolidate, methods=["POST"]),
    Route("/sleep", sleep, methods=["POST"]),
    Route("/explain/{engram_id}", explain),
    Route("/audit", audit),
    Route("/rewind", rewind, methods=["POST"]),
    Route("/memories", memories),
    Route("/graph", graph),
    Route("/reset", reset, methods=["POST"]),
]

app = Starlette(
    routes=routes,
    middleware=[Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])],
)


def _ensure_seeded() -> None:
    """On a fresh cloud deploy the database is empty. Create the schema and seed both demo
    brains exactly once — guarded on an empty engrams table so restarts/redeploys are no-ops
    (and never wipe accumulated state). Seeding embeds text, so this also warms the model."""
    import psycopg

    from .config import DATABASE_URL
    from .store import Store

    # pgvector's register_vector() (run inside Store.__init__) needs the `vector` type to already
    # exist — but a fresh managed Postgres has no pgvector installed, so the very first connection
    # would fail. Create the extension on a raw connection first; every Store() then registers fine.
    with psycopg.connect(DATABASE_URL, autocommit=True) as c:
        c.execute("CREATE EXTENSION IF NOT EXISTS vector")

    s = Store()
    try:
        s.init_schema()  # CREATE EXTENSION/TABLE IF NOT EXISTS — idempotent
        n = s.conn.execute("SELECT count(*) AS n FROM engrams").fetchone()["n"]
    finally:
        s.close()
    if n == 0:
        seed.load(reset=True).close()
        seed_legal.load(reset=False).close()


def main() -> None:
    # Railway (and most PaaS) inject $PORT and expect the app to bind 0.0.0.0; locally we keep
    # the loopback default so nothing else on the machine can reach the dev bridge.
    on_paas = bool(os.environ.get("PORT"))
    port = int(os.environ.get("PORT") or os.environ.get("DIGITAL_BRAIN_HTTP_PORT", "8787"))
    host = os.environ.get("DIGITAL_BRAIN_HTTP_HOST", "0.0.0.0" if on_paas else "127.0.0.1")
    _ensure_seeded()
    uvicorn.run(app, host=host, port=port, log_level="warning")
