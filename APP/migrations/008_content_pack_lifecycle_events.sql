-- Append-only evidence for every Content Pack lifecycle transition.  The
-- mutable current state in content_packs is a projection of this history; the
-- history is retained so trust/lifecycle decisions remain auditable.
CREATE TABLE IF NOT EXISTS content_pack_lifecycle_events (
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
    occurred_at TEXT NOT NULL,
    FOREIGN KEY(pack_id, version) REFERENCES content_packs(pack_id, version) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_content_pack_lifecycle_events_pack
ON content_pack_lifecycle_events(pack_id, version, sequence_no);
