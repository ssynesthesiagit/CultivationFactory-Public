-- Phase 4A-HF1: rules-causal advancement receipts and project-scoped records.
-- Additive only. Existing v1/v2 events and Stage 1 provider data remain unchanged.

CREATE TABLE IF NOT EXISTS stage2_training_transactions (
    event_id TEXT PRIMARY KEY REFERENCES events(event_id) ON DELETE CASCADE,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    character_cl INTEGER NOT NULL,
    attempt_id TEXT NOT NULL,
    retry_of_attempt_id TEXT,
    target_record_id TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    transaction_hash TEXT NOT NULL,
    result TEXT NOT NULL CHECK(result IN ('success','failure')),
    slot_cost INTEGER NOT NULL CHECK(slot_cost >= 0),
    transaction_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(project_id, attempt_id)
);

CREATE TABLE IF NOT EXISTS stage2_calculation_authority_receipts (
    event_id TEXT NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    authority_role TEXT NOT NULL,
    record_id TEXT NOT NULL,
    record_hash TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    binding_hash TEXT NOT NULL,
    binding_json TEXT NOT NULL,
    PRIMARY KEY(event_id, authority_role, record_id)
);

CREATE TABLE IF NOT EXISTS stage2_project_scoped_records (
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    record_id TEXT NOT NULL,
    record_type TEXT NOT NULL,
    lifecycle_state TEXT NOT NULL CHECK(lifecycle_state IN ('active','replaced','retired','blocked')),
    created_by_event_id TEXT NOT NULL REFERENCES events(event_id) ON DELETE RESTRICT,
    replaced_by_event_id TEXT,
    record_hash TEXT NOT NULL,
    record_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(project_id, record_id)
);

CREATE INDEX IF NOT EXISTS idx_stage2_training_project_cl
ON stage2_training_transactions(project_id, character_cl, attempt_id);

CREATE INDEX IF NOT EXISTS idx_stage2_calc_authority_event
ON stage2_calculation_authority_receipts(event_id, authority_role);
