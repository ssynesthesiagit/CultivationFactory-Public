-- Phase 3B HF1: Stage 1 is a blueprint-intent stream, never an advancement stream.

CREATE TABLE IF NOT EXISTS stage1_decision_batches (
    batch_id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL UNIQUE,
    project_id TEXT NOT NULL,
    prompt_id TEXT NOT NULL,
    response_id TEXT,
    schema_version TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN (
        'response_received','validation_failed','validated','approval_pending',
        'approved','committed','projection_pending','projected','projection_failed'
    )),
    expected_project_revision INTEGER NOT NULL,
    catalog_build_id TEXT NOT NULL,
    content_lock_hash TEXT NOT NULL,
    exact_response_sha256 TEXT NOT NULL,
    computed_payload_sha256 TEXT,
    submitted_payload_sha256 TEXT,
    response_payload_json TEXT,
    authored_notes_json TEXT NOT NULL DEFAULT '[]',
    planner_rationale TEXT NOT NULL DEFAULT '',
    validation_json TEXT NOT NULL,
    batch_hash TEXT,
    approved_by TEXT,
    approved_at TEXT,
    committed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(attempt_id) REFERENCES stage1_response_attempts(attempt_id) ON DELETE CASCADE,
    FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE,
    FOREIGN KEY(prompt_id) REFERENCES stage1_prompt_exchanges(prompt_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_stage1_batch_project ON stage1_decision_batches(project_id, created_at);

CREATE TABLE IF NOT EXISTS stage1_blueprint_decisions (
    decision_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    slot_id TEXT NOT NULL,
    decision_state TEXT NOT NULL CHECK(decision_state IN (
        'selected','explicit_none','blocked_missing_authority','deferred_with_reason'
    )),
    selected_record_ids_json TEXT NOT NULL,
    record_snapshots_json TEXT NOT NULL,
    reason_code TEXT,
    reason TEXT,
    decision_json TEXT NOT NULL,
    decision_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(batch_id, ordinal),
    UNIQUE(batch_id, slot_id),
    FOREIGN KEY(batch_id) REFERENCES stage1_decision_batches(batch_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS stage1_batch_transitions (
    transition_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    from_state TEXT,
    to_state TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    actor_identifier TEXT,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(batch_id, ordinal),
    FOREIGN KEY(batch_id) REFERENCES stage1_decision_batches(batch_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS stage1_blueprint_commits (
    project_id TEXT NOT NULL,
    sequence_no INTEGER NOT NULL,
    commit_id TEXT NOT NULL UNIQUE,
    batch_id TEXT NOT NULL UNIQUE,
    previous_commit_hash TEXT NOT NULL,
    commit_hash TEXT NOT NULL,
    intent_state_json TEXT NOT NULL,
    intent_state_hash TEXT NOT NULL,
    project_revision_before INTEGER NOT NULL,
    project_revision_after INTEGER NOT NULL,
    approved_by TEXT NOT NULL,
    committed_at TEXT NOT NULL,
    PRIMARY KEY(project_id, sequence_no),
    UNIQUE(project_id, commit_hash),
    FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE,
    FOREIGN KEY(batch_id) REFERENCES stage1_decision_batches(batch_id)
);

CREATE TABLE IF NOT EXISTS stage1_blueprint_heads (
    project_id TEXT PRIMARY KEY,
    sequence_no INTEGER NOT NULL,
    commit_id TEXT NOT NULL,
    commit_hash TEXT NOT NULL,
    intent_state_hash TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE,
    FOREIGN KEY(commit_id) REFERENCES stage1_blueprint_commits(commit_id)
);

CREATE TABLE IF NOT EXISTS stage1_blueprint_commit_results (
    commit_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL UNIQUE,
    attempt_id TEXT NOT NULL UNIQUE,
    project_id TEXT NOT NULL,
    project_revision_before INTEGER NOT NULL,
    project_revision_after INTEGER NOT NULL,
    intent_state_hash TEXT NOT NULL,
    blueprint_commit_hash TEXT NOT NULL,
    advancement_event_count_before INTEGER NOT NULL,
    advancement_event_count_after INTEGER NOT NULL,
    projection_status TEXT NOT NULL,
    projection_id TEXT,
    projection_hash TEXT,
    last_projection_error_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(batch_id) REFERENCES stage1_decision_batches(batch_id),
    FOREIGN KEY(attempt_id) REFERENCES stage1_response_attempts(attempt_id),
    FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS stage1_blueprint_projections (
    projection_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    commit_id TEXT NOT NULL UNIQUE,
    projection_json TEXT NOT NULL,
    projection_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE,
    FOREIGN KEY(commit_id) REFERENCES stage1_blueprint_commits(commit_id)
);

-- Legacy Stage 1 CL0 mechanics are only identified and quarantined. They are never
-- silently rewritten as intent because doing so would mutate a committed hash chain.
CREATE TABLE IF NOT EXISTS stage1_legacy_event_quarantine (
    event_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    sequence_no INTEGER NOT NULL,
    event_hash TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);

INSERT OR IGNORE INTO stage1_legacy_event_quarantine(
    event_id, project_id, sequence_no, event_hash, reason_code, detected_at
)
SELECT event_id, project_id, sequence_no, event_hash,
       'LEGACY_STAGE1_CL0_ADVANCEMENT_EVENT', datetime('now')
FROM events
WHERE json_extract(event_json, '$.effective_point.character_cl') = 0
  AND (
      json_extract(event_json, '$.effective_point.label') IN ('stage_1_blueprint','stage_1_blueprint_metadata')
      OR json_extract(event_json, '$.payload.stage_id') = 'stage_1_source_blueprint'
      OR json_extract(event_json, '$.planner_response_id') IS NOT NULL
  );
