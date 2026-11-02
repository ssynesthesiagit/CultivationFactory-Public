-- Optional AI provider configuration and append-only request evidence.
-- API secrets are deliberately absent: they live in a Windows DPAPI-protected
-- file or an ephemeral environment variable.
CREATE TABLE IF NOT EXISTS ai_provider_settings (
    provider_id TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
    endpoint TEXT NOT NULL,
    model TEXT NOT NULL,
    thinking_mode TEXT NOT NULL CHECK(thinking_mode IN ('enabled','disabled')),
    max_output_tokens INTEGER NOT NULL,
    timeout_seconds INTEGER NOT NULL,
    data_sharing_acknowledged INTEGER NOT NULL CHECK(data_sharing_acknowledged IN (0,1)),
    acknowledged_by TEXT,
    acknowledged_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_provider_runs (
    run_id TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
    prompt_id TEXT NOT NULL REFERENCES stage1_prompt_exchanges(prompt_id) ON DELETE RESTRICT,
    idempotency_key TEXT NOT NULL,
    prompt_sha256 TEXT NOT NULL,
    model TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    request_bytes BLOB NOT NULL,
    request_sha256 TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL CHECK(status IN ('started','provider_error','response_rejected','validated')),
    http_status INTEGER,
    provider_response_bytes BLOB,
    provider_response_sha256 TEXT,
    provider_response_bytes_count INTEGER,
    completion_content_sha256 TEXT,
    finish_reason TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    stage1_attempt_id TEXT,
    error_code TEXT,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_ai_provider_runs_project
ON ai_provider_runs(project_id, started_at, run_id);

CREATE INDEX IF NOT EXISTS idx_ai_provider_runs_prompt
ON ai_provider_runs(prompt_id, started_at, run_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_ai_provider_runs_idempotency
ON ai_provider_runs(provider_id, prompt_id, idempotency_key);
