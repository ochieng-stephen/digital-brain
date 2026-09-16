"""Local MCP server — exposes the brain's tool surface so ANY model can drive
the thought cycle (design/thought-cycle-protocol.md). The brain serves
scaffolding; the connecting model brings the reasoning.

Run:  uv run python -m digital_brain.mcp_server
"""
from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from .engine import Brain, REGION_DEFAULT
from .models import Outcome
from .seed import INDIV

mcp = MCPServer("digital-brain")
DEFAULT_BRAIN = INDIV


def _brain() -> Brain:
    # One connection per call: cheap and safe for stdio. Embedding model is cached.
    return Brain()


@mcp.tool()
def brain_think(stimulus: str, brain_id: str = DEFAULT_BRAIN, stakes: str = "high") -> dict[str, Any]:
    """Perceive+Recall+Constrain+Deliberate. Returns the CognitionPacket scaffold
    (playbook, recalled memories, hard/soft constraints) for the caller's model to reason within."""
    b = _brain()
    try:
        return b.think(stimulus, brain_id, stakes=stakes).to_dict()
    finally:
        b.close()


@mcp.tool()
def brain_check(cycle_id: str, draft_output: str) -> dict[str, Any]:
    """Validate a draft output against the hard Constitution. Returns {pass, violations}."""
    b = _brain()
    try:
        return b.check(cycle_id, draft_output)
    finally:
        b.close()


@mcp.tool()
def brain_reflect(cycle_id: str, success: bool = True, valence: float = 0.7,
                  action: str = "", action_steps: list[str] | None = None) -> dict[str, Any]:
    """Feed the outcome back to fire plasticity: reinforce fired engrams, wire
    associations, write the episodic memory. Returns a write summary."""
    b = _brain()
    try:
        return b.reflect(cycle_id, Outcome(success=success, valence=valence,
                                           action=action, action_steps=action_steps or []))
    finally:
        b.close()


@mcp.tool()
def brain_recall(query: str, brain_id: str = DEFAULT_BRAIN, top_k: int = 6) -> list[dict[str, Any]]:
    """Introspection: 'what do I know about X' (read-only retrieval)."""
    b = _brain()
    try:
        return b.recall(query, brain_id, top_k=top_k)
    finally:
        b.close()


@mcp.tool()
def brain_consolidate(brain_id: str = DEFAULT_BRAIN, region: str = REGION_DEFAULT) -> dict[str, Any]:
    """Cluster positive-valence episodes into a draft procedural playbook (gated)."""
    b = _brain()
    try:
        return b.consolidate(brain_id, region)
    finally:
        b.close()


@mcp.tool()
def brain_remember(type: str, content: dict[str, Any], brain_id: str = DEFAULT_BRAIN,
                   region: str = REGION_DEFAULT, salience: float = 0.5) -> dict[str, Any]:
    """Propose a NEW memory (type: semantic|episodic|procedural). Write-gated: it lands as a
    'draft' for human review unless the region has earned autonomy. Cannot author Constitution/Instinct."""
    b = _brain()
    try:
        return b.remember(brain_id, type, region, content, salience=salience)
    finally:
        b.close()


@mcp.tool()
def brain_edit(engram_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    """Refine an existing memory's content (shallow-merge patch) and re-embed — e.g. to fix a
    consolidated draft's steps before approval. Reversible. Constitution/Instinct are not editable."""
    b = _brain()
    try:
        return b.edit(engram_id, patch)
    finally:
        b.close()


@mcp.tool()
def brain_forget(engram_id: str) -> dict[str, Any]:
    """Retract a memory (soft-delete). Values (Constitution/Instinct) are never forgotten.
    Reversible via brain_rewind."""
    b = _brain()
    try:
        return b.forget(engram_id)
    finally:
        b.close()


@mcp.tool()
def brain_sleep(brain_id: str = DEFAULT_BRAIN) -> dict[str, Any]:
    """Background 'sleep': decay salience + edges and prune what faded. Values are never pruned."""
    b = _brain()
    try:
        return b.sleep(brain_id)
    finally:
        b.close()


@mcp.tool()
def brain_review(engram_id: str, accepted: bool = True) -> dict[str, Any]:
    """Approve (activate) or reject (prune) a draft engram. Accrues per-region trust."""
    b = _brain()
    try:
        return b.review(engram_id, accepted)
    finally:
        b.close()


@mcp.tool()
def brain_trust(brain_id: str = DEFAULT_BRAIN, region: str = REGION_DEFAULT) -> dict[str, Any]:
    """Show a region's autonomy level, review stats, and any promotion suggestion."""
    b = _brain()
    try:
        return b.trust(brain_id, region)
    finally:
        b.close()


@mcp.tool()
def brain_promote(brain_id: str = DEFAULT_BRAIN, region: str = REGION_DEFAULT) -> dict[str, Any]:
    """Apply the suggested autonomy promotion for a region (earned autonomy)."""
    b = _brain()
    try:
        return b.promote(brain_id, region)
    finally:
        b.close()


@mcp.tool()
def brain_explain(engram_id: str) -> dict[str, Any]:
    """Why does the brain hold this engram? Provenance, associations, and event timeline."""
    b = _brain()
    try:
        return b.explain(engram_id)
    finally:
        b.close()


@mcp.tool()
def brain_audit(brain_id: str = DEFAULT_BRAIN, limit: int = 20) -> list[dict[str, Any]]:
    """The recent event journal (newest first)."""
    b = _brain()
    try:
        return b.audit(brain_id, limit=limit)
    finally:
        b.close()


@mcp.tool()
def brain_rewind(brain_id: str = DEFAULT_BRAIN, steps: int = 1, to_event_id: int | None = None,
                 cycle_id: str | None = None, dry_run: bool = False) -> dict[str, Any]:
    """Undo recent structural changes (engram creation, review status, autonomy level).
    Scope by steps, to_event_id, or a whole cycle_id; dry_run previews without mutating.
    Continuous salience/edge weights are not restored; they self-heal. Applied rewinds are logged."""
    b = _brain()
    try:
        return b.rewind(brain_id, steps=steps, to_event_id=to_event_id,
                        cycle_id=cycle_id, dry_run=dry_run)
    finally:
        b.close()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
