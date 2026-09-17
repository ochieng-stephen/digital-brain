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
import re
import threading
import time
from collections import defaultdict, deque
from typing import Any, Optional

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from . import seed, seed_legal
from .engine import Brain
from .models import Outcome

# ── Per-visitor sandboxing ────────────────────────────────────────────────────────────────────
# The public demo is a shared engine, so each visitor gets a private clone of the demo brains under
# a "<canonical>#<sid>" namespace. Nobody can reach anyone else's state (or the shared template):
# the server forces every request into the caller's own namespace. The browser mints the sid.
TEMPLATE_BRAINS = ["base", "domain:emergency_medicine", "individual:dr_demo",
                   "domain:legal_contract_review", "individual:lawyer_demo"]
SESSION_TTL_SECONDS = 6 * 3600      # idle sandboxes older than this get swept
_SWEEP_EVERY = 60.0                 # at most one TTL sweep per this many seconds
_SWEEP_BATCH = 5                    # sandboxes removed per sweep (bounded work per request)
_SID_RE = re.compile(r"^[a-f0-9]{8,64}$")

# ── Rate limiting (protects the shared Railway CPU; real embeddings run per /think) ─────────────
HEAVY_PATHS = {"/think", "/recall", "/remember", "/consolidate", "/reflect",
               "/sleep", "/rewind", "/reset"}
_RL_WINDOW = 60.0
_RL_PER_SESSION_HEAVY = 25          # heavy calls / window / visitor
_RL_GLOBAL_HEAVY = 90               # heavy calls / window across everyone
_RL_GLOBAL_PROVISION = 40           # new sandboxes / window (blocks sid-rotation clone floods)
_rl_lock = threading.Lock()
_rl_session: dict[str, deque] = defaultdict(deque)
_rl_global: deque = deque()
_rl_provision: deque = deque()
_last_sweep = 0.0


class RateLimited(Exception):
    def __init__(self, retry_after: float = _RL_WINDOW):
        self.retry_after = int(retry_after)


def _valid_sid(sid: str) -> bool:
    return bool(sid) and _SID_RE.match(sid) is not None


def _scope(brain: Optional[str], sid: str) -> str:
    """Force any client-supplied brain into the caller's own session namespace. Only the canonical
    part (before '#') is kept, so a visitor can never address another session's brains or the
    unsuffixed template — this is the isolation guarantee."""
    canonical = (brain or "individual:dr_demo").split("#", 1)[0]
    return f"{canonical}#{sid}"


def _allow(dq: deque, limit: int, now: float) -> bool:
    """Sliding-window admission: drop entries older than the window, then admit if under the limit."""
    cutoff = now - _RL_WINDOW
    while dq and dq[0] < cutoff:
        dq.popleft()
    if len(dq) >= limit:
        return False
    dq.append(now)
    return True


def _rate_check_heavy(sid: str) -> Optional[Response]:
    now = time.time()
    with _rl_lock:
        ok = _allow(_rl_session[sid], _RL_PER_SESSION_HEAVY, now) and \
             _allow(_rl_global, _RL_GLOBAL_HEAVY, now)
    if not ok:
        return J({"error": "rate limited", "retry_after": int(_RL_WINDOW)}, status=429)
    return None


def _clone_template(conn, sid: str) -> None:
    """Clone the pristine template brains into this session's namespace. A freshly-seeded template
    has no associations/events, so fresh engram uuids need no reference remapping; counters reset
    (salience → base_salience, counts → 0) so every sandbox starts identical and clean. The self-FK
    on brains.parent_id is satisfied at statement end, so one INSERT…SELECT is order-independent."""
    suffix = "#" + sid
    conn.execute(
        """INSERT INTO brains(id,name,kind,parent_id,autonomy)
           SELECT id||%s, name, kind,
                  CASE WHEN parent_id IS NULL THEN NULL ELSE parent_id||%s END, autonomy
           FROM brains WHERE id = ANY(%s)
           ON CONFLICT(id) DO NOTHING""",
        (suffix, suffix, TEMPLATE_BRAINS),
    )
    conn.execute(
        """INSERT INTO engrams(brain_id,type,region,content,embedding,salience,base_salience,
                               decay_rate,source,status,confidence,triggers,layer_priority)
           SELECT brain_id||%s, type, region, content, embedding, base_salience, base_salience,
                  decay_rate, source, status, confidence, triggers, layer_priority
           FROM engrams WHERE brain_id = ANY(%s) AND status <> 'pruned'""",
        (suffix, TEMPLATE_BRAINS),
    )
    conn.execute(
        "INSERT INTO sessions(sid) VALUES(%s) ON CONFLICT(sid) DO UPDATE SET last_seen=now()",
        (sid,),
    )


def _wipe_session(conn, sid: str) -> None:
    """Remove one sandbox: side tables (no FK) by suffix, then brains child→parent (engrams and
    their associations cascade), then the sessions row. sid is pre-validated hex, so the LIKE is safe."""
    like = "%#" + sid
    for tbl in ("events", "cycles", "trust"):
        conn.execute(f"DELETE FROM {tbl} WHERE brain_id LIKE %s", (like,))
    for kind in ("individual", "domain", "base"):
        conn.execute("DELETE FROM brains WHERE id LIKE %s AND kind=%s", (like, kind))
    conn.execute("DELETE FROM sessions WHERE sid=%s", (sid,))


def _sweep_expired(conn) -> None:
    rows = conn.execute(
        "SELECT sid FROM sessions WHERE last_seen < now() - make_interval(secs => %s) "
        "ORDER BY last_seen LIMIT %s",
        (SESSION_TTL_SECONDS, _SWEEP_BATCH),
    ).fetchall()
    for r in rows:
        if _valid_sid(r["sid"]):
            _wipe_session(conn, r["sid"])
            with _rl_lock:  # only a permanent sweep drops the rate counter (reset re-uses the sid)
                _rl_session.pop(r["sid"], None)


def _ensure_session(sid: str) -> None:
    """Provision this sandbox on first sight, else refresh its liveness; occasionally sweep aged ones."""
    global _last_sweep
    b = Brain()
    try:
        conn = b.store.conn
        if conn.execute("SELECT 1 FROM sessions WHERE sid=%s", (sid,)).fetchone():
            conn.execute("UPDATE sessions SET last_seen=now() WHERE sid=%s", (sid,))
        else:
            with _rl_lock:
                ok = _allow(_rl_provision, _RL_GLOBAL_PROVISION, time.time())
            if not ok:
                raise RateLimited()
            _clone_template(conn, sid)
        if time.time() - _last_sweep > _SWEEP_EVERY:
            _last_sweep = time.time()
            _sweep_expired(conn)
    finally:
        b.close()


class SessionMiddleware(BaseHTTPMiddleware):
    """Every request (except the Railway /health probe and CORS preflights) must carry a valid
    X-Session header. We rate-limit heavy paths, provision/refresh the sandbox, and stash the sid."""
    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/health" or request.method == "OPTIONS":
            return await call_next(request)
        sid = request.headers.get("x-session", "")
        if not _valid_sid(sid):
            return J({"error": "missing or invalid X-Session header"}, status=400)
        if request.url.path in HEAVY_PATHS:
            limited = _rate_check_heavy(sid)
            if limited is not None:
                return limited
        try:
            _ensure_session(sid)
        except RateLimited as e:
            return J({"error": "rate limited", "retry_after": e.retry_after}, status=429)
        request.state.sid = sid
        return await call_next(request)


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

async def health(req: Request) -> Response:
    """Liveness probe (Railway hits this with no session → global count). When the UI calls it with
    a valid X-Session, report that visitor's own sandbox count instead of the shared total."""
    b = Brain()
    try:
        sid = req.headers.get("x-session", "")
        if _valid_sid(sid):
            n = b.store.conn.execute(
                "SELECT count(*) AS n FROM engrams WHERE brain_id LIKE %s", ("%#" + sid,)
            ).fetchone()["n"]
        else:
            n = b.store.conn.execute("SELECT count(*) AS n FROM engrams").fetchone()["n"]
        return J({"ok": True, "engrams": n})
    finally:
        b.close()


async def brains(req: Request) -> Response:
    """Selectable brains = this session's individuals; each resolves its own layer chain. Includes
    the friendly label + primary region the UI needs for remember/consolidate/trust."""
    b = Brain()
    try:
        rows = b.store.conn.execute(
            "SELECT id, name, kind FROM brains WHERE kind='individual' AND id LIKE %s ORDER BY id",
            ("%#" + req.state.sid,),
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
        packet = b.think(body["stimulus"], _scope(body.get("brain"), req.state.sid),
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
        return J(b.recall(body["query"], _scope(body.get("brain"), req.state.sid),
                          top_k=int(body.get("top_k", 6))))
    finally:
        b.close()


async def remember(req: Request) -> Response:
    body = await req.json()
    b = Brain()
    try:
        return J(b.remember(_scope(body.get("brain"), req.state.sid), body.get("type", "semantic"),
                            body["region"], body["content"], salience=float(body.get("salience", 0.5))))
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
        return J(b.promote(_scope(body.get("brain"), req.state.sid), body["region"]))
    finally:
        b.close()


async def trust(req: Request) -> Response:
    b = Brain()
    try:
        return J(b.trust(_scope(req.query_params.get("brain"), req.state.sid),
                         req.query_params["region"]))
    finally:
        b.close()


async def consolidate(req: Request) -> Response:
    body = await req.json()
    b = Brain()
    try:
        return J(b.consolidate(_scope(body.get("brain"), req.state.sid),
                               body.get("region", "chest_pain_workup")))
    finally:
        b.close()


async def sleep(req: Request) -> Response:
    body = await req.json()
    b = Brain()
    try:
        return J(b.sleep(_scope(body.get("brain"), req.state.sid)))
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
        return J(b.audit(_scope(req.query_params.get("brain"), req.state.sid),
                         limit=int(req.query_params.get("limit", 30))))
    finally:
        b.close()


async def rewind(req: Request) -> Response:
    body = await req.json()
    b = Brain()
    try:
        return J(b.rewind(_scope(body.get("brain"), req.state.sid), steps=int(body.get("steps", 1)),
                          to_event_id=body.get("to_event_id"),
                          cycle_id=body.get("cycle_id"), dry_run=bool(body.get("dry_run", False))))
    finally:
        b.close()


async def memories(req: Request) -> Response:
    b = Brain()
    try:
        return J(_memory_rows(b, _scope(req.query_params.get("brain"), req.state.sid)))
    finally:
        b.close()


async def graph(req: Request) -> Response:
    """The plasticity graph: memory nodes + the Hebbian association edges among them."""
    brain_id = _scope(req.query_params.get("brain"), req.state.sid)
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


async def reset(req: Request) -> Response:
    """Reset the caller's OWN sandbox to the clean seed: wipe its brains and re-clone the template.
    Only ever touches this visitor's namespace — never the shared template or another session."""
    sid = req.state.sid
    b = Brain()
    try:
        _wipe_session(b.store.conn, sid)
        _clone_template(b.store.conn, sid)
        n = b.store.conn.execute(
            "SELECT count(*) AS n FROM engrams WHERE brain_id LIKE %s", ("%#" + sid,)
        ).fetchone()["n"]
        return J({"ok": True, "scope": "session", "engrams": n})
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
    # CORS first (outermost) so 400/429 responses from the session guard still carry CORS headers.
    middleware=[
        Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]),
        Middleware(SessionMiddleware),
    ],
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
