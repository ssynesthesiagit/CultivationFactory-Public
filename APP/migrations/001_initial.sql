CREATE TABLE IF NOT EXISTS content_packs (
    pack_id TEXT NOT NULL,
    version TEXT NOT NULL,
    pack_hash TEXT NOT NULL,
    lifecycle_state TEXT NOT NULL,
    authority TEXT NOT NULL,
    installed_path TEXT,
    manifest_json TEXT NOT NULL,
    installed_at TEXT NOT NULL,
    superseded_by_version TEXT,
    retired_at TEXT,
    PRIMARY KEY(pack_id, version)
);

CREATE TABLE IF NOT EXISTS catalog_builds (
    build_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    record_count INTEGER NOT NULL,
    unresolved_count INTEGER NOT NULL,
    counts_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS catalog_records (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id TEXT NOT NULL,
    content_type TEXT NOT NULL,
    display_name TEXT NOT NULL,
    pack_id TEXT NOT NULL,
    pack_version TEXT NOT NULL,
    authority TEXT NOT NULL,
    publication_state TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_anchor TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    record_hash TEXT NOT NULL,
    minimum_cl INTEGER,
    realm TEXT,
    selected_authority INTEGER NOT NULL DEFAULT 1,
    data_json TEXT NOT NULL,
    unresolved_notes_json TEXT NOT NULL DEFAULT '[]',
    FOREIGN KEY(pack_id, pack_version) REFERENCES content_packs(pack_id, version) ON DELETE CASCADE,
    UNIQUE(record_id, pack_id, pack_version, source_hash, record_hash)
);
CREATE INDEX IF NOT EXISTS idx_catalog_record_id ON catalog_records(record_id);
CREATE INDEX IF NOT EXISTS idx_catalog_type ON catalog_records(content_type);
CREATE INDEX IF NOT EXISTS idx_catalog_pack ON catalog_records(pack_id, pack_version);
CREATE INDEX IF NOT EXISTS idx_catalog_authority ON catalog_records(authority, publication_state);

CREATE TABLE IF NOT EXISTS catalog_dependencies (
    source_row_id INTEGER NOT NULL,
    dependency_record_id TEXT NOT NULL,
    relation TEXT NOT NULL,
    FOREIGN KEY(source_row_id) REFERENCES catalog_records(row_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_dep_target ON catalog_dependencies(dependency_record_id);

CREATE TABLE IF NOT EXISTS catalog_conflicts (
    conflict_id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id TEXT NOT NULL,
    selected_row_id INTEGER,
    competing_row_id INTEGER,
    status TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS catalog_fts USING fts5(
    row_id UNINDEXED,
    record_id,
    display_name,
    content_type,
    summary,
    search_text,
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    working_name TEXT NOT NULL,
    status TEXT NOT NULL,
    revision INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    target_factory_version TEXT NOT NULL,
    target_candidate_schema_version TEXT NOT NULL,
    target_gm_screen_version TEXT NOT NULL,
    catalog_build_hash TEXT,
    quality_target TEXT NOT NULL,
    project_json TEXT NOT NULL,
    compatibility_projection_status TEXT NOT NULL,
    compile_status TEXT NOT NULL,
    consumer_verification_status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project_content_locks (
    project_id TEXT NOT NULL,
    pack_id TEXT NOT NULL,
    version TEXT NOT NULL,
    pack_hash TEXT NOT NULL,
    locked_at TEXT NOT NULL,
    PRIMARY KEY(project_id, pack_id),
    FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS project_locked_records (
    project_id TEXT NOT NULL,
    record_id TEXT NOT NULL,
    pack_id TEXT NOT NULL,
    pack_version TEXT NOT NULL,
    record_hash TEXT NOT NULL,
    record_json TEXT NOT NULL,
    PRIMARY KEY(project_id, record_id),
    FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS draft_events (
    draft_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status TEXT NOT NULL,
    event_json TEXT NOT NULL,
    validation_json TEXT,
    approved_by TEXT,
    FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS events (
    project_id TEXT NOT NULL,
    sequence_no INTEGER NOT NULL,
    event_id TEXT NOT NULL,
    event_hash TEXT NOT NULL,
    previous_event_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    event_json TEXT NOT NULL,
    PRIMARY KEY(project_id, sequence_no),
    UNIQUE(event_id),
    UNIQUE(project_id, event_hash),
    FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS snapshots (
    project_id TEXT NOT NULL,
    sequence_no INTEGER NOT NULL,
    state_hash TEXT NOT NULL,
    state_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(project_id, sequence_no),
    FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS validation_findings (
    finding_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    severity TEXT NOT NULL,
    code TEXT NOT NULL,
    message TEXT NOT NULL,
    resolved INTEGER NOT NULL DEFAULT 0,
    details_json TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS vendor_runs (
    run_id TEXT PRIMARY KEY,
    operation TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    exit_code INTEGER NOT NULL,
    command_json TEXT NOT NULL,
    stdout_path TEXT NOT NULL,
    stderr_path TEXT NOT NULL,
    verdict TEXT NOT NULL,
    details_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recent_errors (
    error_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    code TEXT NOT NULL,
    message TEXT NOT NULL,
    details_json TEXT
);
