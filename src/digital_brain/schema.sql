-- Digital Brain — schema (Postgres + pgvector). See design/data-model.md.
CREATE EXTENSION IF NOT EXISTS vector;

-- Brains form a layering cascade: individual -> domain -> base.
CREATE TABLE IF NOT EXISTS brains (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    kind       TEXT NOT NULL CHECK (kind IN ('base', 'domain', 'individual')),
    parent_id  TEXT REFERENCES brains(id),
    autonomy   JSONB NOT NULL DEFAULT '{"default_level":"gated","region_overrides":{}}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The atom. Shared fields carry the plasticity machinery; `content` (JSONB) is
-- the type-specific payload (semantic | episodic | procedural | value).
CREATE TABLE IF NOT EXISTS engrams (
    id                TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    brain_id          TEXT NOT NULL REFERENCES brains(id) ON DELETE CASCADE,
    type              TEXT NOT NULL CHECK (type IN ('semantic','episodic','procedural','value')),
    region            TEXT NOT NULL,
    content           JSONB NOT NULL,
    embedding         vector(384),
    salience          REAL NOT NULL DEFAULT 0.5,
    base_salience     REAL NOT NULL DEFAULT 0.5,
    decay_rate        REAL NOT NULL DEFAULT 0.02,
    activation_count  INT  NOT NULL DEFAULT 0,
    success_count     INT  NOT NULL DEFAULT 0,
    failure_count     INT  NOT NULL DEFAULT 0,
    last_activated_at TIMESTAMPTZ,
    source            TEXT NOT NULL DEFAULT 'human'
                          CHECK (source IN ('human','consolidated','model_proposed')),
    status            TEXT NOT NULL DEFAULT 'active'
                          CHECK (status IN ('active','draft','quarantined','pruned')),
    confidence        REAL NOT NULL DEFAULT 0.8,
    triggers          TEXT[] NOT NULL DEFAULT '{}',
    layer_priority    INT NOT NULL DEFAULT 0,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_engrams_brain  ON engrams(brain_id);
CREATE INDEX IF NOT EXISTS idx_engrams_type   ON engrams(type);
CREATE INDEX IF NOT EXISTS idx_engrams_status ON engrams(status);
CREATE INDEX IF NOT EXISTS idx_engrams_embedding
    ON engrams USING hnsw (embedding vector_cosine_ops);

-- Hebbian wiring between engrams.
CREATE TABLE IF NOT EXISTS associations (
    from_id            TEXT NOT NULL REFERENCES engrams(id) ON DELETE CASCADE,
    to_id              TEXT NOT NULL REFERENCES engrams(id) ON DELETE CASCADE,
    kind               TEXT NOT NULL,
    weight             REAL NOT NULL DEFAULT 0.1,
    last_reinforced_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (from_id, to_id, kind)
);

-- Append-only event log — the brain is the fold of this; enables audit + rewind.
CREATE TABLE IF NOT EXISTS events (
    id         BIGSERIAL PRIMARY KEY,
    brain_id   TEXT NOT NULL,
    cycle_id   TEXT,
    kind       TEXT NOT NULL,
    payload    JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_events_cycle ON events(cycle_id);

-- Per-cycle activation set, so reflect() knows exactly which engrams fired.
CREATE TABLE IF NOT EXISTS cycles (
    cycle_id   TEXT PRIMARY KEY,
    brain_id   TEXT NOT NULL,
    stimulus   TEXT NOT NULL,
    activated  TEXT[] NOT NULL DEFAULT '{}',
    path       TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Trust ramp: per-region review stats driving earned autonomy.
CREATE TABLE IF NOT EXISTS trust (
    brain_id   TEXT NOT NULL,
    region     TEXT NOT NULL,
    reviews    INT NOT NULL DEFAULT 0,
    accepts    INT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (brain_id, region)
);
