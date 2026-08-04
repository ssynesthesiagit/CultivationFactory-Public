-- Phase 4A-HF2: trust-boundary correction. Additive and backward-readable.

ALTER TABLE project_content_locks ADD COLUMN record_set_hash TEXT;
ALTER TABLE project_content_locks ADD COLUMN payload_files_hash TEXT;
ALTER TABLE project_content_locks ADD COLUMN install_receipt_hash TEXT;
ALTER TABLE project_content_locks ADD COLUMN membership_snapshot_hash TEXT;

ALTER TABLE stage2_proposals ADD COLUMN approved_proposal_hash TEXT;
ALTER TABLE stage2_proposals ADD COLUMN approved_validation_hash TEXT;
ALTER TABLE stage2_proposals ADD COLUMN approved_child_hashes_json TEXT;
ALTER TABLE stage2_proposals ADD COLUMN approved_compiled_event_hashes_json TEXT;
ALTER TABLE stage2_proposals ADD COLUMN approved_lock_proof_hash TEXT;
ALTER TABLE stage2_proposals ADD COLUMN approved_principal_id TEXT;
ALTER TABLE stage2_proposals ADD COLUMN approval_challenge_id TEXT;

ALTER TABLE stage2_commit_receipts ADD COLUMN approved_proposal_hash TEXT;
ALTER TABLE stage2_commit_receipts ADD COLUMN approved_validation_hash TEXT;
ALTER TABLE stage2_commit_receipts ADD COLUMN approved_child_hashes_json TEXT;
ALTER TABLE stage2_commit_receipts ADD COLUMN approved_compiled_event_hashes_json TEXT;
ALTER TABLE stage2_commit_receipts ADD COLUMN approved_lock_proof_hash TEXT;
ALTER TABLE stage2_commit_receipts ADD COLUMN approved_principal_id TEXT;
ALTER TABLE stage2_commit_receipts ADD COLUMN terminal_attempt_id TEXT;

ALTER TABLE stage2_artifacts ADD COLUMN trust_status TEXT NOT NULL DEFAULT 'LEGACY_UNVERIFIED';
ALTER TABLE stage2_artifacts ADD COLUMN event_chain_head TEXT;
ALTER TABLE stage2_artifacts ADD COLUMN state_hash TEXT;
ALTER TABLE stage2_artifacts ADD COLUMN trust_metadata_json TEXT;

CREATE TABLE IF NOT EXISTS content_pack_record_membership (
    pack_hash TEXT NOT NULL,
    pack_id TEXT NOT NULL,
    pack_version TEXT NOT NULL,
    record_set_hash TEXT NOT NULL,
    payload_files_hash TEXT NOT NULL,
    install_receipt_hash TEXT NOT NULL,
    record_id TEXT NOT NULL,
    record_hash TEXT NOT NULL,
    record_path TEXT NOT NULL,
    semantic_hash TEXT NOT NULL,
    record_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(pack_hash, record_id),
    UNIQUE(pack_hash, record_hash)
);
CREATE INDEX IF NOT EXISTS idx_pack_membership_lookup
ON content_pack_record_membership(pack_id,pack_version,record_id);



CREATE TABLE IF NOT EXISTS uninstalled_content_pack_receipts (
    pack_id TEXT NOT NULL,
    version TEXT NOT NULL,
    pack_hash TEXT NOT NULL,
    receipt_hash TEXT NOT NULL,
    receipt_json TEXT NOT NULL,
    uninstalled_at TEXT NOT NULL,
    PRIMARY KEY(pack_id,version)
);
CREATE TABLE IF NOT EXISTS uninstalled_content_pack_record_membership (
    pack_hash TEXT NOT NULL,
    record_id TEXT NOT NULL,
    record_hash TEXT NOT NULL,
    record_json TEXT NOT NULL,
    receipt_hash TEXT NOT NULL,
    uninstalled_at TEXT NOT NULL,
    PRIMARY KEY(pack_hash,record_id)
);
CREATE TRIGGER IF NOT EXISTS trg_hf2_uninstalled_receipt_no_update
BEFORE UPDATE ON uninstalled_content_pack_receipts
BEGIN SELECT RAISE(ABORT,'HF2_INSTALL_RECEIPT_IMMUTABLE'); END;
CREATE TRIGGER IF NOT EXISTS trg_hf2_uninstalled_receipt_no_delete
BEFORE DELETE ON uninstalled_content_pack_receipts
BEGIN SELECT RAISE(ABORT,'HF2_INSTALL_RECEIPT_IMMUTABLE'); END;
CREATE TRIGGER IF NOT EXISTS trg_hf2_uninstalled_membership_no_update
BEFORE UPDATE ON uninstalled_content_pack_record_membership
BEGIN SELECT RAISE(ABORT,'HF2_PACK_MEMBERSHIP_IMMUTABLE'); END;
CREATE TRIGGER IF NOT EXISTS trg_hf2_uninstalled_membership_no_delete
BEFORE DELETE ON uninstalled_content_pack_record_membership
BEGIN SELECT RAISE(ABORT,'HF2_PACK_MEMBERSHIP_IMMUTABLE'); END;

CREATE TABLE IF NOT EXISTS project_locked_replacements (
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    replacement_id TEXT NOT NULL,
    replacement_pack_id TEXT NOT NULL,
    replacement_pack_version TEXT NOT NULL,
    replacement_pack_hash TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    source_record_hash TEXT NOT NULL,
    source_pack_id TEXT NOT NULL,
    source_pack_version TEXT NOT NULL,
    source_pack_hash TEXT NOT NULL,
    target_record_id TEXT NOT NULL,
    target_record_hash TEXT NOT NULL,
    mode TEXT NOT NULL,
    reason TEXT NOT NULL,
    map_path TEXT NOT NULL,
    map_hash TEXT NOT NULL,
    PRIMARY KEY(project_id,replacement_id)
);
CREATE INDEX IF NOT EXISTS idx_project_locked_replacements_source
ON project_locked_replacements(project_id,source_record_id,source_record_hash);

CREATE TABLE IF NOT EXISTS local_approval_challenges (
    challenge_id TEXT PRIMARY KEY,
    operation TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    session_binding_hash TEXT NOT NULL,
    nonce_hash TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    consumed_at TEXT,
    challenge_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_local_approval_challenge_subject
ON local_approval_challenges(operation,subject_id,issued_at);

CREATE TABLE IF NOT EXISTS stage2_commit_attempts (
    attempt_id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL REFERENCES stage2_proposals(proposal_id) ON DELETE RESTRICT,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    attempt_no INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('started','committed','interrupted','rolled_back','retryable_failed','terminal_failed')),
    retryable INTEGER NOT NULL CHECK(retryable IN (0,1)),
    base_revision INTEGER NOT NULL,
    final_revision INTEGER,
    approved_proposal_hash TEXT NOT NULL,
    approved_validation_hash TEXT NOT NULL,
    approved_child_hashes_json TEXT NOT NULL,
    approved_compiled_event_hashes_json TEXT NOT NULL,
    approved_lock_proof_hash TEXT NOT NULL,
    approved_principal_id TEXT NOT NULL,
    event_ids_json TEXT NOT NULL,
    event_hashes_json TEXT NOT NULL,
    state_before_hash TEXT NOT NULL,
    state_after_hash TEXT,
    error_json TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE(proposal_id,attempt_no)
);
CREATE INDEX IF NOT EXISTS idx_stage2_attempts_proposal
ON stage2_commit_attempts(proposal_id,attempt_no);

CREATE TABLE IF NOT EXISTS stage2_rebuild_status (
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    project_revision INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('READY','BLOCKED')),
    event_chain_head TEXT NOT NULL,
    state_hash TEXT NOT NULL,
    artifact_set_hash TEXT,
    trust_metadata_hash TEXT NOT NULL,
    blocker_report_hash TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(project_id,project_revision)
);

-- Preserve legacy failed/rolled-back receipt evidence as immutable attempts, then
-- free the proposal-level terminal receipt slot for retryable proposals.
INSERT OR IGNORE INTO stage2_commit_attempts(
    attempt_id,proposal_id,project_id,attempt_no,status,retryable,base_revision,final_revision,
    approved_proposal_hash,approved_validation_hash,approved_child_hashes_json,
    approved_compiled_event_hashes_json,approved_lock_proof_hash,approved_principal_id,
    event_ids_json,event_hashes_json,state_before_hash,state_after_hash,error_json,created_at,completed_at)
SELECT
    'legacy-attempt:' || commit_id,proposal_id,project_id,1,
    CASE status WHEN 'rolled_back' THEN 'rolled_back' ELSE 'terminal_failed' END,
    CASE status WHEN 'rolled_back' THEN 1 ELSE 0 END,
    base_revision,final_revision,
    COALESCE(approved_proposal_hash,'LEGACY_UNBOUND'),COALESCE(approved_validation_hash,'LEGACY_UNBOUND'),
    COALESCE(approved_child_hashes_json,'[]'),COALESCE(approved_compiled_event_hashes_json,'[]'),
    COALESCE(approved_lock_proof_hash,'LEGACY_UNBOUND'),COALESCE(approved_principal_id,'LEGACY_UNBOUND'),
    event_ids_json,event_hashes_json,state_before_hash,state_after_hash,error_json,created_at,completed_at
FROM stage2_commit_receipts WHERE status IN ('rolled_back','failed');
DELETE FROM stage2_commit_receipts WHERE status IN ('rolled_back','failed');


CREATE TRIGGER IF NOT EXISTS trg_hf2_install_receipt_no_update
BEFORE UPDATE ON content_pack_install_receipts
BEGIN SELECT RAISE(ABORT,'HF2_INSTALL_RECEIPT_IMMUTABLE'); END;


CREATE TRIGGER IF NOT EXISTS trg_hf2_install_receipt_no_delete
BEFORE DELETE ON content_pack_install_receipts
WHEN NOT EXISTS(
    SELECT 1 FROM uninstalled_content_pack_receipts u
    WHERE u.pack_id=OLD.pack_id AND u.version=OLD.version
      AND u.pack_hash=OLD.canonical_content_hash AND u.receipt_hash=OLD.receipt_hash
      AND u.receipt_json=OLD.receipt_json
)
BEGIN SELECT RAISE(ABORT,'HF2_INSTALL_RECEIPT_IMMUTABLE'); END;

CREATE TRIGGER IF NOT EXISTS trg_hf2_membership_no_late_insert
BEFORE INSERT ON content_pack_record_membership
WHEN EXISTS(SELECT 1 FROM project_content_locks l WHERE l.pack_hash=NEW.pack_hash)
BEGIN SELECT RAISE(ABORT,'HF2_PACK_MEMBERSHIP_IMMUTABLE'); END;

CREATE TRIGGER IF NOT EXISTS trg_hf2_project_locked_replacement_no_update
BEFORE UPDATE ON project_locked_replacements
BEGIN SELECT RAISE(ABORT,'HF2_PROJECT_LOCKED_REPLACEMENT_IMMUTABLE'); END;
CREATE TRIGGER IF NOT EXISTS trg_hf2_project_locked_replacement_no_delete
BEFORE DELETE ON project_locked_replacements
BEGIN SELECT RAISE(ABORT,'HF2_PROJECT_LOCKED_REPLACEMENT_IMMUTABLE'); END;

CREATE TRIGGER IF NOT EXISTS trg_hf2_approved_proposal_no_delete
BEFORE DELETE ON stage2_proposals
WHEN OLD.status IN ('approved','committing','committed')
BEGIN SELECT RAISE(ABORT,'HF2_APPROVED_PROPOSAL_IMMUTABLE'); END;

CREATE TRIGGER IF NOT EXISTS trg_hf2_approved_proposal_state_guard
BEFORE UPDATE ON stage2_proposals
WHEN (OLD.status='approved' AND NEW.status NOT IN ('approved','committing','committed'))
  OR (OLD.status='committing' AND NEW.status NOT IN ('committing','approved','committed'))
  OR (OLD.status='committed' AND NEW.status<>'committed')
BEGIN SELECT RAISE(ABORT,'HF2_APPROVED_PROPOSAL_IMMUTABLE'); END;

CREATE TRIGGER IF NOT EXISTS trg_hf2_membership_no_update
BEFORE UPDATE ON content_pack_record_membership
BEGIN SELECT RAISE(ABORT,'HF2_PACK_MEMBERSHIP_IMMUTABLE'); END;
CREATE TRIGGER IF NOT EXISTS trg_hf2_membership_no_delete
BEFORE DELETE ON content_pack_record_membership
WHEN NOT EXISTS(
    SELECT 1 FROM uninstalled_content_pack_record_membership u
    WHERE u.pack_hash=OLD.pack_hash AND u.record_id=OLD.record_id
      AND u.record_hash=OLD.record_hash AND u.record_json=OLD.record_json
      AND u.receipt_hash=OLD.install_receipt_hash
)
BEGIN SELECT RAISE(ABORT,'HF2_PACK_MEMBERSHIP_IMMUTABLE'); END;

CREATE TRIGGER IF NOT EXISTS trg_hf2_project_locked_record_no_update
BEFORE UPDATE ON project_locked_records
BEGIN SELECT RAISE(ABORT,'HF2_PROJECT_LOCKED_RECORD_IMMUTABLE'); END;
CREATE TRIGGER IF NOT EXISTS trg_hf2_project_locked_record_no_delete
BEFORE DELETE ON project_locked_records
BEGIN SELECT RAISE(ABORT,'HF2_PROJECT_LOCKED_RECORD_IMMUTABLE'); END;

CREATE TRIGGER IF NOT EXISTS trg_hf2_approved_proposal_bytes_immutable
BEFORE UPDATE ON stage2_proposals
WHEN OLD.status IN ('approved','committing','committed') AND (
    NEW.proposal_json <> OLD.proposal_json OR NEW.proposal_hash <> OLD.proposal_hash OR
    COALESCE(NEW.validation_json,'') <> COALESCE(OLD.validation_json,'') OR
    NEW.expected_project_revision <> OLD.expected_project_revision OR
    NEW.expected_content_lock_hash <> OLD.expected_content_lock_hash OR
    NEW.target_cl <> OLD.target_cl OR NEW.idempotency_key <> OLD.idempotency_key OR
    COALESCE(NEW.approved_proposal_hash,'') <> COALESCE(OLD.approved_proposal_hash,'') OR
    COALESCE(NEW.approved_validation_hash,'') <> COALESCE(OLD.approved_validation_hash,'') OR
    COALESCE(NEW.approved_child_hashes_json,'') <> COALESCE(OLD.approved_child_hashes_json,'') OR
    COALESCE(NEW.approved_compiled_event_hashes_json,'') <> COALESCE(OLD.approved_compiled_event_hashes_json,'') OR
    COALESCE(NEW.approved_lock_proof_hash,'') <> COALESCE(OLD.approved_lock_proof_hash,'') OR
    COALESCE(NEW.approved_principal_id,'') <> COALESCE(OLD.approved_principal_id,'') OR
    COALESCE(NEW.approval_challenge_id,'') <> COALESCE(OLD.approval_challenge_id,'')
)
BEGIN SELECT RAISE(ABORT,'HF2_APPROVED_PROPOSAL_IMMUTABLE'); END;

CREATE TRIGGER IF NOT EXISTS trg_hf2_approved_child_no_update
BEFORE UPDATE ON stage2_proposal_events
WHEN EXISTS(SELECT 1 FROM stage2_proposals p WHERE p.proposal_id=OLD.proposal_id AND p.status IN ('approved','committing','committed'))
BEGIN SELECT RAISE(ABORT,'HF2_APPROVED_PROPOSAL_CHILD_IMMUTABLE'); END;
CREATE TRIGGER IF NOT EXISTS trg_hf2_approved_child_no_delete
BEFORE DELETE ON stage2_proposal_events
WHEN EXISTS(SELECT 1 FROM stage2_proposals p WHERE p.proposal_id=OLD.proposal_id AND p.status IN ('approved','committing','committed'))
BEGIN SELECT RAISE(ABORT,'HF2_APPROVED_PROPOSAL_CHILD_IMMUTABLE'); END;
CREATE TRIGGER IF NOT EXISTS trg_hf2_approved_child_no_insert
BEFORE INSERT ON stage2_proposal_events
WHEN EXISTS(SELECT 1 FROM stage2_proposals p WHERE p.proposal_id=NEW.proposal_id AND p.status IN ('approved','committing','committed'))
BEGIN SELECT RAISE(ABORT,'HF2_APPROVED_PROPOSAL_CHILD_IMMUTABLE'); END;

CREATE TRIGGER IF NOT EXISTS trg_hf2_terminal_attempt_immutable
BEFORE UPDATE ON stage2_commit_attempts
WHEN OLD.status IN ('committed','rolled_back','retryable_failed','terminal_failed')
BEGIN SELECT RAISE(ABORT,'HF2_COMMIT_ATTEMPT_IMMUTABLE'); END;
CREATE TRIGGER IF NOT EXISTS trg_hf2_attempt_no_delete
BEFORE DELETE ON stage2_commit_attempts
BEGIN SELECT RAISE(ABORT,'HF2_COMMIT_ATTEMPT_IMMUTABLE'); END;
