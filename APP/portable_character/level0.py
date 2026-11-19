"""Source-backed mortal level-0 export for the bounded gameplay smoke.

This module is a narrow mortal dispatch beside the existing CL1--20 creator
pipeline.  It sends the starter through the shared point-buy, completion,
training and Path-attainment validators, preserves the selected
Background/Origin records, and passes the resulting candidate through the
existing :class:`PortableCharacterPackageService.build` exporter and audit.
The optional project export is the connected ProjectStore output; the
deterministic nested project is retained only as a provider-free scratch
fallback for this isolated smoke.
"""

from __future__ import annotations

import io
import json
import tempfile
import zipfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from app.core import canonical_json, sha256_bytes, sha256_file, sha256_json
from contracts.canonical import canonical_project_hash
from character_creation.mortal_level0 import (
    PHB_LEVEL0_LOCATOR,
    PHB_SOURCE_ID,
    PHB_SOURCE_SHA256,
    validate_mortal_level0_choices,
)

from .service import (
    GM_MODEL_NAME,
    GM_VIEW_NAME,
    LEGACY_GM_MODEL_NAME,
    PORTABLE_SCHEMA,
    PROJECT_MEMBER,
    READINESS_SCHEMA,
    PortableCharacterPackageService,
    _canon,
    _zip_info,
)


LEVEL0_SCHEMA = "TianxiaFoundry.MortalLevel0Export.v1"
LEVEL0_AUTHORITY_MEMBER = "Mortal_Level0_Authority.json"
OWNER_SHEET_MEMBER = "Tianxia_Owner_Character_Sheet_v1.json"
SOURCE_PACK_RELATIVE = Path("catalog/typed_authority/C1A_Canonical_Typed_Authority_Pack_v1.json")
BACKGROUND_ID = "tianxia.background.abandoned_orphan"
ORIGIN_ID = "tianxia.origin_insight.street_hardened"
ABILITY_NAMES = ("STR", "DEX", "CON", "INT", "WIS", "CHA")
PATH_IDS = (
    "tianxia.path.body_refining",
    "tianxia.path.qi_cultivation",
    "tianxia.path.spirit_awakening",
)
SOURCE_REF = {
    "source_id": PHB_SOURCE_ID,
    "source_hash": PHB_SOURCE_SHA256,
    "locator": PHB_LEVEL0_LOCATOR,
}


class Level0ExportError(ValueError):
    """A source or starter contract rejection before package mutation."""

    def __init__(self, code: str, **details: Any) -> None:
        self.code = code
        self.details = details
        message = code if not details else f"{code}: {json.dumps(details, sort_keys=True)}"
        super().__init__(message)


def _require(condition: bool, code: str, **details: Any) -> None:
    if not condition:
        raise Level0ExportError(code, **details)


def _load_authority() -> tuple[dict[str, Any], str]:
    source_pack = Path(__file__).parents[1] / SOURCE_PACK_RELATIVE
    _require(source_pack.is_file(), "LEVEL0_SOURCE_PACK_MISSING", path=str(SOURCE_PACK_RELATIVE))
    raw = source_pack.read_bytes()
    authority = json.loads(raw)
    _require(
        authority.get("schema_version") == "TianxiaFactory.TypedAuthorityPack.v1",
        "LEVEL0_SOURCE_PACK_SCHEMA_UNSUPPORTED",
    )
    _require(isinstance(authority.get("records"), dict), "LEVEL0_SOURCE_PACK_RECORDS_INVALID")
    return authority, sha256_bytes(raw)


def _starter_records(authority: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    records = authority["records"]
    background = deepcopy(records.get(BACKGROUND_ID))
    origin = deepcopy(records.get(ORIGIN_ID))
    _require(isinstance(background, dict), "LEVEL0_BACKGROUND_RECORD_MISSING", record_id=BACKGROUND_ID)
    _require(isinstance(origin, dict), "LEVEL0_ORIGIN_RECORD_MISSING", record_id=ORIGIN_ID)
    _require(background.get("canonical_record_id") == BACKGROUND_ID, "LEVEL0_BACKGROUND_RECORD_ID_MISMATCH")
    _require(origin.get("canonical_record_id") == ORIGIN_ID, "LEVEL0_ORIGIN_RECORD_ID_MISMATCH")
    background_stage2 = background.get("stage2_authority") or {}
    origin_stage2 = origin.get("stage2_authority") or {}
    _require(background.get("publication_override") == "published", "LEVEL0_BACKGROUND_NOT_PUBLISHED")
    _require(origin.get("publication_override") == "published", "LEVEL0_ORIGIN_NOT_PUBLISHED")
    _require(background.get("source", {}).get("source_hash"), "LEVEL0_BACKGROUND_SOURCE_MISSING")
    _require(origin.get("source", {}).get("source_hash"), "LEVEL0_ORIGIN_SOURCE_MISSING")
    _require(background_stage2.get("authority_complete") is True, "LEVEL0_BACKGROUND_AUTHORITY_INCOMPLETE")
    _require(
        background_stage2.get("allowed_channels") == ["background-selection"]
        and background_stage2.get("allowed_kinds") == ["background_acquisition"],
        "LEVEL0_BACKGROUND_CHANNEL_UNSUPPORTED",
    )
    _require(
        origin_stage2.get("allowed_channels") == ["origin-selection"]
        and origin_stage2.get("allowed_kinds") == ["origin_insight_acquisition"],
        "LEVEL0_ORIGIN_CHANNEL_UNSUPPORTED",
    )
    return background, origin


def validate_mortal_level0_starter(
    *,
    name: str,
    base_abilities: Mapping[str, int],
    background_ability: str = "DEX",
    background_id: str = BACKGROUND_ID,
    origin_insight_id: str = ORIGIN_ID,
) -> dict[str, Any]:
    """Validate the one explicit source-valid mortal starter.

    The selected background and origin records are copied byte-for-byte from
    the local typed authority pack.  Background ability adjustment is applied
    once; no Path, resource, Method, cultivation, or CL1 data is synthesized.
    """

    _require(isinstance(name, str) and bool(name.strip()) and name == name.strip(), "LEVEL0_NAME_INVALID")
    try:
        completion = validate_mortal_level0_choices(name=name, base_abilities=base_abilities)
    except Exception as exc:
        raise Level0ExportError(getattr(exc, "code", "LEVEL0_CREATOR_VALIDATION_FAILED")) from exc
    _require(tuple(base_abilities) == ABILITY_NAMES, "LEVEL0_ABILITIES_MISMATCH")
    authority, pack_sha256 = _load_authority()
    background, origin = _starter_records(authority)
    _require(background_id == BACKGROUND_ID and origin_insight_id == ORIGIN_ID, "LEVEL0_STARTER_UNSUPPORTED")
    adjustment = background["stage2_authority"]["ability_adjustment"]
    _require(background_ability in adjustment["allowed_abilities"], "LEVEL0_BACKGROUND_ABILITY_UNSUPPORTED")
    _require(adjustment["amount"] == 2, "LEVEL0_BACKGROUND_ADJUSTMENT_UNSUPPORTED")
    abilities = dict(base_abilities)
    abilities[background_ability] += adjustment["amount"]
    _require(abilities[background_ability] <= adjustment["cap"], "LEVEL0_BACKGROUND_ABILITY_CAP")
    _require(set(abilities) == set(ABILITY_NAMES), "LEVEL0_ABILITY_SET_INVALID")
    return {
        "schema": LEVEL0_SCHEMA,
        "name": name,
        "abilities": abilities,
        "base_abilities": dict(base_abilities),
        "background_ability": background_ability,
        "background_record": background,
        "origin_record": origin,
        "authority_pack": {
            "path": SOURCE_PACK_RELATIVE.as_posix(),
            "sha256": pack_sha256,
            "pack_id": authority.get("pack_id"),
            "version": authority.get("version"),
        },
        "path_attainment": {path_id: 0 for path_id in PATH_IDS},
        "active_paths": [],
        "cultivation_resources": [],
        "point_buy": deepcopy(completion["point_buy"]),
        "completion_route": deepcopy(completion["route"]),
        "training_route": deepcopy(completion["training"]),
        "source": deepcopy(SOURCE_REF),
    }


def _nested_project(*, project_id: str, project_revision: int, display_name: str) -> tuple[bytes, dict[str, Any]]:
    project = {
        "schema_version": "TianxiaFoundry.CharacterProject.v1",
        "project_id": project_id,
        "revision": project_revision,
        "name": display_name,
        "active_stage": 1,
        "status": "completed_mortal_level0",
        "factory_target": {"candidate_schema": "TianxiaFoundry.MortalLevel0Export.v1", "producer": "TianxiaFoundry.MortalLevel0PackageService"},
        "event_stream": {"count": 0, "head_hash": "0" * 64, "path": "events.json"},
        "user_locks": [],
        "source_inputs": [],
        "level0_route": "sect_trial_pending",
    }
    project["content_lock_hash"] = sha256_json({"source": "C1A_Canonical_Typed_Authority_Pack_v1"})
    project["updated_at"] = "2026-09-08T00:00:00Z"
    project_hash = canonical_project_hash(project)
    project["canonical_project_hash"] = project_hash
    manifest = {
        "schema_version": "TianxiaFoundry.ProjectExport.v1",
        "project_id": project_id,
        "project_revision": project_revision,
        "revision": project_revision,
        "event_count": 0,
        "latest_event_hash": "0" * 64,
        "state_hash": sha256_json({"project_id": project_id, "revision": project_revision, "state": "completed_mortal_level0"}),
        "content_lock_hash": project["content_lock_hash"],
        "canonical_project_hash": project_hash,
        "created_at": project["updated_at"],
        "files": {},
    }
    manifest["canonical_project_hash"] = project_hash
    files = {
        "manifest.json": _canon(manifest),
        "project.json": _canon(project),
        "events.json": b"[]",
        "replay.json": _canon({"state": "completed_mortal_level0", "revision": project_revision}),
    }
    manifest["files"] = {name: sha256_bytes(data) for name, data in files.items()}
    files["manifest.json"] = _canon(manifest)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name, data in sorted(files.items()):
            zf.writestr(_zip_info(name), data)
    return output.getvalue(), {
        "project_id": project_id,
        "project_revision": project_revision,
        "event_count": 0,
        "event_head_hash": manifest["latest_event_hash"],
        "replay_state_hash": manifest["state_hash"],
        "content_lock_hash": manifest["content_lock_hash"],
        "canonical_project_hash": manifest["canonical_project_hash"],
    }


def build_mortal_level0_package(
    output_zip: Path,
    *,
    character_id: str = "mortal-level0-source-001",
    display_name: str = "Mortal Source Starter",
    base_abilities: Mapping[str, int] | None = None,
    background_ability: str = "DEX",
    project_export: Path | None = None,
) -> dict[str, Any]:
    """Complete the mortal route through the existing portable exporter."""

    choices = validate_mortal_level0_starter(
        name=display_name,
        base_abilities=base_abilities or {"STR": 8, "DEX": 15, "CON": 13, "INT": 10, "WIS": 12, "CHA": 14},
        background_ability=background_ability,
    )
    _require(isinstance(character_id, str) and character_id.strip() == character_id and character_id, "LEVEL0_CHARACTER_ID_INVALID")
    abilities = choices["abilities"]
    con_modifier = (abilities["CON"] - 10) // 2
    hp = max(1, 6 + con_modifier)
    project_id = f"level0-{character_id}"
    source_ref = deepcopy(SOURCE_REF)
    model = {
        "schema": "Tianxia_GM_Character_Model_v2",
        "schema_version": "2.0.0",
        "identity": {"character_id": character_id, "display_name": display_name, "cultivation_level": 0, "realm": "Mortal", "project_id": project_id},
        "binding": {"faction_id": "party", "location_id": "mortal-start"},
        "stage": {"level": 0, "route": "sect_trial_pending", "state": "completed_level0"},
        "abilities": deepcopy(abilities),
        "hit_dice": {"sides": 6, "maximum": 1, "remaining": 1},
        "hp": {"current": hp, "maximum": hp, "formula": "6 + CON modifier"},
        "speed": {"walking_ft": 30},
        "paths": {"attainment": deepcopy(choices["path_attainment"]), "selected": [], "pools": [], "cultivation_permissions": []},
        "background_origin": {"background_id": BACKGROUND_ID, "origin_insight_ids": [ORIGIN_ID], "exceptions": []},
        "metadata": {
            "producer": "TianxiaFoundry.MortalLevel0PackageService",
            "completed_level0": True,
            "level0_authority_member": LEVEL0_AUTHORITY_MEMBER,
            "source_pack_sha256": choices["authority_pack"]["sha256"],
        },
    }
    legacy_model = {"schema_version": "Tianxia_GM_Character_Model_v1", **deepcopy(model)}
    view = {"schema_version": "Tianxia_GM_Character_View_Model_v2", "model": deepcopy(model), "display": {"paths": [], "cultivation_resources": []}}
    owner_sheet = {
        "schema_version": "TianxiaFoundry.OwnerCharacterSheet.v1",
        "identity": deepcopy(model["identity"]),
        "binding": deepcopy(model["binding"]),
        "stage": deepcopy(model["stage"]),
        "abilities": deepcopy(abilities),
        "hp": deepcopy(model["hp"]),
        "hit_dice": deepcopy(model["hit_dice"]),
        "speed": deepcopy(model["speed"]),
        "paths": deepcopy(model["paths"]),
        "background_origin": deepcopy(model["background_origin"]),
        "source": source_ref,
    }
    authority = {
        "schema": LEVEL0_SCHEMA,
        "character_id": character_id,
        "identity": deepcopy(model["identity"]),
        "binding": deepcopy(model["binding"]),
        "stage": deepcopy(model["stage"]),
        "abilities": deepcopy(abilities),
        "base_abilities": deepcopy(choices["base_abilities"]),
        "background_ability": background_ability,
        "hp": deepcopy(model["hp"]),
        "hit_dice": deepcopy(model["hit_dice"]),
        "speed": deepcopy(model["speed"]),
        "paths": deepcopy(model["paths"]),
        "background_record": deepcopy(choices["background_record"]),
        "origin_record": deepcopy(choices["origin_record"]),
        "authority_pack": deepcopy(choices["authority_pack"]),
        "completion": {
            "route": "completed_level0_mortal",
            "point_buy": deepcopy(choices["point_buy"]),
            "factory_validator": deepcopy(choices["completion_route"]),
            "training_validator": deepcopy(choices["training_route"]),
        },
        "source": source_ref,
        "exporter": {"id": "TianxiaFoundry.MortalLevel0PackageService", "version": 1},
    }
    files: dict[str, bytes] = {
        LEVEL0_AUTHORITY_MEMBER: _canon(authority),
        OWNER_SHEET_MEMBER: _canon(owner_sheet),
        GM_MODEL_NAME: _canon(model),
        LEGACY_GM_MODEL_NAME: _canon(legacy_model),
        GM_VIEW_NAME: _canon(view),
        f"source/C2B3_{GM_MODEL_NAME}": _canon(model),
        f"source/C2B3_{GM_VIEW_NAME}": _canon(view),
        f"source/C2B3_{OWNER_SHEET_MEMBER}": _canon(owner_sheet),
        "READINESS.json": _canon({
            "schema_version": READINESS_SCHEMA,
            "completed_level0": True,
            "character_sheet": "SOURCE_VALIDATED",
            "gm_export_available": True,
            "combat": "NOT_ATTEMPTED",
            "active_paths": [],
            "cultivation_resources": [],
        }),
    }
    output_zip = Path(output_zip).resolve()
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mortal-level0-build-", dir=str(output_zip.parent)) as work:
        work_root = Path(work)
        if project_export is None:
            project_bytes, project_identity = _nested_project(project_id=project_id, project_revision=1, display_name=display_name)
            project_path = work_root / "project-export.tianxia-project.zip"
            project_path.write_bytes(project_bytes)
        else:
            project_path = Path(project_export).resolve()
            _require(project_path.is_file(), "LEVEL0_PROJECT_EXPORT_MISSING", path=str(project_path))
            with zipfile.ZipFile(project_path) as project_zip:
                project_manifest = json.loads(project_zip.read("manifest.json"))
                project_doc = json.loads(project_zip.read("project.json"))
            project_identity = {
                "project_id": project_manifest["project_id"],
                "project_revision": project_doc["revision"],
                "event_count": project_manifest["event_count"],
                "event_head_hash": project_manifest["latest_event_hash"],
                "replay_state_hash": project_manifest["state_hash"],
                "content_lock_hash": project_manifest["content_lock_hash"],
                "canonical_project_hash": project_manifest["canonical_project_hash"],
            }
        files[PROJECT_MEMBER] = project_path.read_bytes()
        candidate_manifest = {
            "schema_version": PORTABLE_SCHEMA,
            "package_role": "command5_candidate",
            "display_name": display_name,
            "project_id": project_identity["project_id"],
            "build_profile": "MORTAL_LEVEL0_CANDIDATE",
            "level0_authority": {"path": LEVEL0_AUTHORITY_MEMBER, "schema": LEVEL0_SCHEMA, "authoritative": True},
            "source_producer": {"id": "TianxiaFoundry.MortalLevel0PackageService", "route": "completed_level0_mortal"},
        }
        files["PACKAGE_MANIFEST.json"] = _canon(candidate_manifest)
        candidate_path = work_root / "mortal-level0-candidate.zip"
        with zipfile.ZipFile(candidate_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for name, data in sorted(files.items()):
                zf.writestr(_zip_info(name), data)
        report = PortableCharacterPackageService.build(
            candidate_zip=candidate_path,
            project_export=project_path,
            output_zip=output_zip,
            consumer_identity={"id": "TianxiaFoundry.MortalLevel0PackageService", "route": "completed_level0_mortal"},
        )
    _require(report.get("valid") is True, "LEVEL0_PRODUCER_AUDIT_FAILED")
    _require(report.get("sha256") == sha256_file(output_zip), "LEVEL0_PRODUCER_AUDIT_HASH_MISMATCH")
    report["level0_authority"] = authority
    report["producer_route"] = "completed_level0_mortal"
    report["producer_audit_id"] = "PortableCharacterPackageService.audit"
    return report
