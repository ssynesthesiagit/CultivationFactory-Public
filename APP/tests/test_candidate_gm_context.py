"""Authenticated, provider-free staging context for later GM authoring."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import shutil
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from app.core import CORE_PACK_ID, FoundryError, canonical_json, sha256_bytes, sha256_json
import character_creation.service as creation_service
import character_creation.production_release as production_release
from character_creation.service import CharacterCreationExecutionService
from character_creation.compiler_selection_authority import ACCEPTED_CORE_PACK_HASHES_BY_VERSION
from contracts.canonical import ZERO_HASH, canonical_event_hash, canonical_record_hash
from character_creation.candidate_gm import CandidateGMCapsuleStore
from character_sheet.service import CharacterSheetService
from non_sphere_authority.foundation_mechanics import (
    FOUNDATION_MECHANICS_PACK_VERSION,
    INITIAL_FOUNDATION_MECHANICS_POLICY,
    verified_foundation_records,
)
from non_sphere_authority.service import NonSphereAuthorityService
from projector.v3_bridge import _dynamic_display_contract
from sphere_component_authority import normalize_sphere_automatic_components


PROJECT_ID = "project.gm-candidate"
RUN_ID = "cg1.run.gm-candidate"
LOCK_HASH = "c" * 64
APP_ROOT = Path(__file__).resolve().parents[1]


class _TestDB:
    def __init__(self, root: Path, *, security_dir: Path | None = None, authority_root: Path | None = None):
        data_dir = root / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        self.settings = SimpleNamespace(
            root_dir=authority_root or root,
            data_dir=data_dir,
            db_path=data_dir / "foundry.sqlite3",
            security_dir=security_dir or root / "security",
            factory_zip=None,
            fixture_path=None,
        )
        self.settings.security_dir.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.settings.db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    @contextmanager
    def transaction(self):
        with self.connection() as connection:
            yield connection


class _Stage2Verifier:
    def _verify_terminal_receipt(self, conn, row):
        return json.loads(row["terminal_projection_json"])

    def _verify_rebuild_receipt(self, conn, row):
        return json.loads(row["rebuild_projection_json"])


def _create_schema(db: _TestDB) -> None:
    with db.connection() as conn:
        conn.executescript(
            """
            CREATE TABLE projects(
                project_id TEXT PRIMARY KEY,
                revision INTEGER NOT NULL,
                project_json TEXT NOT NULL,
                canonical_project_hash TEXT NOT NULL
            );
            CREATE TABLE character_creation_runs(
                run_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                starting_revision INTEGER NOT NULL,
                request_json TEXT NOT NULL,
                response_json TEXT NOT NULL,
                execution_mode TEXT NOT NULL DEFAULT 'MANUAL_CHAT',
                idempotency_key TEXT NOT NULL DEFAULT 'fixture',
                transport_json TEXT NOT NULL DEFAULT '{}',
                validation_json TEXT NOT NULL DEFAULT '{}',
                dry_run_json TEXT NOT NULL DEFAULT '{}',
                final_plan_json TEXT NOT NULL DEFAULT '{}',
                owner_descriptive_fields_json TEXT NOT NULL DEFAULT '{}',
                accepted_descriptive_fields_json TEXT NOT NULL DEFAULT '{}',
                quality_json TEXT NOT NULL DEFAULT '{}',
                owner_decision TEXT,
                commit_json TEXT NOT NULL DEFAULT '{}',
                final_revision INTEGER,
                output_json TEXT NOT NULL DEFAULT '{}',
                blockers_json TEXT NOT NULL DEFAULT '[]',
                warnings_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'NEEDS_REVIEW',
                created_at TEXT NOT NULL DEFAULT 'fixture',
                updated_at TEXT NOT NULL DEFAULT 'fixture',
                completed_at TEXT
            );
            CREATE TABLE character_creation_attempt_history(
                attempt_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                action_type TEXT NOT NULL,
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
                completed_at TEXT
            );
            CREATE TABLE project_content_locks(
                project_id TEXT NOT NULL,
                pack_id TEXT NOT NULL,
                version TEXT NOT NULL,
                pack_hash TEXT NOT NULL,
                record_set_hash TEXT NOT NULL,
                payload_files_hash TEXT NOT NULL,
                install_receipt_hash TEXT NOT NULL,
                membership_snapshot_hash TEXT NOT NULL,
                locked_at TEXT NOT NULL
            );
            CREATE TABLE project_locked_records(
                project_id TEXT NOT NULL,
                record_id TEXT NOT NULL,
                pack_id TEXT NOT NULL,
                pack_version TEXT NOT NULL,
                record_hash TEXT NOT NULL,
                record_json TEXT NOT NULL
            );
            CREATE TABLE events(
                project_id TEXT NOT NULL,
                sequence_no INTEGER NOT NULL,
                event_id TEXT NOT NULL,
                event_hash TEXT NOT NULL,
                previous_event_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                event_json TEXT NOT NULL,
                canonical_schema_version TEXT,
                contract_status TEXT
            );
            CREATE TABLE projection_runs(
                projection_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                project_revision INTEGER NOT NULL,
                status TEXT NOT NULL,
                event_head_hash TEXT NOT NULL,
                content_lock_hash TEXT NOT NULL
            );
            CREATE TABLE projection_artifacts(
                projection_id TEXT NOT NULL,
                artifact_name TEXT NOT NULL,
                path TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                bytes INTEGER NOT NULL,
                media_type TEXT NOT NULL
            );
            CREATE TABLE stage2_commit_receipts(
                commit_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                status TEXT NOT NULL,
                final_revision INTEGER,
                event_ids_json TEXT NOT NULL,
                event_hashes_json TEXT NOT NULL,
                terminal_projection_json TEXT NOT NULL,
                terminal_projection_hash TEXT NOT NULL,
                terminal_mechanical_state_hash TEXT NOT NULL,
                integrity_version TEXT NOT NULL,
                integrity_key_id TEXT NOT NULL,
                integrity_domain TEXT NOT NULL,
                integrity_mac TEXT NOT NULL,
                completed_at TEXT NOT NULL
            );
            """
        )


def _project(revision: int, *, event_count: int = 0, event_head: str = ZERO_HASH) -> dict:
    return {
        "schema_version": "TianxiaFoundry.CharacterProject.v3",
        "project_id": PROJECT_ID,
        "revision": revision,
        "name": "Candidate context fixture",
        "content_lock": {"lock_hash": LOCK_HASH, "packs": []},
        "event_stream": {"count": event_count, "head_hash": event_head},
        "user_locks": [],
    }


def _record() -> tuple[dict, str, str]:
    base = {
        "record_id": "PATH-1",
        "content_type": "path",
        "name": "Fixture Path",
        "source_hash": "s" * 64,
    }
    record_hash = canonical_record_hash(base)
    record = {**base, "record_hash": record_hash}
    return record, record_hash, canonical_json(record)


def _automatic_component_source() -> tuple[dict, str, str, dict, dict]:
    component_id = "ATHLETICS_BASE_ATHLETIC_TRAINING"
    parent_id = "tianxia.sphere.athletics"
    parent_source = {
        "path": "09_RULES/Source_Text/Tianxia_Sphere_Compendium_Latest_R0I_85Spheres.md",
        "anchor": "line:4251:column:1",
        "source_hash": "a" * 64,
    }
    component_row = {
        "candidate_record_id": component_id,
        "runtime_component_id": component_id,
        "source_row_id": component_id,
        "display_name": "Athletic Training",
        "player_rules_text": (
            "#### Athletic Training\nWhen you learn the Athletics sphere, "
            "gain proficiency in Strength (Athletics) or Dexterity (Acrobatics)."
        ),
        "source_component_structured_fields": {},
        "record_commitment_sha256": "b" * 64,
        "source_matrix_provenance": {
            "source_path": parent_source["path"],
            "source_anchor": "Sphere of Athletics:lines:4255-4258:athletic_training",
            "source_file_sha256": parent_source["source_hash"],
            "source_authority_sha256": "c" * 64,
            "source_matrix_record_commitment_sha256": "d" * 64,
        },
    }
    parent_base = {
        "record_id": parent_id,
        "content_type": "sphere",
        "display_name": "Athletics",
        "source": parent_source,
        "compatibility": {
            "factory": {
                "raw_projection": {
                    "raw_record": {
                        "resolved_automatic_base_abilities": [component_row],
                    },
                },
            },
        },
    }
    parent_hash = canonical_record_hash(parent_base)
    parent = {**parent_base, "record_hash": parent_hash}
    packet = normalize_sphere_automatic_components(parent)
    component = next(row for row in packet["components"] if row["component_id"] == component_id)
    card = {
        "record_id": component_id,
        "record_hash": component["component_hash"],
        "display_name": component["display_name"],
        "section": "sphere_automatic_components",
        "source": {
            "path": component["source"]["source_path"],
            "anchor": component["source"]["source_anchor"],
            "sha256": component["source"]["source_file_sha256"],
        },
        "parent_sphere_id": parent_id,
        "component_hash": component["component_hash"],
        "automatic_component_flags": {
            key: component[key]
            for key in (
                "automatic_grant",
                "owner_removable",
                "counts_as_talent_choice",
                "counts_as_advancement_talent",
                "counts_as_training_talent",
            )
        },
        "automatic_component_authority": {
            "schema_version": packet["schema_version"],
            "parent_sphere_id": parent_id,
            "package_hash": packet["package_hash"],
            "component_ids": [component_id],
        },
    }
    return parent, parent_hash, canonical_json(parent), packet, card


def _sheet_with_selected_card(fixture, card: dict) -> dict:
    sheet = deepcopy(fixture.sheet)
    owner_sheet = deepcopy(sheet["owner_character_sheet"])
    owner_sheet["selected_record_sections"]["sphere_automatic_components"] = [deepcopy(card)]
    payload = (canonical_json(owner_sheet) + "\n").encode("utf-8")
    artifact_path = Path(sheet["sheet_artifact"]["path"])
    artifact_path.write_bytes(payload)
    sheet["owner_character_sheet"] = owner_sheet
    sheet["sheet_artifact"] = {
        **sheet["sheet_artifact"],
        "sha256": sha256_bytes(payload),
        "bytes": len(payload),
    }
    return sheet


def _method_card_and_records(project: dict) -> tuple[dict, dict, dict]:
    """Build the current projector-shaped Method card from authenticated authority."""
    authority_db = SimpleNamespace(settings=SimpleNamespace(root_dir=APP_ROOT))
    authority = NonSphereAuthorityService(authority_db)
    method = authority.project_locked_method_catalog_record("METHOD-083", mechanical=True)
    packet = {
        "packet_id": "packet.method.gm-candidate",
        "record_id": method["record_id"],
        "advancement_kind": "method_acquisition",
        "target_cl": 1,
        "event_id": "event.method.gm-candidate",
    }
    contract = _dynamic_display_contract(
        project,
        {"snapshot_sha256": "s" * 64},
        {method["record_id"]: method},
        [packet],
        [],
        None,
    )
    cards, _ = CharacterSheetService._build_record_cards(
        {"method": {"state": "acquired", "record_id": method["record_id"]}},
        {"packets": [packet]},
        contract,
        sha256_json(contract),
    )
    card = next(row for row in cards if row["record_id"] == method["record_id"])
    legacy = authority.project_locked_method_catalog_record("METHOD-083")
    return card, legacy, method


def _core_legacy_method_record(method_id: str, pack_version: str) -> dict:
    """Build a public, source-shaped legacy core Method snapshot fixture."""
    authority_db = SimpleNamespace(settings=SimpleNamespace(root_dir=APP_ROOT))
    authority = NonSphereAuthorityService(authority_db)
    method = authority.methods[method_id]
    source_text = method["source_text"]
    raw_method = {
        "id": method_id,
        "number": method["number"],
        "name": method["name"],
        "type": source_text["type"],
        "common_users": source_text["common_users"],
        "compatible_themes": source_text["compatible_themes"],
        "resource_shape": source_text["resource_shape"],
        "resource_shape_key": source_text["resource_shape_key"],
        "breakthrough_shape": source_text["breakthrough_shape"],
        "breakthrough_shape_key": source_text["breakthrough_shape_key"],
        "foundation_shape": source_text["foundation_shape"],
        "foundation_shape_key": source_text["foundation_shape_key"],
        "use_as": source_text["use_as"],
        "source_file": "09_RULES/Indexes/Cultivation_Methods_AI_Index_v0_1.json",
    }
    record = {
        "record_id": method_id,
        "content_type": "cultivation_method",
        "display_name": method["name"],
        "content_binding": {
            "pack_id": CORE_PACK_ID,
            "pack_version": pack_version,
            "pack_hash": ACCEPTED_CORE_PACK_HASHES_BY_VERSION[pack_version],
        },
        "source": {
            "path": "09_RULES/Indexes/Cultivation_Methods_AI_Index_v0_1.json",
            "anchor": f"record:{method_id}",
            "source_hash": "a" * 64,
        },
        "compatibility": {"factory": {"raw_projection": {"raw_record": raw_method}}},
    }
    return {**record, "record_hash": canonical_record_hash(record)}


def _sheet_with_method_card(fixture, card: dict) -> dict:
    sheet = deepcopy(fixture.sheet)
    owner_sheet = deepcopy(sheet["owner_character_sheet"])
    owner_sheet["selected_record_sections"].setdefault("other", []).append(deepcopy(card))
    payload = (canonical_json(owner_sheet) + "\n").encode("utf-8")
    artifact_path = Path(sheet["sheet_artifact"]["path"])
    artifact_path.write_bytes(payload)
    sheet["owner_character_sheet"] = owner_sheet
    sheet["sheet_artifact"] = {
        **sheet["sheet_artifact"],
        "sha256": sha256_bytes(payload),
        "bytes": len(payload),
    }
    return sheet


def _core_legacy_foundation_record(
    foundation_id: str = "ash_born_remnant_core_v0_2B",
    pack_version: str = "2.9.5",
) -> dict:
    """Build a source-shaped Foundation snapshot without private run data."""
    source = deepcopy(verified_foundation_records()[foundation_id])
    base = {
        "record_id": foundation_id,
        "content_type": "foundation",
        "display_name": source["display_name"],
        "summary": source["summary"],
        "content_binding": {
            "pack_id": CORE_PACK_ID,
            "pack_version": pack_version,
            "pack_hash": ACCEPTED_CORE_PACK_HASHES_BY_VERSION[pack_version],
        },
        "source": deepcopy(source["source"]),
        "compatibility": {
            "factory": {
                "raw_projection": {"raw_record": source},
            },
        },
    }
    return {**base, "record_hash": canonical_record_hash(base)}


def _origin_insight_record() -> dict:
    """Build a schema-valid source-backed Origin Insight fixture."""
    base = {
        "schema_version": "TianxiaFoundry.RulesCatalogRecord.v1",
        "record_id": "tianxia.origin_insight.fixture_origin",
        "content_type": "origin_insight",
        "display_name": "Fixture Origin Insight",
        "publication": {
            "status": "published",
            "published_version": "1.0.0",
            "replaced_by": None,
        },
        "content_binding": {
            "pack_id": "pack.fixture",
            "pack_version": "1.0.0",
            "pack_hash": "a" * 64,
        },
        "source": {
            "source_id": "fixture.origin_insight",
            "source_hash": "a" * 64,
            "anchor": "fixture:origin-insight",
            "path": "fixture/origin-insight.json",
        },
        "summary": "A source-backed fixture Origin Insight.",
        "legality": {
            "acquisition_channels": ["origin-insight-selection"],
            "prerequisites": [],
            "incompatibilities": [],
            "minimum_cl": None,
            "realm_rules": {},
            "source_cl": {},
            "suppression": {},
        },
        "grants": [],
        "execution_templates": [],
        "display_projection": {
            "short_description": "A source-backed fixture Origin Insight.",
            "full_description": "A source-backed fixture Origin Insight.",
            "surfaces": ["rules_catalog"],
            "sort_key": "fixture origin insight",
        },
        "compatibility": {
            "factory": {"raw_projection": {}},
            "gm_screen": {},
        },
        "revision_history": [
            {"version": "1.0.0", "summary": "Fixture source."},
        ],
        "regression_tests": [
            {"test_id": "fixture.origin_insight.provenance", "kind": "fixture", "expected": {}},
        ],
    }
    return {**base, "record_hash": canonical_record_hash(base)}


def _background_record() -> dict:
    """Build a schema-valid source-backed Background fixture.

    The record ID must be a real Background so the typed non-Sphere authority
    can project its Stage-2 packages; the descriptive content is fixture text.
    """
    base = {
        "schema_version": "TianxiaFoundry.RulesCatalogRecord.v1",
        "record_id": "tianxia.background.military_brat",
        "content_type": "background",
        "display_name": "Fixture Background",
        "publication": {
            "status": "published",
            "published_version": "1.0.0",
            "replaced_by": None,
        },
        "content_binding": {
            "pack_id": "pack.fixture",
            "pack_version": "1.0.0",
            "pack_hash": "a" * 64,
        },
        "source": {
            "source_id": "fixture.background",
            "source_hash": "a" * 64,
            "anchor": "fixture:background",
            "path": "fixture/background.json",
        },
        "summary": "A source-backed fixture Background.",
        "legality": {
            "acquisition_channels": ["background-selection"],
            "prerequisites": [],
            "incompatibilities": [],
            "minimum_cl": None,
            "realm_rules": {},
            "source_cl": {},
            "suppression": {},
        },
        "grants": [],
        "execution_templates": [],
        "display_projection": {
            "short_description": "A source-backed fixture Background.",
            "full_description": "A source-backed fixture Background.",
            "surfaces": ["rules_catalog"],
            "sort_key": "fixture background",
        },
        "compatibility": {
            "factory": {"raw_projection": {}},
            "gm_screen": {},
        },
        "revision_history": [
            {"version": "1.0.0", "summary": "Fixture source."},
        ],
        "regression_tests": [
            {"test_id": "fixture.background.provenance", "kind": "fixture", "expected": {}},
        ],
    }
    return {**base, "record_hash": canonical_record_hash(base)}


def _background_card_and_records(candidate_context) -> tuple[dict, dict, dict]:
    raw = _background_record()
    with candidate_context.scratch.connection() as conn:
        conn.execute(
            "UPDATE project_content_locks SET pack_hash=? WHERE project_id=? AND pack_id=?",
            ("a" * 64, PROJECT_ID, "pack.fixture"),
        )
        conn.execute(
            "INSERT INTO project_locked_records VALUES(?,?,?,?,?,?)",
            (
                PROJECT_ID,
                raw["record_id"],
                raw["content_binding"]["pack_id"],
                raw["content_binding"]["pack_version"],
                raw["record_hash"],
                canonical_json(raw),
            ),
        )
    store = object.__new__(CandidateGMCapsuleStore)
    resolved, identity = CandidateGMCapsuleStore._resolve_background_projection_snapshot(
        store,
        candidate_context.scratch,
        project_id=PROJECT_ID,
        record_id=raw["record_id"],
        raw_record=raw,
        row_pack_id=raw["content_binding"]["pack_id"],
        row_pack_version=raw["content_binding"]["pack_version"],
        row_pack_hash=raw["content_binding"]["pack_hash"],
        sealed_record_hash=raw["record_hash"],
    )
    assert identity["project_locked_record_hash"] == raw["record_hash"]
    card = {
        "record_id": raw["record_id"],
        "record_hash": resolved["record_hash"],
        "display_name": resolved["display_name"],
        "section": "background_origin",
        "content_type": "background",
        "source": deepcopy(resolved["source"]),
    }
    return card, raw, resolved


def _origin_card_and_records(candidate_context) -> tuple[dict, dict, dict]:
    raw = _origin_insight_record()
    with candidate_context.scratch.connection() as conn:
        # The production lock is a hexadecimal pack digest; keep this fixture
        # schema-valid while leaving the ordinary PATH fixture untouched.
        conn.execute(
            "UPDATE project_content_locks SET pack_hash=? WHERE project_id=? AND pack_id=?",
            ("a" * 64, PROJECT_ID, "pack.fixture"),
        )
        raw["content_binding"]["pack_hash"] = "a" * 64
        raw["record_hash"] = canonical_record_hash(
            {key: value for key, value in raw.items() if key != "record_hash"}
        )
        conn.execute(
            "INSERT INTO project_locked_records VALUES(?,?,?,?,?,?)",
            (
                PROJECT_ID,
                raw["record_id"],
                raw["content_binding"]["pack_id"],
                raw["content_binding"]["pack_version"],
                raw["record_hash"],
                canonical_json(raw),
            ),
        )
    resolved, identity = CandidateGMCapsuleStore._resolve_origin_insight_snapshot(
        candidate_context.scratch,
        project_id=PROJECT_ID,
        record_id=raw["record_id"],
        raw_record=raw,
        row_pack_id=raw["content_binding"]["pack_id"],
        row_pack_version=raw["content_binding"]["pack_version"],
        row_pack_hash=raw["content_binding"]["pack_hash"],
        sealed_record_hash=raw["record_hash"],
    )
    card = {
        "record_id": raw["record_id"],
        "record_hash": resolved["record_hash"],
        "display_name": resolved["display_name"],
        "section": "background_origin",
        "content_type": "origin_insight",
        "source": deepcopy(resolved["source"]),
    }
    return card, raw, resolved


def _sheet_with_origin_card(fixture, card: dict) -> dict:
    sheet = deepcopy(fixture.sheet)
    owner_sheet = deepcopy(sheet["owner_character_sheet"])
    owner_sheet["selected_record_sections"].setdefault("background_origin", []).append(deepcopy(card))
    payload = (canonical_json(owner_sheet) + "\n").encode("utf-8")
    artifact_path = Path(sheet["sheet_artifact"]["path"])
    artifact_path.write_bytes(payload)
    sheet["owner_character_sheet"] = owner_sheet
    sheet["sheet_artifact"] = {
        **sheet["sheet_artifact"],
        "sha256": sha256_bytes(payload),
        "bytes": len(payload),
    }
    return sheet


def _foundation_card_and_records(candidate_context) -> tuple[dict, dict, dict]:
    """Build a projector-shaped mechanics card and its locked Core source."""
    foundation_id = "ash_born_remnant_core_v0_2B"
    raw = _core_legacy_foundation_record(foundation_id)
    resolved, _identity = CandidateGMCapsuleStore._resolve_versioned_foundation_snapshot(
        candidate_context.scratch,
        record_id=foundation_id,
        raw_record=raw,
        row_pack_id=CORE_PACK_ID,
        row_pack_version="2.9.5",
        row_pack_hash=ACCEPTED_CORE_PACK_HASHES_BY_VERSION["2.9.5"],
        foundation_version=FOUNDATION_MECHANICS_PACK_VERSION,
        sealed_record_hash=raw["record_hash"],
    )
    packet = {
        "packet_id": "packet.foundation.gm-candidate",
        "record_id": foundation_id,
        "advancement_kind": "foundation_acquisition",
        "target_cl": 5,
        "event_id": "event.foundation.gm-candidate",
    }
    contract = _dynamic_display_contract(
        _project(8),
        {"snapshot_sha256": "s" * 64},
        {foundation_id: resolved},
        [packet],
        [],
        None,
    )
    cards, _ = CharacterSheetService._build_record_cards(
        {"foundation": {"state": "acquired", "record_id": foundation_id}},
        {"packets": [packet]},
        contract,
        sha256_json(contract),
    )
    return next(row for row in cards if row["record_id"] == foundation_id), raw, resolved


def _fixture_project_lock_proof(db, project_id: str) -> dict:
    """Return the exact snapshot hash used by the test-only proof injection."""
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT record_id,pack_id,pack_version,record_hash,record_json "
            "FROM project_locked_records WHERE project_id=? ORDER BY record_id",
            (project_id,),
        ).fetchall()
    snapshot = [
        {
            "record_id": row["record_id"],
            "record_hash": row["record_hash"],
            "pack_id": row["pack_id"],
            "pack_version": row["pack_version"],
        }
        for row in rows
    ]
    return {
        "record_snapshot_hash": sha256_json(snapshot),
        "sealed_member_records": [dict(row) for row in rows],
        "authorized_extra_records": [],
    }


def _path_family_fixture_records(record_id: str, content_type: str) -> tuple[dict, dict]:
    """Build raw lock bytes plus a distinct authenticated projected card."""
    raw_base = {
        "record_id": record_id,
        "content_type": content_type,
        "display_name": f"Raw {record_id}",
        "content_binding": {
            "pack_id": "pack.fixture",
            "pack_version": "1.0.0",
            "pack_hash": "a" * 64,
        },
        "source": {"path": "fixture/path-family", "anchor": record_id, "source_hash": "s" * 64},
        "compatibility": {"factory": {"raw_projection": {}}},
    }
    raw = {**raw_base, "record_hash": canonical_record_hash(raw_base)}
    authority_db = SimpleNamespace(settings=SimpleNamespace(root_dir=APP_ROOT))
    authority = NonSphereAuthorityService(authority_db)
    projected_base = {
        "record_id": record_id,
        "content_type": content_type,
        "display_name": f"Projected {record_id}",
        "pack_id": "tianxia.non_sphere.authority",
        "pack_version": "P2A",
        "content_binding": {
            "pack_id": "tianxia.non_sphere.authority",
            "pack_version": "P2A",
            "pack_hash": authority.authority_snapshot_hash,
        },
        "source": {"path": "authority/path-family", "anchor": record_id, "source_hash": "a" * 64},
        "compatibility": {"factory": {"stage2_authority": {"authority_complete": True}}},
    }
    projected = {**projected_base, "record_hash": canonical_record_hash(projected_base)}
    return raw, projected


def _sheet_with_card_section(fixture, card: dict, section: str = "other") -> dict:
    sheet = deepcopy(fixture.sheet)
    owner_sheet = deepcopy(sheet["owner_character_sheet"])
    owner_sheet["selected_record_sections"].setdefault(section, []).append(deepcopy(card))
    payload = (canonical_json(owner_sheet) + "\n").encode("utf-8")
    artifact_path = Path(sheet["sheet_artifact"]["path"])
    artifact_path.write_bytes(payload)
    sheet["owner_character_sheet"] = owner_sheet
    sheet["sheet_artifact"] = {
        **sheet["sheet_artifact"],
        "sha256": sha256_bytes(payload),
        "bytes": len(payload),
    }
    return sheet


def _insert_path_family_fixture(candidate_context, raw: dict, projected: dict) -> dict:
    with candidate_context.scratch.connection() as conn:
        conn.execute(
            "UPDATE project_content_locks SET pack_hash=? WHERE project_id=? AND pack_id=?",
            ("a" * 64, PROJECT_ID, "pack.fixture"),
        )
    with candidate_context.scratch.connection() as conn:
        conn.execute(
            "INSERT INTO project_locked_records VALUES(?,?,?,?,?,?)",
            (
                PROJECT_ID,
                raw["record_id"],
                raw["content_binding"]["pack_id"],
                raw["content_binding"]["pack_version"],
                raw["record_hash"],
                canonical_json(raw),
            ),
        )
    card = {
        "record_id": projected["record_id"],
        "record_hash": projected["record_hash"],
        "display_name": projected["display_name"],
        "content_type": projected["content_type"],
        "section": "other",
    }
    return card


def test_project_lock_snapshot_preserves_sealed_member_order_and_rejects_changed_extra():
    sealed = {
        "record_id": "z-sealed-member",
        "pack_id": CORE_PACK_ID,
        "pack_version": "2.9.5",
        "record_hash": "s" * 64,
        "record_json": canonical_json({"record_id": "z-sealed-member", "value": "sealed"}),
    }
    extra = {
        "record_id": "a-authorized-extra",
        "pack_id": "tianxia.non_sphere.authority",
        "pack_version": "P2A",
        "record_hash": "e" * 64,
        "record_json": canonical_json({"record_id": "a-authorized-extra", "value": "extra"}),
    }
    rows = [sealed, extra]
    ordered = [sealed, extra]
    proof_rows = [
        {
            "record_id": row["record_id"],
            "record_hash": row["record_hash"],
            "pack_id": row["pack_id"],
            "pack_version": row["pack_version"],
        }
        for row in ordered
    ]
    proof = {
        "record_snapshot_hash": sha256_json(proof_rows),
        "sealed_member_records": [sealed],
        "authorized_extra_records": [extra],
    }

    CandidateGMCapsuleStore._assert_project_lock_snapshot(
        proof,
        rows,
        project_id="project.lock-order-fixture",
    )

    changed_extra = deepcopy(extra)
    changed_extra["record_json"] = canonical_json({"record_id": extra["record_id"], "value": "changed"})
    with pytest.raises(FoundryError) as caught:
        CandidateGMCapsuleStore._assert_project_lock_snapshot(
            proof,
            [sealed, changed_extra],
            project_id="project.lock-order-fixture",
        )
    assert caught.value.code == "CG1_GM_CANDIDATE_SOURCE_INVALID"


def _sheet_with_foundation_card(fixture, card: dict) -> dict:
    sheet = deepcopy(fixture.sheet)
    owner_sheet = deepcopy(sheet["owner_character_sheet"])
    owner_sheet["selected_record_sections"].setdefault("other", []).append(deepcopy(card))
    payload = (canonical_json(owner_sheet) + "\n").encode("utf-8")
    artifact_path = Path(sheet["sheet_artifact"]["path"])
    artifact_path.write_bytes(payload)
    sheet["owner_character_sheet"] = owner_sheet
    sheet["sheet_artifact"] = {
        **sheet["sheet_artifact"],
        "sha256": sha256_bytes(payload),
        "bytes": len(payload),
    }
    return sheet


@pytest.fixture
def candidate_context(tmp_path):
    root = _TestDB(tmp_path / "root", authority_root=APP_ROOT)
    scratch = _TestDB(tmp_path / "scratch", security_dir=root.settings.security_dir, authority_root=APP_ROOT)
    _create_schema(root)
    _create_schema(scratch)

    event = {
        "schema_version": "TianxiaFoundry.AdvancementEvent.v3",
        "project_id": PROJECT_ID,
        "sequence": 1,
        "event_id": "event.gm-candidate.1",
        "previous_event_hash": ZERO_HASH,
        "advancement": {"kind": "starting_state"},
    }
    event["event_hash"] = canonical_event_hash(event)
    event_json = canonical_json(event)

    root_project = _project(7)
    candidate_project = _project(8, event_count=1, event_head=event["event_hash"])
    with root.connection() as conn:
        conn.execute(
            "INSERT INTO projects VALUES(?,?,?,?)",
            (PROJECT_ID, 7, canonical_json(root_project), sha256_json(root_project)),
        )
        request = {
            "schema": "TianxiaFoundry.CharacterCreationPlanRequest.v3",
            "project_id": PROJECT_ID,
            "project_revision": 7,
            "content_lock_hash": LOCK_HASH,
            "policy": {"planner_prose_is_mechanical_authority": False},
        }
        request["request_sha256"] = CharacterCreationExecutionService.request_payload_sha256(request)
        response_text = canonical_json({
            "schema": "TianxiaFoundry.CharacterCreationPlanResponse.v3",
            "selection_intent": {"by_slot": {"path_choice": ["PATH-1"]}},
        })
        response_sha = sha256_bytes(response_text.encode("utf-8"))
        conn.execute(
            "INSERT INTO character_creation_runs(run_id,project_id,starting_revision,request_json,response_json) VALUES(?,?,?,?,?)",
            (
                RUN_ID,
                PROJECT_ID,
                7,
                canonical_json(request),
                canonical_json({"exact_response_text": response_text, "response_sha256": response_sha}),
            ),
        )

    record, record_hash, record_json = _record()
    projection_lock_hash = sha256_json(candidate_project["content_lock"])
    owner_sheet = {
        "schema_version": "TianxiaFoundry.OwnerCharacterSheet.v1",
        "sheet_id": "sheet.gm-candidate",
        "selected_record_sections": {
            "path_choice": [{
                "record_id": record["record_id"],
                "record_hash": record_hash,
                "name": record["name"],
                "source_hash": record["source_hash"],
            }],
        },
    }
    artifact_values = {
        "Character_Master_Ledger.json": {"schema": "ledger", "project_id": PROJECT_ID},
        "Rules_Selection_Packets.json": {"schema": "packets", "project_id": PROJECT_ID},
        "Projection_Provenance_Map.json": {"schema": "provenance", "project_id": PROJECT_ID},
        "Projection_Coverage_Report.json": {"schema": "coverage", "project_id": PROJECT_ID},
        "Projection_Diagnostics.json": {"schema": "diagnostics", "project_id": PROJECT_ID, "valid": True},
    }
    projection_dir = (
        scratch.settings.data_dir / "projects" / PROJECT_ID / "projections" / "projection.gm-candidate" / "generated"
    )
    projection_dir.mkdir(parents=True, exist_ok=True)
    artifact_meta = []
    for name, value in artifact_values.items():
        payload = (canonical_json(value) + "\n").encode()
        path = projection_dir / name
        path.write_bytes(payload)
        artifact_meta.append({
            "artifact_name": name,
            "path": str(path),
            "sha256": sha256_bytes(payload),
            "bytes": len(payload),
            "media_type": "application/json",
        })

    sheet_path = scratch.settings.data_dir / "character_sheets" / PROJECT_ID / owner_sheet["sheet_id"] / "Owner_Character_Sheet.json"
    sheet_path.parent.mkdir(parents=True, exist_ok=True)
    sheet_bytes = (canonical_json(owner_sheet) + "\n").encode()
    sheet_path.write_bytes(sheet_bytes)
    sheet = {
        "build_status": "CHARACTER_SHEET_READY",
        "owner_character_sheet": owner_sheet,
        "sheet_artifact": {
            "sheet_id": owner_sheet["sheet_id"],
            "path": str(sheet_path),
            "sha256": sha256_bytes(sheet_bytes),
            "bytes": len(sheet_bytes),
        },
    }
    owner_sheet["authority_and_artifact_identity"] = {
        "project_id": PROJECT_ID,
        "project_revision": 8,
        "projection_id": "projection.gm-candidate",
        "advancement_artifact_hashes": {row["artifact_name"]: row["sha256"] for row in artifact_meta},
    }
    # Rewrite the artifact after adding the authenticated identity, matching
    # the real sheet producer's exact bytes.
    sheet_bytes = (canonical_json(owner_sheet) + "\n").encode()
    sheet_path.write_bytes(sheet_bytes)
    sheet["sheet_artifact"].update(sha256=sha256_bytes(sheet_bytes), bytes=len(sheet_bytes))

    with scratch.connection() as conn:
        conn.execute(
            "INSERT INTO projects VALUES(?,?,?,?)",
            (PROJECT_ID, 8, canonical_json(candidate_project), sha256_json(candidate_project)),
        )
        conn.execute(
            "INSERT INTO project_content_locks VALUES(?,?,?,?,?,?,?,?,?)",
            (PROJECT_ID, "pack.fixture", "1.0.0", "p" * 64, "r" * 64, "f" * 64, "i" * 64, "m" * 64, "fixture"),
        )
        conn.execute(
            "INSERT INTO project_locked_records VALUES(?,?,?,?,?,?)",
            (PROJECT_ID, record["record_id"], "pack.fixture", "1.0.0", record_hash, record_json),
        )
        conn.execute(
            "INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?)",
            (PROJECT_ID, 1, event["event_id"], event["event_hash"], ZERO_HASH, "fixture", event_json, event["schema_version"], "valid"),
        )
        conn.execute(
            "INSERT INTO projection_runs VALUES(?,?,?,?,?,?)",
            ("projection.gm-candidate", PROJECT_ID, 8, "READY", event["event_hash"], projection_lock_hash),
        )
        conn.executemany(
            "INSERT INTO projection_artifacts VALUES(?,?,?,?,?,?)",
            [("projection.gm-candidate", row["artifact_name"], row["path"], row["sha256"], row["bytes"], row["media_type"]) for row in artifact_meta],
        )
        terminal_projection = {
            "commit_id": "commit.gm-candidate",
            "event_chain_head": event["event_hash"],
            "event_count": 1,
            "final_revision": 8,
        }
        conn.execute(
            "INSERT INTO stage2_commit_receipts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "commit.gm-candidate", PROJECT_ID, "committed", 8,
                canonical_json([event["event_id"]]), canonical_json([event["event_hash"]]),
                canonical_json(terminal_projection), sha256_json(terminal_projection), "m" * 64,
                "TianxiaFoundry.KeyedIntegrity.v1", "fixture-key", "tianxia.foundry.stage2.terminal_commit.v1", "x" * 64, "fixture",
            ),
        )

    run = {
        "run_id": RUN_ID,
        "project_id": PROJECT_ID,
        "starting_revision": 7,
        "created_at": "2026-09-08T00:00:00+00:00",
        "request": request,
        "response": {"exact_response_text": response_text, "response_sha256": response_sha},
    }
    projection = {
        "project_id": PROJECT_ID,
        "projection_id": "projection.gm-candidate",
        "project_revision": 8,
        "status": "READY",
        "eligible_for_command5": True,
        "event_head_hash": event["event_hash"],
        "content_lock_hash": projection_lock_hash,
        "artifacts": artifact_meta,
    }
    final_plan = {"schema": "TianxiaFoundry.CharacterCreationFinalPlan.v1", "final_plan_sha256": "plan"}
    stage2_commit = {"receipt": {"commit_id": "commit.gm-candidate"}}
    return SimpleNamespace(
        root=root,
        scratch=scratch,
        run=run,
        sheet=sheet,
        projection=projection,
        stage2_commit=stage2_commit,
        final_plan=final_plan,
        stage2=_Stage2Verifier(),
        record_hash=record_hash,
    )


def _capture(fixture, *, final_plan=None, sheet=None, factory_authoring=None):
    store = CandidateGMCapsuleStore(fixture.root)
    return store, store.capture(
        run=fixture.run,
        root_db=fixture.root,
        scratch_db=fixture.scratch,
        scratch_root=fixture.scratch.settings.data_dir.parent,
        sheet=fixture.sheet if sheet is None else sheet,
        projection=fixture.projection,
        stage2_validation={"valid": True},
        stage2_commit=fixture.stage2_commit,
        stage2_service=fixture.stage2,
        final_plan=fixture.final_plan if final_plan is None else final_plan,
        factory_authoring=factory_authoring,
    )


def _synthetic_factory_workspace(
    base: Path,
    *,
    project_id: str,
    project_revision: int,
    projection_id: str,
    event_head_hash: str = "e" * 64,
    candidate_sha256: str | None = None,
) -> tuple[Path, dict]:
    """Create a small public-safe sealed Command 1--4 workspace fixture."""
    workspace = Path(base) / "factory-workspace"
    workspace.mkdir(parents=True, exist_ok=False)
    values = {
        "Command_1/Character_Blueprint.json": {
            "schema": "TianxiaFoundry.Command1CharacterBlueprint.v1",
            "identity": {"display_name": "Synthetic Candidate", "role": "Path", "realm": "Mortal"},
        },
        "Command_2/Canonical_Stats_Resource_Block.json": {
            "schema": "TianxiaFoundry.Command2CanonicalStatsResourceBlock.v1",
            "resources": [{"resource_id": "tianxia.resource.stamina", "name": "Stamina", "current": 10, "maximum": 10}],
            "available_states": [],
        },
        "Command_4/Complete_Action_Surface.json": {
            "schema": "TianxiaFoundry.Command4CompleteActionSurface.v1",
            "status": "ACTION_SURFACE_READY",
            "execution_authority": True,
            "actions": [
                {
                    "action_id": "action.synthetic.one",
                    "record_id": "record.synthetic.one",
                    "name": "Synthetic One",
                    "economy": "action",
                    "action_type": "action",
                    "timing": "Current turn",
                    "cost": "None",
                    "range": "self",
                    "target": "one target",
                    "roll_save_check": "none",
                    "effect": "Descriptive effect one",
                    "failure": "No effect",
                    "duration": "one turn",
                    "limit": "one use",
                    "counterplay": "ordinary counterplay",
                    "resource_costs": [],
                    "resource_gains": [],
                    "resource_requirements": [],
                    "requires_states": [],
                    "execution_authority": True,
                    "executable": True,
                },
                {
                    "action_id": "action.synthetic.two",
                    "record_id": "record.synthetic.two",
                    "name": "Synthetic Two",
                    "economy": "bonus_action",
                    "action_type": "bonus_action",
                    "timing": "Current turn",
                    "cost": "None",
                    "range": "self",
                    "target": "one target",
                    "roll_save_check": "none",
                    "effect": "Descriptive effect two",
                    "failure": "No effect",
                    "duration": "one turn",
                    "limit": "one use",
                    "counterplay": "ordinary counterplay",
                    "resource_costs": [],
                    "resource_gains": [],
                    "resource_requirements": [],
                    "requires_states": [],
                    "execution_authority": True,
                    "executable": True,
                },
            ],
        },
    }
    manifest = {
        "schema_version": "TianxiaFoundry.FactoryCommand1To4Workspace.v1",
        "workspace_status": "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE",
        "project_id": project_id,
        "project_revision": project_revision,
        "projection_id": projection_id,
        "event_head_hash": event_head_hash,
        "identity": {"display_name": "Synthetic Candidate", "role": "Path", "realm": "Mortal"},
    }
    if candidate_sha256 is not None:
        manifest["candidate_sha256"] = candidate_sha256
    values["Workspace_Manifest.json"] = manifest
    for relative, value in values.items():
        path = workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(canonical_json(value), encoding="utf-8")
    hashes = {
        path.relative_to(workspace).as_posix(): sha256_bytes(path.read_bytes())
        for path in sorted(workspace.rglob("*"))
        if path.is_file()
    }
    (workspace / "SHA256SUMS.txt").write_text(
        "".join(f"{hashes[name]}  {name}\n" for name in sorted(hashes)),
        encoding="utf-8",
    )
    hashes["SHA256SUMS.txt"] = sha256_bytes((workspace / "SHA256SUMS.txt").read_bytes())
    factory = {
        "workspace_status": "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE",
        "project_id": project_id,
        "project_revision": project_revision,
        "workspace_path": str(workspace),
        "workspace_sha256": sha256_json(hashes),
        "manifest_sha256": hashes["Workspace_Manifest.json"],
        "artifact_hashes": hashes,
    }
    return workspace, factory


def _capture_with_factory(fixture, *, final_plan=None, sheet=None):
    _workspace, factory = _synthetic_factory_workspace(
        fixture.scratch.settings.data_dir.parent,
        project_id=fixture.run["project_id"],
        project_revision=fixture.projection["project_revision"],
        projection_id=fixture.projection["projection_id"],
        event_head_hash=fixture.projection["event_head_hash"],
    )
    return _capture(
        fixture,
        final_plan=final_plan,
        sheet=sheet,
        factory_authoring=factory,
    )


def _synthetic_composite_provider_result(kwargs: dict, *, settings: dict) -> dict:
    """Return a valid closed-choice response for the synthetic workspace."""
    from factory_authoring.composite_controller import _canonical_wire_bytes

    prompt = json.loads(kwargs["prompt_text"])
    constants = prompt["response_constants"]
    actions = prompt["actions"]
    if isinstance(actions, dict):
        actions = [dict(zip(actions["columns"], row)) for row in actions["rows"]]
    tokens = constants["action_tokens"]
    assert len(tokens) >= 2
    expected = sha256_bytes(
        _canonical_wire_bytes(
            kwargs["prompt_text"],
            kwargs["system_message"],
            settings,
            kwargs["response_schema"],
        )
    )
    assert kwargs["expected_request_sha256"] == expected
    wire_payload = json.loads(_canonical_wire_bytes(
        kwargs["prompt_text"], kwargs["system_message"], settings, kwargs["response_schema"],
    ))
    assert min(settings["max_output_tokens"], kwargs["response_schema_max_output_tokens"]) == wire_payload["max_tokens"]
    theme_sources = prompt.get("descriptive_theme_sources", {})
    theme_ids = [row[0] for row in theme_sources.get("rows", []) if isinstance(row[0], str)]
    if not theme_ids:
        theme_ids = [
            action.get("record_id")
            for action in actions
            if isinstance(action, dict) and isinstance(action.get("record_id"), str)
        ]

    def synthetic_theme(kind: str) -> dict:
        return {
            "display_name": f"Synthetic {kind} theme",
            "core_theme": "A source-bound descriptive fixture theme.",
            "principles": ["Preserve the source meaning.", "Keep description separate from mechanics."],
            "strengths": ["The source is explicit.", "The controller remains authoritative."],
            "risks": ["Narrative can be overread.", "Unselected records remain outside scope."],
            "roleplay_expression": "Use the source context for descriptive play.",
            "tactical_expression": "Resolve all actions through the sealed controller.",
            "gm_usage_notes": "This fixture theme grants no mechanic or effect.",
            "relevant_record_ids": theme_ids,
            "mechanical_effects": [],
        }
    value = {
        "schema": constants["schema"],
        "project_id": constants["project_id"],
        "projection_id": constants["projection_id"],
        "candidate_sha256": constants["candidate_sha256"],
        "request_sha256": constants["request_sha256"],
        "composite_controller": {
            "composite_id": "composite_controller",
            "name": "Synthetic controller",
            "execution_role": "composite_controller",
            "when_to_use": ["when both sealed fixture options are available"],
            "do_not_use_when": ["when a sealed prerequisite is absent"],
            "resource_budget": {"resource_id": "RES_CP", "max_spend": 0},
            "temporal_feasibility": {"same_turn_legal": True, "round_span": 0, "notes": ["Synthetic current-turn plan"]},
            "fallback": {"action_token": tokens[0], "reason": "Use the first zero-resource fixture option."},
            "dao_hook": "Synthetic source reference",
            "i_ching_hook": "Synthetic source reference",
            "sequence": [
                {
                    "step": 1,
                    "action_token": tokens[0],
                    "round_offset": 0,
                    "economy": actions[0]["economy"],
                    "requires_states": [],
                    "external_preconditions": [],
                },
                {
                    "step": 2,
                    "action_token": tokens[1],
                    "round_offset": 0,
                    "economy": actions[1]["economy"],
                    "requires_states": [],
                    "external_preconditions": [],
                },
            ],
            "conditional_options": [],
        },
        "gm_themes": {
            "dao": synthetic_theme("Dao"),
            "i_ching": synthetic_theme("I Ching"),
        },
    }
    raw = canonical_json(value)
    return {
        "provider_id": settings["provider_id"],
        "purpose": "factory_composite_controller",
        "model": settings["model"],
        "request_sha256": expected,
        "response_sha256": sha256_bytes(raw.encode("utf-8")),
        "completion_sha256": sha256_bytes(raw.encode("utf-8")),
        "response_text": raw,
        "finish_reason": "stop",
        "value": deepcopy(value),
    }


def _configure_prefix_and_stage2_batch(fixture) -> dict[str, dict]:
    """Turn the fixture into a prefix-plus-terminal-Stage-2 event stream."""
    with fixture.scratch.connection() as conn:
        row = conn.execute(
            "SELECT event_json,event_hash FROM events WHERE project_id=? AND sequence_no=1",
            (PROJECT_ID,),
        ).fetchone()
        prefix = json.loads(row["event_json"])
        batch = deepcopy(prefix)
        batch.pop("event_hash", None)
        batch["sequence"] = 2
        batch["event_id"] = "event.gm-candidate.stage2"
        batch["previous_event_hash"] = prefix["event_hash"]
        batch["advancement"] = {"kind": "stage2_batch"}
        batch["event_hash"] = canonical_event_hash(batch)
        conn.execute(
            "INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?)",
            (
                PROJECT_ID,
                2,
                batch["event_id"],
                batch["event_hash"],
                prefix["event_hash"],
                "fixture",
                canonical_json(batch),
                batch["schema_version"],
                "valid",
            ),
        )
        project_row = conn.execute(
            "SELECT project_json FROM projects WHERE project_id=?",
            (PROJECT_ID,),
        ).fetchone()
        project = json.loads(project_row["project_json"])
        project["revision"] = 9
        project["event_stream"] = {"count": 2, "head_hash": batch["event_hash"]}
        conn.execute(
            "UPDATE projects SET revision=?,project_json=?,canonical_project_hash=? WHERE project_id=?",
            (9, canonical_json(project), sha256_json(project), PROJECT_ID),
        )
        conn.execute(
            "UPDATE projection_runs SET project_revision=?,event_head_hash=? WHERE project_id=?",
            (9, batch["event_hash"], PROJECT_ID),
        )
        terminal_projection = {
            "commit_id": "commit.gm-candidate",
            "event_chain_head": batch["event_hash"],
            "event_count": 2,
            "final_revision": 9,
        }
        conn.execute(
            """UPDATE stage2_commit_receipts
               SET final_revision=?,event_ids_json=?,event_hashes_json=?,
                   terminal_projection_json=?,terminal_projection_hash=?
               WHERE commit_id=?""",
            (
                9,
                canonical_json([batch["event_id"]]),
                canonical_json([batch["event_hash"]]),
                canonical_json(terminal_projection),
                sha256_json(terminal_projection),
                "commit.gm-candidate",
            ),
        )

    fixture.projection["project_revision"] = 9
    fixture.projection["event_head_hash"] = batch["event_hash"]
    owner_sheet = deepcopy(fixture.sheet["owner_character_sheet"])
    owner_sheet["authority_and_artifact_identity"]["project_revision"] = 9
    sheet_path = Path(fixture.sheet["sheet_artifact"]["path"])
    payload = (canonical_json(owner_sheet) + "\n").encode()
    sheet_path.write_bytes(payload)
    fixture.sheet["owner_character_sheet"] = owner_sheet
    fixture.sheet["sheet_artifact"].update(
        sha256=sha256_bytes(payload),
        bytes=len(payload),
    )
    return {"prefix": prefix, "batch": batch}


def _set_terminal_event_set(fixture, event_ids: list[str], event_hashes: list[str], *, final_revision: int | None = None, projection_updates: dict | None = None) -> None:
    with fixture.scratch.connection() as conn:
        row = conn.execute(
            "SELECT terminal_projection_json,final_revision FROM stage2_commit_receipts WHERE commit_id=?",
            ("commit.gm-candidate",),
        ).fetchone()
        projection = json.loads(row["terminal_projection_json"])
        if projection_updates:
            projection.update(projection_updates)
        revision = row["final_revision"] if final_revision is None else final_revision
        if final_revision is not None:
            projection["final_revision"] = final_revision
        conn.execute(
            """UPDATE stage2_commit_receipts
               SET final_revision=?,event_ids_json=?,event_hashes_json=?,
                   terminal_projection_json=?,terminal_projection_hash=?
               WHERE commit_id=?""",
            (
                revision,
                canonical_json(event_ids),
                canonical_json(event_hashes),
                canonical_json(projection),
                sha256_json(projection),
                "commit.gm-candidate",
            ),
        )


def _install_matching_rebuild_receipt(fixture, *, event_head: str, project_revision: int, terminal_commit_id: str = "commit.gm-candidate") -> None:
    with fixture.scratch.connection() as conn:
        terminal_projection_hash = conn.execute(
            "SELECT terminal_projection_hash FROM stage2_commit_receipts WHERE commit_id=?",
            ("commit.gm-candidate",),
        ).fetchone()[0]
    projection = {
        "project_id": PROJECT_ID,
        "project_revision": project_revision,
        "event_chain_head": event_head,
        "terminal_commit_id": terminal_commit_id,
        "terminal_projection_hash": terminal_projection_hash,
    }
    with fixture.scratch.connection() as conn:
        conn.execute(
            """CREATE TABLE stage2_rebuild_receipts(
                rebuild_receipt_id TEXT,
                project_id TEXT,
                project_revision INTEGER,
                event_chain_head TEXT,
                terminal_commit_id TEXT,
                terminal_projection_hash TEXT,
                rebuild_projection_json TEXT,
                created_at TEXT
            )""",
        )
        conn.execute(
            "INSERT INTO stage2_rebuild_receipts VALUES(?,?,?,?,?,?,?,?)",
            (
                "rebuild.gm-candidate",
                PROJECT_ID,
                project_revision,
                event_head,
                terminal_commit_id,
                terminal_projection_hash,
                canonical_json(projection),
                "fixture",
            ),
        )


def _capsule_path(store: CandidateGMCapsuleStore, summary: dict) -> Path:
    run_key = hashlib.sha256(RUN_ID.encode()).hexdigest()[:32]
    return store.root / "runs" / run_key / "capsules" / summary["capsule_id"]


def _response_path(store: CandidateGMCapsuleStore, summary: dict) -> Path:
    return _capsule_path(store, summary) / "response" / "exact_response_bytes"


def _retained_response_run(fixture) -> tuple[dict, str]:
    """Build a compact run projection whose latest leaf owns the response."""
    run = deepcopy(fixture.run)
    response_text = run["response"]["exact_response_text"]
    response_sha = run["response"]["response_sha256"]
    request_sha = run["request"]["request_sha256"]
    root_attempt = {
        "attempt_id": "cg1.attempt.request-created",
        "run_id": RUN_ID,
        "project_id": PROJECT_ID,
        "ordinal": 1,
        "action_type": "REQUEST_CREATED",
        "status": "PREPARING_REQUEST",
        "request_sha256": request_sha,
        "response_sha256": None,
        "response_text": None,
        "response_byte_count": None,
        "response_bytes_sha256": None,
        "prior_attempt_id": None,
        "binding": {"request_sha256": request_sha},
    }
    leaf_attempt = {
        "attempt_id": "cg1.attempt.response-leaf",
        "run_id": RUN_ID,
        "project_id": PROJECT_ID,
        "ordinal": 2,
        "action_type": "DCC_LINEAR_WALK",
        "status": "BLOCKED",
        "request_sha256": request_sha,
        "response_sha256": response_sha,
        "response_text": response_text,
        "response_byte_count": len(response_text.encode("utf-8")),
        "response_bytes_sha256": response_sha,
        "prior_attempt_id": root_attempt["attempt_id"],
        "binding": {
            "active_request_sha256": request_sha,
            "submitted_request_sha256": None,
            "transport": {"provider_called": True, "purpose": "dcc_linear_step"},
        },
    }
    run["response"] = {"response_sha256": response_sha}
    run["attempt_history"] = [root_attempt, leaf_attempt]
    return run, response_text


def test_capture_load_and_same_context_are_immutable(candidate_context):
    store, summary = _capture(candidate_context)
    capsule = _capsule_path(store, summary)
    before = {path.relative_to(capsule).as_posix(): path.read_bytes() for path in capsule.rglob("*") if path.is_file()}
    repeated_store, repeated = _capture(candidate_context)
    after = {path.relative_to(capsule).as_posix(): path.read_bytes() for path in capsule.rglob("*") if path.is_file()}

    assert repeated_store is not None
    assert repeated["capsule_id"] == summary["capsule_id"]
    assert before == after
    loaded = store.load(RUN_ID)
    assert loaded["context"]["status"] == "CANDIDATE_CONTEXT_CAPTURED"
    assert loaded["selected_record_source"]["selected_record_content_sha256"]
    assert loaded["projection_artifacts"]["Character_Master_Ledger.json"]["schema"] == "ledger"


def test_capture_accepts_authenticated_prefix_and_terminal_stage2_suffix(candidate_context):
    stream = _configure_prefix_and_stage2_batch(candidate_context)

    store, _summary = _capture(candidate_context)

    loaded = store.load(RUN_ID)
    assert loaded["context"]["mechanics"]["event_count"] == 2
    assert loaded["context"]["mechanics"]["event_head_hash"] == stream["batch"]["event_hash"]


def test_capture_rejects_ambiguous_terminal_receipt_order(candidate_context):
    with candidate_context.scratch.connection() as conn:
        original = conn.execute(
            "SELECT * FROM stage2_commit_receipts WHERE commit_id=?",
            ("commit.gm-candidate",),
        ).fetchone()
        values = list(original)
        values[0] = "commit.gm-candidate.ambiguous"
        conn.execute(
            "INSERT INTO stage2_commit_receipts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            values,
        )

    with pytest.raises(FoundryError) as caught:
        _capture(candidate_context)

    assert caught.value.code == "CG1_GM_CANDIDATE_RECEIPT_INVALID"
    assert caught.value.details["receipt_count"] == 2


@pytest.mark.parametrize(
    ("event_ids", "event_hashes"),
    [
        pytest.param(
            lambda stream: [stream["prefix"]["event_id"]],
            lambda stream: [stream["prefix"]["event_hash"]],
            id="prefix-only",
        ),
        pytest.param(
            lambda stream: [stream["batch"]["event_id"], stream["prefix"]["event_id"]],
            lambda stream: [stream["batch"]["event_hash"], stream["prefix"]["event_hash"]],
            id="reversed-order",
        ),
        pytest.param(
            lambda stream: [stream["batch"]["event_id"], stream["batch"]["event_id"]],
            lambda stream: [stream["batch"]["event_hash"], stream["batch"]["event_hash"]],
            id="duplicate-event",
        ),
        pytest.param(
            lambda stream: [stream["batch"]["event_id"]],
            lambda stream: ["0" * 64],
            id="tampered-hash",
        ),
    ],
)
def test_capture_rejects_nonterminal_or_tampered_terminal_event_sets(
    candidate_context,
    event_ids,
    event_hashes,
):
    stream = _configure_prefix_and_stage2_batch(candidate_context)
    _set_terminal_event_set(candidate_context, event_ids(stream), event_hashes(stream))

    with pytest.raises(FoundryError) as caught:
        _capture(candidate_context)

    assert caught.value.code == "CG1_GM_CANDIDATE_RECEIPT_INVALID"
    assert caught.value.details["candidate_event_count"] == 2
    assert caught.value.details["candidate_event_head"] == stream["batch"]["event_hash"]


@pytest.mark.parametrize(
    ("projection_updates", "final_revision"),
    [
        pytest.param({"event_count": 1}, None, id="partial-event-count"),
        pytest.param({"event_chain_head": "0" * 64}, None, id="wrong-event-head"),
        pytest.param({}, 8, id="stale-final-revision"),
    ],
)
def test_capture_rejects_terminal_projection_not_bound_to_full_candidate_state(
    candidate_context,
    projection_updates,
    final_revision,
):
    stream = _configure_prefix_and_stage2_batch(candidate_context)
    _set_terminal_event_set(
        candidate_context,
        [stream["batch"]["event_id"]],
        [stream["batch"]["event_hash"]],
        final_revision=final_revision,
        projection_updates=projection_updates,
    )

    with pytest.raises(FoundryError) as caught:
        _capture(candidate_context)

    assert caught.value.code == "CG1_GM_CANDIDATE_RECEIPT_INVALID"
    details = caught.value.details
    assert details["candidate_event_count"] == 2
    assert details["candidate_event_head"] == stream["batch"]["event_hash"]
    assert details["candidate_project_revision"] == 9


def test_capture_binds_matching_rebuild_receipt_to_terminal_projection(candidate_context):
    stream = _configure_prefix_and_stage2_batch(candidate_context)
    _install_matching_rebuild_receipt(
        candidate_context,
        event_head=stream["batch"]["event_hash"],
        project_revision=9,
    )

    store, summary = _capture(candidate_context)

    loaded = store.load(RUN_ID)
    assert loaded["context"]["mechanics"]["rebuild_receipt_id"] == "rebuild.gm-candidate"
    assert summary["capsule_id"] == loaded["summary"]["capsule_id"]


@pytest.mark.parametrize(
    ("event_head", "project_revision", "terminal_commit_id"),
    [
        pytest.param("0" * 64, 9, "commit.gm-candidate", id="wrong-rebuild-head"),
        pytest.param("event-head", 8, "commit.gm-candidate", id="wrong-rebuild-revision"),
        pytest.param("event-head", 9, "other-commit", id="wrong-rebuild-terminal"),
    ],
)
def test_capture_rejects_rebuild_receipt_not_bound_to_terminal_state(
    candidate_context,
    event_head,
    project_revision,
    terminal_commit_id,
):
    stream = _configure_prefix_and_stage2_batch(candidate_context)
    _install_matching_rebuild_receipt(
        candidate_context,
        event_head=stream["batch"]["event_hash"] if event_head == "event-head" else event_head,
        project_revision=project_revision,
        terminal_commit_id=terminal_commit_id,
    )

    with pytest.raises(FoundryError) as caught:
        _capture(candidate_context)

    assert caught.value.code == "CG1_GM_CANDIDATE_RECEIPT_INVALID"
    assert caught.value.details["candidate_project_revision"] == 9


def test_capture_binds_locked_sphere_automatic_component_and_rejects_unbound_variants(candidate_context):
    parent, parent_hash, parent_json, packet, card = _automatic_component_source()
    ordinary_collision_base = {
        "record_id": card["record_id"],
        "content_type": "talent",
        "display_name": "Ordinary catalog collision",
        "source": {"path": "fixture", "anchor": "collision", "source_hash": "z" * 64},
    }
    ordinary_collision_hash = canonical_record_hash(ordinary_collision_base)
    ordinary_collision = {**ordinary_collision_base, "record_hash": ordinary_collision_hash}
    with candidate_context.scratch.connection() as conn:
        project_row = conn.execute(
            "SELECT project_json FROM projects WHERE project_id=?",
            (PROJECT_ID,),
        ).fetchone()
        projection_lock_hash = sha256_json(json.loads(project_row["project_json"])["content_lock"])
        conn.execute(
            "UPDATE projection_runs SET content_lock_hash=? WHERE projection_id=?",
            (projection_lock_hash, candidate_context.projection["projection_id"]),
        )
        conn.execute(
            "INSERT INTO project_locked_records VALUES(?,?,?,?,?,?)",
            (PROJECT_ID, parent["record_id"], "pack.fixture", "1.0.0", parent_hash, parent_json),
        )
        # The automatic component deliberately shares an ID with an ordinary
        # locked row.  Structural component routing must win over this
        # namespace collision; matching an arbitrary direct-row hash is not
        # an authority decision.
        conn.execute(
            "INSERT INTO project_locked_records VALUES(?,?,?,?,?,?)",
            (PROJECT_ID, ordinary_collision["record_id"], "pack.fixture", "1.0.0", ordinary_collision_hash, canonical_json(ordinary_collision)),
        )
    candidate_context.projection["content_lock_hash"] = projection_lock_hash

    sheet = _sheet_with_selected_card(candidate_context, card)
    store, summary = _capture(candidate_context, sheet=sheet)
    loaded = store.load(RUN_ID)
    source_rows = {
        row["record_id"]: row
        for row in loaded["selected_record_source"]["locked_records"]
    }
    component_source = source_rows[card["record_id"]]
    assert component_source["binding_kind"] == "locked_sphere_automatic_component"
    assert component_source["parent_record_id"] == parent["record_id"]
    assert component_source["parent_record_hash"] == parent_hash
    assert component_source["automatic_component_package_hash"] == packet["package_hash"]
    assert component_source["record_hash"] == card["component_hash"]
    assert loaded["context"]["source"]["record_ids"] == sorted(["PATH-1", card["record_id"]])
    assert summary["capsule_id"] == loaded["summary"]["capsule_id"]

    variants = []
    absent = deepcopy(card)
    absent["record_id"] = "ATHLETICS_BASE_UNAUTHENTICATED"
    absent["component_hash"] = "e" * 64
    absent["record_hash"] = "e" * 64
    absent["automatic_component_authority"]["component_ids"] = [absent["record_id"]]
    variants.append(absent)
    missing_binding = deepcopy(card)
    missing_binding.pop("parent_sphere_id")
    variants.append(missing_binding)
    unbound = deepcopy(card)
    unbound["automatic_component_authority"]["package_hash"] = "0" * 64
    variants.append(unbound)

    for invalid in variants:
        with pytest.raises(FoundryError) as caught:
            _capture(candidate_context, sheet=_sheet_with_selected_card(candidate_context, invalid))
        assert caught.value.code == "CG1_GM_CANDIDATE_SOURCE_INVALID"

    altered = deepcopy(card)
    altered["record_hash"] = "f" * 64
    with pytest.raises(FoundryError) as caught:
        _capture(candidate_context, sheet=_sheet_with_selected_card(candidate_context, altered))
    assert caught.value.code == "CG1_GM_CANDIDATE_SOURCE_INVALID"
    assert caught.value.details["observed_card_hash"] == "f" * 64
    assert caught.value.details["expected_source_hash"] == card["component_hash"]
    assert caught.value.details["locked_source_identity"] == {
        "binding_kind": "locked_sphere_automatic_component",
        "pack_id": "pack.fixture",
        "pack_version": "1.0.0",
        "parent_record_id": parent["record_id"],
        "parent_record_hash": parent_hash,
        "automatic_component_package_hash": packet["package_hash"],
    }

    mismatched_parent_base = deepcopy(parent)
    mismatched_parent_base.pop("record_id")
    mismatched_parent_base.pop("record_hash")
    mismatched_parent_base["canonical_sphere_id"] = "tianxia.sphere.mismatched"
    mismatched_parent_hash = canonical_record_hash(mismatched_parent_base)
    mismatched_parent = {**mismatched_parent_base, "record_hash": mismatched_parent_hash}
    mismatched_packet = normalize_sphere_automatic_components(mismatched_parent)
    mismatched_component = next(
        row
        for row in mismatched_packet["components"]
        if row["component_id"] == card["record_id"]
    )
    mismatched_card = deepcopy(card)
    mismatched_card["record_hash"] = mismatched_component["component_hash"]
    mismatched_card["component_hash"] = mismatched_component["component_hash"]
    mismatched_card["automatic_component_authority"]["package_hash"] = mismatched_packet["package_hash"]
    with candidate_context.scratch.connection() as conn:
        conn.execute(
            "UPDATE project_locked_records SET record_hash=?,record_json=? WHERE project_id=? AND record_id=?",
            (mismatched_parent_hash, canonical_json(mismatched_parent), PROJECT_ID, parent["record_id"]),
        )
    with pytest.raises(FoundryError) as caught:
        _capture(candidate_context, sheet=_sheet_with_selected_card(candidate_context, mismatched_card))
    assert caught.value.code == "CG1_GM_CANDIDATE_SOURCE_INVALID"


def test_capture_reports_observed_and_expected_hash_for_ordinary_card_mismatch(candidate_context):
    sheet = deepcopy(candidate_context.sheet)
    card = sheet["owner_character_sheet"]["selected_record_sections"]["path_choice"][0]
    card["record_hash"] = "f" * 64
    payload = (canonical_json(sheet["owner_character_sheet"]) + "\n").encode("utf-8")
    artifact_path = Path(sheet["sheet_artifact"]["path"])
    artifact_path.write_bytes(payload)
    sheet["sheet_artifact"] = {
        **sheet["sheet_artifact"],
        "sha256": sha256_bytes(payload),
        "bytes": len(payload),
    }

    with pytest.raises(FoundryError) as caught:
        _capture(candidate_context, sheet=sheet)

    assert caught.value.code == "CG1_GM_CANDIDATE_SOURCE_INVALID"
    details = caught.value.details
    assert details["record_id"] == "PATH-1"
    assert details["observed_card_hash"] == "f" * 64
    assert details["expected_source_hash"] == candidate_context.record_hash
    assert details["locked_source_identity"]["binding_kind"] == "project_locked_record"
    assert details["locked_source_identity"]["pack_id"] == "pack.fixture"


@pytest.mark.parametrize(
    ("record_id", "content_type"),
    [
        ("tianxia.path.fixture_body", "path"),
        ("tianxia.path.fixture_body.feature.synthetic", "path_feature"),
        ("tianxia.subpath.fixture_body.synthetic", "subpath"),
    ],
)
def test_capture_binds_path_family_cards_to_proof_bound_projection(
    candidate_context,
    monkeypatch,
    record_id,
    content_type,
):
    raw, projected = _path_family_fixture_records(record_id, content_type)
    card = _insert_path_family_fixture(candidate_context, raw, projected)
    proof = _fixture_project_lock_proof(candidate_context.scratch, PROJECT_ID)
    monkeypatch.setattr(
        CandidateGMCapsuleStore,
        "_project_lock_proof",
        staticmethod(lambda _db, _project_id: deepcopy(proof)),
    )

    def resolve(_store, _conn, _project_id, requested_id, **_kwargs):
        assert requested_id == record_id
        return deepcopy(projected)

    from project_store.service import ProjectStore

    monkeypatch.setattr(ProjectStore, "_resolve_locked_record_after_proof", resolve)
    store, summary = _capture(
        candidate_context,
        sheet=_sheet_with_card_section(candidate_context, card),
    )
    source = {
        row["record_id"]: row
        for row in store.load(RUN_ID)["selected_record_source"]["locked_records"]
    }[record_id]
    assert source["record_hash"] == projected["record_hash"]
    assert source["record_json"] == canonical_json(projected)
    assert source["pack_id"] == "tianxia.non_sphere.authority"
    assert source["project_locked_pack_id"] == "pack.fixture"
    assert source["project_locked_pack_version"] == "1.0.0"
    assert source["project_locked_pack_hash"] == "a" * 64
    assert source["project_locked_record_hash"] == raw["record_hash"]
    assert summary["capsule_id"]


def test_path_family_rejects_rehashed_raw_row_outside_sealed_membership(
    candidate_context,
    monkeypatch,
):
    raw, projected = _path_family_fixture_records("tianxia.path.fixture_tamper", "path")
    card = _insert_path_family_fixture(candidate_context, raw, projected)
    proof = _fixture_project_lock_proof(candidate_context.scratch, PROJECT_ID)
    monkeypatch.setattr(
        CandidateGMCapsuleStore,
        "_project_lock_proof",
        staticmethod(lambda _db, _project_id: deepcopy(proof)),
    )
    tampered_base = {**raw, "display_name": "Rehashed but unsealed"}
    tampered = {**tampered_base, "record_hash": canonical_record_hash(tampered_base)}
    with candidate_context.scratch.connection() as conn:
        conn.execute(
            "UPDATE project_locked_records SET record_hash=?,record_json=? "
            "WHERE project_id=? AND record_id=?",
            (tampered["record_hash"], canonical_json(tampered), PROJECT_ID, raw["record_id"]),
        )
    from project_store.service import ProjectStore

    monkeypatch.setattr(
        ProjectStore,
        "_resolve_locked_record_after_proof",
        lambda *_args, **_kwargs: deepcopy(projected),
    )
    with pytest.raises(FoundryError) as caught:
        _capture(candidate_context, sheet=_sheet_with_card_section(candidate_context, card))
    assert caught.value.code == "CG1_GM_CANDIDATE_SOURCE_INVALID"
    assert caught.value.details.get("project_id") == PROJECT_ID or caught.value.details.get("record_id") == raw["record_id"]


def test_path_family_rejects_derived_card_hash_tamper(candidate_context, monkeypatch):
    raw, projected = _path_family_fixture_records("tianxia.path.fixture_card_tamper", "path")
    card = _insert_path_family_fixture(candidate_context, raw, projected)
    card["record_hash"] = "f" * 64
    proof = _fixture_project_lock_proof(candidate_context.scratch, PROJECT_ID)
    monkeypatch.setattr(
        CandidateGMCapsuleStore,
        "_project_lock_proof",
        staticmethod(lambda _db, _project_id: deepcopy(proof)),
    )
    from project_store.service import ProjectStore

    monkeypatch.setattr(
        ProjectStore,
        "_resolve_locked_record_after_proof",
        lambda *_args, **_kwargs: deepcopy(projected),
    )
    with pytest.raises(FoundryError) as caught:
        _capture(candidate_context, sheet=_sheet_with_card_section(candidate_context, card))
    assert caught.value.code == "CG1_GM_CANDIDATE_SOURCE_INVALID"
    assert caught.value.details["observed_card_hash"] == "f" * 64
    assert caught.value.details["expected_source_hash"] == projected["record_hash"]


def test_path_family_rejects_pack_mismatched_projection(candidate_context, monkeypatch):
    raw, projected = _path_family_fixture_records("tianxia.path.fixture_pack_mismatch", "path")
    card = _insert_path_family_fixture(candidate_context, raw, projected)
    wrong_projection = deepcopy(projected)
    wrong_projection["content_binding"]["pack_id"] = "pack.wrong"
    wrong_projection["record_hash"] = canonical_record_hash(
        {key: value for key, value in wrong_projection.items() if key != "record_hash"}
    )
    proof = _fixture_project_lock_proof(candidate_context.scratch, PROJECT_ID)
    monkeypatch.setattr(
        CandidateGMCapsuleStore,
        "_project_lock_proof",
        staticmethod(lambda _db, _project_id: deepcopy(proof)),
    )
    from project_store.service import ProjectStore

    monkeypatch.setattr(
        ProjectStore,
        "_resolve_locked_record_after_proof",
        lambda *_args, **_kwargs: deepcopy(wrong_projection),
    )
    with pytest.raises(FoundryError) as caught:
        _capture(candidate_context, sheet=_sheet_with_card_section(candidate_context, card))
    assert caught.value.code == "CG1_GM_CANDIDATE_SOURCE_INVALID"


def test_path_namespace_rejects_non_path_source_type(candidate_context, monkeypatch):
    raw, projected = _path_family_fixture_records("tianxia.path.fixture_wrong_type", "path")
    raw_base = {**raw, "content_type": "talent"}
    raw = {**raw_base, "record_hash": canonical_record_hash(raw_base)}
    card = _insert_path_family_fixture(candidate_context, raw, projected)
    proof = _fixture_project_lock_proof(candidate_context.scratch, PROJECT_ID)
    monkeypatch.setattr(
        CandidateGMCapsuleStore,
        "_project_lock_proof",
        staticmethod(lambda _db, _project_id: deepcopy(proof)),
    )
    with pytest.raises(FoundryError) as caught:
        _capture(candidate_context, sheet=_sheet_with_card_section(candidate_context, card))
    assert caught.value.code == "CG1_GM_CANDIDATE_SOURCE_INVALID"


def test_background_alias_remains_an_ordinary_locked_card(candidate_context):
    base = {
        "record_id": "tianxia.background_sphere.scoundrel",
        "content_type": "sphere",
        "display_name": "Scoundrel sphere alias",
        "source": {"path": "fixture/background", "anchor": "alias", "source_hash": "s" * 64},
    }
    raw = {**base, "record_hash": canonical_record_hash(base)}
    with candidate_context.scratch.connection() as conn:
        conn.execute(
            "INSERT INTO project_locked_records VALUES(?,?,?,?,?,?)",
            (PROJECT_ID, raw["record_id"], "pack.fixture", "1.0.0", raw["record_hash"], canonical_json(raw)),
        )
    card = {"record_id": raw["record_id"], "record_hash": raw["record_hash"], "section": "background_origin"}
    store, _summary = _capture(candidate_context, sheet=_sheet_with_card_section(candidate_context, card, "background_origin"))
    source = next(
        row
        for row in store.load(RUN_ID)["selected_record_source"]["locked_records"]
        if row["record_id"] == raw["record_id"]
    )
    assert source["record_hash"] == raw["record_hash"]
    assert source["record_json"] == canonical_json(raw)


def test_path_milestone_identifier_is_not_accepted_as_a_card(candidate_context):
    record_id = "tianxia.path.fixture_body.feature.synthetic.cl8"
    raw_base = {
        "record_id": record_id,
        "content_type": "path_feature",
        "display_name": "Planning milestone",
        "content_binding": {"pack_id": "pack.fixture", "pack_version": "1.0.0", "pack_hash": "p" * 64},
    }
    raw = {**raw_base, "record_hash": canonical_record_hash(raw_base)}
    with candidate_context.scratch.connection() as conn:
        conn.execute(
            "INSERT INTO project_locked_records VALUES(?,?,?,?,?,?)",
            (PROJECT_ID, record_id, "pack.fixture", "1.0.0", raw["record_hash"], canonical_json(raw)),
        )
    card = {"record_id": record_id, "record_hash": raw["record_hash"], "section": "other"}
    with pytest.raises(FoundryError) as caught:
        _capture(candidate_context, sheet=_sheet_with_card_section(candidate_context, card))
    assert caught.value.code == "CG1_GM_CANDIDATE_SOURCE_INVALID"
    assert caught.value.details["record_id"] == record_id


def test_capture_binds_versioned_method_card_to_candidate_source(candidate_context):
    """A mechanics-version card must resolve from the same frozen request authority."""
    card, legacy, mechanical = _method_card_and_records(_project(8))
    assert card["record_hash"] == mechanical["record_hash"]
    assert legacy["record_hash"] != mechanical["record_hash"]

    with candidate_context.root.connection() as conn:
        request_row = conn.execute(
            "SELECT request_json FROM character_creation_runs WHERE run_id=?",
            (RUN_ID,),
        ).fetchone()
        request = json.loads(request_row["request_json"])
        request["server_owned_authority"] = {
            "initial_method_mechanics_policy": {
                "schema": "TianxiaFoundry.InitialMethodMechanicsPolicy.v2",
                "selected_primary_method": "activate_after_acquisition",
                "resource_maximum": "source_typed_profiles",
                "refill_current": False,
                "record_version": "0.6.0-mechanics.1",
            },
        }
        request["request_sha256"] = CharacterCreationExecutionService.request_payload_sha256(request)
        conn.execute(
            "UPDATE character_creation_runs SET request_json=? WHERE run_id=?",
            (canonical_json(request), RUN_ID),
        )
    candidate_context.run["request"] = request
    candidate_context.sheet = _sheet_with_method_card(candidate_context, card)
    with candidate_context.scratch.connection() as conn:
        conn.execute(
            "INSERT INTO project_locked_records VALUES(?,?,?,?,?,?)",
            (
                PROJECT_ID,
                legacy["record_id"],
                legacy["content_binding"]["pack_id"],
                legacy["content_binding"]["pack_version"],
                legacy["record_hash"],
                canonical_json(legacy),
            ),
        )

    store, summary = _capture(candidate_context, sheet=candidate_context.sheet)
    loaded = store.load(RUN_ID)
    source_rows = {
        row["record_id"]: row
        for row in loaded["selected_record_source"]["locked_records"]
    }
    assert source_rows["METHOD-083"]["record_hash"] == mechanical["record_hash"]
    assert source_rows["METHOD-083"]["pack_version"] == mechanical["content_binding"]["pack_version"]
    assert source_rows["METHOD-083"]["project_locked_record_hash"] == legacy["record_hash"]
    assert source_rows["METHOD-083"]["project_locked_pack_version"] == legacy["content_binding"]["pack_version"]
    assert summary["capsule_id"] == loaded["summary"]["capsule_id"]


@pytest.mark.parametrize("method_id", ["METHOD-001", "METHOD-080"])
@pytest.mark.parametrize("pack_version", sorted(ACCEPTED_CORE_PACK_HASHES_BY_VERSION))
def test_versioned_core_method_snapshot_projects_each_accepted_release(
    candidate_context, method_id, pack_version
):
    raw = _core_legacy_method_record(method_id, pack_version)
    resolved, identity = CandidateGMCapsuleStore._resolve_versioned_method_snapshot(
        candidate_context.scratch,
        record_id=method_id,
        raw_record=raw,
        row_pack_id=CORE_PACK_ID,
        row_pack_version=pack_version,
        row_pack_hash=ACCEPTED_CORE_PACK_HASHES_BY_VERSION[pack_version],
        method_version="0.6.0-mechanics.1",
    )

    assert resolved["record_id"] == method_id
    assert resolved["content_binding"]["pack_id"] == "tianxia.non_sphere.authority"
    assert resolved["content_binding"]["pack_version"] == "0.6.0-mechanics.1"
    assert identity == {
        "project_locked_pack_id": CORE_PACK_ID,
        "project_locked_pack_version": pack_version,
        "project_locked_pack_hash": ACCEPTED_CORE_PACK_HASHES_BY_VERSION[pack_version],
        "project_locked_record_hash": raw["record_hash"],
        "project_locked_record_json_sha256": sha256_bytes(canonical_json(raw).encode("utf-8")),
    }


@pytest.mark.parametrize(
    "row_pack_id,row_pack_version,row_pack_hash",
    [
        ("pack.unknown", "2.9.5", ACCEPTED_CORE_PACK_HASHES_BY_VERSION["2.9.5"]),
        (CORE_PACK_ID, "9.9.9", "b" * 64),
        (CORE_PACK_ID, "2.9.5", "b" * 64),
    ],
    ids=["unknown-pack", "unknown-version", "wrong-pack-hash"],
)
def test_versioned_core_method_snapshot_rejects_unsupported_pack_binding(
    candidate_context, row_pack_id, row_pack_version, row_pack_hash
):
    raw = _core_legacy_method_record("METHOD-001", "2.9.5")
    with pytest.raises(FoundryError) as caught:
        CandidateGMCapsuleStore._resolve_versioned_method_snapshot(
            candidate_context.scratch,
            record_id="METHOD-001",
            raw_record=raw,
            row_pack_id=row_pack_id,
            row_pack_version=row_pack_version,
            row_pack_hash=row_pack_hash,
            method_version="0.6.0-mechanics.1",
        )
    assert caught.value.code == "CG1_GM_CANDIDATE_SOURCE_INVALID"


def test_versioned_core_method_snapshot_rejects_tampered_source(candidate_context):
    raw = _core_legacy_method_record("METHOD-001", "2.9.5")
    raw["compatibility"]["factory"]["raw_projection"]["raw_record"]["name"] = "tampered"
    raw["record_hash"] = canonical_record_hash({key: value for key, value in raw.items() if key != "record_hash"})
    with pytest.raises(FoundryError) as caught:
        CandidateGMCapsuleStore._resolve_versioned_method_snapshot(
            candidate_context.scratch,
            record_id="METHOD-001",
            raw_record=raw,
            row_pack_id=CORE_PACK_ID,
            row_pack_version="2.9.5",
            row_pack_hash=ACCEPTED_CORE_PACK_HASHES_BY_VERSION["2.9.5"],
            method_version="0.6.0-mechanics.1",
        )
    assert caught.value.code == "CG1_GM_CANDIDATE_SOURCE_INVALID"


def test_versioned_method_snapshot_rejects_unknown_selected_derivation(candidate_context):
    raw = _core_legacy_method_record("METHOD-001", "2.9.5")
    with pytest.raises(FoundryError) as caught:
        CandidateGMCapsuleStore._resolve_versioned_method_snapshot(
            candidate_context.scratch,
            record_id="METHOD-001",
            raw_record=raw,
            row_pack_id=CORE_PACK_ID,
            row_pack_version="2.9.5",
            row_pack_hash=ACCEPTED_CORE_PACK_HASHES_BY_VERSION["2.9.5"],
            method_version="0.7.0-unknown",
        )
    assert caught.value.code == "CG1_GM_CANDIDATE_SOURCE_INVALID"


def test_versioned_foundation_snapshot_projects_sealed_mechanics_and_preserves_raw_identity(candidate_context):
    raw = _core_legacy_foundation_record()
    resolved, identity = CandidateGMCapsuleStore._resolve_versioned_foundation_snapshot(
        candidate_context.scratch,
        record_id=raw["record_id"],
        raw_record=raw,
        row_pack_id=CORE_PACK_ID,
        row_pack_version="2.9.5",
        row_pack_hash=ACCEPTED_CORE_PACK_HASHES_BY_VERSION["2.9.5"],
        foundation_version=FOUNDATION_MECHANICS_PACK_VERSION,
        sealed_record_hash=raw["record_hash"],
    )

    assert resolved["record_id"] == raw["record_id"]
    assert resolved["content_binding"]["pack_id"] == "tianxia.non_sphere.authority"
    assert resolved["content_binding"]["pack_version"] == FOUNDATION_MECHANICS_PACK_VERSION
    assert identity == {
        "project_locked_pack_id": CORE_PACK_ID,
        "project_locked_pack_version": "2.9.5",
        "project_locked_pack_hash": ACCEPTED_CORE_PACK_HASHES_BY_VERSION["2.9.5"],
        "project_locked_record_hash": raw["record_hash"],
        "project_locked_record_json_sha256": sha256_bytes(canonical_json(raw).encode("utf-8")),
    }


def test_capture_binds_versioned_foundation_card_to_candidate_source(candidate_context, monkeypatch):
    request = deepcopy(candidate_context.run["request"])
    request["server_owned_authority"] = {
        "initial_foundation_mechanics_policy": deepcopy(INITIAL_FOUNDATION_MECHANICS_POLICY),
    }
    request["request_sha256"] = CharacterCreationExecutionService.request_payload_sha256(request)
    with candidate_context.root.connection() as conn:
        conn.execute(
            "UPDATE character_creation_runs SET request_json=? WHERE run_id=?",
            (canonical_json(request), RUN_ID),
        )
    candidate_context.run["request"] = request

    card, raw, resolved = _foundation_card_and_records(candidate_context)
    with candidate_context.scratch.connection() as conn:
        conn.execute(
            "INSERT INTO project_content_locks VALUES(?,?,?,?,?,?,?,?,?)",
            (
                PROJECT_ID,
                CORE_PACK_ID,
                "2.9.5",
                ACCEPTED_CORE_PACK_HASHES_BY_VERSION["2.9.5"],
                "r" * 64,
                "f" * 64,
                "i" * 64,
                "m" * 64,
                "fixture",
            ),
        )
        conn.execute(
            "INSERT INTO project_locked_records VALUES(?,?,?,?,?,?)",
            (
                PROJECT_ID,
                raw["record_id"],
                CORE_PACK_ID,
                "2.9.5",
                raw["record_hash"],
                canonical_json(raw),
            ),
        )

    monkeypatch.setattr(
        CandidateGMCapsuleStore,
        "_project_lock_proof",
        staticmethod(_fixture_project_lock_proof),
    )
    store, summary = _capture(
        candidate_context,
        sheet=_sheet_with_foundation_card(candidate_context, card),
    )
    loaded = store.load(RUN_ID)
    source_rows = {
        row["record_id"]: row
        for row in loaded["selected_record_source"]["locked_records"]
    }
    source = source_rows[raw["record_id"]]
    assert card["record_hash"] == resolved["record_hash"]
    assert source["record_hash"] == resolved["record_hash"]
    assert source["pack_version"] == FOUNDATION_MECHANICS_PACK_VERSION
    assert source["project_locked_pack_id"] == CORE_PACK_ID
    assert source["project_locked_pack_version"] == "2.9.5"
    assert source["project_locked_record_hash"] == raw["record_hash"]
    assert summary["capsule_id"] == loaded["summary"]["capsule_id"]


def test_capture_binds_authenticated_origin_projection_and_retains_raw_identity(candidate_context, monkeypatch):
    card, raw, resolved = _origin_card_and_records(candidate_context)
    monkeypatch.setattr(
        CandidateGMCapsuleStore,
        "_project_lock_proof",
        staticmethod(_fixture_project_lock_proof),
    )

    store, summary = _capture(
        candidate_context,
        sheet=_sheet_with_origin_card(candidate_context, card),
    )
    loaded = store.load(RUN_ID)
    source = next(
        row
        for row in loaded["selected_record_source"]["locked_records"]
        if row["record_id"] == raw["record_id"]
    )
    projected = json.loads(source["record_json"])

    assert card["record_hash"] == resolved["record_hash"]
    assert source["record_hash"] == resolved["record_hash"]
    assert source["project_locked_pack_id"] == raw["content_binding"]["pack_id"]
    assert source["project_locked_pack_version"] == raw["content_binding"]["pack_version"]
    assert source["project_locked_record_hash"] == raw["record_hash"]
    assert projected["content_type"] == "origin_insight"
    assert projected["compatibility"]["factory"]["stage2_authority"]["authority_complete"] is True
    assert summary["capsule_id"] == loaded["summary"]["capsule_id"]


def test_origin_snapshot_rejects_rehashed_tampered_raw_and_missing_lock_hash(candidate_context):
    _card, raw, _resolved = _origin_card_and_records(candidate_context)
    tampered = deepcopy(raw)
    tampered["summary"] = "tampered source"
    tampered["record_hash"] = canonical_record_hash(
        {key: value for key, value in tampered.items() if key != "record_hash"}
    )
    with pytest.raises(FoundryError) as caught:
        CandidateGMCapsuleStore._resolve_origin_insight_snapshot(
            candidate_context.scratch,
            project_id=PROJECT_ID,
            record_id=raw["record_id"],
            raw_record=tampered,
            row_pack_id=raw["content_binding"]["pack_id"],
            row_pack_version=raw["content_binding"]["pack_version"],
            row_pack_hash=raw["content_binding"]["pack_hash"],
            sealed_record_hash=raw["record_hash"],
        )
    assert caught.value.code == "CG1_GM_CANDIDATE_SOURCE_INVALID"

    with pytest.raises(FoundryError) as caught:
        CandidateGMCapsuleStore._resolve_origin_insight_snapshot(
            candidate_context.scratch,
            project_id=PROJECT_ID,
            record_id=raw["record_id"],
            raw_record=raw,
            row_pack_id=raw["content_binding"]["pack_id"],
            row_pack_version=raw["content_binding"]["pack_version"],
            row_pack_hash=None,
            sealed_record_hash=raw["record_hash"],
        )
    assert caught.value.code == "CG1_GM_CANDIDATE_SOURCE_INVALID"


def test_origin_snapshot_rejects_malformed_derived_authority(candidate_context, monkeypatch):
    _card, raw, _resolved = _origin_card_and_records(candidate_context)
    from project_store.service import ProjectStore

    original = ProjectStore._resolve_project_locked_origin_insight_after_proof

    def malformed(self, conn, project_id, record_id):
        projected = deepcopy(original(self, conn, project_id, record_id))
        projected["compatibility"]["factory"]["stage2_authority"] = {"authority_complete": True}
        projected["record_hash"] = canonical_record_hash(
            {key: value for key, value in projected.items() if key != "record_hash"}
        )
        return projected

    monkeypatch.setattr(ProjectStore, "_resolve_project_locked_origin_insight_after_proof", malformed)
    with pytest.raises(FoundryError) as caught:
        CandidateGMCapsuleStore._resolve_origin_insight_snapshot(
            candidate_context.scratch,
            project_id=PROJECT_ID,
            record_id=raw["record_id"],
            raw_record=raw,
            row_pack_id=raw["content_binding"]["pack_id"],
            row_pack_version=raw["content_binding"]["pack_version"],
            row_pack_hash=raw["content_binding"]["pack_hash"],
            sealed_record_hash=raw["record_hash"],
        )
    assert caught.value.code == "CG1_GM_CANDIDATE_SOURCE_INVALID"


def test_versioned_foundation_snapshot_preserves_legacy_p2a_route(candidate_context):
    raw = _core_legacy_foundation_record()
    resolved, identity = CandidateGMCapsuleStore._resolve_versioned_foundation_snapshot(
        candidate_context.scratch,
        record_id=raw["record_id"],
        raw_record=raw,
        row_pack_id=CORE_PACK_ID,
        row_pack_version="2.9.5",
        row_pack_hash=ACCEPTED_CORE_PACK_HASHES_BY_VERSION["2.9.5"],
        foundation_version=None,
        sealed_record_hash=raw["record_hash"],
    )
    assert resolved["content_binding"]["pack_id"] == "tianxia.non_sphere.authority"
    assert resolved["content_binding"]["pack_version"] == "P2A"
    assert identity["project_locked_record_hash"] == raw["record_hash"]


@pytest.mark.parametrize(
    "row_pack_id,row_pack_version,row_pack_hash",
    [
        ("pack.unknown", "2.9.5", ACCEPTED_CORE_PACK_HASHES_BY_VERSION["2.9.5"]),
        (CORE_PACK_ID, "9.9.9", "b" * 64),
        (CORE_PACK_ID, "2.9.5", "b" * 64),
        (CORE_PACK_ID, "2.9.5", None),
        (CORE_PACK_ID, "2.9.5", ""),
        ("tianxia.non_sphere.authority", "9.9", "b" * 64),
    ],
    ids=[
        "unknown-pack",
        "unknown-version",
        "wrong-pack-hash",
        "missing-pack-hash",
        "ambiguous-pack-hash",
        "unknown-ns-version",
    ],
)
def test_versioned_foundation_snapshot_rejects_unsupported_pack_binding(
    candidate_context, row_pack_id, row_pack_version, row_pack_hash,
):
    raw = _core_legacy_foundation_record()
    with pytest.raises(FoundryError) as caught:
        CandidateGMCapsuleStore._resolve_versioned_foundation_snapshot(
            candidate_context.scratch,
            record_id=raw["record_id"],
            raw_record=raw,
            row_pack_id=row_pack_id,
            row_pack_version=row_pack_version,
            row_pack_hash=row_pack_hash,
            foundation_version=FOUNDATION_MECHANICS_PACK_VERSION,
            sealed_record_hash=raw["record_hash"],
        )
    assert caught.value.code == "CG1_GM_CANDIDATE_SOURCE_INVALID"


def test_versioned_foundation_snapshot_rejects_self_rehashed_legacy_p2a_source(candidate_context):
    raw = _core_legacy_foundation_record()
    raw["content_binding"] = {
        "pack_id": "tianxia.non_sphere.authority",
        "pack_version": "P2A",
    }
    raw["record_hash"] = canonical_record_hash(
        {key: value for key, value in raw.items() if key != "record_hash"}
    )
    with pytest.raises(FoundryError) as caught:
        CandidateGMCapsuleStore._resolve_versioned_foundation_snapshot(
            candidate_context.scratch,
            record_id=raw["record_id"],
            raw_record=raw,
            row_pack_id="tianxia.non_sphere.authority",
            row_pack_version="P2A",
            row_pack_hash=None,
            foundation_version=None,
            sealed_record_hash=raw["record_hash"],
        )
    assert caught.value.code == "CG1_GM_CANDIDATE_SOURCE_INVALID"


def test_versioned_foundation_snapshot_rejects_malformed_factory_compatibility(candidate_context):
    raw = _core_legacy_foundation_record()
    malformed = deepcopy(raw)
    malformed["compatibility"]["factory"] = ["malformed"]
    malformed["record_hash"] = canonical_record_hash(
        {key: value for key, value in malformed.items() if key != "record_hash"}
    )
    with pytest.raises(FoundryError) as caught:
        CandidateGMCapsuleStore._resolve_versioned_foundation_snapshot(
            candidate_context.scratch,
            record_id=raw["record_id"],
            raw_record=malformed,
            row_pack_id=CORE_PACK_ID,
            row_pack_version="2.9.5",
            row_pack_hash=ACCEPTED_CORE_PACK_HASHES_BY_VERSION["2.9.5"],
            foundation_version=FOUNDATION_MECHANICS_PACK_VERSION,
            sealed_record_hash=malformed["record_hash"],
        )
    assert caught.value.code == "CG1_GM_CANDIDATE_SOURCE_INVALID"


def test_versioned_foundation_snapshot_rejects_tampered_source_and_policy_version(candidate_context):
    raw = _core_legacy_foundation_record()
    tampered = deepcopy(raw)
    tampered["compatibility"]["factory"]["raw_projection"]["raw_record"]["summary"] = "tampered"
    with pytest.raises(FoundryError) as caught:
        CandidateGMCapsuleStore._resolve_versioned_foundation_snapshot(
            candidate_context.scratch,
            record_id=raw["record_id"],
            raw_record=tampered,
            row_pack_id=CORE_PACK_ID,
            row_pack_version="2.9.5",
            row_pack_hash=ACCEPTED_CORE_PACK_HASHES_BY_VERSION["2.9.5"],
            foundation_version=FOUNDATION_MECHANICS_PACK_VERSION,
            sealed_record_hash=raw["record_hash"],
        )
    assert caught.value.code == "CG1_GM_CANDIDATE_SOURCE_INVALID"

    rehashed = deepcopy(raw)
    rehashed["compatibility"]["factory"]["raw_projection"]["raw_record"]["summary"] = "tampered"
    rehashed["record_hash"] = canonical_record_hash(
        {key: value for key, value in rehashed.items() if key != "record_hash"}
    )
    with pytest.raises(FoundryError) as caught:
        CandidateGMCapsuleStore._resolve_versioned_foundation_snapshot(
            candidate_context.scratch,
            record_id=raw["record_id"],
            raw_record=rehashed,
            row_pack_id=CORE_PACK_ID,
            row_pack_version="2.9.5",
            row_pack_hash=ACCEPTED_CORE_PACK_HASHES_BY_VERSION["2.9.5"],
            foundation_version=FOUNDATION_MECHANICS_PACK_VERSION,
            sealed_record_hash=raw["record_hash"],
        )
    assert caught.value.code == "CG1_GM_CANDIDATE_SOURCE_INVALID"

    with pytest.raises(FoundryError) as caught:
        CandidateGMCapsuleStore._resolve_versioned_foundation_snapshot(
            candidate_context.scratch,
            record_id=raw["record_id"],
            raw_record=raw,
            row_pack_id=CORE_PACK_ID,
            row_pack_version="2.9.5",
            row_pack_hash=ACCEPTED_CORE_PACK_HASHES_BY_VERSION["2.9.5"],
            foundation_version="0.4D-mechanics.1",
            sealed_record_hash=raw["record_hash"],
        )
    assert caught.value.code == "CG1_GM_CANDIDATE_SOURCE_INVALID"


def test_versioned_foundation_snapshot_rejects_mismatched_derived_version(candidate_context, monkeypatch):
    raw = _core_legacy_foundation_record()
    original = NonSphereAuthorityService.project_locked_foundation_catalog_record

    def wrong_version(self, foundation_id, *, snapshot_record=None, mechanical=False):
        projected = original(
            self,
            foundation_id,
            snapshot_record=snapshot_record,
            mechanical=mechanical,
        )
        if mechanical:
            projected["content_binding"]["pack_version"] = "P2A"
            projected["record_hash"] = canonical_record_hash(projected)
        return projected

    monkeypatch.setattr(
        NonSphereAuthorityService,
        "project_locked_foundation_catalog_record",
        wrong_version,
    )
    with pytest.raises(FoundryError) as caught:
        CandidateGMCapsuleStore._resolve_versioned_foundation_snapshot(
            candidate_context.scratch,
            record_id=raw["record_id"],
            raw_record=raw,
            row_pack_id=CORE_PACK_ID,
            row_pack_version="2.9.5",
            row_pack_hash=ACCEPTED_CORE_PACK_HASHES_BY_VERSION["2.9.5"],
            foundation_version=FOUNDATION_MECHANICS_PACK_VERSION,
            sealed_record_hash=raw["record_hash"],
        )
    assert caught.value.code == "CG1_GM_CANDIDATE_SOURCE_INVALID"


def test_capture_matches_projection_service_content_lock_identity(candidate_context):
    """The projector seals the canonical content-lock document, not lock_hash."""
    with candidate_context.scratch.connection() as conn:
        row = conn.execute(
            "SELECT project_json FROM projects WHERE project_id=?",
            (PROJECT_ID,),
        ).fetchone()
    projected_lock_hash = sha256_json(json.loads(row["project_json"])["content_lock"])
    candidate_context.projection["content_lock_hash"] = projected_lock_hash
    with candidate_context.scratch.connection() as conn:
        conn.execute(
            "UPDATE projection_runs SET content_lock_hash=? WHERE projection_id=?",
            (projected_lock_hash, candidate_context.projection["projection_id"]),
        )

    store, summary = _capture(candidate_context)
    assert summary["projection_id"] == candidate_context.projection["projection_id"]

    # A row that reports the request/project lock_hash directly is not the
    # ProjectionService contract and must remain rejected.
    candidate_context.projection["content_lock_hash"] = LOCK_HASH
    with candidate_context.scratch.connection() as conn:
        conn.execute(
            "UPDATE projection_runs SET content_lock_hash=? WHERE projection_id=?",
            (LOCK_HASH, candidate_context.projection["projection_id"]),
        )
    with pytest.raises(FoundryError) as caught:
        _capture(candidate_context)
    assert caught.value.code == "CG1_GM_CANDIDATE_PROJECTION_INVALID"
    assert store is not None


def test_loader_rejects_payload_tamper_and_stale_root_anchor(candidate_context):
    store, summary = _capture(candidate_context)
    capsule = _capsule_path(store, summary)
    target = capsule / "projection" / "Character_Master_Ledger.json"
    original = target.read_bytes()
    target.write_bytes(original + b"tamper")
    with pytest.raises(FoundryError) as caught:
        store.load(RUN_ID)
    assert caught.value.code == "CG1_GM_CANDIDATE_PAYLOAD_TAMPERED"
    target.write_bytes(original)

    with candidate_context.root.connection() as conn:
        changed = _project(8)
        conn.execute(
            "UPDATE projects SET revision=?,project_json=?,canonical_project_hash=? WHERE project_id=?",
            (8, canonical_json(changed), sha256_json(changed), PROJECT_ID),
        )
    with pytest.raises(FoundryError) as caught:
        store.load(RUN_ID)
    assert caught.value.code == "CG1_GM_CANDIDATE_ROOT_ANCHOR_STALE"


def test_changed_context_gets_new_capsule_and_old_bytes_remain(candidate_context):
    store, first = _capture(candidate_context)
    changed_plan = deepcopy(candidate_context.final_plan)
    changed_plan["owner_note"] = "changed context"
    _store, second = _capture(candidate_context, final_plan=changed_plan)
    assert second["capsule_id"] != first["capsule_id"]
    assert _capsule_path(store, first).is_dir()
    assert _capsule_path(store, second).is_dir()


def test_summary_and_load_are_read_only(candidate_context):
    store, summary = _capture(candidate_context)
    capsule = _capsule_path(store, summary)
    before_files = {path.relative_to(capsule).as_posix(): path.read_bytes() for path in capsule.rglob("*") if path.is_file()}
    with candidate_context.root.connection() as conn:
        before_rows = conn.execute("SELECT COUNT(*) FROM character_creation_runs").fetchone()[0]
    assert store.summary(RUN_ID)["capsule_id"] == summary["capsule_id"]
    assert store.load(RUN_ID)["summary"]["capsule_id"] == summary["capsule_id"]
    after_files = {path.relative_to(capsule).as_posix(): path.read_bytes() for path in capsule.rglob("*") if path.is_file()}
    with candidate_context.root.connection() as conn:
        after_rows = conn.execute("SELECT COUNT(*) FROM character_creation_runs").fetchone()[0]
    assert before_files == after_files
    assert before_rows == after_rows


def test_character_creation_service_exposes_provider_free_candidate_reads(candidate_context):
    store, summary = _capture(candidate_context)
    service = object.__new__(CharacterCreationExecutionService)
    service.candidate_gm = store
    assert service.candidate_gm_summary(RUN_ID)["capsule_id"] == summary["capsule_id"]
    assert service.load_candidate_gm_context(RUN_ID)["summary"]["capsule_id"] == summary["capsule_id"]


def test_loader_rejects_missing_or_tampered_exact_response_bytes(candidate_context):
    store, summary = _capture(candidate_context)
    target = _response_path(store, summary)
    original = target.read_bytes()
    target.write_bytes(original + b"tamper")
    with pytest.raises(FoundryError) as caught:
        store.load(RUN_ID)
    assert caught.value.code == "CG1_GM_CANDIDATE_PAYLOAD_TAMPERED"
    target.write_bytes(original)
    target.unlink()
    with pytest.raises(FoundryError) as caught:
        store.load(RUN_ID)
    assert caught.value.code == "CG1_GM_CANDIDATE_PAYLOAD_MISSING"


def test_capture_rejects_missing_or_mismatched_persisted_exact_response(candidate_context):
    with candidate_context.root.connection() as conn:
        conn.execute(
            "UPDATE character_creation_runs SET response_json=? WHERE run_id=?",
            (canonical_json({"response_sha256": candidate_context.run["response"]["response_sha256"]}), RUN_ID),
        )
    with pytest.raises(FoundryError) as caught:
        _capture(candidate_context)
    assert caught.value.code == "CG1_GM_CANDIDATE_RUN_ANCHOR_INVALID"


def test_candidate_anchor_uses_hash_bound_retained_leaf_when_row_is_compact(candidate_context):
    run, response_text = _retained_response_run(candidate_context)
    with candidate_context.root.connection() as conn:
        conn.execute(
            "UPDATE character_creation_runs SET response_json=? WHERE run_id=?",
            (canonical_json({"response_sha256": run["response"]["response_sha256"]}), RUN_ID),
        )
    anchor = CandidateGMCapsuleStore(candidate_context.root)._request_anchor(run, candidate_context.root)
    assert anchor["response_text"] == response_text
    assert anchor["response_bytes"] == response_text.encode("utf-8")
    assert anchor["response_sha256"] == run["response"]["response_sha256"]


def test_first_submission_marker_rejects_malformed_response_less_history(candidate_context):
    run = deepcopy(candidate_context.run)
    response_text = run["response"]["exact_response_text"]
    response_sha = run["response"]["response_sha256"]
    request_sha = run["request"]["request_sha256"]
    run["attempt_history"] = [{
        "attempt_id": "cg1.attempt.request-created",
        "run_id": RUN_ID,
        "project_id": PROJECT_ID,
        "ordinal": 1,
        "action_type": "REQUEST_CREATED",
        "status": "PREPARING_REQUEST",
        "request_sha256": request_sha,
        "response_sha256": None,
        "response_text": None,
        "response_byte_count": 1,
        "response_bytes_sha256": None,
        "prior_attempt_id": None,
        "binding": {"request_sha256": request_sha},
    }]
    run["_response_evidence"] = {
        "schema": "TianxiaFoundry.ResponseCompileEvidence.v1",
        "kind": "PRE_PERSISTENCE",
        "run_id": RUN_ID,
        "project_id": PROJECT_ID,
        "request_sha256": request_sha,
        "response_sha256": response_sha,
    }
    with candidate_context.root.connection() as conn:
        conn.execute(
            "UPDATE character_creation_runs SET response_json=? WHERE run_id=?",
            (canonical_json({}), RUN_ID),
        )
    with pytest.raises(FoundryError) as caught:
        CandidateGMCapsuleStore(candidate_context.root)._request_anchor(run, candidate_context.root)
    assert caught.value.code == "CG1_GM_CANDIDATE_RUN_ANCHOR_INVALID"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda run: run["attempt_history"][-1].update(run_id="other.run"),
        lambda run: run["attempt_history"][-1].update(request_sha256="r" * 64),
        lambda run: run["attempt_history"][-1].update(response_sha256="h" * 64, response_bytes_sha256="h" * 64),
        lambda run: run["attempt_history"][-1].update(response_text="tampered response"),
        lambda run: run["attempt_history"].append({**run["attempt_history"][-1], "attempt_id": "cg1.attempt.stale", "ordinal": 3, "prior_attempt_id": run["attempt_history"][-1]["attempt_id"], "response_text": None, "response_sha256": None, "response_byte_count": None, "response_bytes_sha256": None}),
    ],
    ids=["wrong-run", "wrong-request", "hash-tamper", "leaf-tamper", "stale-leaf"],
)
def test_candidate_anchor_rejects_unbound_or_tampered_retained_leaf(candidate_context, mutation):
    run, _response_text = _retained_response_run(candidate_context)
    mutation(run)
    with candidate_context.root.connection() as conn:
        conn.execute(
            "UPDATE character_creation_runs SET response_json=? WHERE run_id=?",
            (canonical_json({"response_sha256": candidate_context.run["response"]["response_sha256"]}), RUN_ID),
        )
    with pytest.raises(FoundryError) as caught:
        CandidateGMCapsuleStore(candidate_context.root)._request_anchor(run, candidate_context.root)
    assert caught.value.code == "CG1_GM_CANDIDATE_RUN_ANCHOR_INVALID"


def test_retry_local_build_rehydrates_authentic_retained_leaf(candidate_context):
    run, response_text = _retained_response_run(candidate_context)
    run.update(status="NEEDS_REVIEW", execution_mode="STANDARD_API", transport={})
    service = object.__new__(CharacterCreationExecutionService)
    service.db = candidate_context.root
    service.get = lambda _run_id: deepcopy(run)
    service._is_dcc_route_run = lambda _run: True
    captured = {}

    def capture_retry(run_id, exact_text, transport, **kwargs):
        captured.update(run_id=run_id, response_text=exact_text, transport=transport, kwargs=kwargs)
        return {"status": "NEEDS_REVIEW"}

    service._apply_response = capture_retry
    result = service.retry_local_build(RUN_ID)
    assert result["status"] == "NEEDS_REVIEW"
    assert captured["run_id"] == RUN_ID
    assert captured["response_text"] == response_text
    assert captured["transport"]["provider_called"] is False
    assert captured["transport"]["transfer"] == "retry_local_build"


def test_capture_rejects_symlinked_runs_ancestor(candidate_context, tmp_path):
    store = CandidateGMCapsuleStore(candidate_context.root)
    store.root.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (store.root / "runs").symlink_to(outside, target_is_directory=True)
    with pytest.raises(FoundryError) as caught:
        _capture(candidate_context)
    assert caught.value.code == "CG1_GM_CANDIDATE_PATH_INVALID"
    assert not list(outside.rglob("*"))


def test_load_rejects_symlinked_run_key_ancestor(candidate_context, tmp_path):
    store, summary = _capture(candidate_context)
    run_key = hashlib.sha256(RUN_ID.encode()).hexdigest()[:32]
    run_dir = store.root / "runs" / run_key
    moved = tmp_path / "run-backup"
    run_dir.rename(moved)
    run_dir.symlink_to(moved, target_is_directory=True)
    try:
        with pytest.raises(FoundryError) as caught:
            store.load(RUN_ID)
        assert caught.value.code == "CG1_GM_CANDIDATE_PATH_INVALID"
    finally:
        run_dir.unlink()
        moved.rename(run_dir)


def test_capture_rejects_swapped_sheet_authority_fields(candidate_context):
    swapped = deepcopy(candidate_context.sheet)
    owner_sheet = deepcopy(swapped["owner_character_sheet"])
    authority = deepcopy(owner_sheet["authority_and_artifact_identity"])
    authority["project_id"], authority["projection_id"] = (
        authority["projection_id"], authority["project_id"]
    )
    owner_sheet["authority_and_artifact_identity"] = authority
    artifact_path = Path(swapped["sheet_artifact"]["path"])
    payload = (canonical_json(owner_sheet) + "\n").encode("utf-8")
    artifact_path.write_bytes(payload)
    swapped["owner_character_sheet"] = owner_sheet
    swapped["sheet_artifact"] = {
        **swapped["sheet_artifact"],
        "sha256": sha256_bytes(payload),
        "bytes": len(payload),
    }

    with pytest.raises(FoundryError) as caught:
        _capture(candidate_context, sheet=swapped)
    assert caught.value.code == "CG1_GM_CANDIDATE_SHEET_INVALID"


def test_apply_response_persists_capsule_after_release_block_and_cleanup(
    candidate_context, monkeypatch
):
    """Exercise the real submission failure seam around the actual capsule capture."""
    run = deepcopy(candidate_context.run)
    request = deepcopy(run["request"])
    request["stage1_prompt"] = {"prompt_id": "prompt.gm-candidate"}
    request["request_sha256"] = CharacterCreationExecutionService.request_payload_sha256(request)
    run["request"] = request
    response_text = run["response"]["exact_response_text"]
    run["attempt_history"] = [{
        "attempt_id": "cg1.attempt.first-request",
        "run_id": RUN_ID,
        "project_id": PROJECT_ID,
        "ordinal": 1,
        "action_type": "REQUEST_CREATED",
        "status": "PREPARING_REQUEST",
        "request_sha256": request["request_sha256"],
        "response_sha256": None,
        "response_text": None,
        "response_byte_count": None,
        "response_bytes_sha256": None,
        "prior_attempt_id": None,
        "binding": {"request_sha256": request["request_sha256"]},
    }]
    run["_response_evidence"] = {
        "schema": "TianxiaFoundry.ResponseCompileEvidence.v1",
        "kind": "PRE_PERSISTENCE",
        "run_id": RUN_ID,
        "project_id": PROJECT_ID,
        "request_sha256": request["request_sha256"],
        "response_sha256": run["response"]["response_sha256"],
    }
    scratch_run = (
        RUN_ID,
        PROJECT_ID,
        7,
        canonical_json(request),
        canonical_json(run["response"]),
    )
    with candidate_context.root.connection() as conn:
        conn.execute(
            "UPDATE character_creation_runs SET request_json=?,response_json=? WHERE run_id=?",
            (canonical_json(request), canonical_json({}), RUN_ID),
        )
    with candidate_context.scratch.connection() as conn:
        conn.execute(
            "INSERT INTO character_creation_runs(run_id,project_id,starting_revision,request_json,response_json) VALUES(?,?,?,?,?)",
            scratch_run,
        )

    compile_plan = {
        "stage1_response": "{}",
        "stage2_proposal": {"choices": []},
        "output_profile": {"combat_ready": False},
        "owner_descriptive_fields": {},
        "uncertainties": [],
        "fallbacks": [],
    }

    class _Stage1:
        @staticmethod
        def validate_response(*_args, **_kwargs):
            return {"attempt_id": "stage1.gm-candidate", "validation": {"valid": True}}

        @staticmethod
        def approve_and_commit(*_args, **_kwargs):
            return {"commit_id": "stage1.gm-candidate"}

    class _Sheets:
        @staticmethod
        def build(_project_id):
            return deepcopy(candidate_context.sheet)

    class _Release:
        @staticmethod
        def compile(_project_id, **_kwargs):
            _workspace, factory_authoring = _synthetic_factory_workspace(
                candidate_context.scratch.settings.data_dir.parent,
                project_id=PROJECT_ID,
                project_revision=candidate_context.projection["project_revision"],
                projection_id=candidate_context.projection["projection_id"],
                event_head_hash=candidate_context.projection["event_head_hash"],
            )
            _kwargs["_candidate_authoring_callback"](factory_authoring)
            raise FoundryError(
                "CG1_GM_AUTHORING_REQUIRED",
                "The production release requires a genuine GM authored artifact.",
                details={"fixture": "truthful-release-gate"},
                status_code=409,
            )

    class _ScratchDB:
        def __init__(self, _settings):
            self.settings = candidate_context.scratch.settings

        def migrate(self):
            return None

        def connection(self):
            return candidate_context.scratch.connection()

        def transaction(self):
            return candidate_context.scratch.transaction()

    class _ScratchDirectory:
        def __enter__(self):
            return str(candidate_context.scratch.settings.data_dir.parent)

        def __exit__(self, _exc_type, _exc, _traceback):
            shutil.rmtree(candidate_context.scratch.settings.data_dir.parent)
            return False

    monkeypatch.setattr(creation_service, "Settings", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(creation_service, "Database", _ScratchDB)
    monkeypatch.setattr(
        creation_service.tempfile,
        "TemporaryDirectory",
        lambda *_args, **_kwargs: _ScratchDirectory(),
    )

    service = object.__new__(CharacterCreationExecutionService)
    service.db = candidate_context.root
    service.owner_principal = "fixture-owner"
    service.candidate_gm = CandidateGMCapsuleStore(candidate_context.root)
    service.get = lambda _run_id: deepcopy(run)
    service._plan_with_accepted_final_target = lambda _run, plan, _accepted: deepcopy(plan)
    service._execution_descriptive_fields = lambda _run, plan: deepcopy(plan)
    service._require_frozen_choice_snapshot = lambda _run: {"snapshot_sha256": "f" * 64}
    service._snapshot_data = lambda _target, **_kwargs: None
    service._snapshot_external_security = lambda _target: None
    service._materialize_descriptive_fields = lambda *_args, **_kwargs: None
    service._materialize_delegated_final_grant_plan = lambda *_args, **_kwargs: None
    service._materialize_method_hard_lock = lambda *_args, **_kwargs: {"locked": True}
    service._materialize_constructed_arts = lambda *_args, **_kwargs: {"locked": True}
    service._delegated_path_ids_from_canonical_intent = lambda _intent: []
    service._issue_initial_catalog_provenance = lambda *_args, **_kwargs: None
    service._build_character_creation_projection = lambda *_args, **_kwargs: deepcopy(candidate_context.projection)
    service._stage2_commit = lambda *_args, **_kwargs: (
        {"valid": True},
        deepcopy(candidate_context.stage2_commit),
        deepcopy(candidate_context.projection),
    )
    service.pipeline_factory = lambda _scratch_db: {
        "stage1": _Stage1(),
        "stage2": candidate_context.stage2,
        "projections": object(),
        "character_sheets": _Sheets(),
        "production_release": _Release(),
    }
    capture_calls = []
    real_capture = service.candidate_gm.capture

    def capture(**kwargs):
        capture_calls.append(kwargs)
        return real_capture(**kwargs)

    service.candidate_gm.capture = capture

    def _compile_through_real_capture(compile_run, _response_text, **_kwargs):
        return CharacterCreationExecutionService._compile_once(
            service,
            compile_run,
            compile_plan,
            1,
            final_plan=candidate_context.final_plan,
        )

    service._validate_and_compile = _compile_through_real_capture
    service._apply_response(RUN_ID, response_text, {"provider_called": False})

    with candidate_context.root.connection() as conn:
        row = conn.execute(
            "SELECT response_json,validation_json,status FROM character_creation_runs WHERE run_id=?",
            (RUN_ID,),
        ).fetchone()
        attempt = conn.execute(
            "SELECT status,error_json FROM character_creation_attempt_history WHERE run_id=?",
            (RUN_ID,),
        ).fetchone()
    persisted_response = json.loads(row["response_json"])
    validation = json.loads(row["validation_json"])
    diagnostic = validation["last_submission_error"]
    summary = diagnostic["details"]["gm_candidate_capsule"]
    assert row["status"] == "NEEDS_REVIEW"
    assert persisted_response == run["response"]
    assert diagnostic["code"] == "CG1_GM_AUTHORING_REQUIRED"
    assert attempt["status"] == "BLOCKED"
    assert json.loads(attempt["error_json"])["code"] == "CG1_GM_AUTHORING_REQUIRED"
    assert not candidate_context.scratch.settings.data_dir.parent.exists()
    loaded = service.candidate_gm.load(RUN_ID)
    assert len(capture_calls) == 1
    assert capture_calls[0]["factory_authoring"]["project_id"] == PROJECT_ID
    assert loaded["summary"]["capsule_id"] == summary["capsule_id"]
    assert loaded["context"]["status"] == "CANDIDATE_CONTEXT_CAPTURED"
    assert loaded["context"]["factory_workspace"]["project_id"] == PROJECT_ID
    assert loaded["context"]["factory_workspace"]["project_revision"] == 8
    assert any(name.startswith("factory_workspace/") for name in loaded["manifest"]["entries"])


def test_capture_binds_authenticated_background_projection_and_retains_raw_identity(candidate_context, monkeypatch):
    """Background cards carry the ProjectStore authority projection hash, not the raw lock hash."""
    card, raw, resolved = _background_card_and_records(candidate_context)
    assert resolved["record_hash"] != raw["record_hash"]
    monkeypatch.setattr(
        CandidateGMCapsuleStore,
        "_project_lock_proof",
        staticmethod(_fixture_project_lock_proof),
    )

    store, summary = _capture(
        candidate_context,
        sheet=_sheet_with_origin_card(candidate_context, card),
    )
    loaded = store.load(RUN_ID)
    source = next(
        row
        for row in loaded["selected_record_source"]["locked_records"]
        if row["record_id"] == raw["record_id"]
    )
    projected = json.loads(source["record_json"])

    assert source["record_hash"] == resolved["record_hash"]
    assert source["project_locked_pack_id"] == raw["content_binding"]["pack_id"]
    assert source["project_locked_pack_version"] == raw["content_binding"]["pack_version"]
    assert source["project_locked_pack_hash"] == raw["content_binding"]["pack_hash"]
    assert source["project_locked_record_hash"] == raw["record_hash"]
    assert "binding_kind" not in source
    authority = projected["compatibility"]["factory"]["stage2_authority"]
    assert projected["content_type"] == "background"
    assert authority["authority_complete"] is True
    assert "background_acquisition" in authority["allowed_kinds"]
    assert authority["rule_id"] == f"ns1r.{raw['record_id']}.background-acquisition.v1"
    assert summary["capsule_id"] == loaded["summary"]["capsule_id"]


def test_capture_rejects_background_card_that_disagrees_with_projection(candidate_context, monkeypatch):
    """A forged Background card hash fails closed; a card that still equals the
    raw sealed hash (a sealed row whose typed authority was already complete,
    so ProjectStore returns it unchanged) keeps the ordinary raw-lock path."""
    card, raw, _resolved = _background_card_and_records(candidate_context)
    monkeypatch.setattr(
        CandidateGMCapsuleStore,
        "_project_lock_proof",
        staticmethod(_fixture_project_lock_proof),
    )
    forged = {**card, "record_hash": "b" * 64}
    with pytest.raises(FoundryError) as caught:
        _capture(candidate_context, sheet=_sheet_with_origin_card(candidate_context, forged))
    assert caught.value.code == "CG1_GM_CANDIDATE_SOURCE_INVALID"

    raw_hash_card = {**card, "record_hash": raw["record_hash"]}
    store, _summary = _capture(candidate_context, sheet=_sheet_with_origin_card(candidate_context, raw_hash_card))
    source = next(
        row
        for row in store.load(RUN_ID)["selected_record_source"]["locked_records"]
        if row["record_id"] == raw["record_id"]
    )
    assert source["record_hash"] == raw["record_hash"]
    assert "project_locked_record_hash" not in source


def test_background_snapshot_rejects_tampered_raw_and_forged_projection(candidate_context, monkeypatch):
    _card, raw, _resolved = _background_card_and_records(candidate_context)
    store = object.__new__(CandidateGMCapsuleStore)
    kwargs = dict(
        project_id=PROJECT_ID,
        record_id=raw["record_id"],
        row_pack_id=raw["content_binding"]["pack_id"],
        row_pack_version=raw["content_binding"]["pack_version"],
        row_pack_hash=raw["content_binding"]["pack_hash"],
        sealed_record_hash=raw["record_hash"],
    )
    tampered = deepcopy(raw)
    tampered["summary"] = "tampered source"
    tampered["record_hash"] = canonical_record_hash(
        {key: value for key, value in tampered.items() if key != "record_hash"}
    )
    with pytest.raises(FoundryError) as caught:
        CandidateGMCapsuleStore._resolve_background_projection_snapshot(
            store, candidate_context.scratch, raw_record=tampered, **kwargs
        )
    assert caught.value.code == "CG1_GM_CANDIDATE_SOURCE_INVALID"

    from project_store.service import ProjectStore

    def forged(self, conn, project_id, record_id):
        value = deepcopy(raw)
        value["summary"] = "forged descriptive change"
        value["compatibility"]["factory"]["stage2_authority"] = {
            "authority_complete": True,
            "allowed_kinds": ["background_acquisition"],
            "allowed_channels": ["background-selection"],
            "rule_id": f"ns1r.{record_id}.background-acquisition.v1",
            "source_authority_snapshot_hash": "c" * 64,
        }
        value["record_hash"] = canonical_record_hash(value)
        return value

    monkeypatch.setattr(ProjectStore, "_resolve_project_locked_background_after_proof", forged)
    with pytest.raises(FoundryError) as caught:
        CandidateGMCapsuleStore._resolve_background_projection_snapshot(
            store, candidate_context.scratch, raw_record=raw, **kwargs
        )
    assert caught.value.code == "CG1_GM_CANDIDATE_SOURCE_INVALID"


def _minimal_factory_workspace_snapshot(tmp_path: Path) -> tuple[CandidateGMCapsuleStore, dict, dict, Path]:
    workspace = tmp_path / "factory-workspace"
    workspace.mkdir()
    manifest = {
        "schema_version": "TianxiaFoundry.FactoryCommand1To4Workspace.v1",
        "workspace_status": "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE",
        "project_id": PROJECT_ID,
        "project_revision": 8,
        "projection_id": "projection.gm-candidate",
        "event_head_hash": "e" * 64,
    }
    manifest_path = workspace / "Workspace_Manifest.json"
    manifest_path.write_text(canonical_json(manifest), encoding="utf-8")
    manifest_digest = sha256_bytes(manifest_path.read_bytes())
    (workspace / "SHA256SUMS.txt").write_text(
        f"{manifest_digest}  Workspace_Manifest.json\n", encoding="utf-8",
    )
    hashes = {
        path.relative_to(workspace).as_posix(): sha256_bytes(path.read_bytes())
        for path in sorted(workspace.rglob("*"))
        if path.is_file()
    }
    factory = {
        "workspace_status": "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE",
        "project_id": PROJECT_ID,
        "project_revision": 8,
        "workspace_path": str(workspace),
        "workspace_sha256": sha256_json(hashes),
        "manifest_sha256": hashes["Workspace_Manifest.json"],
        "artifact_hashes": hashes,
    }
    candidate = {"metadata": {"project_revision": 8, "canonical_project_hash": "c" * 64}}
    return CandidateGMCapsuleStore.__new__(CandidateGMCapsuleStore), factory, candidate, workspace


@pytest.mark.parametrize("mutation", ["project", "revision", "tamper"])
def test_factory_workspace_snapshot_rejects_wrong_lineage_or_tampered_bytes(tmp_path: Path, mutation: str):
    store, factory, candidate, workspace = _minimal_factory_workspace_snapshot(tmp_path)
    if mutation == "project":
        factory["project_id"] = "project.other"
    elif mutation == "revision":
        factory["project_revision"] = 7
    else:
        (workspace / "Workspace_Manifest.json").write_text(
            canonical_json({
                "workspace_status": "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE",
                "project_id": PROJECT_ID,
                "project_revision": 8,
                "projection_id": "projection.changed",
            }),
            encoding="utf-8",
        )
    with pytest.raises(FoundryError) as caught:
        store._factory_workspace_snapshot(
            factory,
            project_id=PROJECT_ID,
            candidate_project=candidate,
            scratch_root=tmp_path,
        )
    assert caught.value.code == "CG1_GM_CANDIDATE_WORKSPACE_INVALID"


def test_production_release_hands_off_the_single_factory_build_once(tmp_path: Path, monkeypatch):
    calls = {"build": 0}
    captured: list[dict] = []

    class _Factory:
        def __init__(self, _db):
            pass

        def build(self, project_id):
            calls["build"] += 1
            return {"project_id": project_id, "workspace_id": "workspace.once"}

    class _Profile:
        def __init__(self, *_args, **_kwargs):
            pass

    release = object.__new__(production_release.CharacterProductionReleaseAdapter)
    release.db = object()
    release.gm_export = SimpleNamespace(_gm_screen_root=lambda: tmp_path / "gm")
    release.readiness = lambda: {"ready": True, "factory": {"factory_root": str(tmp_path / "factory")}}
    monkeypatch.setattr(production_release, "FactoryAuthoringWorkspaceService", _Factory)
    monkeypatch.setattr(production_release, "CharacterGMCommand5Profile", _Profile)

    with pytest.raises(RuntimeError, match="forced production failure after factory_authoring"):
        release.compile(
            PROJECT_ID,
            output_root=tmp_path / "output",
            fail_after="factory_authoring",
            _candidate_authoring_callback=captured.append,
        )
    assert calls["build"] == 1
    assert captured == [{"project_id": PROJECT_ID, "workspace_id": "workspace.once"}]


def test_traditions_are_path_family_cards_like_subpaths() -> None:
    # Regression: an owner build that chose the Spirit Awakening Tradition
    # "Thrum of the Grave" failed capture with CG1_GM_CANDIDATE_SOURCE_INVALID
    # because the tradition card carried the typed projection hash while only
    # tianxia.subpath.* rows were routed through the Path-family resolver.
    from character_creation.candidate_gm import CandidateGMCapsuleStore

    predicate = CandidateGMCapsuleStore._is_path_family_record
    assert predicate("tianxia.tradition.spirit.thrum_of_the_grave") is True
    assert predicate("tianxia.tradition.spirit.thrum_of_the_grave", {"content_type": "subpath"}) is True
    # The raw locked row of a Tradition is typed "tradition"; its projection is typed "subpath".
    assert predicate("tianxia.tradition.spirit.thrum_of_the_grave", {"content_type": "tradition"}) is True
    assert predicate("tianxia.subpath.body.kensei", {"content_type": "subpath"}) is True
    assert predicate("tianxia.tradition.spirit.thrum_of_the_grave", {"content_type": "talent"}) is False
    assert predicate("tianxia.talent.alchemy.court_of_the_three_legged_cauldron") is False

