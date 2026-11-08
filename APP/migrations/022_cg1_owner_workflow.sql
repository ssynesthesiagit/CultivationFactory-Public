CREATE TABLE IF NOT EXISTS character_creation_preferences(
  project_id TEXT NOT NULL,
  owner_principal_hash TEXT NOT NULL,
  execution_mode TEXT NOT NULL CHECK(execution_mode IN ('MANUAL_CHAT','STANDARD_API','AUTO_FINALIZE_WHEN_CLEAN')),
  updated_at TEXT NOT NULL,
  PRIMARY KEY(project_id,owner_principal_hash),
  FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS character_creation_auto_finalize_opt_ins(
  receipt_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  owner_principal_id TEXT NOT NULL,
  owner_principal_hash TEXT NOT NULL,
  project_revision INTEGER NOT NULL,
  content_lock_hash TEXT NOT NULL,
  request_sha256 TEXT NOT NULL,
  candidate_identity TEXT NOT NULL,
  output_profile_sha256 TEXT NOT NULL,
  receipt_sha256 TEXT NOT NULL UNIQUE,
  revoked_at TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_cg1_opt_in_binding ON character_creation_auto_finalize_opt_ins(
  project_id,owner_principal_hash,project_revision,content_lock_hash,request_sha256,candidate_identity,output_profile_sha256
);
