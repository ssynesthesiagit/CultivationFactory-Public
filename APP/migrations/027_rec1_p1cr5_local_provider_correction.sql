-- The local-provider correction is a distinct immutable attempt-history event.
-- Rebuild the constrained table so both databases created before this
-- migration and fresh databases accept that event without broadening any
-- unrelated action or mutability constraints.
DROP TRIGGER IF EXISTS trg_cg1_project_delete_retains_attempt_history;
DROP TRIGGER IF EXISTS trg_cg1_run_delete_retains_attempt_history;
DROP TRIGGER IF EXISTS trg_cg1_attempt_history_no_update;
DROP TRIGGER IF EXISTS trg_cg1_attempt_history_no_delete;
DROP INDEX IF EXISTS idx_cg1_attempt_history_run;
DROP INDEX IF EXISTS idx_cg1_attempt_history_project;

CREATE TABLE IF NOT EXISTS character_creation_attempt_history_local_v2(
  attempt_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  ordinal INTEGER NOT NULL,
  action_type TEXT NOT NULL CHECK(action_type IN ('REQUEST_CREATED','IMPORT_RESPONSE','REPLACE_RESPONSE','RETRY_LOCAL_BUILD','EDIT_BRIEF_CREATE_NEW_REQUEST','CANCEL_BUILD','FINALIZE','LOCAL_PROVIDER_CORRECTION')),
  status TEXT NOT NULL,
  request_sha256 TEXT,
  response_sha256 TEXT,
  response_bytes BLOB,
  response_text TEXT,
  canonical_intent_json TEXT NOT NULL DEFAULT '{}',
  materialization_receipt_json TEXT NOT NULL DEFAULT '{}',
  validation_json TEXT NOT NULL DEFAULT '{}',
  quality_json TEXT NOT NULL DEFAULT '{}',
  candidate_identity TEXT,
  materialized_plan_sha256 TEXT,
  submitted_plan_sha256 TEXT,
  prior_attempt_id TEXT,
  binding_json TEXT NOT NULL DEFAULT '{}',
  links_json TEXT NOT NULL DEFAULT '{}',
  blockers_json TEXT NOT NULL DEFAULT '[]',
  error_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  completed_at TEXT,
  UNIQUE(run_id,ordinal),
  FOREIGN KEY(run_id) REFERENCES character_creation_runs(run_id) ON DELETE CASCADE,
  FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);

INSERT INTO character_creation_attempt_history_local_v2(
  attempt_id,run_id,project_id,ordinal,action_type,status,
  request_sha256,response_sha256,response_bytes,response_text,canonical_intent_json,
  materialization_receipt_json,validation_json,quality_json,candidate_identity,
  materialized_plan_sha256,submitted_plan_sha256,prior_attempt_id,binding_json,links_json,
  blockers_json,error_json,created_at,completed_at)
SELECT
  attempt_id,run_id,project_id,ordinal,action_type,status,
  request_sha256,response_sha256,response_bytes,response_text,canonical_intent_json,
  materialization_receipt_json,validation_json,quality_json,candidate_identity,
  materialized_plan_sha256,submitted_plan_sha256,prior_attempt_id,binding_json,links_json,
  blockers_json,error_json,created_at,completed_at
FROM character_creation_attempt_history;

DROP TABLE IF EXISTS character_creation_attempt_history;
ALTER TABLE character_creation_attempt_history_local_v2 RENAME TO character_creation_attempt_history;

CREATE INDEX IF NOT EXISTS idx_cg1_attempt_history_run ON character_creation_attempt_history(run_id,ordinal);
CREATE INDEX IF NOT EXISTS idx_cg1_attempt_history_project ON character_creation_attempt_history(project_id,created_at);

CREATE TRIGGER IF NOT EXISTS trg_cg1_attempt_history_no_update
BEFORE UPDATE ON character_creation_attempt_history
BEGIN
  SELECT RAISE(ABORT, 'character_creation_attempt_history is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_cg1_attempt_history_no_delete
BEFORE DELETE ON character_creation_attempt_history
BEGIN
  SELECT RAISE(ABORT, 'character_creation_attempt_history is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_cg1_project_delete_retains_attempt_history
BEFORE DELETE ON projects
WHEN EXISTS(
  SELECT 1 FROM character_creation_attempt_history h
  WHERE h.project_id=OLD.project_id
)
BEGIN
  SELECT RAISE(ABORT, 'CG1_ATTEMPT_HISTORY_MUST_BE_RETAINED');
END;

CREATE TRIGGER IF NOT EXISTS trg_cg1_run_delete_retains_attempt_history
BEFORE DELETE ON character_creation_runs
WHEN EXISTS(
  SELECT 1 FROM character_creation_attempt_history h
  WHERE h.run_id=OLD.run_id
)
BEGIN
  SELECT RAISE(ABORT, 'CG1_ATTEMPT_HISTORY_MUST_BE_RETAINED');
END;
