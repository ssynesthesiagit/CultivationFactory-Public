-- Retained append-only lifecycle evidence.  Migration 008 tied history to the
-- mutable installed-pack projection with ON DELETE CASCADE, so uninstalling a
-- pack erased the very evidence the table was intended to preserve.  Keep the
-- original table for migration compatibility, but copy all history into an
-- independent audit stream and use this stream for every future event.
CREATE TABLE IF NOT EXISTS content_pack_lifecycle_audit_events (
    sequence_no INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    pack_id TEXT NOT NULL,
    version TEXT NOT NULL,
    canonical_content_hash TEXT NOT NULL,
    from_state TEXT,
    to_state TEXT NOT NULL,
    superseded_by_version TEXT,
    transition_kind TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    evidence_hash TEXT NOT NULL,
    occurred_at TEXT NOT NULL
);

INSERT OR IGNORE INTO content_pack_lifecycle_audit_events(
    event_id,pack_id,version,canonical_content_hash,from_state,to_state,
    superseded_by_version,transition_kind,evidence_json,evidence_hash,occurred_at
)
SELECT event_id,pack_id,version,canonical_content_hash,from_state,to_state,
       superseded_by_version,transition_kind,evidence_json,evidence_hash,occurred_at
FROM content_pack_lifecycle_events;

CREATE INDEX IF NOT EXISTS idx_content_pack_lifecycle_audit_pack
ON content_pack_lifecycle_audit_events(pack_id, version, sequence_no);
