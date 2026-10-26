-- Replacement authority is immutable content owned by an exact Content Pack
-- version. It never rewrites the pinned Factory/core record that it replaces.
CREATE TABLE IF NOT EXISTS catalog_record_replacements (
    replacement_id TEXT NOT NULL,
    replacement_pack_id TEXT NOT NULL,
    replacement_pack_version TEXT NOT NULL,
    replacement_pack_hash TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    source_record_hash TEXT NOT NULL,
    source_pack_id TEXT NOT NULL,
    source_pack_version TEXT NOT NULL,
    source_pack_hash TEXT NOT NULL,
    target_record_id TEXT NOT NULL,
    target_record_hash TEXT NOT NULL,
    mode TEXT NOT NULL CHECK(mode='replace_in_selection'),
    reason TEXT NOT NULL,
    map_path TEXT NOT NULL,
    map_hash TEXT NOT NULL,
    PRIMARY KEY(replacement_pack_id, replacement_pack_version, replacement_id),
    UNIQUE(replacement_pack_id, replacement_pack_version, source_record_id, source_pack_id, source_pack_version, source_record_hash),
    FOREIGN KEY(replacement_pack_id, replacement_pack_version)
        REFERENCES content_packs(pack_id, version) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_catalog_replacement_source
    ON catalog_record_replacements(source_record_id, source_pack_id, source_pack_version, source_record_hash);
CREATE INDEX IF NOT EXISTS idx_catalog_replacement_target
    ON catalog_record_replacements(target_record_id, replacement_pack_id, replacement_pack_version, target_record_hash);
