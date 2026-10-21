-- Phase 4A-HF2 R5: process-epoch and monotonic clock authority for exact approvals.
-- Additive and restart-convergent. Historical challenge/evidence rows remain readable,
-- but outstanding rows without R5 clock authority fail closed when used.

ALTER TABLE exact_approval_challenges ADD COLUMN process_epoch_id TEXT;
ALTER TABLE exact_approval_challenges ADD COLUMN issued_monotonic_ns INTEGER;
ALTER TABLE exact_approval_challenges ADD COLUMN deadline_monotonic_ns INTEGER;
ALTER TABLE exact_approval_challenges ADD COLUMN consumed_monotonic_ns INTEGER;
ALTER TABLE exact_approval_challenges ADD COLUMN invalidated_observed_at TEXT;
ALTER TABLE exact_approval_challenges ADD COLUMN invalidation_reason TEXT;

ALTER TABLE exact_approval_evidence ADD COLUMN process_epoch_id TEXT;
ALTER TABLE exact_approval_evidence ADD COLUMN consumed_monotonic_ns INTEGER;

CREATE TABLE IF NOT EXISTS approval_clock_authority_state (
    singleton_id INTEGER PRIMARY KEY CHECK(singleton_id=1),
    wall_high_water_at TEXT NOT NULL,
    last_process_epoch_id TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approval_process_epochs (
    process_epoch_id TEXT PRIMARY KEY,
    process_id INTEGER NOT NULL,
    first_seen_wall_at TEXT NOT NULL,
    first_seen_monotonic_ns INTEGER NOT NULL,
    monotonic_high_water_ns INTEGER NOT NULL,
    last_seen_wall_at TEXT NOT NULL,
    last_seen_monotonic_ns INTEGER NOT NULL,
    registered_at TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS trg_hf2_r5_clock_authority_no_delete
BEFORE DELETE ON approval_clock_authority_state
BEGIN SELECT RAISE(ABORT,'HF2_CLOCK_AUTHORITY_IMMUTABLE'); END;

CREATE TRIGGER IF NOT EXISTS trg_hf2_r5_clock_authority_monotonic
BEFORE UPDATE ON approval_clock_authority_state
WHEN NEW.singleton_id<>OLD.singleton_id OR NEW.wall_high_water_at<OLD.wall_high_water_at
BEGIN SELECT RAISE(ABORT,'HF2_CLOCK_AUTHORITY_HIGH_WATER_REVERSED'); END;

CREATE TRIGGER IF NOT EXISTS trg_hf2_r5_process_epoch_no_delete
BEFORE DELETE ON approval_process_epochs
BEGIN SELECT RAISE(ABORT,'HF2_PROCESS_EPOCH_IMMUTABLE'); END;

CREATE TRIGGER IF NOT EXISTS trg_hf2_r5_process_epoch_monotonic
BEFORE UPDATE ON approval_process_epochs
WHEN NEW.process_epoch_id<>OLD.process_epoch_id OR NEW.process_id<>OLD.process_id OR
     NEW.first_seen_wall_at<>OLD.first_seen_wall_at OR
     NEW.first_seen_monotonic_ns<>OLD.first_seen_monotonic_ns OR
     NEW.registered_at<>OLD.registered_at OR
     NEW.monotonic_high_water_ns<OLD.monotonic_high_water_ns
BEGIN SELECT RAISE(ABORT,'HF2_PROCESS_EPOCH_HIGH_WATER_REVERSED'); END;

DROP TRIGGER IF EXISTS trg_hf2_r4_challenge_binding_immutable;
CREATE TRIGGER IF NOT EXISTS trg_hf2_r5_challenge_binding_immutable
BEFORE UPDATE ON exact_approval_challenges
WHEN
    NEW.challenge_id<>OLD.challenge_id OR NEW.challenge_hash<>OLD.challenge_hash OR
    NEW.principal_id<>OLD.principal_id OR NEW.principal_hash<>OLD.principal_hash OR
    NEW.operation<>OLD.operation OR NEW.subject_type<>OLD.subject_type OR NEW.subject_id<>OLD.subject_id OR
    NEW.exact_bytes_hash<>OLD.exact_bytes_hash OR NEW.binding_hash<>OLD.binding_hash OR
    NEW.project_lock_hash<>OLD.project_lock_hash OR NEW.nonce_hash<>OLD.nonce_hash OR
    NEW.issued_at<>OLD.issued_at OR NEW.expires_at<>OLD.expires_at OR NEW.challenge_json<>OLD.challenge_json OR
    COALESCE(NEW.process_epoch_id,'')<>COALESCE(OLD.process_epoch_id,'') OR
    COALESCE(NEW.issued_monotonic_ns,-1)<>COALESCE(OLD.issued_monotonic_ns,-1) OR
    COALESCE(NEW.deadline_monotonic_ns,-1)<>COALESCE(OLD.deadline_monotonic_ns,-1) OR
    OLD.status<>'issued' OR NEW.status NOT IN ('consumed','expired','invalidated') OR
    (NEW.status='consumed' AND (NEW.consumed_at IS NULL OR NEW.consumed_monotonic_ns IS NULL OR
       NEW.expired_observed_at IS NOT NULL OR NEW.invalidated_observed_at IS NOT NULL OR NEW.invalidation_reason IS NOT NULL)) OR
    (NEW.status='expired' AND (NEW.expired_observed_at IS NULL OR NEW.consumed_at IS NOT NULL OR
       NEW.consumed_monotonic_ns IS NOT NULL OR NEW.invalidated_observed_at IS NOT NULL OR NEW.invalidation_reason IS NOT NULL)) OR
    (NEW.status='invalidated' AND (NEW.invalidated_observed_at IS NULL OR NEW.invalidation_reason IS NULL OR
       NEW.consumed_at IS NOT NULL OR NEW.consumed_monotonic_ns IS NOT NULL OR NEW.expired_observed_at IS NOT NULL))
BEGIN SELECT RAISE(ABORT,'HF2_APPROVAL_CHALLENGE_IMMUTABLE'); END;
