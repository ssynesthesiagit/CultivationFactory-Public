-- Independent of project rows: Undo and a missing project cannot clear a halt.
ALTER TABLE project_deletion_requests ADD COLUMN recovery_required INTEGER NOT NULL DEFAULT 0 CHECK(recovery_required IN (0,1));
ALTER TABLE project_deletion_requests ADD COLUMN quarantine TEXT;
CREATE INDEX idx_project_deletion_recovery ON project_deletion_requests(recovery_required);
