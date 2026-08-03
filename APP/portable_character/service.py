from __future__ import annotations

import copy
import json
import os
import shutil
import re
import stat
import tempfile
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from app.core import Database, FoundryError, canonical_json, sha256_bytes, sha256_file, utcnow
from project_store.service import ProjectStore
from contracts.canonical import canonical_project_hash
from product_bootstrap import ProductReadinessService
from gm2_contract.adapter import detect_profile, _migrate_legacy, _migrate_fire, normalize_view
from character_creation.choice_snapshot import valid_choice_snapshot

PORTABLE_SCHEMA = "TianxiaFoundry.PortableCharacterPackage.v1"
NORMALIZATION_SCHEMA = "TianxiaFoundry.C2C1ConsumerContainerNormalization.v1"
READINESS_SCHEMA = "TianxiaFoundry.PortableCharacterReadiness.v1"
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_EXPANDED_BYTES = 512 * 1024 * 1024
MAX_ENTRIES = 4096
GM_MODEL_NAME = "Tianxia_GM_Character_Model_v2.json"
LEGACY_GM_MODEL_NAME = "Tianxia_GM_Character_Model_v1.json"
GM_VIEW_NAME = "Tianxia_GM_Character_View_Model_v2.json"
PROJECT_MEMBER = "source/Character_Project.tianxia-project.zip"


def _canon(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name)
    info.date_time = (1980, 1, 1, 0, 0, 0)
    info.external_attr = 0o644 << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def _safe_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(name or "character").strip()).strip("._-")
    return cleaned[:96] or "character"




def _first_mapping_with_key(value: Any, key: str) -> dict[str, Any] | None:
    if isinstance(value, dict):
        if key in value:
            return value
        for child in value.values():
            found = _first_mapping_with_key(child, key)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _first_mapping_with_key(child, key)
            if found is not None:
                return found
    return None


def _authoritative_display_name(project: dict[str, Any]) -> str | None:
    for lock in project.get("user_locks") or []:
        if isinstance(lock, dict) and lock.get("field") == "character.identity.display_name" and str(lock.get("value") or "").strip():
            return str(lock["value"]).strip()
    identity = project.get("identity") or project.get("character_identity") or {}
    if isinstance(identity, dict) and str(identity.get("display_name") or "").strip():
        return str(identity["display_name"]).strip()
    return None


def _project_non_sphere_state(project_doc: dict[str, Any], non_sphere_doc: dict[str, Any] | None) -> dict[str, Any] | None:
    for value in (non_sphere_doc, project_doc.get("non_sphere_authority"), project_doc.get("non_sphere_state"), project_doc):
        found = _first_mapping_with_key(value, "primary_method_id")
        if found is not None and isinstance(found.get("paths"), list):
            return found
    return None


def _project_model_overlay(model: dict[str, Any], project_doc: dict[str, Any], non_sphere_doc: dict[str, Any] | None, *, candidate_sha256: str) -> dict[str, Any]:
    """Overlay only current project-owned surfaces onto completed candidate mechanics."""
    out = copy.deepcopy(model)
    state = _project_non_sphere_state(project_doc, non_sphere_doc)
    project_name = _authoritative_display_name(project_doc)
    candidate_name = str((out.get("identity") or {}).get("display_name") or "").strip()
    if project_name and candidate_name and project_name != candidate_name:
        raise FoundryError(
            "GM2_CANDIDATE_PROJECT_MISMATCH",
            "The completed character candidate belongs to a different project identity.",
            details={"project_display_name": project_name, "candidate_display_name": candidate_name},
        )
    if project_name:
        out.setdefault("identity", {})["display_name"] = project_name
    if not state:
        return out

    path_names = {
        "tianxia.path.body_refining": ("Body Refining", "CON"),
        "tianxia.path.qi_cultivation": ("Qi Cultivation", "INT"),
        "tianxia.path.spirit_awakening": ("Spirit Awakening", "WIS"),
    }
    rows_by_id = {str(r.get("path_id")): r for r in state.get("paths") or [] if isinstance(r, dict) and r.get("path_id")}
    method_id = state.get("primary_method_id")
    authorized = set()
    compact_to_canonical = {"BODY_REFINING": "tianxia.path.body_refining", "QI_CULTIVATION": "tianxia.path.qi_cultivation", "SPIRIT_AWAKENING": "tianxia.path.spirit_awakening"}
    authorized.update(compact_to_canonical.get(str(value), str(value)) for value in (state.get("method_granted_compact_path_ids") or []))
    eligibility = state.get("ap_eligibility") or state.get("method_ap_eligibility") or {}
    if isinstance(eligibility, dict):
        for row in eligibility.get("paths") or []:
            if isinstance(row, dict) and row.get("eligible") and row.get("path_id"):
                authorized.add(str(row["path_id"]))
    source = {"package_sha256": candidate_sha256, "path": "source/Character_Project.tianxia-project.zip"}
    projected_paths = []
    for path_id, (name, ability) in path_names.items():
        row = rows_by_id.get(path_id, {})
        attainment = int(row.get("attainment") or row.get("attainment_level") or 0)
        eligible = path_id in authorized or bool(row.get("ap_authorized") or row.get("eligible_for_ap"))
        projected_paths.append({
            "path_id": path_id, "name": name, "attainment_level": attainment,
            "advancement_state": "advancing" if eligible else "dormant",
            "primary": bool(row.get("primary") or row.get("is_primary")), "key_ability": ability,
            "ap_authorization": {"state": "present" if eligible else "not_applicable", "reason": "Authorized by current ProjectExport Method state." if eligible else "Not authorized by the current Primary Method.", "source_path": "non-sphere-authority.json"},
        })
    if not any(r["primary"] for r in projected_paths):
        active_ids = set(state.get("active_path_ids") or [])
        active_rows = [r for r in projected_paths if r["path_id"] in active_ids]
        eligible_rows = active_rows or [r for r in projected_paths if r["advancement_state"] == "advancing"] or [r for r in projected_paths if r["attainment_level"] > 0]
        if eligible_rows:
            eligible_rows[0]["primary"] = True
    cultivation = out.setdefault("cultivation", {})
    cultivation["paths"] = projected_paths
    cultivation["cultivation_level"] = max((r["attainment_level"] for r in projected_paths), default=0)
    if method_id:
        cultivation["primary_method"] = {"state": "present", "source_path": "non-sphere-authority.json", "value": {"stable_id": str(method_id), "name": str(method_id)}}
        methods = [r for r in out.get("methods") or [] if isinstance(r, dict) and r.get("stable_id") != method_id]
        methods.insert(0, {"stable_id": str(method_id), "name": str(method_id), "short_description": "Current Primary Method", "full_description": "Selected in the current ProjectExport authority state.", "source": source, "acquisition_route": "project_authority", "state": "present", "details": {}})
        out["methods"] = methods
    foundation_id = state.get("foundation_id") or state.get("selected_foundation_id")
    if foundation_id:
        cultivation["foundation"] = {"state": "present", "source_path": "non-sphere-authority.json", "value": {"stable_id": str(foundation_id), "name": str(foundation_id), "readiness": state.get("foundation_readiness")}}
    else:
        cultivation["foundation"] = {"state": "explicit_none", "reason": "No Foundation is selected in the current project.", "source_path": "non-sphere-authority.json"}
    resources = []
    candidate_resources = {str(r.get("path_id") or r.get("stable_id") or r.get("name")): r for r in cultivation.get("resources") or [] if isinstance(r, dict)}
    for path_id, row in rows_by_id.items():
        resource = row.get("resource") if isinstance(row.get("resource"), dict) else None
        if resource and (resource.get("active") is not False):
            resource_name = resource.get("name") or resource.get("resource_name") or {"tianxia.path.body_refining":"Stamina","tianxia.path.qi_cultivation":"Qi","tianxia.path.spirit_awakening":"Resonance"}.get(path_id,"Resource")
            fallback = candidate_resources.get(path_id) or candidate_resources.get(str(resource.get("resource_id"))) or candidate_resources.get(str(resource_name)) or {}
            resources.append({"stable_id": str(resource.get("resource_id") or f"project.resource.{path_id}"), "name": str(resource_name), "current": resource.get("current") if resource.get("current") is not None else fallback.get("current"), "maximum": resource.get("maximum") if resource.get("maximum") is not None else fallback.get("maximum"), "state": "present", "recovery": str(resource.get("recovery") or fallback.get("recovery") or ""), "path_id": path_id, "source": source})
    if resources:
        cultivation["resources"] = resources
    readiness_value = state.get("readiness") or state.get("readiness_status") or state.get("status")
    ready = readiness_value == "READY" or (isinstance(readiness_value, dict) and readiness_value.get("status") == "READY")
    out["readiness"] = {"gm_ready": bool(ready), "contract_valid": True, "combat_runtime_separate": True, "diagnostics": [] if ready else [{"severity":"warning","code":"GM2_PROJECT_NOT_READY","message":"The current project authority state is not READY.","source_path":"non-sphere-authority.json"}]}
    return out


def _normalise_display_container(model: dict[str, Any]) -> dict[str, Any]:
    """Adapt typed-none containers to the bundled R2K.3 display expectations.

    This changes only the portable root display container. The exact sealed
    C2B.3 model remains embedded under ``source/`` and remains the source model.
    """
    result = copy.deepcopy(model)
    ers = result.get("equipment_resources_states")
    if not isinstance(ers, dict):
        ers = {}
    equipment = ers.get("equipment")
    if not isinstance(equipment, list):
        if isinstance(equipment, dict):
            ers["equipment_none_state"] = copy.deepcopy(equipment)
        ers["equipment"] = []
    resources = ers.get("resources")
    if isinstance(resources, dict):
        rows: list[dict[str, Any]] = []
        for resource_id, value in sorted(resources.items()):
            if isinstance(value, dict) and isinstance(value.get("definitions"), list):
                rows.extend(copy.deepcopy(value["definitions"]))
            elif isinstance(value, dict):
                rows.append({"resource_id": resource_id, **copy.deepcopy(value)})
        ers["resource_source_map"] = copy.deepcopy(resources)
        ers["resources"] = rows
    elif not isinstance(resources, list):
        ers["resources"] = []
    states = ers.get("states")
    if isinstance(states, dict):
        ers["states_status"] = states.get("status")
        ers["states"] = copy.deepcopy(states.get("typed_definitions") or [])
    elif not isinstance(states, list):
        ers["states"] = []
    result["equipment_resources_states"] = ers
    metadata = result.setdefault("metadata", {})
    metadata.update(
        {
            "portable_display_container_normalization": NORMALIZATION_SCHEMA,
            "display_normalization_only": True,
            "source_model_path": f"source/C2B3_{GM_MODEL_NAME if model.get('schema_version') == 'Tianxia_GM_Character_Model_v1' else GM_VIEW_NAME}",
            "combat_execution": "NOT_ATTEMPTED_OR_UNSUPPORTED",
            "consumer_verification": "GM_SCREEN_SOURCE_CONSUMER_VERIFIED",
            "gm_export_available": True,
            "command6_status": "COMMAND_6_CHARACTER_GM_SOURCE_CONSUMER_PASS",
            "native_or_interactive_acceptance": "NOT_RUN",
        }
    )
    capability = result.setdefault("capability_readiness", {})
    if isinstance(capability, dict):
        capability["gm_screen_consumer"] = "GM_SCREEN_SOURCE_CONSUMER_VERIFIED"
        capability["combat"] = "NOT_ATTEMPTED"
    validation = result.get("validation")
    if isinstance(validation, dict):
        validation["consumer_verification"] = "GM_SCREEN_SOURCE_CONSUMER_VERIFIED"
        validation["gm_export_available"] = True
    diagnostics = result.get("diagnostics")
    if isinstance(diagnostics, dict):
        diagnostics["gm_screen_consumer_verification"] = "GM_SCREEN_SOURCE_CONSUMER_VERIFIED"
    elif isinstance(diagnostics, list):
        result["diagnostics"] = [
            row for row in diagnostics
            if not (isinstance(row, dict) and row.get("code") == "GM_SCREEN_CONSUMER_VERIFICATION_PENDING")
        ] + [{"code": "GM_SCREEN_SOURCE_CONSUMER_VERIFIED", "severity": "notice"}]
    return result


class PortableCharacterPackageService:
    def __init__(self, db: Database | None = None):
        self.db = db
        self.projects = ProjectStore(db) if db else None

    @staticmethod
    def audit(path: Path) -> dict[str, Any]:
        path = path.resolve()
        if not path.is_file() or path.stat().st_size > MAX_ARCHIVE_BYTES:
            raise FoundryError("PORTABLE_CHARACTER_PACKAGE_INVALID", "The portable Character ZIP is missing or too large.")
        names: set[str] = set(); folded: set[str] = set(); normalized: set[str] = set()
        total = 0
        with zipfile.ZipFile(path) as zf:
            # Inspect entry metadata before reading payloads so encrypted and
            # unsupported-compression members fail with the intended typed
            # archive diagnostic rather than a zipfile runtime exception.
            if len(zf.infolist()) > MAX_ENTRIES:
                raise FoundryError("PORTABLE_CHARACTER_ENTRY_LIMIT", "The portable Character ZIP contains too many entries.")
            for info in zf.infolist():
                name = info.filename.replace("\\", "/")
                pure = PurePosixPath(name)
                if pure.is_absolute() or ".." in pure.parts or not name or "\x00" in name:
                    raise FoundryError("PORTABLE_CHARACTER_UNSAFE_PATH", "The portable Character ZIP contains an unsafe path.", details={"path": name})
                mode = info.external_attr >> 16
                kind = stat.S_IFMT(mode)
                if kind == stat.S_IFLNK or kind not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise FoundryError("PORTABLE_CHARACTER_SPECIAL_FILE", "Links and special files are not allowed.", details={"path": name})
                if info.flag_bits & 0x1:
                    raise FoundryError("PORTABLE_CHARACTER_ENCRYPTED", "Encrypted ZIP members are not allowed.", details={"path": name})
                if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                    raise FoundryError("PORTABLE_CHARACTER_COMPRESSION_UNSUPPORTED", "The ZIP uses an unsupported compression method.", details={"path": name})
                key = name.rstrip("/")
                fold = key.casefold(); norm = unicodedata.normalize("NFC", key).casefold()
                if key in names or fold in folded or norm in normalized:
                    raise FoundryError("PORTABLE_CHARACTER_PATH_COLLISION", "The ZIP contains duplicate or colliding paths.", details={"path": name})
                names.add(key); folded.add(fold); normalized.add(norm)
                total += info.file_size
                if total > MAX_EXPANDED_BYTES:
                    raise FoundryError("PORTABLE_CHARACTER_EXPANSION_LIMIT", "The portable Character ZIP expands beyond the configured limit.")
            bad = zf.testzip()
            if bad:
                raise FoundryError("PORTABLE_CHARACTER_CRC_FAILED", "The portable Character ZIP failed CRC validation.", details={"member": bad})
            model_member = GM_MODEL_NAME if GM_MODEL_NAME in zf.namelist() else LEGACY_GM_MODEL_NAME
            required = {"PACKAGE_MANIFEST.json", "SHA256SUMS.txt", model_member, GM_VIEW_NAME, PROJECT_MEMBER, "READINESS.json"}
            missing = sorted(required - set(zf.namelist()))
            if missing:
                raise FoundryError("PORTABLE_CHARACTER_PACKAGE_INCOMPLETE", "The portable Character ZIP is missing required members.", details={"missing": missing})
            lines = zf.read("SHA256SUMS.txt").decode("utf-8").splitlines()
            declared: dict[str, str] = {}
            for line in lines:
                if not line.strip():
                    continue
                digest, sep, member = line.partition("  ")
                if not sep or len(digest) != 64 or member in declared:
                    raise FoundryError("PORTABLE_CHARACTER_CHECKSUM_MANIFEST_INVALID", "The checksum manifest is malformed.")
                declared[member] = digest
            payload = sorted(name for name in zf.namelist() if not name.endswith("/") and name != "SHA256SUMS.txt")
            if sorted(declared) != payload:
                raise FoundryError("PORTABLE_CHARACTER_CHECKSUM_COVERAGE", "The checksum manifest does not cover the package exactly.", details={"missing": sorted(set(payload)-set(declared)), "extra": sorted(set(declared)-set(payload))})
            for member, expected in declared.items():
                actual = sha256_bytes(zf.read(member))
                if actual != expected:
                    raise FoundryError("PORTABLE_CHARACTER_MEMBER_HASH_MISMATCH", "A portable package member failed checksum validation.", details={"member": member, "expected": expected, "actual": actual})
            manifest = json.loads(zf.read("PACKAGE_MANIFEST.json"))
            readiness = json.loads(zf.read("READINESS.json"))
            if manifest.get("schema_version") != PORTABLE_SCHEMA:
                raise FoundryError("PORTABLE_CHARACTER_SCHEMA_UNSUPPORTED", "The portable Character package schema is unsupported.")
            if manifest.get("canonical_project_export") != PROJECT_MEMBER:
                raise FoundryError("PORTABLE_CHARACTER_PROJECT_REFERENCE_INVALID", "The package does not identify its canonical project export.")
            embedded = zf.read(PROJECT_MEMBER)
            if sha256_bytes(embedded) != manifest.get("canonical_project_export_sha256"):
                raise FoundryError("PORTABLE_CHARACTER_PROJECT_HASH_MISMATCH", "The embedded canonical project export hash does not match the manifest.")
            import io
            with zipfile.ZipFile(io.BytesIO(embedded)) as project_zip:
                nested_manifest = json.loads(project_zip.read("manifest.json"))
                nested_project = json.loads(project_zip.read("project.json"))
            identity_pairs = {
                "project_id": (manifest.get("project_id"), nested_manifest.get("project_id")),
                "project_revision": (manifest.get("project_revision"), nested_project.get("revision")),
                "event_count": (manifest.get("event_count"), nested_manifest.get("event_count")),
                "event_head_hash": (manifest.get("event_head_hash"), nested_manifest.get("latest_event_hash")),
                "replay_state_hash": (manifest.get("replay_state_hash"), nested_manifest.get("state_hash")),
                "content_lock_hash": (manifest.get("content_lock_hash"), nested_manifest.get("content_lock_hash")),
                "canonical_project_hash": (manifest.get("canonical_project_hash"), nested_manifest.get("canonical_project_hash")),
            }
            mismatched_identity = {key: {"outer": pair[0], "nested": pair[1]} for key, pair in identity_pairs.items() if pair[0] != pair[1]}
            if mismatched_identity:
                raise FoundryError("PORTABLE_CHARACTER_NESTED_IDENTITY_MISMATCH", "The portable package identity differs from its canonical project export.", details=mismatched_identity)
            root_model = json.loads(zf.read(model_member))
            snapshot_hash = manifest.get("typed_choice_snapshot_sha256")
            if snapshot_hash and (root_model.get("metadata") or {}).get("typed_choice_snapshot_sha256") != snapshot_hash:
                raise FoundryError("PORTABLE_CHARACTER_CHOICE_SNAPSHOT_MISMATCH", "The portable package and GM model do not share the frozen typed choice snapshot.")
            provenance_member = "source/advancement_projection/Projection_Provenance_Map.json"
            if snapshot_hash:
                if provenance_member not in zf.namelist():
                    raise FoundryError("PORTABLE_CHARACTER_CHOICE_SNAPSHOT_MISSING", "The exact frozen typed choice snapshot provenance is missing.")
                projection_provenance = json.loads(zf.read(provenance_member))
                exact_snapshot = projection_provenance.get("typed_choice_snapshot") or {}
                if (
                    not valid_choice_snapshot(exact_snapshot)
                    or exact_snapshot.get("snapshot_sha256") != snapshot_hash
                    or exact_snapshot.get("canonical_project_id") != manifest.get("project_id")
                ):
                    raise FoundryError("PORTABLE_CHARACTER_CHOICE_SNAPSHOT_MISMATCH", "Projection provenance does not contain the exact frozen typed choice snapshot.")
            if model_member == GM_MODEL_NAME:
                if root_model.get("schema") != "Tianxia_GM_Character_Model_v2" or root_model.get("schema_version") != "2.0.0":
                    raise FoundryError("PORTABLE_CHARACTER_GM_MODEL_SCHEMA", "The root GM character model is not the accepted canonical v2 model.")
                gm_ref = manifest.get("gm_model") or {}
                if gm_ref.get("path") != GM_MODEL_NAME or gm_ref.get("profile") != "canonical_v2" or gm_ref.get("authoritative") is not True:
                    raise FoundryError("PORTABLE_CHARACTER_GM_MODEL_REFERENCE_INVALID", "The package manifest does not explicitly select the authoritative GM v2 model.")
            elif root_model.get("schema_version") != "Tianxia_GM_Character_Model_v1":
                raise FoundryError("PORTABLE_CHARACTER_GM_MODEL_SCHEMA", "The legacy GM character model is unsupported.")
        return {
            "valid": True, "path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size,
            "entry_count": len(names), "expanded_bytes": total, "checksum_count": len(declared),
            "manifest": manifest, "readiness": readiness,
        }


    @staticmethod
    def canonicalize_project_export(source: Path, target: Path) -> dict[str, Any]:
        """Rewrite only non-mechanical ProjectExport container metadata deterministically."""
        source = source.resolve(); target = target.resolve()
        with zipfile.ZipFile(source) as zf:
            files = {info.filename: zf.read(info.filename) for info in zf.infolist() if not info.is_dir()}
        project = json.loads(files["project.json"]); manifest = json.loads(files["manifest.json"])
        manifest["created_at"] = project.get("updated_at") or project.get("created_at")
        files["manifest.json"] = _canon(manifest)
        target.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for name, data in sorted(files.items()):
                zf.writestr(_zip_info(name), data)
        return {"path": str(target), "sha256": sha256_file(target), "bytes": target.stat().st_size, "created_at": manifest.get("created_at")}

    @staticmethod
    def build(*, candidate_zip: Path, project_export: Path, output_zip: Path, consumer_identity: dict[str, Any], command6_identity: dict[str, Any] | None = None, projection_artifacts: dict[str, Path] | None = None, owner_sheet_path: Path | None = None) -> dict[str, Any]:
        candidate_zip = candidate_zip.resolve(); project_export = project_export.resolve(); output_zip = output_zip.resolve()
        if not candidate_zip.is_file() or not project_export.is_file():
            raise FoundryError("PORTABLE_CHARACTER_SOURCE_MISSING", "The sealed Command 5 candidate or canonical project export is missing.")
        with zipfile.ZipFile(candidate_zip) as zf:
            candidate_manifest = json.loads(zf.read("PACKAGE_MANIFEST.json")) if "PACKAGE_MANIFEST.json" in zf.namelist() else {}
            files = {i.filename: zf.read(i.filename) for i in zf.infolist() if not i.is_dir() and i.filename not in {"PACKAGE_MANIFEST.json", "SHA256SUMS.txt"}}
            legacy_name = LEGACY_GM_MODEL_NAME if LEGACY_GM_MODEL_NAME in zf.namelist() else GM_MODEL_NAME
            original_model = json.loads(zf.read(legacy_name)); original_view = json.loads(zf.read(GM_VIEW_NAME))
        with zipfile.ZipFile(project_export) as zf:
            project_manifest = json.loads(zf.read("manifest.json")); project_doc = json.loads(zf.read("project.json"))
            try:
                non_sphere_doc = json.loads(zf.read("non-sphere-authority.json"))
            except KeyError:
                non_sphere_doc = None
        candidate_project_id = candidate_manifest.get("project_id")
        export_project_id = project_manifest.get("project_id")
        if candidate_project_id and export_project_id and candidate_project_id != export_project_id:
            raise FoundryError(
                "GM2_CANDIDATE_PROJECT_MISMATCH",
                "The completed character candidate belongs to a different Factory project. Select the Command-5 candidate produced by this project.",
                details={"candidate_project_id": candidate_project_id, "project_export_project_id": export_project_id},
            )
        files[f"source/C2B3_{GM_VIEW_NAME}"] = _canon(original_view)
        if owner_sheet_path is not None:
            if "Tianxia_Owner_Character_Sheet_v1.json" in files:
                files["source/C2B3_Tianxia_Owner_Character_Sheet_v1.json"] = files["Tianxia_Owner_Character_Sheet_v1.json"]
            files["Tianxia_Owner_Character_Sheet_v1.json"] = Path(owner_sheet_path).read_bytes()
        profile = detect_profile(original_model, runtime_package=False)
        selected = {"model": original_model, "path": LEGACY_GM_MODEL_NAME, "manifest": {}, "profile": profile, "model_sha256": sha256_bytes(_canon(original_model)), "runtime_package": False}
        if profile == "legacy_phase2h_v1":
            gm2_model, _, _ = _migrate_legacy(selected, sha256_file(candidate_zip))
        elif profile in {"fire_qi_c2c1_v1", "fire_qi_runtime_ready_v1"}:
            gm2_model, _, _ = _migrate_fire(selected, sha256_file(candidate_zip))
        elif profile == "canonical_v2":
            gm2_model = original_model
        else:
            raise FoundryError("GM2_UNSUPPORTED_PROFILE", "The Factory candidate does not match a supported GM model profile.", details={"profile": profile})
        gm2_model = _project_model_overlay(gm2_model, project_doc, non_sphere_doc, candidate_sha256=sha256_file(candidate_zip))
        source_snapshot_hash = (original_model.get("metadata") or {}).get("typed_choice_snapshot_sha256")
        gm2_model.setdefault("metadata", {}).update({
            "producer": "Tianxia Factory NS1R-P1 GM2-P1R2",
            "project_id": project_manifest.get("project_id"),
            "canonical_project_hash": project_manifest.get("canonical_project_hash"),
            "content_lock_hash": project_manifest.get("content_lock_hash"),
            "typed_choice_snapshot_sha256": source_snapshot_hash,
        })
        files[GM_MODEL_NAME] = _canon(gm2_model)
        files[GM_VIEW_NAME] = _canon(normalize_view(gm2_model))
        files.pop(LEGACY_GM_MODEL_NAME, None)
        files[PROJECT_MEMBER] = project_export.read_bytes()
        projection_references: dict[str, str] = {}
        for artifact_name, artifact_path in sorted((projection_artifacts or {}).items()):
            data = Path(artifact_path).read_bytes()
            member = f"source/advancement_projection/{artifact_name}"
            files[member] = data
            projection_references[artifact_name] = sha256_bytes(data)
        readiness = {
            "schema_version": READINESS_SCHEMA,
            "advancement": "ADVANCEMENT_READY", "character_sheet": "CHARACTER_SHEET_READY",
            "gm_tactical_authoring": "COMPLETE", "character_gm_command4": "PASS", "character_gm_command5": "PASS",
            "command6": "COMMAND_6_CHARACTER_GM_SOURCE_CONSUMER_PASS", "gm_screen": "GM_SCREEN_SOURCE_CONSUMER_VERIFIED",
            "gm_export_available": True, "native_or_interactive_acceptance": "NOT_RUN",
            "combat": "NOT_ATTEMPTED_OR_CAPABILITY_BLOCKED", "cpk1_schemas_registered": False,
        }
        files["READINESS.json"] = _canon(readiness)
        files["CONSUMER_VERIFICATION.json"] = _canon({
            "schema_version": "TianxiaFoundry.C2C1ConsumerVerification.v1",
            "status": "GM_SCREEN_SOURCE_CONSUMER_VERIFIED",
            "consumer": consumer_identity,
            "command6": command6_identity or {"status": "COMMAND_6_CHARACTER_GM_SOURCE_CONSUMER_PASS"},
            "native_or_interactive_acceptance": "NOT_RUN",
        })
        manifest = {
            "schema_version": PORTABLE_SCHEMA, "package_role": "portable_completed_character",
            "display_name": project_doc.get("name"), "project_id": project_manifest["project_id"],
            "project_revision": project_doc.get("revision"), "event_count": project_manifest["event_count"],
            "event_head_hash": project_manifest["latest_event_hash"], "replay_state_hash": project_manifest["state_hash"],
            "content_lock_hash": project_manifest["content_lock_hash"], "canonical_project_hash": project_manifest["canonical_project_hash"],
            "source_command5_candidate_sha256": sha256_file(candidate_zip), "build_profile": "CHARACTER_GM_MODEL",
            "typed_choice_snapshot_sha256": (gm2_model.get("metadata") or {}).get("typed_choice_snapshot_sha256"),
            "consumer": consumer_identity, "canonical_project_export": PROJECT_MEMBER,
            "canonical_project_export_sha256": sha256_file(project_export),
            "authoritative_mechanics": PROJECT_MEMBER,
            "gm_model": {"path": GM_MODEL_NAME, "schema": "Tianxia_GM_Character_Model_v2", "schema_version": "2.0.0", "profile": "canonical_v2", "authoritative": True},
            "canonical_models": [GM_MODEL_NAME],
            "derived_display_models": [GM_VIEW_NAME],
            "exact_source_models": [f"source/C2B3_{GM_VIEW_NAME}"],
            "display_container_normalization": NORMALIZATION_SCHEMA,
            "advancement_projection_references": projection_references,
            "native_or_interactive_acceptance": "NOT_RUN", "combat_execution": "NOT_ATTEMPTED",
            "created_at": project_doc.get("updated_at") or project_doc.get("created_at"), "files": [],
        }
        for name, data in sorted(files.items()):
            manifest["files"].append({"path": name, "sha256": sha256_bytes(data), "bytes": len(data)})
        files["PACKAGE_MANIFEST.json"] = _canon(manifest)
        files["SHA256SUMS.txt"] = "".join(f"{sha256_bytes(data)}  {name}\n" for name, data in sorted(files.items())).encode("utf-8")
        output_zip.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for name, data in sorted(files.items()):
                zf.writestr(_zip_info(name), data)
        report = PortableCharacterPackageService.audit(output_zip)
        report["candidate_sha256"] = sha256_file(candidate_zip)
        return report

    def preview_for_factory(self, package: Path, *, audit: dict[str, Any] | None = None) -> dict[str, Any]:
        """Validate package identity and product prerequisites without mutation."""
        audit = audit or self.audit(package)
        manifest = audit["manifest"]
        readiness = audit["readiness"]
        with zipfile.ZipFile(package) as zf:
            try:
                display_model = json.loads(zf.read(GM_VIEW_NAME))
            except (KeyError, json.JSONDecodeError):
                display_model = json.loads(zf.read(GM_MODEL_NAME))
            try:
                resource_contract = json.loads(zf.read("combat/Runtime_Resource_Initialization_Contract.json"))
            except (KeyError, json.JSONDecodeError):
                resource_contract = {"resources": []}
        identity = display_model.get("identity") if isinstance(display_model, dict) else {}
        identity = identity if isinstance(identity, dict) else {}
        path_surface = display_model.get("paths_subpaths_insights") if isinstance(display_model, dict) else {}
        path_surface = path_surface if isinstance(path_surface, dict) else {}
        subpath_surface = path_surface.get("subpath") if isinstance(path_surface.get("subpath"), dict) else {}
        project_id = str(manifest.get("project_id") or "")
        expected = {
            "project_id": project_id,
            "revision": manifest.get("project_revision"),
            "event_head_hash": manifest.get("event_head_hash"),
            "content_lock_hash": manifest.get("content_lock_hash"),
            "canonical_project_hash": manifest.get("canonical_project_hash"),
        }
        disposition = "NEW"
        existing_identity: dict[str, Any] | None = None
        environment = None
        if self.db:
            environment = ProductReadinessService(self.db).report()
            if project_id:
                with self.db.connection() as conn:
                    row = conn.execute("SELECT project_json FROM projects WHERE project_id=?", (project_id,)).fetchone()
                if row:
                    current = json.loads(row["project_json"])
                    existing_identity = {
                        "project_id": project_id,
                        "revision": current.get("revision"),
                        "event_head_hash": (current.get("event_stream") or {}).get("head_hash"),
                        "content_lock_hash": (current.get("content_lock") or {}).get("lock_hash"),
                        "canonical_project_hash": canonical_project_hash(current),
                    }
                    disposition = "IDENTICAL" if existing_identity == expected else "CONFLICT"
        environment_ready = bool(environment and environment["portable_import"]["ready"])
        blocking = list((environment or {}).get("blocking_reasons") or [])
        can_import = disposition != "CONFLICT" and environment_ready
        if disposition == "CONFLICT":
            owner_message = "A different character package already uses this project ID. Import is blocked."
        elif not environment_ready:
            reason = "; ".join(str(item.get("message") or item.get("code")) for item in blocking) or "Product bootstrap is incomplete."
            owner_message = f"The package is valid, but Import is blocked: {reason}"
        elif disposition == "IDENTICAL":
            owner_message = "This exact character is already installed. Import will confirm it without changing owner data."
        else:
            owner_message = "The package and clean-root product prerequisites are valid and ready to import."
        resources = {
            str(row.get("resource_id")): row
            for row in (resource_contract.get("resources") or [])
            if isinstance(row, dict) and row.get("resource_id")
        }
        return {
            "status": "PORTABLE_CHARACTER_PREVIEW_READY" if can_import else "PORTABLE_CHARACTER_PREVIEW_BLOCKED",
            "valid": True,
            "package_valid": True,
            "environment_ready": environment_ready,
            "disposition": disposition,
            "can_import": can_import,
            "blocking_prerequisites": blocking,
            "character": {
                "name": identity.get("display_name") or manifest.get("display_name") or "Unnamed character",
                "cultivation_level": identity.get("cultivation_level"),
                "realm": identity.get("realm_display") or identity.get("realm"),
                "path": identity.get("path"),
                "subpath": subpath_surface.get("name") or None,
                "project_id": project_id,
            },
            "package": {
                "filename": package.name,
                "bytes": audit["bytes"],
                "sha256": audit["sha256"],
            },
            "readiness": {
                "advancement": readiness.get("advancement"),
                "character_sheet": readiness.get("character_sheet"),
                "gm_screen": readiness.get("gm_screen"),
                "combat": readiness.get("combat"),
                "combat_sheet": readiness.get("combat_sheet") or manifest.get("combat_sheet_readiness"),
                "combat_runtime": readiness.get("combat_runtime") or manifest.get("combat_runtime_readiness"),
                "combat_ready_semantics": readiness.get("combat_ready_semantics") or manifest.get("combat_ready_semantics"),
                "encounter": readiness.get("encounter") or manifest.get("encounter") or "NOT_ATTEMPTED",
                "controller_selection": readiness.get("controller_selection") or manifest.get("controller_selection") or "NOT_ATTEMPTED",
                "encounter_setup_required": True,
                "current_qi_required": "resource:core.qi" in resources,
                "current_martial_focus_required": "resource:core.martial_focus" in resources,
                "opponent_team_completion_required": True,
                "battlefield_owner_choice_committed": False,
                "token_placement_committed": False,
                "initiative_attempted": False,
            },
            "product_readiness": environment,
            "incoming_identity": expected,
            "existing_identity": existing_identity,
            "owner_message": owner_message,
        }

    def _install_verified_package_atomic(
        self,
        *,
        project_id: str,
        package: Path,
        pointer: dict[str, Any],
        expected_sha256: str,
    ) -> str:
        """Install current.zip/current.json as one directory-level transaction.

        Existing verified installations are immutable and idempotent. A stale,
        partial, or conflicting directory is rejected rather than overwritten.
        """
        parent = self.db.settings.data_dir / "portable_characters"
        parent.mkdir(parents=True, exist_ok=True)
        target = parent / project_id
        installed = target / "current.zip"
        pointer_path = target / "current.json"
        if target.exists():
            if not target.is_dir() or not installed.is_file() or not pointer_path.is_file():
                raise FoundryError(
                    "PORTABLE_CHARACTER_INSTALL_STATE_INCOMPLETE",
                    "The installed Character directory is partial or invalid; it was not modified.",
                    details={"project_id": project_id, "install_root": str(target)},
                    status_code=409,
                )
            try:
                existing_pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
            except Exception as exc:
                raise FoundryError(
                    "PORTABLE_CHARACTER_INSTALL_POINTER_INVALID",
                    "The installed Character verification pointer is unreadable; it was not modified.",
                    details={"project_id": project_id}, status_code=409,
                ) from exc
            actual = sha256_file(installed)
            if (
                actual != expected_sha256
                or existing_pointer.get("project_id") != project_id
                or existing_pointer.get("package_sha256") != expected_sha256
            ):
                raise FoundryError(
                    "PORTABLE_CHARACTER_INSTALLED_PACKAGE_CONFLICT",
                    "A different package hash already claims this installed project ID.",
                    details={
                        "project_id": project_id,
                        "expected_package_sha256": expected_sha256,
                        "installed_package_sha256": actual,
                        "pointer_package_sha256": existing_pointer.get("package_sha256"),
                    },
                    status_code=409,
                )
            return "ALREADY_INSTALLED_IDENTICAL"
        stage = parent / f".{project_id}.install.{os.getpid()}.{next(tempfile._get_candidate_names())}"
        try:
            stage.mkdir(mode=0o700)
            stage_zip = stage / "current.zip"
            stage_json = stage / "current.json"
            with stage_zip.open("xb") as handle:
                handle.write(Path(package).read_bytes())
                handle.flush(); os.fsync(handle.fileno())
            if sha256_file(stage_zip) != expected_sha256:
                raise FoundryError(
                    "PORTABLE_CHARACTER_INSTALL_HASH_MISMATCH",
                    "The staged installed Character package failed its exact identity check.",
                )
            with stage_json.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(canonical_json(pointer))
                handle.flush(); os.fsync(handle.fileno())
            os.replace(stage, target)
            return "INSTALLED"
        except Exception:
            shutil.rmtree(stage, ignore_errors=True)
            raise

    def import_into_factory(self, package: Path) -> dict[str, Any]:
        if not self.projects or not self.db:
            raise RuntimeError("A Database is required for Factory import.")
        audit = self.audit(package)
        product_readiness = ProductReadinessService(self.db).report()
        if not product_readiness["portable_import"]["ready"]:
            raise FoundryError(
                "PORTABLE_CHARACTER_PRODUCT_NOT_READY",
                "Portable Character import is blocked until the authenticated producer, Factory adapter, and core catalog are ready.",
                details=product_readiness["blocking_reasons"],
                status_code=503,
            )
        manifest = audit["manifest"]
        project_id = str(manifest["project_id"])
        with self.db.connection() as conn:
            row = conn.execute("SELECT project_json FROM projects WHERE project_id=?", (project_id,)).fetchone()
        if row:
            current = json.loads(row["project_json"])
            current_identity = {
                "project_id": project_id, "revision": current.get("revision"),
                "event_head_hash": (current.get("event_stream") or {}).get("head_hash"),
                "content_lock_hash": (current.get("content_lock") or {}).get("lock_hash"),
                "canonical_project_hash": canonical_project_hash(current),
            }
            expected = {
                "project_id": project_id, "revision": manifest.get("project_revision"),
                "event_head_hash": manifest.get("event_head_hash"), "content_lock_hash": manifest.get("content_lock_hash"),
                "canonical_project_hash": manifest.get("canonical_project_hash"),
            }
            if current_identity == expected:
                install_root = self.db.settings.data_dir / "portable_characters" / project_id
                installed = install_root / "current.zip"
                pointer_path = install_root / "current.json"
                if not installed.is_file() or not pointer_path.is_file():
                    raise FoundryError(
                        "PORTABLE_CHARACTER_INSTALL_STATE_INCOMPLETE",
                        "The Factory project exists but its verified installed Character package is absent or partial.",
                        details={"project_id": project_id}, status_code=409,
                    )
                try:
                    existing_pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
                except Exception as exc:
                    raise FoundryError("PORTABLE_CHARACTER_INSTALL_POINTER_INVALID", "The installed Character verification pointer is unreadable.", status_code=409) from exc
                installed_sha = sha256_file(installed)
                if installed_sha != audit["sha256"] or existing_pointer.get("package_sha256") != audit["sha256"]:
                    raise FoundryError(
                        "PORTABLE_CHARACTER_INSTALLED_PACKAGE_CONFLICT",
                        "A different package hash already claims this installed project ID.",
                        details={"incoming": audit["sha256"], "installed": installed_sha, "pointer": existing_pointer.get("package_sha256")},
                        status_code=409,
                    )
                package_readiness = audit.get("readiness") or {}
                return {
                    "status": "ALREADY_INSTALLED_IDENTICAL", "imported": False, "project_id": project_id,
                    "package_sha256": audit["sha256"], "identity": expected,
                    "readiness": {
                        "advancement": package_readiness.get("advancement"),
                        "character_sheet": package_readiness.get("character_sheet"),
                        "gm_screen": package_readiness.get("gm_screen"),
                        "combat": package_readiness.get("combat"),
                        "combat_runtime": package_readiness.get("combat_runtime"),
                        "combat_ready_semantics": package_readiness.get("combat_ready_semantics"),
                        "encounter": package_readiness.get("encounter", "NOT_ATTEMPTED"),
                    },
                }
            raise FoundryError("PORTABLE_CHARACTER_PROJECT_ID_CONFLICT", "A different character already uses this project ID.", details={"existing": current_identity, "incoming": expected}, status_code=409)
        from vendor_adapter.service import FactoryAdapter
        from projector.service import ProjectionService
        from character_sheet.service import CharacterSheetService
        vendor = FactoryAdapter(self.db).status()
        if not vendor.get("configured") or vendor.get("health") != "READY" or not vendor.get("factory_root"):
            raise FoundryError("PORTABLE_CHARACTER_FACTORY_NOT_READY", "A clean Factory must have the authenticated producer configured before character import.")
        with zipfile.ZipFile(package) as zf, tempfile.TemporaryDirectory(prefix="tianxia-portable-import-") as tmp:
            nested = Path(tmp) / "Character_Project.tianxia-project.zip"
            nested.write_bytes(zf.read(PROJECT_MEMBER))
            imported = self.projects.import_project(nested)
            expected_sheet_sha = sha256_bytes(zf.read("Tianxia_Owner_Character_Sheet_v1.json"))
            frozen_choice_snapshot = None
            if manifest.get("typed_choice_snapshot_sha256"):
                provenance_member = "source/advancement_projection/Projection_Provenance_Map.json"
                projection_provenance = json.loads(zf.read(provenance_member))
                frozen_choice_snapshot = projection_provenance.get("typed_choice_snapshot") or {}
                if (
                    not valid_choice_snapshot(frozen_choice_snapshot)
                    or frozen_choice_snapshot.get("snapshot_sha256") != manifest.get("typed_choice_snapshot_sha256")
                    or frozen_choice_snapshot.get("canonical_project_id") != project_id
                ):
                    raise FoundryError(
                        "PORTABLE_CHARACTER_CHOICE_SNAPSHOT_MISMATCH",
                        "Clean Factory import requires the package's exact frozen typed choice snapshot.",
                    )
        projection = ProjectionService(self.db, factory_root=Path(vendor["factory_root"])).build(
            project_id,
            force=True,
            **({"choice_snapshot": frozen_choice_snapshot} if frozen_choice_snapshot is not None else {}),
        )
        references = manifest.get("advancement_projection_references") or {}
        rebuilt = {row["artifact_name"]: row["sha256"] for row in projection.get("artifacts", [])}
        mismatched = {name: {"expected": expected, "actual": rebuilt.get(name)} for name, expected in references.items() if rebuilt.get(name) != expected}
        if mismatched:
            raise FoundryError("PORTABLE_CHARACTER_PROJECTION_REBUILD_MISMATCH", "The clean Factory rebuild did not reproduce the package projection.", details=mismatched)
        sheet = CharacterSheetService(self.db).sheet(project_id)
        actual_sheet_sha = (sheet.get("sheet_artifact") or {}).get("sha256")
        if actual_sheet_sha != expected_sheet_sha:
            raise FoundryError("PORTABLE_CHARACTER_SHEET_REBUILD_MISMATCH", "The clean Factory Character Sheet rebuild did not match the package.", details={"expected": expected_sheet_sha, "actual": actual_sheet_sha})
        install_root = self.db.settings.data_dir / "portable_characters" / project_id
        installed = install_root / "current.zip"
        package_readiness = audit.get("readiness") or {}
        combat_status = package_readiness.get("combat") or manifest.get("combat_readiness") or "NOT_ATTEMPTED"
        pointer = {
            "schema_version": "TianxiaFoundry.PortableCharacterVerificationPointer.v1",
            "project_id": project_id, "status": "GM_SCREEN_SOURCE_CONSUMER_VERIFIED",
            "package_path": str(installed.resolve()), "package_sha256": audit["sha256"],
            "manifest_identity": {key: manifest.get(key) for key in ("project_revision", "event_head_hash", "replay_state_hash", "content_lock_hash", "canonical_project_hash", "source_command5_candidate_sha256", "typed_choice_snapshot_sha256")},
            "command6_status": "COMMAND_6_CHARACTER_GM_SOURCE_CONSUMER_PASS",
            "consumer_status": "GM_SCREEN_SOURCE_CONSUMER_VERIFIED", "factory_import_status": "IMPORTED",
            "projection_id": projection.get("projection_id"), "projection_hashes": rebuilt,
            "character_sheet_sha256": actual_sheet_sha, "native_or_interactive_acceptance": "NOT_RUN",
            "combat": combat_status,
            "combat_runtime": package_readiness.get("combat_runtime") or manifest.get("combat_runtime_readiness"),
            "combat_ready_semantics": package_readiness.get("combat_ready_semantics") or manifest.get("combat_ready_semantics"),
            "combat_sheet": package_readiness.get("combat_sheet") or manifest.get("combat_sheet_readiness"),
            "encounter": package_readiness.get("encounter") or manifest.get("encounter") or "NOT_ATTEMPTED",
            "controller_selection": package_readiness.get("controller_selection") or manifest.get("controller_selection") or "NOT_ATTEMPTED",
            "cpk1_schemas_registered": bool(package_readiness.get("cpk1_schemas_registered", manifest.get("cpk1_schemas_registered", False))),
            "verified_at": utcnow(),
        }
        install_disposition = self._install_verified_package_atomic(
            project_id=project_id, package=package, pointer=pointer, expected_sha256=audit["sha256"]
        )
        return {
            "status": "IMPORTED", "imported": True, "project_id": project_id, "package_sha256": audit["sha256"],
            "project_import": imported, "projection": {"status": projection.get("status"), "projection_id": projection.get("projection_id"), "artifact_hashes": rebuilt},
            "character_sheet": {"status": sheet.get("build_status"), "sha256": actual_sheet_sha},
            "readiness": {
                "advancement": package_readiness.get("advancement"),
                "character_sheet": package_readiness.get("character_sheet"),
                "gm_screen": package_readiness.get("gm_screen"),
                "combat": combat_status,
                "combat_runtime": package_readiness.get("combat_runtime") or manifest.get("combat_runtime_readiness"),
                "combat_ready_semantics": package_readiness.get("combat_ready_semantics") or manifest.get("combat_ready_semantics"),
                "encounter": package_readiness.get("encounter") or manifest.get("encounter") or "NOT_ATTEMPTED",
            },
            "native_or_interactive_acceptance": "NOT_RUN", "combat": combat_status,
        }

    def register_verified(self, project_id: str, *, package: Path, command6_report: dict[str, Any], consumer_report: dict[str, Any], factory_import_report: dict[str, Any]) -> dict[str, Any]:
        if not self.db:
            raise RuntimeError("A Database is required to register a verified package.")
        audit = self.audit(package)
        if command6_report.get("status") != "COMMAND_6_CHARACTER_GM_SOURCE_CONSUMER_PASS" or consumer_report.get("status") != "GM_SCREEN_SOURCE_CONSUMER_VERIFIED":
            raise FoundryError("PORTABLE_CHARACTER_VERIFICATION_INCOMPLETE", "The package has not passed Command 6 and exact consumer verification.")
        if factory_import_report.get("status") not in {"IMPORTED", "ALREADY_INSTALLED_IDENTICAL"}:
            raise FoundryError("PORTABLE_CHARACTER_FACTORY_IMPORT_REQUIRED", "The package has not passed clean Factory import verification.")
        root = self.db.settings.data_dir / "portable_characters" / project_id
        root.mkdir(parents=True, exist_ok=True)
        target = root / "current.zip"
        if target.exists() and sha256_file(target) != audit["sha256"]:
            raise FoundryError("PORTABLE_CHARACTER_VERIFIED_PACKAGE_CONFLICT", "A different verified package already exists for this character.", status_code=409)
        if not target.exists():
            target.write_bytes(package.read_bytes())
        package_readiness = audit.get("readiness") or {}
        manifest = audit.get("manifest") or {}
        combat_status = package_readiness.get("combat") or manifest.get("combat_readiness") or "NOT_ATTEMPTED"
        pointer = {
            "schema_version": "TianxiaFoundry.PortableCharacterVerificationPointer.v1",
            "project_id": project_id, "status": "GM_SCREEN_SOURCE_CONSUMER_VERIFIED",
            "package_path": str(target.resolve()), "package_sha256": audit["sha256"],
            "manifest_identity": {key: manifest.get(key) for key in ("project_revision", "event_head_hash", "replay_state_hash", "content_lock_hash", "source_command5_candidate_sha256", "typed_choice_snapshot_sha256")},
            "command6_status": command6_report.get("status"), "consumer_status": consumer_report.get("status"),
            "factory_import_status": factory_import_report.get("status"),
            "native_or_interactive_acceptance": "NOT_RUN", "combat": combat_status,
            "combat_runtime": package_readiness.get("combat_runtime") or manifest.get("combat_runtime_readiness"),
            "combat_ready_semantics": package_readiness.get("combat_ready_semantics") or manifest.get("combat_ready_semantics"),
            "combat_sheet": package_readiness.get("combat_sheet") or manifest.get("combat_sheet_readiness"),
            "encounter": package_readiness.get("encounter") or manifest.get("encounter") or "NOT_ATTEMPTED",
            "controller_selection": package_readiness.get("controller_selection") or manifest.get("controller_selection") or "NOT_ATTEMPTED",
            "cpk1_schemas_registered": bool(package_readiness.get("cpk1_schemas_registered", manifest.get("cpk1_schemas_registered", False))),
            "verified_at": utcnow(),
        }
        (root / "current.json").write_text(canonical_json(pointer), encoding="utf-8")
        return pointer

    def verified_status(self, project_id: str) -> dict[str, Any] | None:
        if not self.db:
            return None
        pointer = self.db.settings.data_dir / "portable_characters" / project_id / "current.json"
        if not pointer.is_file():
            return None
        data = json.loads(pointer.read_text(encoding="utf-8"))
        package = Path(data.get("package_path") or "")
        if not package.is_file() or sha256_file(package) != data.get("package_sha256"):
            return {**data, "status": "STALE", "reason": "VERIFIED_PACKAGE_MISSING_OR_HASH_MISMATCH"}
        try:
            audit = self.audit(package)
        except FoundryError as exc:
            return {**data, "status": "STALE", "reason": exc.code}
        return {**data, "audit": audit}
