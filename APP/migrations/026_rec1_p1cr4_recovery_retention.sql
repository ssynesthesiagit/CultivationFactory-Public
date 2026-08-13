-- Character-creation attempts are immutable recovery evidence.  Project
-- deletion must never silently cascade through a run and erase that history.
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
