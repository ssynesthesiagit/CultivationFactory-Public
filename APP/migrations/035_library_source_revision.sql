-- Durable source versions are independent of second-resolution timestamps.
-- Triggers cover every writer, including accepted identity updates and imports.
CREATE TABLE IF NOT EXISTS project_library_source_revision (
    project_id TEXT PRIMARY KEY REFERENCES projects(project_id) ON DELETE CASCADE,
    revision INTEGER NOT NULL DEFAULT 1
);
INSERT OR IGNORE INTO project_library_source_revision(project_id) SELECT project_id FROM projects;
CREATE TRIGGER library_project_insert AFTER INSERT ON projects BEGIN
    INSERT INTO project_library_source_revision(project_id) VALUES(NEW.project_id);
END;
CREATE TRIGGER library_project_update AFTER UPDATE ON projects BEGIN
    UPDATE project_library_source_revision SET revision=revision+1 WHERE project_id=NEW.project_id;
END;
CREATE TRIGGER library_run_insert AFTER INSERT ON character_creation_runs BEGIN
    UPDATE project_library_source_revision SET revision=revision+1 WHERE project_id=NEW.project_id;
END;
CREATE TRIGGER library_run_update AFTER UPDATE ON character_creation_runs BEGIN
    UPDATE project_library_source_revision SET revision=revision+1
    WHERE project_id=OLD.project_id OR project_id=NEW.project_id;
END;
CREATE TRIGGER library_run_delete AFTER DELETE ON character_creation_runs BEGIN
    UPDATE project_library_source_revision SET revision=revision+1 WHERE project_id=OLD.project_id;
END;
