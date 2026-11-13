CREATE TABLE IF NOT EXISTS character_creation_attempt_history(
  attempt_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  ordinal INTEGER NOT NULL,
  action_type TEXT NOT NULL CHECK(action_type IN ('REQUEST_CREATED','IMPORT_RESPONSE','REPLACE_RESPONSE','RETRY_LOCAL_BUILD','EDIT_BRIEF_CREATE_NEW_REQUEST','CANCEL_BUILD','FINALIZE')),
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
CREATE INDEX IF NOT EXISTS idx_cg1_attempt_history_run ON character_creation_attempt_history(run_id,ordinal);
CREATE INDEX IF NOT EXISTS idx_cg1_attempt_history_project ON character_creation_attempt_history(project_id,created_at);

CREATE TABLE IF NOT EXISTS character_creation_brief_edits(
  edit_id TEXT PRIMARY KEY,
  source_run_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  payload_sha256 TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('PREPARED','CONSUMED','CANCELLED')),
  child_run_id TEXT,
  created_at TEXT NOT NULL,
  consumed_at TEXT,
  FOREIGN KEY(source_run_id) REFERENCES character_creation_runs(run_id) ON DELETE CASCADE,
  FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_cg1_brief_edits_source ON character_creation_brief_edits(source_run_id,created_at);

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
