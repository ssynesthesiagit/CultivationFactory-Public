-- Exact backed-up rows only; service inserts/removes grants in one transaction.
-- Normal append-only protection, including retained attempts, remains unchanged.
CREATE TABLE project_permanent_delete_authorizations(
    table_name TEXT NOT NULL,
    row_id INTEGER NOT NULL,
    PRIMARY KEY(table_name,row_id)
);

DROP TRIGGER IF EXISTS trg_hf2_approved_proposal_no_delete;
CREATE TRIGGER trg_hf2_approved_proposal_no_delete
BEFORE DELETE ON stage2_proposals
WHEN NOT EXISTS(SELECT 1 FROM project_permanent_delete_authorizations a
                WHERE a.table_name='stage2_proposals' AND a.row_id=OLD.rowid)
AND (OLD.status IN ('approved','committing','committed'))
BEGIN SELECT RAISE(ABORT,'HF2_APPROVED_PROPOSAL_IMMUTABLE'); END;

DROP TRIGGER IF EXISTS trg_hf2_approved_child_no_delete;
CREATE TRIGGER trg_hf2_approved_child_no_delete
BEFORE DELETE ON stage2_proposal_events
WHEN NOT EXISTS(SELECT 1 FROM project_permanent_delete_authorizations a
                WHERE a.table_name='stage2_proposal_events' AND a.row_id=OLD.rowid)
AND (EXISTS(SELECT 1 FROM stage2_proposals p WHERE p.proposal_id=OLD.proposal_id AND p.status IN ('approved','committing','committed')))
BEGIN SELECT RAISE(ABORT,'HF2_APPROVED_PROPOSAL_CHILD_IMMUTABLE'); END;

DROP TRIGGER IF EXISTS trg_hf2_attempt_no_delete;
CREATE TRIGGER trg_hf2_attempt_no_delete
BEFORE DELETE ON stage2_commit_attempts
WHEN NOT EXISTS(SELECT 1 FROM project_permanent_delete_authorizations a
                WHERE a.table_name='stage2_commit_attempts' AND a.row_id=OLD.rowid)
BEGIN SELECT RAISE(ABORT,'HF2_COMMIT_ATTEMPT_IMMUTABLE'); END;

DROP TRIGGER IF EXISTS trg_hf2_r2_committed_receipt_no_delete;
CREATE TRIGGER trg_hf2_r2_committed_receipt_no_delete
BEFORE DELETE ON stage2_commit_receipts
WHEN NOT EXISTS(SELECT 1 FROM project_permanent_delete_authorizations a
                WHERE a.table_name='stage2_commit_receipts' AND a.row_id=OLD.rowid)
AND (OLD.status='committed')
BEGIN SELECT RAISE(ABORT,'HF2_COMMIT_RECEIPT_IMMUTABLE'); END;

DROP TRIGGER IF EXISTS trg_hf2_r2_rebuild_history_no_delete;
CREATE TRIGGER trg_hf2_r2_rebuild_history_no_delete
BEFORE DELETE ON stage2_rebuild_history
WHEN NOT EXISTS(SELECT 1 FROM project_permanent_delete_authorizations a
                WHERE a.table_name='stage2_rebuild_history' AND a.row_id=OLD.rowid)
BEGIN SELECT RAISE(ABORT,'HF2_REBUILD_HISTORY_IMMUTABLE'); END;

DROP TRIGGER IF EXISTS trg_hf2_r3_challenge_no_delete;
CREATE TRIGGER trg_hf2_r3_challenge_no_delete
BEFORE DELETE ON exact_approval_challenges
WHEN NOT EXISTS(SELECT 1 FROM project_permanent_delete_authorizations a
                WHERE a.table_name='exact_approval_challenges' AND a.row_id=OLD.rowid)
BEGIN SELECT RAISE(ABORT,'HF2_APPROVAL_CHALLENGE_IMMUTABLE'); END;

DROP TRIGGER IF EXISTS trg_hf2_r3_evidence_no_delete;
CREATE TRIGGER trg_hf2_r3_evidence_no_delete
BEFORE DELETE ON exact_approval_evidence
WHEN NOT EXISTS(SELECT 1 FROM project_permanent_delete_authorizations a
                WHERE a.table_name='exact_approval_evidence' AND a.row_id=OLD.rowid)
BEGIN SELECT RAISE(ABORT,'HF2_APPROVAL_EVIDENCE_IMMUTABLE'); END;

DROP TRIGGER IF EXISTS trg_hf2_r4_rebuild_receipt_no_delete;
CREATE TRIGGER trg_hf2_r4_rebuild_receipt_no_delete
BEFORE DELETE ON stage2_rebuild_receipts
WHEN NOT EXISTS(SELECT 1 FROM project_permanent_delete_authorizations a
                WHERE a.table_name='stage2_rebuild_receipts' AND a.row_id=OLD.rowid)
BEGIN SELECT RAISE(ABORT,'HF2_REBUILD_RECEIPT_IMMUTABLE'); END;

DROP TRIGGER IF EXISTS trg_hf2_r4_committed_event_no_delete;
CREATE TRIGGER trg_hf2_r4_committed_event_no_delete
BEFORE DELETE ON events
WHEN NOT EXISTS(SELECT 1 FROM project_permanent_delete_authorizations a
                WHERE a.table_name='events' AND a.row_id=OLD.rowid)
AND (EXISTS(SELECT 1 FROM stage2_commit_receipts r, json_each(r.event_ids_json) j WHERE r.status='committed' AND r.project_id=OLD.project_id AND j.value=OLD.event_id))
BEGIN SELECT RAISE(ABORT,'HF2_COMMITTED_EVENT_IMMUTABLE'); END;

DROP TRIGGER IF EXISTS trg_hf2_project_locked_replacement_no_delete;
CREATE TRIGGER trg_hf2_project_locked_replacement_no_delete
BEFORE DELETE ON project_locked_replacements
WHEN NOT EXISTS(SELECT 1 FROM project_permanent_delete_authorizations a
                WHERE a.table_name='project_locked_replacements' AND a.row_id=OLD.rowid)
AND (NOT EXISTS(SELECT 1 FROM character_builder_temporary_delete_authorizations a WHERE a.project_id=OLD.project_id))
BEGIN SELECT RAISE(ABORT,'HF2_PROJECT_LOCKED_REPLACEMENT_IMMUTABLE'); END;

DROP TRIGGER IF EXISTS trg_dcc_controller_run_bindings_no_delete;
CREATE TRIGGER trg_dcc_controller_run_bindings_no_delete
BEFORE DELETE ON dcc_controller_run_bindings
WHEN NOT EXISTS(SELECT 1 FROM project_permanent_delete_authorizations a
                WHERE a.table_name='dcc_controller_run_bindings' AND a.row_id=OLD.rowid)
BEGIN SELECT RAISE(ABORT,'dcc_controller_run_bindings is append-only'); END;

DROP TRIGGER IF EXISTS trg_dcc_controller_events_no_delete;
CREATE TRIGGER trg_dcc_controller_events_no_delete
BEFORE DELETE ON dcc_controller_events
WHEN NOT EXISTS(SELECT 1 FROM project_permanent_delete_authorizations a
                WHERE a.table_name='dcc_controller_events' AND a.row_id=OLD.rowid)
BEGIN SELECT RAISE(ABORT,'dcc_controller_events is append-only'); END;

DROP TRIGGER IF EXISTS trg_cg1_attempt_history_no_delete;
CREATE TRIGGER trg_cg1_attempt_history_no_delete
BEFORE DELETE ON character_creation_attempt_history
WHEN NOT EXISTS(SELECT 1 FROM project_permanent_delete_authorizations a
                WHERE a.table_name='character_creation_attempt_history' AND a.row_id=OLD.rowid)
BEGIN SELECT RAISE(ABORT,'character_creation_attempt_history is append-only'); END;

DROP TRIGGER IF EXISTS trg_cg1_project_delete_retains_attempt_history;
CREATE TRIGGER trg_cg1_project_delete_retains_attempt_history
BEFORE DELETE ON projects
WHEN NOT EXISTS(SELECT 1 FROM project_permanent_delete_authorizations a
                WHERE a.table_name='projects' AND a.row_id=OLD.rowid)
AND (EXISTS(SELECT 1 FROM character_creation_attempt_history h WHERE h.project_id=OLD.project_id))
BEGIN SELECT RAISE(ABORT,'CG1_ATTEMPT_HISTORY_MUST_BE_RETAINED'); END;
DROP TRIGGER IF EXISTS trg_cg1_run_delete_retains_attempt_history;
CREATE TRIGGER trg_cg1_run_delete_retains_attempt_history
BEFORE DELETE ON character_creation_runs
WHEN NOT EXISTS(SELECT 1 FROM project_permanent_delete_authorizations a
                WHERE a.table_name='character_creation_runs' AND a.row_id=OLD.rowid)
AND (EXISTS(SELECT 1 FROM character_creation_attempt_history h WHERE h.run_id=OLD.run_id))
BEGIN SELECT RAISE(ABORT,'CG1_ATTEMPT_HISTORY_MUST_BE_RETAINED'); END;
