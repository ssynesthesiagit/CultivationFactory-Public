-- Cover the scalar global recovery chooser projection without touching the
-- retained request/response/validation JSON payloads.
CREATE INDEX IF NOT EXISTS idx_cg1_recovery_chooser
ON character_creation_runs(
  project_id,
  created_at DESC,
  status,
  run_id,
  starting_revision,
  execution_mode,
  updated_at
);
