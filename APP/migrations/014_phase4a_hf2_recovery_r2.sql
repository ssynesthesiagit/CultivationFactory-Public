-- Phase 4A-HF2 Recovery R2: attempt-oriented commit recovery and artifact quarantine.
-- Additive only. R1 approval bindings and immutable content membership remain unchanged.

ALTER TABLE stage2_commit_attempts ADD COLUMN approved_principal_hash TEXT NOT NULL DEFAULT 'LEGACY_UNBOUND';
ALTER TABLE stage2_commit_attempts ADD COLUMN binding_set_hash TEXT NOT NULL DEFAULT 'LEGACY_UNBOUND';
ALTER TABLE stage2_commit_receipts ADD COLUMN approved_principal_hash TEXT NOT NULL DEFAULT 'LEGACY_UNBOUND';
ALTER TABLE stage2_commit_receipts ADD COLUMN binding_set_hash TEXT NOT NULL DEFAULT 'LEGACY_UNBOUND';

CREATE UNIQUE INDEX IF NOT EXISTS idx_stage2_attempt_one_started
ON stage2_commit_attempts(proposal_id)
WHERE status='started';

CREATE UNIQUE INDEX IF NOT EXISTS idx_stage2_attempt_one_committed
ON stage2_commit_attempts(proposal_id)
WHERE status='committed';

CREATE TRIGGER IF NOT EXISTS trg_hf2_r2_attempt_terminal_no_update
BEFORE UPDATE ON stage2_commit_attempts
WHEN OLD.status <> 'started'
BEGIN SELECT RAISE(ABORT,'HF2_COMMIT_ATTEMPT_IMMUTABLE'); END;

CREATE TRIGGER IF NOT EXISTS trg_hf2_r2_committed_receipt_no_update
BEFORE UPDATE ON stage2_commit_receipts
WHEN OLD.status='committed'
BEGIN SELECT RAISE(ABORT,'HF2_COMMIT_RECEIPT_IMMUTABLE'); END;

CREATE TRIGGER IF NOT EXISTS trg_hf2_r2_committed_receipt_no_delete
BEFORE DELETE ON stage2_commit_receipts
WHEN OLD.status='committed'
BEGIN SELECT RAISE(ABORT,'HF2_COMMIT_RECEIPT_IMMUTABLE'); END;

CREATE TABLE IF NOT EXISTS stage2_rebuild_history (
    rebuild_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    project_revision INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('READY','BLOCKED')),
    event_chain_head TEXT NOT NULL,
    state_hash TEXT NOT NULL,
    artifact_set_hash TEXT,
    trust_metadata_hash TEXT NOT NULL,
    blocker_report_hash TEXT NOT NULL,
    artifact_names_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_stage2_rebuild_history_project
ON stage2_rebuild_history(project_id,project_revision,created_at);

CREATE TRIGGER IF NOT EXISTS trg_hf2_r2_rebuild_history_no_update
BEFORE UPDATE ON stage2_rebuild_history
BEGIN SELECT RAISE(ABORT,'HF2_REBUILD_HISTORY_IMMUTABLE'); END;

CREATE TRIGGER IF NOT EXISTS trg_hf2_r2_rebuild_history_no_delete
BEFORE DELETE ON stage2_rebuild_history
BEGIN SELECT RAISE(ABORT,'HF2_REBUILD_HISTORY_IMMUTABLE'); END;

CREATE TRIGGER IF NOT EXISTS trg_hf2_r2_attempt_binding_no_update
BEFORE UPDATE ON stage2_commit_attempts
WHEN
    NEW.attempt_id <> OLD.attempt_id OR
    NEW.proposal_id <> OLD.proposal_id OR
    NEW.project_id <> OLD.project_id OR
    NEW.attempt_no <> OLD.attempt_no OR
    NEW.base_revision <> OLD.base_revision OR
    COALESCE(NEW.approved_proposal_hash,'') <> COALESCE(OLD.approved_proposal_hash,'') OR
    COALESCE(NEW.approved_validation_hash,'') <> COALESCE(OLD.approved_validation_hash,'') OR
    COALESCE(NEW.approved_child_hashes_json,'') <> COALESCE(OLD.approved_child_hashes_json,'') OR
    COALESCE(NEW.approved_compiled_event_hashes_json,'') <> COALESCE(OLD.approved_compiled_event_hashes_json,'') OR
    COALESCE(NEW.approved_lock_proof_hash,'') <> COALESCE(OLD.approved_lock_proof_hash,'') OR
    COALESCE(NEW.approved_principal_id,'') <> COALESCE(OLD.approved_principal_id,'') OR
    COALESCE(NEW.approved_principal_hash,'') <> COALESCE(OLD.approved_principal_hash,'') OR
    COALESCE(NEW.binding_set_hash,'') <> COALESCE(OLD.binding_set_hash,'') OR
    COALESCE(NEW.state_before_hash,'') <> COALESCE(OLD.state_before_hash,'') OR
    COALESCE(NEW.created_at,'') <> COALESCE(OLD.created_at,'')
BEGIN SELECT RAISE(ABORT,'HF2_COMMIT_ATTEMPT_BINDING_IMMUTABLE'); END;
