CREATE TABLE IF NOT EXISTS projection_runs (
    projection_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    project_revision INTEGER NOT NULL,
    content_lock_hash TEXT NOT NULL,
    event_head_hash TEXT,
    status TEXT NOT NULL,
    generated_dir TEXT NOT NULL,
    ledger_sha256 TEXT,
    rules_packets_sha256 TEXT,
    provenance_sha256 TEXT,
    coverage_sha256 TEXT,
    diagnostics_sha256 TEXT,
    candidate_sha256 TEXT,
    command5_status TEXT NOT NULL DEFAULT 'NOT_RUN',
    command6_status TEXT NOT NULL DEFAULT 'NOT_RUN',
    created_at TEXT NOT NULL,
    completed_at TEXT,
    diagnostics_json TEXT NOT NULL DEFAULT '[]',
    UNIQUE(project_id, project_revision, content_lock_hash, event_head_hash),
    FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_projection_project ON projection_runs(project_id, created_at DESC);

CREATE TABLE IF NOT EXISTS projection_artifacts (
    projection_id TEXT NOT NULL,
    artifact_name TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    bytes INTEGER NOT NULL,
    media_type TEXT NOT NULL,
    PRIMARY KEY(projection_id, artifact_name),
    FOREIGN KEY(projection_id) REFERENCES projection_runs(projection_id) ON DELETE CASCADE
);
