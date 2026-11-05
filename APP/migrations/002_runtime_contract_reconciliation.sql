CREATE TABLE IF NOT EXISTS contract_migration_runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    source_database_hash TEXT,
    status TEXT NOT NULL,
    inventory_json TEXT NOT NULL,
    mapping_json TEXT NOT NULL,
    quarantine_count INTEGER NOT NULL DEFAULT 0,
    report_path TEXT
);

CREATE TABLE IF NOT EXISTS contract_quarantine (
    quarantine_id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_family TEXT NOT NULL,
    object_key TEXT NOT NULL,
    declared_schema_version TEXT,
    reason_code TEXT NOT NULL,
    diagnostics_json TEXT NOT NULL,
    original_json TEXT NOT NULL,
    quarantined_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS event_hash_mappings (
    project_id TEXT NOT NULL,
    sequence_no INTEGER NOT NULL,
    event_id TEXT NOT NULL,
    old_event_hash TEXT NOT NULL,
    new_event_hash TEXT NOT NULL,
    old_previous_event_hash TEXT,
    new_previous_event_hash TEXT NOT NULL,
    mapping_reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(project_id, sequence_no)
);

CREATE TABLE IF NOT EXISTS canonical_object_validations (
    validation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_family TEXT NOT NULL,
    object_key TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    boundary TEXT NOT NULL,
    valid INTEGER NOT NULL,
    diagnostics_json TEXT NOT NULL,
    object_hash TEXT,
    validated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_contract_validation_object ON canonical_object_validations(object_family, object_key);

CREATE TABLE IF NOT EXISTS ai_stage_responses (
    response_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    project_revision INTEGER NOT NULL,
    protocol_version TEXT NOT NULL,
    response_json TEXT NOT NULL,
    response_hash TEXT NOT NULL,
    validation_json TEXT NOT NULL,
    accepted_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);

ALTER TABLE catalog_records ADD COLUMN raw_projection_json TEXT;
ALTER TABLE catalog_records ADD COLUMN canonical_schema_version TEXT;
ALTER TABLE catalog_records ADD COLUMN contract_status TEXT NOT NULL DEFAULT 'legacy-unverified';

ALTER TABLE projects ADD COLUMN legacy_project_json TEXT;
ALTER TABLE projects ADD COLUMN canonical_project_hash TEXT;
ALTER TABLE projects ADD COLUMN canonical_schema_version TEXT;
ALTER TABLE projects ADD COLUMN contract_status TEXT NOT NULL DEFAULT 'legacy-unverified';

ALTER TABLE events ADD COLUMN legacy_event_json TEXT;
ALTER TABLE events ADD COLUMN legacy_event_hash TEXT;
ALTER TABLE events ADD COLUMN canonical_schema_version TEXT;
ALTER TABLE events ADD COLUMN contract_status TEXT NOT NULL DEFAULT 'legacy-unverified';
