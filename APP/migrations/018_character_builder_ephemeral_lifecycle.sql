CREATE TABLE IF NOT EXISTS character_builder_project_lifecycle (
    project_id TEXT PRIMARY KEY REFERENCES projects(project_id) ON DELETE CASCADE,
    persistence_state TEXT NOT NULL CHECK(persistence_state IN ('temporary','saved_draft','completed')),
    lifecycle_source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_character_builder_project_lifecycle_state
    ON character_builder_project_lifecycle(persistence_state, updated_at, project_id);

-- HF2 immutable project snapshots remain protected by default. A narrowly
-- scoped transactional authorization permits deletion only for projects that
-- the builder service has already verified as explicitly temporary.
CREATE TABLE IF NOT EXISTS character_builder_temporary_delete_authorizations (
    project_id TEXT PRIMARY KEY,
    reason TEXT NOT NULL,
    authorized_at TEXT NOT NULL
);

DROP TRIGGER IF EXISTS trg_hf2_project_locked_replacement_no_delete;
CREATE TRIGGER trg_hf2_project_locked_replacement_no_delete
BEFORE DELETE ON project_locked_replacements
WHEN NOT EXISTS(
    SELECT 1 FROM character_builder_temporary_delete_authorizations a
    WHERE a.project_id=OLD.project_id
)
BEGIN SELECT RAISE(ABORT,'HF2_PROJECT_LOCKED_REPLACEMENT_IMMUTABLE'); END;

DROP TRIGGER IF EXISTS trg_hf2_project_locked_record_no_delete;
CREATE TRIGGER trg_hf2_project_locked_record_no_delete
BEFORE DELETE ON project_locked_records
WHEN NOT EXISTS(
    SELECT 1 FROM character_builder_temporary_delete_authorizations a
    WHERE a.project_id=OLD.project_id
)
BEGIN SELECT RAISE(ABORT,'HF2_PROJECT_LOCKED_RECORD_IMMUTABLE'); END;
