"""CLI to drive the thought cycle directly. State lives in Postgres, so
`think` in one invocation and `check`/`reflect` in later ones share a cycle.

    brain seed --reset
    brain think "45yo chest pain radiating to arm, diaphoretic"
    brain check <cycle_id> "<draft output>"
    brain reflect <cycle_id> --step "12-lead ECG" --step "serial troponin"
    brain recall "clot in the lungs"
    brain consolidate
"""
from __future__ import annotations

import json

import click

from .engine import Brain, REGION_DEFAULT
from .models import Outcome
from .seed import INDIV
from .seed import load as seed_load
from .seed_legal import load as seed_legal_load

DEFAULT_BRAIN = INDIV


def _emit(obj) -> None:
    click.echo(json.dumps(obj, indent=2, default=str))


@click.group()
def cli() -> None:
    """Digital Brain — local cognition layer."""


@cli.command()
@click.option("--reset/--no-reset", default=True, help="Truncate before seeding.")
@click.option("--domain", type=click.Choice(["medical", "legal", "all"]), default="medical",
              show_default=True, help="Which domain(s) to seed under the shared base brain.")
def seed(reset: bool, domain: str) -> None:
    """(Re)seed a demo brain. 'all' layers both domains under one base to show the cascade."""
    if domain == "medical":
        s = seed_load(reset=reset)
    elif domain == "legal":
        s = seed_legal_load(reset=reset)
    else:  # all: reset once, then layer legal onto the shared base
        seed_load(reset=reset).close()
        s = seed_legal_load(reset=False)
    n = s.conn.execute("SELECT count(*) AS n FROM engrams").fetchone()["n"]
    s.close()
    click.echo(f"Seeded domain='{domain}': {n} engrams total across the layer chain(s).")


@cli.command()
@click.argument("stimulus")
@click.option("--brain", "brain_id", default=DEFAULT_BRAIN, show_default=True)
@click.option("--stakes", default="high", type=click.Choice(["low", "high"]), show_default=True)
def think(stimulus: str, brain_id: str, stakes: str) -> None:
    """Perceive+Recall+Constrain+Deliberate → CognitionPacket."""
    b = Brain()
    _emit(b.think(stimulus, brain_id, stakes=stakes).to_dict())
    b.close()


@cli.command()
@click.argument("cycle_id")
@click.argument("draft_output")
def check(cycle_id: str, draft_output: str) -> None:
    """Validate a draft output against the hard Constitution."""
    b = Brain()
    _emit(b.check(cycle_id, draft_output))
    b.close()


@cli.command()
@click.argument("cycle_id")
@click.option("--success/--fail", default=True)
@click.option("--valence", default=0.7, type=float)
@click.option("--action", default="", help="Short summary of what was done.")
@click.option("--step", "steps", multiple=True, help="A step actually taken (repeatable).")
def reflect(cycle_id: str, success: bool, valence: float, action: str, steps: tuple[str, ...]) -> None:
    """Feed the outcome back → fire the plasticity engine."""
    b = Brain()
    _emit(b.reflect(cycle_id, Outcome(success=success, valence=valence,
                                      action=action, action_steps=list(steps))))
    b.close()


@cli.command()
@click.argument("query")
@click.option("--brain", "brain_id", default=DEFAULT_BRAIN, show_default=True)
@click.option("--top-k", default=6, type=int)
def recall(query: str, brain_id: str, top_k: int) -> None:
    """Introspection: what do I know about X."""
    b = Brain()
    for r in b.recall(query, brain_id, top_k=top_k):
        label = r["content"].get("concept") or r["content"].get("name") or r["content"].get("rule")
        click.echo(f"{r['sim']:.3f}  [{r['type']:<10}] {label}")
    b.close()


@cli.command()
@click.argument("type_", metavar="TYPE")
@click.argument("content")
@click.option("--brain", "brain_id", default=DEFAULT_BRAIN, show_default=True)
@click.option("--region", default=REGION_DEFAULT, show_default=True)
@click.option("--salience", default=0.5, type=float)
def remember(type_: str, content: str, brain_id: str, region: str, salience: float) -> None:
    """Propose a NEW memory (semantic|episodic|procedural). CONTENT is a JSON object.
    Write-gated: 'draft' unless the region has earned autonomy. Never authors values."""
    b = Brain()
    _emit(b.remember(brain_id, type_, region, json.loads(content), salience=salience))
    b.close()


@cli.command()
@click.argument("engram_id")
@click.argument("patch")
def edit(engram_id: str, patch: str) -> None:
    """Refine a memory's content (PATCH is a JSON object, shallow-merged) and re-embed."""
    b = Brain()
    _emit(b.edit(engram_id, json.loads(patch)))
    b.close()


@cli.command()
@click.argument("engram_id")
def forget(engram_id: str) -> None:
    """Retract a memory (soft-delete). Values are never forgotten; reversible via rewind."""
    b = Brain()
    _emit(b.forget(engram_id))
    b.close()


@cli.command()
@click.option("--brain", "brain_id", default=DEFAULT_BRAIN, show_default=True)
@click.option("--region", default=REGION_DEFAULT, show_default=True)
def consolidate(brain_id: str, region: str) -> None:
    """Cluster positive-valence episodes → draft a refined playbook."""
    b = Brain()
    _emit(b.consolidate(brain_id, region))
    b.close()


@cli.command()
@click.option("--brain", "brain_id", default=DEFAULT_BRAIN, show_default=True)
def sleep(brain_id: str) -> None:
    """Background 'sleep': decay salience + edges, prune what faded (values kept)."""
    b = Brain()
    _emit(b.sleep(brain_id))
    b.close()


@cli.command()
@click.argument("engram_id")
@click.option("--approve/--reject", default=True, help="Approve (activate) or reject (prune) a draft.")
def review(engram_id: str, approve: bool) -> None:
    """Review a draft engram; accrues per-region trust (may auto-demote on a reject burst)."""
    b = Brain()
    _emit(b.review(engram_id, approve))
    b.close()


@cli.command()
@click.option("--brain", "brain_id", default=DEFAULT_BRAIN, show_default=True)
@click.option("--region", default=REGION_DEFAULT, show_default=True)
def trust(brain_id: str, region: str) -> None:
    """Show a region's autonomy level, review stats, and any promotion suggestion."""
    b = Brain()
    _emit(b.trust(brain_id, region))
    b.close()


@cli.command()
@click.option("--brain", "brain_id", default=DEFAULT_BRAIN, show_default=True)
@click.option("--region", default=REGION_DEFAULT, show_default=True)
def promote(brain_id: str, region: str) -> None:
    """Apply the suggested autonomy promotion for a region (earned autonomy)."""
    b = Brain()
    _emit(b.promote(brain_id, region))
    b.close()


@cli.command()
@click.argument("engram_id")
def explain(engram_id: str) -> None:
    """Why does the brain hold this engram? Provenance + association + event timeline."""
    b = Brain()
    _emit(b.explain(engram_id))
    b.close()


@cli.command()
@click.option("--brain", "brain_id", default=DEFAULT_BRAIN, show_default=True)
@click.option("--limit", default=20, type=int)
def audit(brain_id: str, limit: int) -> None:
    """Show the recent event journal (newest first)."""
    b = Brain()
    for row in b.audit(brain_id, limit=limit):
        click.echo(f"#{row['event']:<5} {row['when'][:19]}  {row['summary']}")
    b.close()


@cli.command()
@click.option("--brain", "brain_id", default=DEFAULT_BRAIN, show_default=True)
@click.option("--steps", default=1, type=int, help="Undo the last N structural events.")
@click.option("--to", "to_event_id", default=None, type=int, help="Undo everything after this event id.")
@click.option("--cycle", "cycle_id", default=None, help="Undo a whole cycle by its cycle_id.")
@click.option("--dry-run", is_flag=True, default=False, help="Preview without mutating.")
def rewind(brain_id: str, steps: int, to_event_id: int | None,
           cycle_id: str | None, dry_run: bool) -> None:
    """Undo recent structural changes (creation/status/autonomy). Itself logged (unless --dry-run)."""
    b = Brain()
    _emit(b.rewind(brain_id, steps=steps, to_event_id=to_event_id,
                   cycle_id=cycle_id, dry_run=dry_run))
    b.close()


if __name__ == "__main__":
    cli()
