CREATE TABLE IF NOT EXISTS non_sphere_authority_evidence(
    evidence_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    authority_type TEXT NOT NULL,
    targets_json TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    source_identity TEXT NOT NULL,
    source_hash TEXT NOT NULL CHECK(length(source_hash)=64),
    project_revision INTEGER NOT NULL,
    event_sequence INTEGER,
    amount_awarded INTEGER,
    amount_consumed INTEGER NOT NULL DEFAULT 0,
    creation_authority TEXT NOT NULL,
    valid INTEGER NOT NULL DEFAULT 1,
    revoked_at TEXT,
    evidence_hash TEXT NOT NULL CHECK(length(evidence_hash)=64),
    created_at TEXT NOT NULL,
    UNIQUE(project_id, authority_type, source_kind, source_identity, evidence_hash)
);
CREATE INDEX IF NOT EXISTS idx_ns_evidence_project_type ON non_sphere_authority_evidence(project_id, authority_type, valid);

CREATE TABLE IF NOT EXISTS non_sphere_ap_consumptions(
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    evidence_id TEXT NOT NULL REFERENCES non_sphere_authority_evidence(evidence_id) ON DELETE CASCADE,
    idempotency_key TEXT NOT NULL,
    operation_hash TEXT NOT NULL CHECK(length(operation_hash)=64),
    amount INTEGER NOT NULL CHECK(amount > 0),
    transaction_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(project_id, evidence_id, idempotency_key)
);
