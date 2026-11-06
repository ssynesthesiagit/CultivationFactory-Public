-- Phase 4A-HF2 Recovery R3: server-derived principals, one-time exact-byte challenges,
-- and immutable approval evidence. Additive; R1/R2 invariants remain unchanged.

CREATE TABLE IF NOT EXISTS exact_approval_challenges (
    challenge_id TEXT PRIMARY KEY,
    challenge_hash TEXT NOT NULL UNIQUE,
    principal_id TEXT NOT NULL,
    principal_hash TEXT NOT NULL,
    operation TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    exact_bytes_hash TEXT NOT NULL,
    binding_hash TEXT NOT NULL,
    project_lock_hash TEXT NOT NULL,
    nonce_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('issued','consumed','expired','invalidated')),
    issued_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    consumed_at TEXT,
    challenge_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_exact_approval_challenges_subject
ON exact_approval_challenges(operation,subject_type,subject_id,issued_at);

CREATE TABLE IF NOT EXISTS exact_approval_evidence (
    evidence_id TEXT PRIMARY KEY,
    challenge_id TEXT NOT NULL UNIQUE REFERENCES exact_approval_challenges(challenge_id),
    challenge_hash TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    principal_hash TEXT NOT NULL,
    operation TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    exact_bytes_hash TEXT NOT NULL,
    binding_hash TEXT NOT NULL,
    project_lock_hash TEXT NOT NULL,
    evidence_hash TEXT NOT NULL UNIQUE,
    evidence_json TEXT NOT NULL,
    consumed_at TEXT NOT NULL
);

ALTER TABLE stage2_proposals ADD COLUMN approval_evidence_id TEXT;
ALTER TABLE content_pack_install_receipts ADD COLUMN human_principal_id TEXT;
ALTER TABLE content_pack_install_receipts ADD COLUMN human_principal_hash TEXT;
ALTER TABLE content_pack_install_receipts ADD COLUMN human_challenge_id TEXT;
ALTER TABLE content_pack_install_receipts ADD COLUMN human_evidence_id TEXT;
ALTER TABLE content_pack_lifecycle_audit_events ADD COLUMN authoritative_principal_id TEXT;
ALTER TABLE content_pack_lifecycle_audit_events ADD COLUMN approval_challenge_id TEXT;
ALTER TABLE content_pack_lifecycle_audit_events ADD COLUMN approval_evidence_id TEXT;

CREATE TRIGGER IF NOT EXISTS trg_hf2_r3_challenge_binding_immutable
BEFORE UPDATE ON exact_approval_challenges
WHEN
    NEW.challenge_id<>OLD.challenge_id OR NEW.challenge_hash<>OLD.challenge_hash OR
    NEW.principal_id<>OLD.principal_id OR NEW.principal_hash<>OLD.principal_hash OR
    NEW.operation<>OLD.operation OR NEW.subject_type<>OLD.subject_type OR NEW.subject_id<>OLD.subject_id OR
    NEW.exact_bytes_hash<>OLD.exact_bytes_hash OR NEW.binding_hash<>OLD.binding_hash OR
    NEW.project_lock_hash<>OLD.project_lock_hash OR NEW.nonce_hash<>OLD.nonce_hash OR
    NEW.issued_at<>OLD.issued_at OR NEW.expires_at<>OLD.expires_at OR NEW.challenge_json<>OLD.challenge_json OR
    OLD.status<>'issued' OR NEW.status NOT IN ('consumed','expired','invalidated')
BEGIN SELECT RAISE(ABORT,'HF2_APPROVAL_CHALLENGE_IMMUTABLE'); END;

CREATE TRIGGER IF NOT EXISTS trg_hf2_r3_challenge_no_delete
BEFORE DELETE ON exact_approval_challenges
BEGIN SELECT RAISE(ABORT,'HF2_APPROVAL_CHALLENGE_IMMUTABLE'); END;
CREATE TRIGGER IF NOT EXISTS trg_hf2_r3_evidence_no_update
BEFORE UPDATE ON exact_approval_evidence
BEGIN SELECT RAISE(ABORT,'HF2_APPROVAL_EVIDENCE_IMMUTABLE'); END;
CREATE TRIGGER IF NOT EXISTS trg_hf2_r3_evidence_no_delete
BEFORE DELETE ON exact_approval_evidence
BEGIN SELECT RAISE(ABORT,'HF2_APPROVAL_EVIDENCE_IMMUTABLE'); END;

DROP TRIGGER IF EXISTS trg_hf2_approved_proposal_bytes_immutable;
CREATE TRIGGER trg_hf2_approved_proposal_bytes_immutable
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
    COALESCE(NEW.approval_challenge_id,'') <> COALESCE(OLD.approval_challenge_id,'') OR
    COALESCE(NEW.approval_evidence_id,'') <> COALESCE(OLD.approval_evidence_id,'')
)
BEGIN SELECT RAISE(ABORT,'HF2_APPROVED_PROPOSAL_IMMUTABLE'); END;
