-- Compact, durable facts used by the character-library chooser. Rows are
-- filled lazily by the endpoint and invalidated by its existing project stamp.
CREATE TABLE IF NOT EXISTS project_library_summary (
    project_id TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    name TEXT,
    title TEXT,
    target_cl INTEGER,
    background TEXT,
    paths_json TEXT NOT NULL DEFAULT '[]',
    completed_at TEXT,
    last_worked_at TEXT,
    user_lock_fields_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);
