CREATE TABLE IF NOT EXISTS stage1_prompt_exchanges (
    prompt_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    project_revision INTEGER NOT NULL,
    catalog_build_id TEXT NOT NULL,
    content_lock_hash TEXT NOT NULL,
    envelope_schema_version TEXT NOT NULL,
    envelope_json TEXT NOT NULL,
    prompt_bytes BLOB NOT NULL,
    prompt_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE,
    UNIQUE(project_id, project_revision, prompt_sha256)
);
CREATE INDEX IF NOT EXISTS idx_stage1_prompt_project ON stage1_prompt_exchanges(project_id, project_revision);

CREATE TABLE IF NOT EXISTS stage1_response_attempts (
    attempt_id TEXT PRIMARY KEY,
    prompt_id TEXT NOT NULL,
    prior_attempt_id TEXT,
    response_id TEXT,
    exact_response_bytes BLOB NOT NULL,
    exact_response_sha256 TEXT NOT NULL,
    response_payload_sha256 TEXT,
    parsing_status TEXT NOT NULL,
    response_json TEXT,
    validation_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(prompt_id) REFERENCES stage1_prompt_exchanges(prompt_id) ON DELETE CASCADE,
    FOREIGN KEY(prior_attempt_id) REFERENCES stage1_response_attempts(attempt_id),
    UNIQUE(prompt_id, exact_response_sha256)
);
CREATE INDEX IF NOT EXISTS idx_stage1_response_prompt ON stage1_response_attempts(prompt_id, created_at);

CREATE TABLE IF NOT EXISTS stage1_response_draft_links (
    attempt_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    slot_id TEXT NOT NULL,
    choice_id TEXT NOT NULL,
    draft_id TEXT NOT NULL,
    PRIMARY KEY(attempt_id, ordinal),
    UNIQUE(draft_id),
    FOREIGN KEY(attempt_id) REFERENCES stage1_response_attempts(attempt_id) ON DELETE CASCADE,
    FOREIGN KEY(draft_id) REFERENCES draft_events(draft_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS stage1_approvals (
    approval_id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL UNIQUE,
    approved_by TEXT NOT NULL,
    approved_at TEXT NOT NULL,
    project_revision_at_approval INTEGER NOT NULL,
    FOREIGN KEY(attempt_id) REFERENCES stage1_response_attempts(attempt_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS stage1_commit_results (
    commit_id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL UNIQUE,
    approval_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    project_revision_before INTEGER NOT NULL,
    project_revision_after INTEGER NOT NULL,
    committed_event_ids_json TEXT NOT NULL,
    replay_state_hash TEXT NOT NULL,
    replay_head_hash TEXT,
    projection_id TEXT,
    projection_status TEXT NOT NULL,
    projection_artifact_hashes_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(attempt_id) REFERENCES stage1_response_attempts(attempt_id) ON DELETE CASCADE,
    FOREIGN KEY(approval_id) REFERENCES stage1_approvals(approval_id),
    FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);
