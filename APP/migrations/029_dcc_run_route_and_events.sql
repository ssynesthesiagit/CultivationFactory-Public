-- New DCC runs carry one immutable route binding and an append-only event
-- stream.  Legacy character_creation_runs rows are intentionally not
-- backfilled: absence of a binding is the legacy compatibility state.
CREATE TABLE IF NOT EXISTS dcc_controller_run_bindings(
  run_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  route_mode TEXT NOT NULL CHECK(route_mode IN ('LEGACY_FULL_PLAN','DETERMINISTIC_CREATIVE_CONTROLLER')),
  binding_json TEXT NOT NULL,
  binding_sha256 TEXT NOT NULL CHECK(length(binding_sha256)=64),
  request_sha256 TEXT NOT NULL CHECK(length(request_sha256)=64),
  state TEXT NOT NULL CHECK(state='INACTIVE'),
  created_at TEXT NOT NULL,
  UNIQUE(project_id,run_id),
  FOREIGN KEY(run_id) REFERENCES character_creation_runs(run_id) ON DELETE RESTRICT,
  FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_dcc_controller_bindings_project
ON dcc_controller_run_bindings(project_id,created_at DESC);

CREATE TABLE IF NOT EXISTS dcc_controller_events(
  event_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  route_binding_sha256 TEXT NOT NULL CHECK(length(route_binding_sha256)=64),
  ordinal INTEGER NOT NULL CHECK(ordinal>=1),
  event_type TEXT NOT NULL,
  previous_event_sha256 TEXT,
  subject_sha256 TEXT NOT NULL CHECK(length(subject_sha256)=64),
  state_sha256_before TEXT NOT NULL CHECK(length(state_sha256_before)=64),
  state_sha256_after TEXT NOT NULL CHECK(length(state_sha256_after)=64),
  event_json TEXT NOT NULL,
  event_sha256 TEXT NOT NULL CHECK(length(event_sha256)=64),
  created_at TEXT NOT NULL,
  UNIQUE(run_id,ordinal),
  UNIQUE(run_id,event_sha256),
  FOREIGN KEY(run_id) REFERENCES dcc_controller_run_bindings(run_id) ON DELETE RESTRICT,
  FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_dcc_controller_events_run
ON dcc_controller_events(run_id,ordinal);

CREATE INDEX IF NOT EXISTS idx_dcc_controller_events_project
ON dcc_controller_events(project_id,created_at);

CREATE TRIGGER IF NOT EXISTS trg_dcc_controller_run_bindings_no_update
BEFORE UPDATE ON dcc_controller_run_bindings
BEGIN
  SELECT RAISE(ABORT,'dcc_controller_run_bindings is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_dcc_controller_run_bindings_no_delete
BEFORE DELETE ON dcc_controller_run_bindings
BEGIN
  SELECT RAISE(ABORT,'dcc_controller_run_bindings is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_dcc_controller_events_no_update
BEFORE UPDATE ON dcc_controller_events
BEGIN
  SELECT RAISE(ABORT,'dcc_controller_events is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_dcc_controller_events_no_delete
BEFORE DELETE ON dcc_controller_events
BEGIN
  SELECT RAISE(ABORT,'dcc_controller_events is append-only');
END;

-- Read-only compatibility names keep the table contract discoverable without
-- creating a second mutable copy of the binding or event stream.
CREATE VIEW IF NOT EXISTS character_creation_controller_bindings AS
SELECT * FROM dcc_controller_run_bindings;

CREATE VIEW IF NOT EXISTS character_creation_controller_events AS
SELECT * FROM dcc_controller_events;
