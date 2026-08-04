CREATE TABLE IF NOT EXISTS non_sphere_character_states(
    project_id TEXT PRIMARY KEY REFERENCES projects(project_id) ON DELETE CASCADE,
    schema_version TEXT NOT NULL,
    authority_snapshot_hash TEXT NOT NULL CHECK(length(authority_snapshot_hash)=64),
    state_json TEXT NOT NULL,
    state_hash TEXT NOT NULL CHECK(length(state_hash)=64),
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_non_sphere_states_authority ON non_sphere_character_states(authority_snapshot_hash);
