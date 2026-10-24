-- Phase 4A-HF2 Recovery R4: external keyed integrity anchors, convergent trust migration,
-- terminal event anchors, append-only rebuild receipts, and irreversible challenge expiry.

ALTER TABLE exact_approval_challenges ADD COLUMN expired_observed_at TEXT;
ALTER TABLE exact_approval_evidence ADD COLUMN approval_projection_json TEXT;
ALTER TABLE exact_approval_evidence ADD COLUMN approval_projection_hash TEXT;
ALTER TABLE exact_approval_evidence ADD COLUMN integrity_version TEXT;
ALTER TABLE exact_approval_evidence ADD COLUMN integrity_key_id TEXT;
ALTER TABLE exact_approval_evidence ADD COLUMN integrity_domain TEXT;
ALTER TABLE exact_approval_evidence ADD COLUMN integrity_mac TEXT;

ALTER TABLE stage2_commit_attempts ADD COLUMN approval_evidence_id TEXT;
ALTER TABLE stage2_commit_receipts ADD COLUMN approval_evidence_id TEXT;
ALTER TABLE stage2_commit_receipts ADD COLUMN terminal_projection_json TEXT;
ALTER TABLE stage2_commit_receipts ADD COLUMN terminal_projection_hash TEXT;
ALTER TABLE stage2_commit_receipts ADD COLUMN terminal_mechanical_state_hash TEXT;
ALTER TABLE stage2_commit_receipts ADD COLUMN integrity_version TEXT;
ALTER TABLE stage2_commit_receipts ADD COLUMN integrity_key_id TEXT;
ALTER TABLE stage2_commit_receipts ADD COLUMN integrity_domain TEXT;
ALTER TABLE stage2_commit_receipts ADD COLUMN integrity_mac TEXT;

ALTER TABLE stage2_artifacts ADD COLUMN rebuild_receipt_id TEXT;
ALTER TABLE stage2_rebuild_status ADD COLUMN rebuild_receipt_id TEXT;

CREATE TABLE IF NOT EXISTS stage2_rebuild_receipts (
    rebuild_receipt_id TEXT PRIMARY KEY,
    rebuild_id TEXT NOT NULL UNIQUE,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    project_revision INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('READY','BLOCKED')),
    terminal_commit_id TEXT,
    terminal_projection_hash TEXT,
    event_chain_head TEXT NOT NULL,
    mechanical_state_hash TEXT NOT NULL,
    artifact_set_hash TEXT,
    ordered_artifacts_json TEXT NOT NULL,
    blocker_report_hash TEXT NOT NULL,
    rebuild_projection_json TEXT NOT NULL,
    rebuild_projection_hash TEXT NOT NULL,
    integrity_version TEXT NOT NULL,
    integrity_key_id TEXT NOT NULL,
    integrity_domain TEXT NOT NULL,
    integrity_mac TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_stage2_rebuild_receipts_project
ON stage2_rebuild_receipts(project_id,project_revision,created_at);
CREATE TRIGGER IF NOT EXISTS trg_hf2_r4_rebuild_receipt_no_update
BEFORE UPDATE ON stage2_rebuild_receipts
BEGIN SELECT RAISE(ABORT,'HF2_REBUILD_RECEIPT_IMMUTABLE'); END;
CREATE TRIGGER IF NOT EXISTS trg_hf2_r4_rebuild_receipt_no_delete
BEFORE DELETE ON stage2_rebuild_receipts
BEGIN SELECT RAISE(ABORT,'HF2_REBUILD_RECEIPT_IMMUTABLE'); END;

ALTER TABLE content_pack_install_receipts ADD COLUMN authority_disposition TEXT NOT NULL DEFAULT 'legacy_unproven';
ALTER TABLE content_pack_install_receipts ADD COLUMN install_projection_json TEXT;
ALTER TABLE content_pack_install_receipts ADD COLUMN install_projection_hash TEXT;
ALTER TABLE content_pack_install_receipts ADD COLUMN integrity_version TEXT;
ALTER TABLE content_pack_install_receipts ADD COLUMN integrity_key_id TEXT;
ALTER TABLE content_pack_install_receipts ADD COLUMN integrity_domain TEXT;
ALTER TABLE content_pack_install_receipts ADD COLUMN integrity_mac TEXT;

ALTER TABLE content_pack_lifecycle_audit_events ADD COLUMN transition_projection_json TEXT;
ALTER TABLE content_pack_lifecycle_audit_events ADD COLUMN transition_projection_hash TEXT;
ALTER TABLE content_pack_lifecycle_audit_events ADD COLUMN integrity_version TEXT;
ALTER TABLE content_pack_lifecycle_audit_events ADD COLUMN integrity_key_id TEXT;
ALTER TABLE content_pack_lifecycle_audit_events ADD COLUMN integrity_domain TEXT;
ALTER TABLE content_pack_lifecycle_audit_events ADD COLUMN integrity_mac TEXT;

CREATE TABLE IF NOT EXISTS content_pack_legacy_trust_inventory (
    pack_id TEXT NOT NULL,
    version TEXT NOT NULL,
    receipt_hash TEXT NOT NULL,
    prior_trust_state TEXT NOT NULL,
    disposition TEXT NOT NULL,
    inventoried_at TEXT NOT NULL,
    reason TEXT NOT NULL,
    PRIMARY KEY(pack_id,version)
);
INSERT OR IGNORE INTO content_pack_legacy_trust_inventory(
    pack_id,version,receipt_hash,prior_trust_state,disposition,inventoried_at,reason)
SELECT pack_id,version,receipt_hash,trust_state,'legacy_unproven',datetime('now'),
       'Pre-R4 exact-human-trust receipt lacks a valid external keyed integrity anchor.'
FROM content_pack_install_receipts
WHERE trust_state='human_trusted_exact_archive';

CREATE TABLE IF NOT EXISTS integrity_key_registry (
    key_id TEXT PRIMARY KEY,
    integrity_version TEXT NOT NULL,
    algorithm TEXT NOT NULL,
    platform_status TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('active','rotated','missing'))
);

DROP TRIGGER IF EXISTS trg_hf2_r3_challenge_binding_immutable;
CREATE TRIGGER IF NOT EXISTS trg_hf2_r4_challenge_binding_immutable
BEFORE UPDATE ON exact_approval_challenges
WHEN
    NEW.challenge_id<>OLD.challenge_id OR NEW.challenge_hash<>OLD.challenge_hash OR
    NEW.principal_id<>OLD.principal_id OR NEW.principal_hash<>OLD.principal_hash OR
    NEW.operation<>OLD.operation OR NEW.subject_type<>OLD.subject_type OR NEW.subject_id<>OLD.subject_id OR
    NEW.exact_bytes_hash<>OLD.exact_bytes_hash OR NEW.binding_hash<>OLD.binding_hash OR
    NEW.project_lock_hash<>OLD.project_lock_hash OR NEW.nonce_hash<>OLD.nonce_hash OR
    NEW.issued_at<>OLD.issued_at OR NEW.expires_at<>OLD.expires_at OR NEW.challenge_json<>OLD.challenge_json OR
    OLD.status<>'issued' OR NEW.status NOT IN ('consumed','expired','invalidated') OR
    (NEW.status='expired' AND NEW.expired_observed_at IS NULL) OR
    (NEW.status<>'expired' AND COALESCE(NEW.expired_observed_at,'')<>COALESCE(OLD.expired_observed_at,''))
BEGIN SELECT RAISE(ABORT,'HF2_APPROVAL_CHALLENGE_IMMUTABLE'); END;

CREATE TRIGGER IF NOT EXISTS trg_hf2_r4_committed_event_no_update
BEFORE UPDATE ON events
WHEN EXISTS(
    SELECT 1 FROM stage2_commit_receipts r, json_each(r.event_ids_json) j
    WHERE r.status='committed' AND r.project_id=OLD.project_id AND j.value=OLD.event_id
)
BEGIN SELECT RAISE(ABORT,'HF2_COMMITTED_EVENT_IMMUTABLE'); END;
CREATE TRIGGER IF NOT EXISTS trg_hf2_r4_committed_event_no_delete
BEFORE DELETE ON events
WHEN EXISTS(
    SELECT 1 FROM stage2_commit_receipts r, json_each(r.event_ids_json) j
    WHERE r.status='committed' AND r.project_id=OLD.project_id AND j.value=OLD.event_id
)
BEGIN SELECT RAISE(ABORT,'HF2_COMMITTED_EVENT_IMMUTABLE'); END;

CREATE TRIGGER IF NOT EXISTS trg_hf2_r4_project_stream_no_rewrite
BEFORE UPDATE OF project_json,revision ON projects
WHEN EXISTS(SELECT 1 FROM stage2_commit_receipts r WHERE r.status='committed' AND r.project_id=OLD.project_id)
 AND (
   CAST(json_extract(NEW.project_json,'$.event_stream.count') AS INTEGER) < CAST(json_extract(OLD.project_json,'$.event_stream.count') AS INTEGER)
   OR (
      CAST(json_extract(NEW.project_json,'$.event_stream.count') AS INTEGER)=CAST(json_extract(OLD.project_json,'$.event_stream.count') AS INTEGER)
      AND COALESCE(json_extract(NEW.project_json,'$.event_stream.head_hash'),'')<>COALESCE(json_extract(OLD.project_json,'$.event_stream.head_hash'),'')
   )
 )
BEGIN SELECT RAISE(ABORT,'HF2_COMMITTED_PROJECT_STREAM_IMMUTABLE'); END;

DROP TRIGGER IF EXISTS trg_hf2_r2_attempt_binding_no_update;
CREATE TRIGGER IF NOT EXISTS trg_hf2_r4_attempt_binding_no_update
BEFORE UPDATE ON stage2_commit_attempts
WHEN
    NEW.attempt_id <> OLD.attempt_id OR NEW.proposal_id <> OLD.proposal_id OR NEW.project_id <> OLD.project_id OR
    NEW.attempt_no <> OLD.attempt_no OR NEW.base_revision <> OLD.base_revision OR
    COALESCE(NEW.approved_proposal_hash,'') <> COALESCE(OLD.approved_proposal_hash,'') OR
    COALESCE(NEW.approved_validation_hash,'') <> COALESCE(OLD.approved_validation_hash,'') OR
    COALESCE(NEW.approved_child_hashes_json,'') <> COALESCE(OLD.approved_child_hashes_json,'') OR
    COALESCE(NEW.approved_compiled_event_hashes_json,'') <> COALESCE(OLD.approved_compiled_event_hashes_json,'') OR
    COALESCE(NEW.approved_lock_proof_hash,'') <> COALESCE(OLD.approved_lock_proof_hash,'') OR
    COALESCE(NEW.approved_principal_id,'') <> COALESCE(OLD.approved_principal_id,'') OR
    COALESCE(NEW.approved_principal_hash,'') <> COALESCE(OLD.approved_principal_hash,'') OR
    COALESCE(NEW.binding_set_hash,'') <> COALESCE(OLD.binding_set_hash,'') OR
    COALESCE(NEW.approval_evidence_id,'') <> COALESCE(OLD.approval_evidence_id,'') OR
    COALESCE(NEW.state_before_hash,'') <> COALESCE(OLD.state_before_hash,'') OR
    COALESCE(NEW.created_at,'') <> COALESCE(OLD.created_at,'')
BEGIN SELECT RAISE(ABORT,'HF2_COMMIT_ATTEMPT_BINDING_IMMUTABLE'); END;

CREATE TRIGGER IF NOT EXISTS trg_hf2_r4_pack_lifecycle_no_update
BEFORE UPDATE ON content_pack_lifecycle_audit_events
BEGIN SELECT RAISE(ABORT,'HF2_CONTENT_PACK_LIFECYCLE_EVIDENCE_IMMUTABLE'); END;
CREATE TRIGGER IF NOT EXISTS trg_hf2_r4_pack_lifecycle_no_delete
BEFORE DELETE ON content_pack_lifecycle_audit_events
BEGIN SELECT RAISE(ABORT,'HF2_CONTENT_PACK_LIFECYCLE_EVIDENCE_IMMUTABLE'); END;
