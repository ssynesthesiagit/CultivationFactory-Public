-- Queue metadata deliberately has no project FK: retain the owner's request
-- and outcome after deletion. It is not part of a project's restore snapshot.
CREATE TABLE project_deletion_requests (
    project_id TEXT PRIMARY KEY,
    requested_by TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    confirmation TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('queued','failed','deleted')),
    reason TEXT,
    backup TEXT,
    processed_at TEXT
);
CREATE INDEX idx_project_deletion_requests_status ON project_deletion_requests(status);
