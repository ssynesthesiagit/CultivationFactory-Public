"""Empty synthetic database for Melody's public NS1R acquisition regressions.

The public snapshot excludes SQL migration files. These constraint-bearing
schema shapes cover acquisition, sealed pack membership and their referenced
tables/views/triggers; every test record is inserted synthetically. This is
not an application migration or private database fixture.
"""


def initialize_acquisition_database(db):
    """Install the synthetic fixture schema without accessing packaged migrations."""
    with db.connection() as connection:
        connection.executescript(SCHEMA)


# The registry loads its complete schema set; declare these joined paths so the
# public exporter can supply the real validators rather than fake validation.
PUBLIC_CONTRACT_INPUTS = (
    'schemas/AI_Stage_Response.schema.json',
    'schemas/Advancement_Event.schema.json',
    'schemas/Advancement_Event_v2.schema.json',
    'schemas/Advancement_Event_v3.schema.json',
    'schemas/Blueprint_Decision.schema.json',
    'schemas/Blueprint_Decision_Batch.schema.json',
    'schemas/Blueprint_Intent_State.schema.json',
    'schemas/Character_Project.schema.json',
    'schemas/Content_Pack_Manifest.schema.json',
    'schemas/Content_Pack_Signature.schema.json',
    'schemas/Cultivation_Insight_Stage2_Authority_v1.schema.json',
    'schemas/Foundation_Replacement_Map.schema.json',
    'schemas/Leveling_Ledger_v1.schema.json',
    'schemas/Leveling_Ledger_v2.schema.json',
    'schemas/Project_Scoped_Forged_Technique.schema.json',
    'schemas/Rules_Catalog_Record.schema.json',
    'schemas/Service_API_Contracts.schema.json',
    'schemas/Service_Error.schema.json',
    'schemas/Sphere_Automatic_Component_Authority_v1.schema.json',
    'schemas/Stage1_Clipboard_Exchange.schema.json',
    'schemas/Stage1_Clipboard_Exchange_v2.schema.json',
    'schemas/Stage1_Clipboard_Response.schema.json',
    'schemas/Stage1_Clipboard_Response_v2.schema.json',
    'schemas/Stage1_Prompt_Envelope.schema.json',
    'schemas/Stage1_Prompt_Envelope_v2.schema.json',
    'schemas/Stage2_Advancement_Proposal.schema.json',
    'schemas/Stage2_Advancement_Proposal_v2.schema.json',
    'schemas/Stage2_Blocker_Report.schema.json',
    'schemas/Stage2_Field_Provenance_Map.schema.json',
    'schemas/Stage2_Reconciliation_Report.schema.json',
    'schemas/Stage2_Safe_Formula.schema.json',
    'schemas/Stage2_Training_Transaction.schema.json',
    'schemas/Stage2_Training_Transaction_v1.schema.json',
)


SCHEMA = r"""
CREATE TABLE catalog_records (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id TEXT NOT NULL,
    content_type TEXT NOT NULL,
    display_name TEXT NOT NULL,
    pack_id TEXT NOT NULL,
    pack_version TEXT NOT NULL,
    authority TEXT NOT NULL,
    publication_state TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_anchor TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    record_hash TEXT NOT NULL,
    minimum_cl INTEGER,
    realm TEXT,
    selected_authority INTEGER NOT NULL DEFAULT 1,
    data_json TEXT NOT NULL,
    unresolved_notes_json TEXT NOT NULL DEFAULT '[]', raw_projection_json TEXT, canonical_schema_version TEXT, contract_status TEXT NOT NULL DEFAULT 'legacy-unverified',
    FOREIGN KEY(pack_id, pack_version) REFERENCES content_packs(pack_id, version) ON DELETE CASCADE,
    UNIQUE(record_id, pack_id, pack_version, source_hash, record_hash)
);

CREATE TABLE character_builder_temporary_delete_authorizations (
    project_id TEXT PRIMARY KEY,
    reason TEXT NOT NULL,
    authorized_at TEXT NOT NULL
);

CREATE TABLE "character_creation_attempt_history"(
  attempt_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  ordinal INTEGER NOT NULL,
  action_type TEXT NOT NULL CHECK(action_type IN ('REQUEST_CREATED','IMPORT_RESPONSE','REPLACE_RESPONSE','RETRY_LOCAL_BUILD','EDIT_BRIEF_CREATE_NEW_REQUEST','CANCEL_BUILD','FINALIZE','LOCAL_PROVIDER_CORRECTION','DCC_LINEAR_WALK')),
  status TEXT NOT NULL,
  request_sha256 TEXT,
  response_sha256 TEXT,
  response_bytes BLOB,
  response_text TEXT,
  canonical_intent_json TEXT NOT NULL DEFAULT '{}',
  materialization_receipt_json TEXT NOT NULL DEFAULT '{}',
  validation_json TEXT NOT NULL DEFAULT '{}',
  quality_json TEXT NOT NULL DEFAULT '{}',
  candidate_identity TEXT,
  materialized_plan_sha256 TEXT,
  submitted_plan_sha256 TEXT,
  prior_attempt_id TEXT,
  binding_json TEXT NOT NULL DEFAULT '{}',
  links_json TEXT NOT NULL DEFAULT '{}',
  blockers_json TEXT NOT NULL DEFAULT '[]',
  error_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  completed_at TEXT,
  UNIQUE(run_id,ordinal),
  FOREIGN KEY(run_id) REFERENCES character_creation_runs(run_id) ON DELETE CASCADE,
  FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);

CREATE TABLE character_creation_runs(
  run_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  starting_revision INTEGER NOT NULL,
  execution_mode TEXT NOT NULL CHECK(execution_mode IN ('MANUAL_CHAT','STANDARD_API','AUTO_FINALIZE_WHEN_CLEAN')),
  idempotency_key TEXT NOT NULL,
  request_json TEXT NOT NULL,
  transport_json TEXT NOT NULL DEFAULT '{}',
  response_json TEXT NOT NULL DEFAULT '{}',
  validation_json TEXT NOT NULL DEFAULT '{}',
  dry_run_json TEXT NOT NULL DEFAULT '{}',
  quality_json TEXT NOT NULL DEFAULT '{}',
  owner_decision TEXT,
  commit_json TEXT NOT NULL DEFAULT '{}',
  final_revision INTEGER,
  output_json TEXT NOT NULL DEFAULT '{}',
  blockers_json TEXT NOT NULL DEFAULT '[]',
  warnings_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  completed_at TEXT, final_plan_json TEXT NOT NULL DEFAULT '{}', owner_descriptive_fields_json TEXT NOT NULL DEFAULT '{}', accepted_descriptive_fields_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE(project_id,idempotency_key),
  FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);

CREATE TABLE content_pack_install_receipts (
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
    installed_at TEXT NOT NULL, human_principal_id TEXT, human_principal_hash TEXT, human_challenge_id TEXT, human_evidence_id TEXT, authority_disposition TEXT NOT NULL DEFAULT 'legacy_unproven', install_projection_json TEXT, install_projection_hash TEXT, integrity_version TEXT, integrity_key_id TEXT, integrity_domain TEXT, integrity_mac TEXT,
    PRIMARY KEY(pack_id, version),
    FOREIGN KEY(pack_id, version) REFERENCES content_packs(pack_id, version) ON DELETE CASCADE
);

CREATE TABLE content_pack_record_membership (
    pack_hash TEXT NOT NULL,
    pack_id TEXT NOT NULL,
    pack_version TEXT NOT NULL,
    record_set_hash TEXT NOT NULL,
    payload_files_hash TEXT NOT NULL,
    install_receipt_hash TEXT NOT NULL,
    record_id TEXT NOT NULL,
    record_hash TEXT NOT NULL,
    record_path TEXT NOT NULL,
    semantic_hash TEXT NOT NULL,
    record_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(pack_hash, record_id),
    UNIQUE(pack_hash, record_hash)
);

CREATE TABLE content_packs (
    pack_id TEXT NOT NULL,
    version TEXT NOT NULL,
    pack_hash TEXT NOT NULL,
    lifecycle_state TEXT NOT NULL,
    authority TEXT NOT NULL,
    installed_path TEXT,
    manifest_json TEXT NOT NULL,
    installed_at TEXT NOT NULL,
    superseded_by_version TEXT,
    retired_at TEXT,
    PRIMARY KEY(pack_id, version)
);

CREATE TABLE events (
    project_id TEXT NOT NULL,
    sequence_no INTEGER NOT NULL,
    event_id TEXT NOT NULL,
    event_hash TEXT NOT NULL,
    previous_event_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    event_json TEXT NOT NULL, legacy_event_json TEXT, legacy_event_hash TEXT, canonical_schema_version TEXT, contract_status TEXT NOT NULL DEFAULT 'legacy-unverified',
    PRIMARY KEY(project_id, sequence_no),
    UNIQUE(event_id),
    UNIQUE(project_id, event_hash),
    FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);

CREATE TABLE integrity_key_registry (
    key_id TEXT PRIMARY KEY,
    integrity_version TEXT NOT NULL,
    algorithm TEXT NOT NULL,
    platform_status TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('active','rotated','missing'))
);

CREATE TABLE locked_record_blobs(
  record_hash TEXT PRIMARY KEY CHECK(length(record_hash)=64),
  record_json TEXT NOT NULL
);

CREATE TABLE non_sphere_ap_consumptions(
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    evidence_id TEXT NOT NULL REFERENCES non_sphere_authority_evidence(evidence_id) ON DELETE CASCADE,
    idempotency_key TEXT NOT NULL,
    operation_hash TEXT NOT NULL CHECK(length(operation_hash)=64),
    amount INTEGER NOT NULL CHECK(amount > 0),
    transaction_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(project_id, evidence_id, idempotency_key)
);

CREATE TABLE non_sphere_authority_evidence(
    evidence_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    authority_type TEXT NOT NULL,
    targets_json TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    source_identity TEXT NOT NULL,
    source_hash TEXT NOT NULL CHECK(length(source_hash)=64),
    project_revision INTEGER NOT NULL,
    event_sequence INTEGER,
    amount_awarded INTEGER,
    amount_consumed INTEGER NOT NULL DEFAULT 0,
    creation_authority TEXT NOT NULL,
    valid INTEGER NOT NULL DEFAULT 1,
    revoked_at TEXT,
    evidence_hash TEXT NOT NULL CHECK(length(evidence_hash)=64),
    created_at TEXT NOT NULL,
    UNIQUE(project_id, authority_type, source_kind, source_identity, evidence_hash)
);

CREATE TABLE non_sphere_character_states(
    project_id TEXT PRIMARY KEY REFERENCES projects(project_id) ON DELETE CASCADE,
    schema_version TEXT NOT NULL,
    authority_snapshot_hash TEXT NOT NULL CHECK(length(authority_snapshot_hash)=64),
    state_json TEXT NOT NULL,
    state_hash TEXT NOT NULL CHECK(length(state_hash)=64),
    updated_at TEXT NOT NULL
);

CREATE TABLE project_content_locks (
    project_id TEXT NOT NULL,
    pack_id TEXT NOT NULL,
    version TEXT NOT NULL,
    pack_hash TEXT NOT NULL,
    locked_at TEXT NOT NULL, record_set_hash TEXT, payload_files_hash TEXT, install_receipt_hash TEXT, membership_snapshot_hash TEXT,
    PRIMARY KEY(project_id, pack_id),
    FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);

CREATE TABLE project_library_source_revision (
    project_id TEXT PRIMARY KEY REFERENCES projects(project_id) ON DELETE CASCADE,
    revision INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE project_locked_record_refs(
  project_id TEXT NOT NULL,
  record_id TEXT NOT NULL,
  pack_id TEXT NOT NULL,
  pack_version TEXT NOT NULL,
  record_hash TEXT NOT NULL,
  record_json_override TEXT,
  PRIMARY KEY(project_id, record_id),
  FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);

CREATE TABLE project_permanent_delete_authorizations(
    table_name TEXT NOT NULL,
    row_id INTEGER NOT NULL,
    PRIMARY KEY(table_name,row_id)
);

CREATE TABLE projects (
    project_id TEXT PRIMARY KEY,
    working_name TEXT NOT NULL,
    status TEXT NOT NULL,
    revision INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    target_factory_version TEXT NOT NULL,
    target_candidate_schema_version TEXT NOT NULL,
    target_gm_screen_version TEXT NOT NULL,
    catalog_build_hash TEXT,
    quality_target TEXT NOT NULL,
    project_json TEXT NOT NULL,
    compatibility_projection_status TEXT NOT NULL,
    compile_status TEXT NOT NULL,
    consumer_verification_status TEXT NOT NULL
, legacy_project_json TEXT, canonical_project_hash TEXT, canonical_schema_version TEXT, contract_status TEXT NOT NULL DEFAULT 'legacy-unverified');

CREATE TABLE snapshots (
    project_id TEXT NOT NULL,
    sequence_no INTEGER NOT NULL,
    state_hash TEXT NOT NULL,
    state_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(project_id, sequence_no),
    FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);

CREATE TABLE stage2_commit_receipts (
    commit_id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL UNIQUE REFERENCES stage2_proposals(proposal_id) ON DELETE RESTRICT,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK(status IN ('started','committed','rolled_back','failed')),
    base_revision INTEGER NOT NULL,
    final_revision INTEGER,
    event_ids_json TEXT NOT NULL,
    event_hashes_json TEXT NOT NULL,
    state_before_hash TEXT NOT NULL,
    state_after_hash TEXT,
    error_json TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT
, approved_proposal_hash TEXT, approved_validation_hash TEXT, approved_child_hashes_json TEXT, approved_compiled_event_hashes_json TEXT, approved_lock_proof_hash TEXT, approved_principal_id TEXT, terminal_attempt_id TEXT, approved_principal_hash TEXT NOT NULL DEFAULT 'LEGACY_UNBOUND', binding_set_hash TEXT NOT NULL DEFAULT 'LEGACY_UNBOUND', approval_evidence_id TEXT, terminal_projection_json TEXT, terminal_projection_hash TEXT, terminal_mechanical_state_hash TEXT, integrity_version TEXT, integrity_key_id TEXT, integrity_domain TEXT, integrity_mac TEXT);

CREATE TABLE stage2_proposals (
    proposal_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    idempotency_key TEXT NOT NULL,
    expected_project_revision INTEGER NOT NULL,
    expected_content_lock_hash TEXT NOT NULL,
    target_cl INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('draft','validated','blocked','approved','committing','committed','failed')),
    proposal_json TEXT NOT NULL,
    proposal_hash TEXT NOT NULL,
    validation_json TEXT,
    approved_by TEXT,
    approved_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL, approved_proposal_hash TEXT, approved_validation_hash TEXT, approved_child_hashes_json TEXT, approved_compiled_event_hashes_json TEXT, approved_lock_proof_hash TEXT, approved_principal_id TEXT, approval_challenge_id TEXT, approval_evidence_id TEXT,
    UNIQUE(project_id,idempotency_key)
);

CREATE TABLE uninstalled_content_pack_receipts (
    pack_id TEXT NOT NULL,
    version TEXT NOT NULL,
    pack_hash TEXT NOT NULL,
    receipt_hash TEXT NOT NULL,
    receipt_json TEXT NOT NULL,
    uninstalled_at TEXT NOT NULL,
    PRIMARY KEY(pack_id,version)
);

CREATE TABLE uninstalled_content_pack_record_membership (
    pack_hash TEXT NOT NULL,
    record_id TEXT NOT NULL,
    record_hash TEXT NOT NULL,
    record_json TEXT NOT NULL,
    receipt_hash TEXT NOT NULL,
    uninstalled_at TEXT NOT NULL,
    PRIMARY KEY(pack_hash,record_id)
);

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

CREATE INDEX idx_catalog_authority ON catalog_records(authority, publication_state);

CREATE INDEX idx_catalog_pack ON catalog_records(pack_id, pack_version);

CREATE INDEX idx_catalog_record_id ON catalog_records(record_id);

CREATE INDEX idx_catalog_records_record_hash
ON catalog_records(record_hash);

CREATE INDEX idx_catalog_type ON catalog_records(content_type);

CREATE INDEX idx_cg1_attempt_history_project ON character_creation_attempt_history(project_id,created_at);

CREATE INDEX idx_cg1_attempt_history_run ON character_creation_attempt_history(run_id,ordinal);

CREATE INDEX idx_cg1_recovery_chooser
ON character_creation_runs(
  project_id,
  created_at DESC,
  status,
  run_id,
  starting_revision,
  execution_mode,
  updated_at
);

CREATE INDEX idx_character_creation_runs_project ON character_creation_runs(project_id,created_at DESC);

CREATE INDEX idx_content_pack_receipts_trust
ON content_pack_install_receipts(trust_state, signer_key_id);

CREATE INDEX idx_non_sphere_states_authority ON non_sphere_character_states(authority_snapshot_hash);

CREATE INDEX idx_ns_evidence_project_type ON non_sphere_authority_evidence(project_id, authority_type, valid);

CREATE INDEX idx_pack_membership_lookup
ON content_pack_record_membership(pack_id,pack_version,record_id);

CREATE INDEX idx_project_locked_record_refs_hash
ON project_locked_record_refs(record_hash);

CREATE INDEX idx_stage2_proposals_project ON stage2_proposals(project_id,created_at);

CREATE TRIGGER library_project_insert AFTER INSERT ON projects BEGIN
    INSERT INTO project_library_source_revision(project_id) VALUES(NEW.project_id);
END;

CREATE TRIGGER library_project_update AFTER UPDATE ON projects BEGIN
    UPDATE project_library_source_revision SET revision=revision+1 WHERE project_id=NEW.project_id;
END;

CREATE TRIGGER library_run_delete AFTER DELETE ON character_creation_runs BEGIN
    UPDATE project_library_source_revision SET revision=revision+1 WHERE project_id=OLD.project_id;
END;

CREATE TRIGGER library_run_insert AFTER INSERT ON character_creation_runs BEGIN
    UPDATE project_library_source_revision SET revision=revision+1 WHERE project_id=NEW.project_id;
END;

CREATE TRIGGER library_run_update AFTER UPDATE ON character_creation_runs BEGIN
    UPDATE project_library_source_revision SET revision=revision+1
    WHERE project_id=OLD.project_id OR project_id=NEW.project_id;
END;

CREATE TRIGGER trg_cg1_attempt_history_no_delete
BEFORE DELETE ON character_creation_attempt_history
WHEN NOT EXISTS(SELECT 1 FROM project_permanent_delete_authorizations a
                WHERE a.table_name='character_creation_attempt_history' AND a.row_id=OLD.rowid)
BEGIN SELECT RAISE(ABORT,'character_creation_attempt_history is append-only'); END;

CREATE TRIGGER trg_cg1_attempt_history_no_update
BEFORE UPDATE ON character_creation_attempt_history
BEGIN
  SELECT RAISE(ABORT, 'character_creation_attempt_history is append-only');
END;

CREATE TRIGGER trg_cg1_project_delete_retains_attempt_history
BEFORE DELETE ON projects
WHEN NOT EXISTS(SELECT 1 FROM project_permanent_delete_authorizations a
                WHERE a.table_name='projects' AND a.row_id=OLD.rowid)
AND (EXISTS(SELECT 1 FROM character_creation_attempt_history h WHERE h.project_id=OLD.project_id))
BEGIN SELECT RAISE(ABORT,'CG1_ATTEMPT_HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER trg_cg1_run_delete_retains_attempt_history
BEFORE DELETE ON character_creation_runs
WHEN NOT EXISTS(SELECT 1 FROM project_permanent_delete_authorizations a
                WHERE a.table_name='character_creation_runs' AND a.row_id=OLD.rowid)
AND (EXISTS(SELECT 1 FROM character_creation_attempt_history h WHERE h.run_id=OLD.run_id))
BEGIN SELECT RAISE(ABORT,'CG1_ATTEMPT_HISTORY_MUST_BE_RETAINED'); END;

CREATE TRIGGER trg_hf2_approved_proposal_bytes_immutable
BEFORE UPDATE ON stage2_proposals
WHEN OLD.status IN ('approved','committing','committed') AND (
    NEW.proposal_json <> OLD.proposal_json OR NEW.proposal_hash <> OLD.proposal_hash OR
    COALESCE(NEW.validation_json,'') <> COALESCE(OLD.validation_json,'') OR
    NEW.expected_project_revision <> OLD.expected_project_revision OR
    NEW.expected_content_lock_hash <> OLD.expected_content_lock_hash OR
    NEW.target_cl <> OLD.target_cl OR NEW.idempotency_key <> OLD.idempotency_key OR
    COALESCE(NEW.approved_proposal_hash,'') <> COALESCE(OLD.approved_proposal_hash,'') OR
    COALESCE(NEW.approved_validation_hash,'') <> COALESCE(OLD.approved_validation_hash,'') OR
    COALESCE(NEW.approved_child_hashes_json,'') <> COALESCE(OLD.approved_child_hashes_json,'') OR
    COALESCE(NEW.approved_compiled_event_hashes_json,'') <> COALESCE(OLD.approved_compiled_event_hashes_json,'') OR
    COALESCE(NEW.approved_lock_proof_hash,'') <> COALESCE(OLD.approved_lock_proof_hash,'') OR
    COALESCE(NEW.approved_principal_id,'') <> COALESCE(OLD.approved_principal_id,'') OR
    COALESCE(NEW.approval_challenge_id,'') <> COALESCE(OLD.approval_challenge_id,'') OR
    COALESCE(NEW.approval_evidence_id,'') <> COALESCE(OLD.approval_evidence_id,'')
)
BEGIN SELECT RAISE(ABORT,'HF2_APPROVED_PROPOSAL_IMMUTABLE'); END;

CREATE TRIGGER trg_hf2_approved_proposal_no_delete
BEFORE DELETE ON stage2_proposals
WHEN NOT EXISTS(SELECT 1 FROM project_permanent_delete_authorizations a
                WHERE a.table_name='stage2_proposals' AND a.row_id=OLD.rowid)
AND (OLD.status IN ('approved','committing','committed'))
BEGIN SELECT RAISE(ABORT,'HF2_APPROVED_PROPOSAL_IMMUTABLE'); END;

CREATE TRIGGER trg_hf2_approved_proposal_state_guard
BEFORE UPDATE ON stage2_proposals
WHEN (OLD.status='approved' AND NEW.status NOT IN ('approved','committing','committed'))
  OR (OLD.status='committing' AND NEW.status NOT IN ('committing','approved','committed'))
  OR (OLD.status='committed' AND NEW.status<>'committed')
BEGIN SELECT RAISE(ABORT,'HF2_APPROVED_PROPOSAL_IMMUTABLE'); END;

CREATE TRIGGER trg_hf2_install_receipt_no_delete
BEFORE DELETE ON content_pack_install_receipts
WHEN NOT EXISTS(
    SELECT 1 FROM uninstalled_content_pack_receipts u
    WHERE u.pack_id=OLD.pack_id AND u.version=OLD.version
      AND u.pack_hash=OLD.canonical_content_hash AND u.receipt_hash=OLD.receipt_hash
      AND u.receipt_json=OLD.receipt_json
)
BEGIN SELECT RAISE(ABORT,'HF2_INSTALL_RECEIPT_IMMUTABLE'); END;

CREATE TRIGGER trg_hf2_install_receipt_no_update
BEFORE UPDATE ON content_pack_install_receipts
BEGIN SELECT RAISE(ABORT,'HF2_INSTALL_RECEIPT_IMMUTABLE'); END;

CREATE TRIGGER trg_hf2_membership_no_delete
BEFORE DELETE ON content_pack_record_membership
WHEN NOT EXISTS(
    SELECT 1 FROM uninstalled_content_pack_record_membership u
    WHERE u.pack_hash=OLD.pack_hash AND u.record_id=OLD.record_id
      AND u.record_hash=OLD.record_hash AND u.record_json=OLD.record_json
      AND u.receipt_hash=OLD.install_receipt_hash
)
BEGIN SELECT RAISE(ABORT,'HF2_PACK_MEMBERSHIP_IMMUTABLE'); END;

CREATE TRIGGER trg_hf2_membership_no_late_insert
BEFORE INSERT ON content_pack_record_membership
WHEN EXISTS(SELECT 1 FROM project_content_locks l WHERE l.pack_hash=NEW.pack_hash)
BEGIN SELECT RAISE(ABORT,'HF2_PACK_MEMBERSHIP_IMMUTABLE'); END;

CREATE TRIGGER trg_hf2_membership_no_update
BEFORE UPDATE ON content_pack_record_membership
BEGIN SELECT RAISE(ABORT,'HF2_PACK_MEMBERSHIP_IMMUTABLE'); END;

CREATE TRIGGER trg_hf2_r2_committed_receipt_no_delete
BEFORE DELETE ON stage2_commit_receipts
WHEN NOT EXISTS(SELECT 1 FROM project_permanent_delete_authorizations a
                WHERE a.table_name='stage2_commit_receipts' AND a.row_id=OLD.rowid)
AND (OLD.status='committed')
BEGIN SELECT RAISE(ABORT,'HF2_COMMIT_RECEIPT_IMMUTABLE'); END;

CREATE TRIGGER trg_hf2_r2_committed_receipt_no_update
BEFORE UPDATE ON stage2_commit_receipts
WHEN OLD.status='committed'
BEGIN SELECT RAISE(ABORT,'HF2_COMMIT_RECEIPT_IMMUTABLE'); END;

CREATE TRIGGER trg_hf2_r4_committed_event_no_delete
BEFORE DELETE ON events
WHEN NOT EXISTS(SELECT 1 FROM project_permanent_delete_authorizations a
                WHERE a.table_name='events' AND a.row_id=OLD.rowid)
AND (EXISTS(SELECT 1 FROM stage2_commit_receipts r, json_each(r.event_ids_json) j WHERE r.status='committed' AND r.project_id=OLD.project_id AND j.value=OLD.event_id))
BEGIN SELECT RAISE(ABORT,'HF2_COMMITTED_EVENT_IMMUTABLE'); END;

CREATE TRIGGER trg_hf2_r4_committed_event_no_update
BEFORE UPDATE ON events
WHEN EXISTS(
    SELECT 1 FROM stage2_commit_receipts r, json_each(r.event_ids_json) j
    WHERE r.status='committed' AND r.project_id=OLD.project_id AND j.value=OLD.event_id
)
BEGIN SELECT RAISE(ABORT,'HF2_COMMITTED_EVENT_IMMUTABLE'); END;

CREATE TRIGGER trg_hf2_r4_project_stream_no_rewrite
BEFORE UPDATE OF project_json,revision ON projects
WHEN EXISTS(SELECT 1 FROM stage2_commit_receipts r WHERE r.status='committed' AND r.project_id=OLD.project_id)
 AND (
   CAST(json_extract(NEW.project_json,'$.event_stream.count') AS INTEGER) < CAST(json_extract(OLD.project_json,'$.event_stream.count') AS INTEGER)
   OR (
      CAST(json_extract(NEW.project_json,'$.event_stream.count') AS INTEGER)=CAST(json_extract(OLD.project_json,'$.event_stream.count') AS INTEGER)
      AND COALESCE(json_extract(NEW.project_json,'$.event_stream.head_hash'),'')<>COALESCE(json_extract(OLD.project_json,'$.event_stream.head_hash'),'')
   )
 )
BEGIN SELECT RAISE(ABORT,'HF2_COMMITTED_PROJECT_STREAM_IMMUTABLE'); END;

CREATE TRIGGER trg_hf2_uninstalled_membership_no_delete
BEFORE DELETE ON uninstalled_content_pack_record_membership
BEGIN SELECT RAISE(ABORT,'HF2_PACK_MEMBERSHIP_IMMUTABLE'); END;

CREATE TRIGGER trg_hf2_uninstalled_membership_no_update
BEFORE UPDATE ON uninstalled_content_pack_record_membership
BEGIN SELECT RAISE(ABORT,'HF2_PACK_MEMBERSHIP_IMMUTABLE'); END;

CREATE TRIGGER trg_hf2_uninstalled_receipt_no_delete
BEFORE DELETE ON uninstalled_content_pack_receipts
BEGIN SELECT RAISE(ABORT,'HF2_INSTALL_RECEIPT_IMMUTABLE'); END;

CREATE TRIGGER trg_hf2_uninstalled_receipt_no_update
BEFORE UPDATE ON uninstalled_content_pack_receipts
BEGIN SELECT RAISE(ABORT,'HF2_INSTALL_RECEIPT_IMMUTABLE'); END;

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

CREATE TRIGGER trg_project_locked_record_no_delete
INSTEAD OF DELETE ON project_locked_records
WHEN NOT EXISTS(
  SELECT 1 FROM character_builder_temporary_delete_authorizations a
  WHERE a.project_id = OLD.project_id
)
BEGIN
  SELECT RAISE(ABORT, 'HF2_PROJECT_LOCKED_RECORD_IMMUTABLE');
END;

CREATE TRIGGER trg_project_locked_record_no_update
INSTEAD OF UPDATE ON project_locked_records
BEGIN
  SELECT RAISE(ABORT, 'HF2_PROJECT_LOCKED_RECORD_IMMUTABLE');
END;
"""
