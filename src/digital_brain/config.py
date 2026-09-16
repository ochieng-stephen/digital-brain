"""Central configuration and tunable 'temperament' knobs.

The plasticity constants below are the brain's *temperament* (see
design/plasticity-engine.md): change them and the same schema behaves like a
different mind (impulsive vs. deliberate, fluid vs. stable, ...).
"""
from __future__ import annotations

import os

# Local Postgres + pgvector (not Neon). See design/mvp-medical.md.
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql:///digital_brain")

# Local embedding model — retrieval only, NOT an LLM, no API key.
EMBED_MODEL = os.environ.get("DIGITAL_BRAIN_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
VECTOR_DIM = 384  # bge-small-en-v1.5 output dimension

# --- Retrieval / attention weights (data-model.md "Retrieval = attention") ---
W_SIM = 1.0        # semantic similarity to the stimulus
W_SALIENCE = 0.6   # learned importance
W_ASSOC = 0.4      # spreading-activation boost from already-lit engrams
W_RECENCY = 0.15   # recency
W_VALENCE = 0.20   # emotional tagging

RECALL_TOP_K = 6
# Fast path = INSTINCT: it fires automatically when a *well-practiced* procedure (high salience,
# earned through repeated successful reflection) matches with enough confidence. Not caller-set.
FAST_PATH_SIM = 0.62          # confidence floor: a match at least this strong can be trusted to instinct
FAST_PATH_SALIENCE = 0.85     # a procedure must be practiced to this salience to become instinctual
                              # (seed playbooks start at 0.8 → deliberate until reinforced past this)

# --- Plasticity 'temperament' knobs (plasticity-engine.md) ---
LEARNING_RATE = 0.25
DEFAULT_DECAY_RATE = 0.02
PRUNE_THRESHOLD = 0.05
CONSOLIDATION_MIN_CLUSTER = 5   # positive-valence episodes before abstracting a playbook
CONSOLIDATION_SIM = 0.72        # cosine threshold for grouping episodes

# --- Recall reliability (down-weight chronically-unhelpful memories in retrieval, non-destructively) ---
RECALL_EVIDENCE_MIN = 3            # judged outcomes (success+failure) before a track record affects recall
RECALL_UNRELIABLE_PENALTY = 0.35  # max recall down-weight for an all-failure memory (floors at 1-this; never removed)

# --- Sleep job (background decay + pruning) ---
EDGE_DECAY_HALF_LIFE_DAYS = 30.0   # association weight halves every N idle days
EDGE_PRUNE_THRESHOLD = 0.02        # drop associations weaker than this

# --- Trust ramp (earned per-region autonomy) ---
AUTONOMY_ORDER = ["gated", "guarded", "autonomous"]
TRUST_PROMOTE_MIN_REVIEWS = 5      # reviews needed before a promotion is suggested
TRUST_PROMOTE_RATE = 0.8           # min accept-rate to suggest promotion
TRUST_DEMOTE_WINDOW = 3            # look at the last N reviews for a demotion burst
TRUST_DEMOTE_REJECTS = 2           # rejects within the window that trigger auto-demotion
