CREATE TABLE IF NOT EXISTS content_pack_install_receipts (
    pack_id TEXT NOT NULL,
    version TEXT NOT NULL,
    canonical_content_hash TEXT NOT NULL,
    payload_files_hash TEXT NOT NULL,
    record_set_hash TEXT NOT NULL,
    archive_sha256 TEXT,
    package_identity_sha256 TEXT NOT NULL,
    package_bytes INTEGER NOT NULL,
    trust_state TEXT NOT NULL,
    signer_key_id TEXT,
    signature_sidecar_sha256 TEXT,
    human_approved_by TEXT,
    human_approval_hash TEXT,
    receipt_json TEXT NOT NULL,
    receipt_hash TEXT NOT NULL,
    installed_at TEXT NOT NULL,
    PRIMARY KEY(pack_id, version),
    FOREIGN KEY(pack_id, version) REFERENCES content_packs(pack_id, version) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_content_pack_receipts_trust
ON content_pack_install_receipts(trust_state, signer_key_id);
