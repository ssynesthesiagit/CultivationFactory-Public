-- Store each locked catalogue record once instead of once per project.
--
-- Locking a project used to copy the whole core catalogue into
-- project_locked_records.  On the owner's database that was 45,683 rows and
-- 492.9 MB holding only 70.4 MB of distinct content, and every new project
-- added roughly another 74 MB.  Building that copy in memory is also what
-- drove the Factory to 16.5 GB resident during a character-builder catalogue
-- lock on 2026-09-04.
--
-- The bytes were already stored elsewhere: 45,682 of those rows are
-- byte-identical to the catalog_records row carrying the same record_hash,
-- and within catalog_records a record_hash maps to exactly one data_json.
-- Only one row (a non-sphere METHOD-081 authority record, 4 KB) has no
-- catalogue row at all.
--
-- So the base table now stores a record_hash reference, content that has no
-- catalogue row goes to locked_record_blobs, and a view named
-- project_locked_records reassembles the original shape.  Every existing
-- reader keeps its query unchanged; INSTEAD OF triggers keep writers working
-- and keep the immutability guarantee the old row triggers provided.

CREATE TABLE IF NOT EXISTS locked_record_blobs(
  record_hash TEXT PRIMARY KEY CHECK(length(record_hash)=64),
  record_json TEXT NOT NULL
);

-- record_json_override holds the row's own bytes in the one case that matters:
-- when the supplied content does not equal what its record_hash resolves to.
-- Deduplication must not become a laundering step. If a row is written whose
-- bytes disagree with its hash, those exact bytes are kept so the existing
-- project_lock_proof mismatch detection still sees them, unchanged. For every
-- ordinary row the content matches and this stays NULL.
CREATE TABLE IF NOT EXISTS project_locked_record_refs(
  project_id TEXT NOT NULL,
  record_id TEXT NOT NULL,
  pack_id TEXT NOT NULL,
  pack_version TEXT NOT NULL,
  record_hash TEXT NOT NULL,
  record_json_override TEXT,
  PRIMARY KEY(project_id, record_id),
  FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_project_locked_record_refs_hash
ON project_locked_record_refs(record_hash);

-- The view resolves content by record_hash. catalog_records had no index
-- usable for that lookup: its only covering index is the composite
-- UNIQUE(record_id, pack_id, pack_version, source_hash, record_hash), where
-- record_hash is the last column. Without this index each resolved row costs
-- a full scan of catalog_records, which made reading one project's 6,526
-- locked records take 15.8 s instead of milliseconds.
CREATE INDEX IF NOT EXISTS idx_catalog_records_record_hash
ON catalog_records(record_hash);

-- Content that no catalogue row can supply. The join in the view below reads
-- catalog_records first, so a blob is only consulted when that misses.
INSERT OR IGNORE INTO locked_record_blobs(record_hash, record_json)
SELECT DISTINCT p.record_hash, p.record_json
FROM project_locked_records p
WHERE NOT EXISTS(SELECT 1 FROM catalog_records c WHERE c.record_hash = p.record_hash);

INSERT OR IGNORE INTO project_locked_record_refs(
  project_id, record_id, pack_id, pack_version, record_hash, record_json_override)
SELECT
  p.project_id, p.record_id, p.pack_id, p.pack_version, p.record_hash,
  CASE
    WHEN p.record_json = COALESCE(
      (SELECT c.data_json FROM catalog_records c WHERE c.record_hash = p.record_hash),
      (SELECT b.record_json FROM locked_record_blobs b WHERE b.record_hash = p.record_hash)
    ) THEN NULL
    ELSE p.record_json
  END
FROM project_locked_records p;

DROP TRIGGER IF EXISTS trg_hf2_project_locked_record_no_update;

DROP TRIGGER IF EXISTS trg_hf2_project_locked_record_no_delete;

DROP TABLE IF EXISTS project_locked_records;

CREATE VIEW project_locked_records AS
SELECT
  r.project_id      AS project_id,
  r.record_id       AS record_id,
  r.pack_id         AS pack_id,
  r.pack_version    AS pack_version,
  r.record_hash     AS record_hash,
  COALESCE(
    r.record_json_override,
    (SELECT c.data_json FROM catalog_records c WHERE c.record_hash = r.record_hash),
    (SELECT b.record_json FROM locked_record_blobs b WHERE b.record_hash = r.record_hash)
  )                 AS record_json
FROM project_locked_record_refs r;

-- A locked record stays immutable: rebinding a record_id to different bytes
-- is refused with the same code the old row trigger raised. Re-inserting the
-- identical binding is allowed so a retried lock is idempotent.
CREATE TRIGGER trg_project_locked_record_insert
INSTEAD OF INSERT ON project_locked_records
BEGIN
  SELECT RAISE(ABORT, 'HF2_PROJECT_LOCKED_RECORD_IMMUTABLE')
  WHERE EXISTS(
    SELECT 1 FROM project_locked_record_refs s
    WHERE s.project_id = NEW.project_id
      AND s.record_id = NEW.record_id
      AND s.record_hash <> NEW.record_hash
  );

  SELECT RAISE(ABORT, 'HF2_PROJECT_LOCKED_RECORD_CONTENT_UNRESOLVABLE')
  WHERE NEW.record_json IS NULL;

  INSERT OR IGNORE INTO locked_record_blobs(record_hash, record_json)
  SELECT NEW.record_hash, NEW.record_json
  WHERE NOT EXISTS(SELECT 1 FROM catalog_records c WHERE c.record_hash = NEW.record_hash);

  -- Keep the row's own bytes whenever they disagree with what the hash
  -- resolves to, so a mismatched write stays visible to project_lock_proof
  -- instead of being quietly replaced by the catalogue copy.
  INSERT OR REPLACE INTO project_locked_record_refs(
    project_id, record_id, pack_id, pack_version, record_hash, record_json_override)
  VALUES(
    NEW.project_id, NEW.record_id, NEW.pack_id, NEW.pack_version, NEW.record_hash,
    CASE
      WHEN NEW.record_json = COALESCE(
        (SELECT c.data_json FROM catalog_records c WHERE c.record_hash = NEW.record_hash),
        (SELECT b.record_json FROM locked_record_blobs b WHERE b.record_hash = NEW.record_hash)
      ) THEN NULL
      ELSE NEW.record_json
    END);
END;

CREATE TRIGGER trg_project_locked_record_no_update
INSTEAD OF UPDATE ON project_locked_records
BEGIN
  SELECT RAISE(ABORT, 'HF2_PROJECT_LOCKED_RECORD_IMMUTABLE');
END;

-- Deleting a project still removes its references through the foreign key
-- cascade on the base table. A direct delete against the view keeps the old
-- authorization rule.
CREATE TRIGGER trg_project_locked_record_no_delete
INSTEAD OF DELETE ON project_locked_records
WHEN NOT EXISTS(
  SELECT 1 FROM character_builder_temporary_delete_authorizations a
  WHERE a.project_id = OLD.project_id
)
BEGIN
  SELECT RAISE(ABORT, 'HF2_PROJECT_LOCKED_RECORD_IMMUTABLE');
END;

CREATE TRIGGER trg_project_locked_record_authorized_delete
INSTEAD OF DELETE ON project_locked_records
WHEN EXISTS(
  SELECT 1 FROM character_builder_temporary_delete_authorizations a
  WHERE a.project_id = OLD.project_id
)
BEGIN
  DELETE FROM project_locked_record_refs
  WHERE project_id = OLD.project_id AND record_id = OLD.record_id;
END;
