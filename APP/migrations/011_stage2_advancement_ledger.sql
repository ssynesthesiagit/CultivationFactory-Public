-- Phase 4A: Stage 2 event-sourced advancement ledger core.
-- Additive only. Existing Stage 1 and AdvancementEvent.v1 rows remain byte-identical.

CREATE TABLE IF NOT EXISTS stage2_proposals (
    proposal_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    idempotency_key TEXT NOT NULL,
    expected_project_revision INTEGER NOT NULL,
    expected_content_lock_hash TEXT NOT NULL,
    target_cl INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('draft','validated','blocked','approved','committing','committed','failed')),
    proposal_json TEXT NOT NULL,
    proposal_hash TEXT NOT NULL,
    validation_json TEXT,
    approved_by TEXT,
    approved_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id,idempotency_key)
);

CREATE TABLE IF NOT EXISTS stage2_proposal_events (
    proposal_id TEXT NOT NULL REFERENCES stage2_proposals(proposal_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    event_request_json TEXT NOT NULL,
    event_request_hash TEXT NOT NULL,
    PRIMARY KEY(proposal_id,ordinal)
);

CREATE TABLE IF NOT EXISTS stage2_commit_receipts (
    commit_id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL UNIQUE REFERENCES stage2_proposals(proposal_id) ON DELETE RESTRICT,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK(status IN ('started','committed','rolled_back','failed')),
    base_revision INTEGER NOT NULL,
    final_revision INTEGER,
    event_ids_json TEXT NOT NULL,
    event_hashes_json TEXT NOT NULL,
    state_before_hash TEXT NOT NULL,
    state_after_hash TEXT,
    error_json TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS stage2_level_snapshots (
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    project_revision INTEGER NOT NULL,
    character_cl INTEGER NOT NULL,
    event_sequence INTEGER NOT NULL,
    snapshot_hash TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(project_id,project_revision,character_cl)
);

CREATE TABLE IF NOT EXISTS stage2_artifacts (
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    project_revision INTEGER NOT NULL,
    artifact_name TEXT NOT NULL,
    media_type TEXT NOT NULL,
    artifact_hash TEXT NOT NULL,
    artifact_bytes BLOB NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(project_id,project_revision,artifact_name)
);

CREATE TABLE IF NOT EXISTS stage2_blockers (
    blocker_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    project_revision INTEGER NOT NULL,
    proposal_id TEXT,
    blocker_code TEXT NOT NULL,
    severity TEXT NOT NULL CHECK(severity IN ('blocker','error','warning')),
    pointer TEXT NOT NULL,
    message TEXT NOT NULL,
    details_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_stage2_proposals_project ON stage2_proposals(project_id,created_at);
CREATE INDEX IF NOT EXISTS idx_stage2_snapshots_project ON stage2_level_snapshots(project_id,project_revision,character_cl);
CREATE INDEX IF NOT EXISTS idx_stage2_artifacts_project ON stage2_artifacts(project_id,project_revision);
CREATE INDEX IF NOT EXISTS idx_stage2_blockers_project ON stage2_blockers(project_id,project_revision,resolved_at);
