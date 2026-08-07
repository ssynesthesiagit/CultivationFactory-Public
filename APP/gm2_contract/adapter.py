from __future__ import annotations

import hashlib
import json
import re
import stat
import unicodedata
import zipfile
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from sphere_component_authority import build_sphere_automatic_component_authority

GM_V1 = "Tianxia_GM_Character_Model_v1"
GM_V2 = "Tianxia_GM_Character_Model_v2"
VIEW_V2 = "Tianxia_GM_Normalized_View_Model_v2"
ADAPTER_ID = "Tianxia.GM2.ReferenceAdapter.1.0.0"
CONSUMER_VERSION = "2.0.0"
ABILITIES = ("STR", "DEX", "CON", "INT", "WIS", "CHA")
PATHS = (
    ("tianxia.path.body_refining", "Body Refining", "CON"),
    ("tianxia.path.qi_cultivation", "Qi Cultivation", "INT/CHA"),
    ("tianxia.path.spirit_awakening", "Spirit Awakening", "WIS"),
)

ERROR_MESSAGES = {
    "GM2_UNSUPPORTED_SCHEMA": "This character package uses a GM model schema this GM Screen does not support.",
    "GM2_UNSUPPORTED_PROFILE": "The GM model schema is recognized, but its structural profile is not supported.",
    "GM2_STRUCTURALLY_INVALID_MODEL": "The GM model is present but structurally invalid. No character was imported.",
    "GM2_CONFLICTING_IDENTITIES": "The package contains models that claim conflicting character or project identities.",
    "GM2_MISSING_REQUIRED_MODEL": "The package does not contain a supported GM Character Model.",
    "GM2_INCOMPLETE_STAGE1_PROJECT": "This is an incomplete Stage 1 Factory project backup, not a completed Character Package. Complete and export the character before importing it into the GM Screen.",
    "GM2_UNSUPPORTED_FIELD": "The migration encountered a required field that cannot be represented without inventing mechanics.",
    "GM2_MODEL_NOT_GM_READY": "The model is valid but explicitly marked not ready for GM display.",
    "GM2_CONSUMER_TOO_OLD": "This GM Character Model requires a newer GM Screen consumer.",
    "GM2_AMBIGUOUS_MODEL_AUTHORITY": "The package contains multiple equally authoritative but incompatible GM models. No model was selected.",
    "GM2_PACKAGE_CHECKSUM_INVALID": "The package failed checksum verification and was not imported.",
    "GM2_PACKAGE_UNSAFE": "The package contains an unsafe, encrypted, linked, or colliding archive entry and was not imported.",
}


class GM2Error(Exception):
    def __init__(self, code: str, details: dict[str, Any] | None = None):
        super().__init__(ERROR_MESSAGES.get(code, code))
        self.code = code
        self.details = details or {}

    def response(self) -> dict[str, Any]:
        return {
            "schema": "Tianxia_GM_Validation_Error_Response_v2",
            "status": "REJECTED",
            "error_code": self.code,
            "owner_message": ERROR_MESSAGES.get(self.code, str(self)),
            "details": self.details,
        }


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _semver_tuple(value: str) -> tuple[int, int, int]:
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)", str(value or ""))
    return tuple(map(int, m.groups())) if m else (0, 0, 0)


def _safe_archive_entries(zf: zipfile.ZipFile) -> None:
    seen: set[str] = set()
    folded: set[str] = set()
    normalized: set[str] = set()
    for info in zf.infolist():
        name = info.filename.replace("\\", "/")
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or re.match(r"^[A-Za-z]:", name) or "\x00" in name:
            raise GM2Error("GM2_PACKAGE_UNSAFE", {"entry": name, "reason": "unsafe_path"})
        nfc = unicodedata.normalize("NFC", name)
        if name in seen or name.casefold() in folded or nfc.casefold() in normalized:
            raise GM2Error("GM2_PACKAGE_UNSAFE", {"entry": name, "reason": "path_collision"})
        seen.add(name); folded.add(name.casefold()); normalized.add(nfc.casefold())
        mode = (info.external_attr >> 16) & 0xFFFF
        kind = stat.S_IFMT(mode)
        if kind not in (0, stat.S_IFREG, stat.S_IFDIR) or kind == stat.S_IFLNK:
            raise GM2Error("GM2_PACKAGE_UNSAFE", {"entry": name, "reason": "special_file"})
        if info.flag_bits & 1:
            raise GM2Error("GM2_PACKAGE_UNSAFE", {"entry": name, "reason": "encrypted"})
    bad = zf.testzip()
    if bad:
        raise GM2Error("GM2_PACKAGE_CHECKSUM_INVALID", {"entry": bad, "reason": "crc"})


def _parse_checksum_lines(text: str) -> dict[str, str]:
    declared: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        m = re.match(r"^([0-9a-fA-F]{64})\s+[* ]?(.+)$", line)
        if not m or m.group(2) in declared:
            raise GM2Error("GM2_PACKAGE_CHECKSUM_INVALID", {"line": line, "reason": "invalid_or_duplicate_declaration"})
        declared[m.group(2)] = m.group(1).lower()
    return declared


def audit_package(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    package_sha = sha256_bytes(data)
    with zipfile.ZipFile(path) as zf:
        _safe_archive_entries(zf)
        names = [i.filename.replace("\\", "/") for i in zf.infolist() if not i.is_dir()]
        details: dict[str, Any] = {"package_sha256": package_sha, "entry_count": len(names), "crc": "PASS", "archive_safety": "PASS", "collision_check": "PASS"}
        if "SHA256SUMS.txt" not in names:
            raise GM2Error("GM2_PACKAGE_CHECKSUM_INVALID", {"reason": "SHA256SUMS.txt missing"})
        declared = _parse_checksum_lines(zf.read("SHA256SUMS.txt").decode("utf-8"))
        expected = set(names) - {"SHA256SUMS.txt"}
        strict = set(declared) == expected
        manifest_self_auth = False
        if not strict and "manifest.json" in names:
            manifest = json.loads(zf.read("manifest.json"))
            files = manifest.get("files") if isinstance(manifest, dict) else None
            if isinstance(files, dict):
                manifest_self_auth = all(name in names and sha256_bytes(zf.read(name)) == digest for name, digest in files.items())
                strict = set(declared) == set(files) and manifest_self_auth and expected - set(declared) == {"manifest.json"}
        if not strict:
            raise GM2Error("GM2_PACKAGE_CHECKSUM_INVALID", {"reason": "coverage", "declared": sorted(declared), "expected": sorted(expected)})
        mismatches = [name for name, digest in declared.items() if name not in names or sha256_bytes(zf.read(name)) != digest]
        if mismatches:
            raise GM2Error("GM2_PACKAGE_CHECKSUM_INVALID", {"reason": "digest_mismatch", "entries": mismatches})
        details.update({"checksum_coverage": "PASS", "checksum_count": len(declared), "manifest_self_authentication": manifest_self_auth})
        return details


def _read_jsons(path: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    parsed: dict[str, Any] = {}
    raw: dict[str, bytes] = {}
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            body = zf.read(info)
            raw[name] = body
            if name.lower().endswith(".json"):
                try:
                    parsed[name] = json.loads(body)
                except Exception:
                    parsed[name] = {"__parse_error__": True}
    return parsed, raw


def detect_profile(model: Any, *, runtime_package: bool = False) -> str | None:
    if not isinstance(model, dict):
        return None
    if model.get("schema") == GM_V2:
        return "canonical_v2" if model.get("schema_version") == "2.0.0" else None
    if model.get("schema_version") != GM_V1:
        return None
    identity = model.get("identity") or {}
    stats = model.get("stats") or {}
    legacy = (
        isinstance(identity.get("CL"), int)
        and isinstance(stats.get("hp_current"), (int, float))
        and isinstance(stats.get("hp_max"), (int, float))
        and isinstance(stats.get("ac_active"), (int, float))
        and isinstance(stats.get("speed_ft"), (int, float))
        and isinstance(stats.get("ability_scores"), dict)
    )
    fire = (
        isinstance(identity.get("cultivation_level"), int)
        and isinstance(stats.get("hit_points"), dict)
        and isinstance((stats.get("hit_points") or {}).get("maximum"), (int, float))
        and isinstance(stats.get("armor_class"), dict)
        and isinstance((stats.get("armor_class") or {}).get("value"), (int, float))
        and isinstance(stats.get("speed"), dict)
        and isinstance(stats.get("abilities"), list)
        and isinstance(model.get("paths_subpaths_insights"), dict)
    )
    if legacy:
        return "legacy_phase2h_v1"
    if fire:
        return "fire_qi_runtime_ready_v1" if runtime_package else "fire_qi_c2c1_v1"
    return "recognized_v1_unsupported_profile"



def _v2_structural_issues(model: dict[str, Any]) -> list[str]:
    required = (
        "metadata", "identity", "cultivation", "combat", "ability_scores",
        "skills", "spheres", "automatic_base_abilities", "talents", "actions",
        "reactions", "methods", "recorded_arts", "forged_techniques",
        "equipment", "states", "companions", "provenance", "readiness",
        "incomplete_surfaces", "field_states",
    )
    issues = [f"missing:{key}" for key in required if key not in model]
    identity = model.get("identity")
    cultivation = model.get("cultivation")
    combat = model.get("combat")
    readiness = model.get("readiness")
    if not isinstance(identity, dict) or not identity.get("display_name"):
        issues.append("identity.display_name")
    if not isinstance(cultivation, dict) or not isinstance(cultivation.get("paths"), list) or len(cultivation.get("paths") or []) != 3:
        issues.append("cultivation.paths_exactly_three")
    if not isinstance(combat, dict) or combat.get("runtime_contract") != "not_duplicated":
        issues.append("combat.runtime_contract_not_duplicated")
    if not isinstance(readiness, dict) or not isinstance(readiness.get("gm_ready"), bool) or not isinstance(readiness.get("contract_valid"), bool):
        issues.append("readiness_flags")
    return sorted(set(issues))

def _candidate_score(path: str, profile: str, manifest: dict[str, Any]) -> int:
    gm_ref = manifest.get("gm_model") if isinstance(manifest, dict) else None
    if isinstance(gm_ref, dict) and gm_ref.get("path") == path:
        return 100
    canonical = set(manifest.get("canonical_models") or []) if isinstance(manifest, dict) else set()
    derived = set(manifest.get("derived_display_models") or []) if isinstance(manifest, dict) else set()
    exact = set(manifest.get("exact_source_models") or []) if isinstance(manifest, dict) else set()
    if path in canonical:
        return 95
    if profile == "canonical_v2" and PurePosixPath(path).name == "Tianxia_GM_Character_Model_v2.json":
        return 90 if "/" not in path else 85
    if path in derived:
        return 80
    if profile.startswith("legacy_") or profile.startswith("fire_qi_"):
        if path == "Tianxia_GM_Character_Model_v1.json":
            return 75
        if path in exact:
            return 70
    return 50


def _identity_claim(model: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    identity = model.get("identity") or {}
    metadata = model.get("metadata") or {}
    return {
        "display_name": identity.get("display_name") or identity.get("name"),
        "character_id": identity.get("character_id") or metadata.get("character_id"),
        "project_id": metadata.get("project_id") or manifest.get("project_id"),
        "canonical_project_hash": metadata.get("canonical_project_hash") or manifest.get("canonical_project_hash"),
        "content_lock_hash": metadata.get("content_lock_hash") or manifest.get("content_lock_hash"),
    }


def select_candidate(path: Path) -> dict[str, Any]:
    parsed, raw = _read_jsons(path)
    project_manifest = parsed.get("manifest.json") if isinstance(parsed.get("manifest.json"), dict) else None
    project = parsed.get("project.json") if isinstance(parsed.get("project.json"), dict) else None
    if project_manifest and project_manifest.get("schema_version") == "TianxiaFoundry.ProjectExport.v1":
        raise GM2Error("GM2_INCOMPLETE_STAGE1_PROJECT", {"project_id": project_manifest.get("project_id"), "project_status": (project or {}).get("status"), "active_stage": (project or {}).get("active_stage")})
    manifest = parsed.get("PACKAGE_MANIFEST.json") if isinstance(parsed.get("PACKAGE_MANIFEST.json"), dict) else {}
    runtime_package = "combat/Combat_Sheet.json" in raw or str(manifest.get("package_role", "")).endswith("combat_runtime_ready")
    candidates: list[dict[str, Any]] = []
    unsupported_schema: list[dict[str, Any]] = []
    for candidate_path, value in parsed.items():
        if not isinstance(value, dict):
            continue
        schema = value.get("schema") or value.get("schema_version")
        if isinstance(schema, str) and schema.startswith("Tianxia_GM_Character_Model_") and schema not in (GM_V1, GM_V2):
            unsupported_schema.append({"path": candidate_path, "schema": schema})
            continue
        if schema in (GM_V1, GM_V2):
            profile = detect_profile(value, runtime_package=runtime_package)
            if profile is None:
                unsupported_schema.append({"path": candidate_path, "schema": schema, "schema_version": value.get("schema_version")})
                continue
            issues = _v2_structural_issues(value) if profile == "canonical_v2" else []
            if issues:
                candidates.append({
                    "path": candidate_path, "model": value,
                    "model_sha256": sha256_bytes(raw[candidate_path]),
                    "profile": "canonical_v2_structurally_invalid",
                    "score": _candidate_score(candidate_path, "canonical_v2", manifest),
                    "identity": _identity_claim(value, manifest), "structural_issues": issues,
                })
                continue
            candidates.append({
                "path": candidate_path,
                "model": value,
                "model_sha256": sha256_bytes(raw[candidate_path]),
                "profile": profile,
                "score": _candidate_score(candidate_path, profile, manifest),
                "identity": _identity_claim(value, manifest),
            })
    if not candidates:
        if unsupported_schema:
            raise GM2Error("GM2_UNSUPPORTED_SCHEMA", {"candidates": unsupported_schema})
        raise GM2Error("GM2_MISSING_REQUIRED_MODEL", {"json_files": sorted(parsed)})
    invalid_v2 = [c for c in candidates if c["profile"] == "canonical_v2_structurally_invalid"]
    candidates = [c for c in candidates if c["profile"] != "canonical_v2_structurally_invalid"]
    if not candidates and invalid_v2:
        raise GM2Error("GM2_STRUCTURALLY_INVALID_MODEL", {"candidates": [{k:v for k,v in c.items() if k != "model"} for c in invalid_v2]})
    supported = [c for c in candidates if c["profile"] != "recognized_v1_unsupported_profile"]
    if not supported:
        raise GM2Error("GM2_UNSUPPORTED_PROFILE", {"candidates": [{k:v for k,v in c.items() if k != "model"} for c in candidates]})
    # Any candidate that claims a different project or character identity is a hard conflict.
    claims = [c["identity"] for c in supported]
    for key in ("project_id", "canonical_project_hash", "content_lock_hash", "character_id"):
        vals = {str(c.get(key)) for c in claims if c.get(key) not in (None, "")}
        if len(vals) > 1:
            raise GM2Error("GM2_CONFLICTING_IDENTITIES", {"field": key, "values": sorted(vals)})
    supported.sort(key=lambda c: (-c["score"], c["path"]))
    top = [c for c in supported if c["score"] == supported[0]["score"]]
    if len(top) > 1:
        semantic = {sha256_bytes(canonical_bytes(c["model"])) for c in top}
        if len(semantic) > 1:
            raise GM2Error("GM2_AMBIGUOUS_MODEL_AUTHORITY", {"candidates": [{k:v for k,v in c.items() if k != "model"} for c in top]})
    selected = supported[0]
    selected["manifest"] = manifest
    selected["runtime_package"] = runtime_package
    selected["all_candidates"] = [{k:v for k,v in c.items() if k != "model"} for c in supported]
    return selected


def _source(package_sha: str, path: str, sha: str | None = None, *, anchor: str | None = None, record_id: str | None = None) -> dict[str, Any]:
    out = {"package_sha256": package_sha, "path": path}
    if sha:
        out["sha256"] = sha
    if anchor:
        out["anchor"] = anchor
    if record_id:
        out["record_id"] = record_id
    return out


def _record_source(record: Any, package_sha: str, model_path: str, model_sha: str) -> dict[str, Any]:
    if isinstance(record, dict):
        src = record.get("source") or record.get("source_reference") or {}
        if isinstance(src, dict):
            p = src.get("path") or src.get("source_path") or model_path
            h = src.get("sha256") or model_sha
            a = src.get("anchor") or src.get("heading")
            rid = record.get("record_id") or record.get("stable_id") or record.get("talent_id") or record.get("sphere_id")
            return _source(package_sha, str(p), str(h) if h else None, anchor=str(a) if a else None, record_id=str(rid) if rid else None)
    return _source(package_sha, model_path, model_sha)


def _state(state: str, reason: str = "", source_path: str = "", value: Any = None, include_value: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {"state": state}
    if reason:
        out["reason"] = reason
    if source_path:
        out["source_path"] = source_path
    if include_value:
        out["value"] = value
    return out


def _display_record(record: Any, package_sha: str, model_path: str, model_sha: str, *, fallback_id: str, fallback_name: str, acquisition_route: str = "") -> dict[str, Any]:
    if not isinstance(record, dict):
        return {"stable_id": fallback_id, "name": str(record or fallback_name), "short_description": "", "full_description": "", "source": _source(package_sha, model_path, model_sha), "acquisition_route": acquisition_route, "state": "present", "details": {}}
    stable_id = record.get("stable_id") or record.get("record_id") or record.get("talent_id") or record.get("sphere_id") or record.get("feature_id") or record.get("id") or fallback_id
    name = record.get("display_name") or record.get("name") or record.get("sphere_name") or record.get("title") or fallback_name
    short = record.get("short_description") or record.get("one_line_description") or record.get("mechanical_summary") or record.get("summary") or ""
    full = record.get("full_description") or record.get("description") or record.get("effect") or record.get("mechanical_summary") or ""
    excluded = {"source", "source_reference", "full_description", "short_description", "one_line_description", "description", "effect"}
    details = {k:v for k,v in record.items() if k not in excluded}
    return {"stable_id": str(stable_id), "name": str(name), "short_description": str(short), "full_description": str(full), "source": _record_source(record, package_sha, model_path, model_sha), "acquisition_route": str(record.get("acquisition_route") or record.get("acquisition_type") or acquisition_route), "state": str(record.get("state") or "present"), "details": details}


def _automatic_component_projection(model: dict[str, Any], sphere_rows: list[Any]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Carry the locked Sphere component packets into the GM transport model."""
    section = model.get("spheres_talents") or {}
    packets: dict[str, dict[str, Any]] = {}
    candidates: list[Any] = []
    candidates.extend(section.get("automatic_sphere_component_receipts") or [] if isinstance(section, dict) else [])
    candidates.extend(model.get("automatic_sphere_component_receipts") or [])
    candidates.extend(sphere_rows)
    for row in candidates:
        if not isinstance(row, dict):
            continue
        packet = row.get("automatic_component_authority") if isinstance(row.get("automatic_component_authority"), dict) else row
        parent = packet.get("parent_sphere_id") or row.get("stable_id") or row.get("sphere_id")
        components = packet.get("components")
        if isinstance(parent, str) and parent and isinstance(components, list):
            candidate = {key: value for key, value in packet.items()}
            prior = packets.get(parent)
            if prior is not None and (
                prior.get("package_hash") != candidate.get("package_hash")
                or [row.get("component_hash") for row in prior.get("components") or []]
                != [row.get("component_hash") for row in candidate.get("components") or []]
            ):
                raise GM2Error("GM2_CONFLICTING_SPHERE_COMPONENT_AUTHORITY", {"parent_sphere_id": parent})
            packets[parent] = candidate

    flat = []
    flat.extend(section.get("automatic_sphere_components") or [] if isinstance(section, dict) else [])
    flat.extend(model.get("automatic_sphere_components") or [])
    by_parent: dict[str, list[dict[str, Any]]] = {}
    for row in flat:
        if isinstance(row, dict) and isinstance(row.get("parent_sphere_id"), str):
            by_parent.setdefault(row["parent_sphere_id"], []).append(row)
    for parent, rows in by_parent.items():
        if parent not in packets:
            packets[parent] = build_sphere_automatic_component_authority(parent, rows)

    components: list[dict[str, Any]] = []
    seen: set[str] = set()
    for parent in sorted(packets):
        for component in packets[parent].get("components") or []:
            if not isinstance(component, dict):
                continue
            component_id = component.get("component_id")
            if isinstance(component_id, str) and component_id not in seen:
                seen.add(component_id)
                components.append(component)
    return packets, components


def _insight_projection(model: dict[str, Any], package_sha: str, model_path: str, model_sha: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Expose the same ordinary Insight occurrences in GM2 as in the sheet."""
    section = model.get("paths_subpaths_insights") or {}
    raw_occurrences = model.get("cultivation_insight_occurrences") or section.get("cultivation_insight_occurrences") or []
    if isinstance(raw_occurrences, dict):
        raw_occurrences = raw_occurrences.get("occurrences") or raw_occurrences.get("items") or []
    occurrences: list[dict[str, Any]] = []
    for row in raw_occurrences if isinstance(raw_occurrences, list) else []:
        if not isinstance(row, dict):
            continue
        record_id = row.get("record_id") or row.get("insight_id") or row.get("stable_id")
        if not isinstance(record_id, str) or not record_id:
            continue
        normalized = deepcopy(row)
        normalized.setdefault("record_id", record_id)
        occurrences.append(normalized)
    raw_rows = model.get("insights") or []
    by_id: dict[str, dict[str, Any]] = {}
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        record_id = row.get("stable_id") or row.get("insight_id") or row.get("record_id")
        if isinstance(record_id, str) and record_id:
            by_id[record_id] = deepcopy(row)
    ids = [value for value in section.get("cultivation_insight_record_ids") or [] if isinstance(value, str)]
    ids.extend(row["record_id"] for row in occurrences)
    for record_id in dict.fromkeys(ids):
        row = by_id.get(record_id)
        if row is None:
            row = _display_record(
                {"record_id": record_id, "display_name": record_id, "summary": "Ordinary Cultivation Insight occurrence."},
                package_sha,
                model_path,
                model_sha,
                fallback_id=record_id,
                fallback_name=record_id,
                acquisition_route="cultivation_insight_acquisition",
            )
        row.setdefault("stable_id", record_id)
        row.setdefault("name", record_id)
        row.setdefault("acquisition_route", "cultivation_insight_acquisition")
        row.setdefault("state", "present")
        row.setdefault("details", {})
        row["details"]["occurrences"] = [deepcopy(item) for item in occurrences if item.get("record_id") == record_id]
        by_id[record_id] = row
    return [by_id[key] for key in sorted(by_id)], occurrences


def _action(record: dict[str, Any], package_sha: str, model_path: str, model_sha: str, index: int) -> dict[str, Any]:
    economy = record.get("economy") or record.get("action_type") or record.get("bucket") or record.get("category") or "unspecified"
    return {
        "stable_id": str(record.get("action_id") or record.get("stable_id") or record.get("record_id") or record.get("id") or f"action.{index}"),
        "name": str(record.get("display_name") or record.get("action_name") or record.get("name") or f"Action {index}"),
        "economy": str(economy),
        "trigger": str(record.get("trigger") or record.get("timing") or ""),
        "cost": str(record.get("cost") or record.get("resource_cost") or ""),
        "range": str(record.get("range") or ""),
        "target": str(record.get("target") or record.get("target_or_area") or ""),
        "roll_or_save": str(record.get("roll_or_save") or record.get("roll_save_check") or ""),
        "effect": str(record.get("effect") or record.get("success_effect") or record.get("full_description") or ""),
        "duration": str(record.get("duration") or ""),
        "limit": str(record.get("limit") or record.get("failure_or_limit") or ""),
        "source": _record_source(record, package_sha, model_path, model_sha),
        "runtime_contract": "excluded_from_gm_transport",
    }


def _empty_paths(active_path_name: str, active_level: int, active_key: str, source_path: str, primary_method_state: str) -> list[dict[str, Any]]:
    active_norm = active_path_name.strip().lower()
    known = {name.lower() for _, name, _ in PATHS}
    if active_level > 0 and active_norm not in known:
        raise GM2Error("GM2_UNSUPPORTED_FIELD", {"field": "active_path", "value": active_path_name, "source_path": source_path})
    rows = []
    for pid, name, key in PATHS:
        active = name.lower() == active_norm
        auth = _state(primary_method_state if active else "not_applicable", "Source does not explicitly enumerate Method AP authorization." if active and primary_method_state == "unavailable" else ("Dormant level-0 Path has no active AP route." if not active else ""), source_path)
        rows.append({"path_id": pid, "name": name, "attainment_level": active_level if active else 0, "advancement_state": "advancing" if active and active_level > 0 else "dormant", "primary": active, "key_ability": active_key if active else key, "ap_authorization": auth})
    return rows


def _legacy_saves(stats: dict[str, Any]) -> list[dict[str, Any]]:
    raw = stats.get("saving_throws") or {}
    return [{"ability": ab, "bonus": raw.get(ab), "state": "present" if ab in raw else "unavailable"} for ab in ABILITIES]


def _fire_saves(stats: dict[str, Any]) -> list[dict[str, Any]]:
    raw = stats.get("saving_throws")
    if isinstance(raw, list):
        by = {str(x.get("ability")):x.get("bonus") for x in raw if isinstance(x, dict)}
    elif isinstance(raw, dict):
        by = raw
    else:
        by = {}
    return [{"ability": ab, "bonus": by.get(ab), "state": "present" if ab in by else "unavailable"} for ab in ABILITIES]


def _metadata(profile: str, package_sha: str, model: dict[str, Any], manifest: dict[str, Any], model_path: str, model_sha: str) -> dict[str, Any]:
    ident = model.get("identity") or {}
    md = model.get("metadata") or {}
    profile_out = {"legacy_phase2h_v1":"migrated_legacy_phase2h_v1","fire_qi_c2c1_v1":"migrated_fire_qi_c2c1_v1","fire_qi_runtime_ready_v1":"migrated_fire_qi_runtime_ready_v1","canonical_v2":"canonical_v2"}[profile]
    return {
        "character_package_schema": str(manifest.get("schema_version") or "legacy_character_zip"),
        "gm_model_schema": GM_V2,
        "model_profile": profile_out,
        "producer_version": str(md.get("producer_version") or md.get("build_profile_version") or manifest.get("schema_version") or "legacy-unversioned"),
        "minimum_consumer_version": CONSUMER_VERSION,
        "source_checkpoint": "GM2_READ_ONLY_REFERENCE_MIGRATION",
        "content_lock_hash": md.get("content_lock_hash") or manifest.get("content_lock_hash"),
        "canonical_project_hash": md.get("canonical_project_hash") or manifest.get("canonical_project_hash"),
        "character_id": str(ident.get("character_id") or md.get("character_id") or ""),
        "project_id": md.get("project_id") or manifest.get("project_id"),
        "package_sha256": package_sha,
        "migration_history": [{"adapter_id": ADAPTER_ID, "source_profile": profile, "source_package_sha256": package_sha, "source_model_path": model_path, "source_model_sha256": model_sha}],
        "deterministic_serialization": {"encoding":"UTF-8","key_order":"lexicographic","whitespace":"compact","newline":"LF"},
    }


def _ability_records_from_dict(scores: dict[str, Any], modifiers: dict[str, Any] | None = None) -> dict[str, Any]:
    modifiers = modifiers or {}
    out = {}
    for ab in ABILITIES:
        score = scores.get(ab)
        mod = modifiers.get(ab)
        if mod is None and isinstance(score, (int, float)):
            mod = (int(score) - 10) // 2
        out[ab] = {"score": score if isinstance(score, int) else None, "modifier": mod if isinstance(mod, int) else None, "state": "present" if isinstance(score, int) else "unavailable"}
    return out


def _ability_records_from_list(rows: list[Any]) -> dict[str, Any]:
    by = {str(x.get("ability")):x for x in rows if isinstance(x, dict)}
    return {ab:{"score": by.get(ab,{}).get("score") if isinstance(by.get(ab,{}).get("score"),int) else None,"modifier": by.get(ab,{}).get("modifier") if isinstance(by.get(ab,{}).get("modifier"),int) else None,"state":"present" if ab in by else "unavailable"} for ab in ABILITIES}


def _skills_from_dict(raw: dict[str, Any], package_sha: str, model_path: str, model_sha: str) -> list[dict[str, Any]]:
    return [{"name":str(name),"ability":"unavailable","bonus":bonus if isinstance(bonus,(int,float)) else None,"proficiency":"unavailable","state":"present","source":_source(package_sha,model_path,model_sha)} for name,bonus in sorted(raw.items())]


def _skills_from_list(raw: list[Any], package_sha: str, model_path: str, model_sha: str) -> list[dict[str, Any]]:
    out=[]
    for row in raw:
        if not isinstance(row,dict): continue
        out.append({"name":str(row.get("skill") or row.get("name") or "Unnamed skill"),"ability":str(row.get("ability") or "unavailable"),"bonus":row.get("bonus") if isinstance(row.get("bonus"),(int,float)) else None,"proficiency":str(row.get("proficiency") or "unavailable"),"state":"present","source":_record_source(row,package_sha,model_path,model_sha)})
    return out


def _legacy_subpath(model: dict[str, Any], package_sha: str, model_path: str, model_sha: str) -> list[dict[str, Any]]:
    features = ((model.get("spheres_talents") or {}).get("features") or [])
    ids = [str(f.get("owning_subpath_id")) for f in features if isinstance(f,dict) and f.get("owning_subpath_id")]
    if not ids:
        return []
    sid = sorted(set(ids))[0]
    name = " ".join(part.capitalize() for part in sid.split(".")[-1].split("_"))
    return [{"stable_id":sid,"name":name,"short_description":"","full_description":"","source":_source(package_sha,model_path,model_sha,record_id=sid),"acquisition_route":"path_subpath_selection","state":"present","details":{"selected_at_cl":3,"derivation":"stable owning_subpath_id present on source features"}}]


def _migrate_legacy(selected: dict[str, Any], package_sha: str) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    model=selected["model"]; path=selected["path"]; msha=selected["model_sha256"]; manifest=selected["manifest"]
    identity=model.get("identity") or {}; stats=model.get("stats") or {}; source=_source(package_sha,path,msha)
    active_path=str(identity.get("path") or stats.get("path") or "")
    cl=int(identity.get("CL") or stats.get("CL") or 0); key=str(identity.get("key_ability") or "")
    method=model.get("method")
    method_state="unavailable" if isinstance(method,dict) and method else "explicit_none"
    paths=_empty_paths(active_path,cl,key,path,method_state)
    resources=[]
    if stats.get("primary_resource_name"):
        resources.append({"stable_id":f"tianxia.resource.{str(stats.get('primary_resource_name')).lower()}","name":str(stats.get("primary_resource_name")),"current":stats.get("primary_resource_current"),"maximum":stats.get("primary_resource_max"),"state":"present","recovery":"","path_id":next((p["path_id"] for p in paths if p["primary"]),""),"source":source})
    sphere_rows=((model.get("spheres_talents") or {}).get("spheres") or [])
    spheres=[_display_record(x,package_sha,path,msha,fallback_id=f"sphere.{i}",fallback_name=f"Sphere {i}") for i,x in enumerate(sphere_rows,1)]
    sphere_packets, automatic_components = _automatic_component_projection(model, sphere_rows)
    insights, insight_occurrences = _insight_projection(model, package_sha, path, msha)
    for sphere in spheres:
        packet=sphere_packets.get(sphere["stable_id"])
        if packet:
            sphere["automatic_component_authority"]=packet
            sphere["automatic_component_ids"]=list(packet.get("component_ids") or [])
    talents=[]
    for i,x in enumerate(((model.get("spheres_talents") or {}).get("talents") or []),1):
        r=_display_record(x,package_sha,path,msha,fallback_id=f"talent.{i}",fallback_name=f"Talent {i}")
        route=r["acquisition_route"]
        r["ordinary_advancement_cost"]=0 if "free" in route or "background" in route else 1
        r["training_slot_cost"]=1 if "train" in route else 0
        talents.append(r)
    actions_all=[_action(x,package_sha,path,msha,i) for i,x in enumerate(model.get("actions") or [],1) if isinstance(x,dict)]
    reactions=[a for a in actions_all if "reaction" in a["economy"].lower()]
    actions=[a for a in actions_all if a not in reactions]
    foundation=[]
    if isinstance(model.get("foundation"),dict) and model["foundation"]:
        foundation=[_display_record(model["foundation"],package_sha,path,msha,fallback_id="foundation.legacy",fallback_name="Foundation",acquisition_route="foundation_selection")]
    methods=[]
    if isinstance(method,dict) and method:
        methods=[_display_record(method,package_sha,path,msha,fallback_id="method.legacy",fallback_name="Method",acquisition_route="method_selection")]
    equipment=[_display_record(x,package_sha,path,msha,fallback_id=f"equipment.{i}",fallback_name=f"Equipment {i}") for i,x in enumerate(((model.get("equipment_resources_states") or {}).get("equipment") or []),1)]
    states=[_display_record(x,package_sha,path,msha,fallback_id=f"state.{i}",fallback_name=f"State {i}") for i,x in enumerate(((model.get("equipment_resources_states") or {}).get("states") or []),1)]
    recorded=[_display_record(x,package_sha,path,msha,fallback_id=f"recorded_art.{i}",fallback_name=f"Recorded Art {i}") for i,x in enumerate(model.get("martial_manuals") or [],1)]
    forged=[_display_record(x,package_sha,path,msha,fallback_id=f"forged.{i}",fallback_name=f"Forged Technique {i}") for i,x in enumerate(model.get("forged_techniques") or [],1)]
    automatic_surface_state="present" if automatic_components else "unavailable"
    automatic_surface_reason="Canonical Sphere automatic-component packets are present." if automatic_components else "The legacy Phase2H model predates separate automatic base-ability projection."
    incomplete=[{"surface":"automatic_base_abilities","state":automatic_surface_state,"reason":automatic_surface_reason,"source_path":path},{"surface":"method_ap_authorized_paths","state":"unavailable","reason":"The legacy Method record does not explicitly enumerate AP-authorized Paths.","source_path":path},{"surface":"active_path_expressions","state":"unavailable","reason":"The legacy model does not encode a distinct active Path-expression surface.","source_path":path}]
    diagnostics=[{"severity":"warning","code":"GM2_LEGACY_METHOD_AP_AUTHORITY_UNAVAILABLE","message":"Primary Method is preserved, but its AP-authorized Paths are not explicitly encoded.","source_path":path}]
    out={
      "schema":GM_V2,"schema_version":"2.0.0","metadata":_metadata(selected["profile"],package_sha,model,manifest,path,msha),
      "identity":{"character_id":str(identity.get("character_id") or "lee_jia_legacy"),"display_name":str(identity.get("display_name") or identity.get("name") or "Unnamed Character"),"species":str(identity.get("species") or ""),"creature_type":str(identity.get("creature_type") or ""),"size":str(identity.get("size") or ""),"title":_state("present" if identity.get("title") else "absent",source_path=path,value=identity.get("title"),include_value=bool(identity.get("title"))),"concept":str(identity.get("concept_summary") or identity.get("concept") or "")},
      "cultivation":{"cultivation_level":cl,"realm":str(identity.get("realm") or stats.get("realm") or ""),"paths":paths,"primary_method":_state("present" if methods else "explicit_none",source_path=path,value=methods[0]["stable_id"] if methods else None,include_value=bool(methods)),"subpaths_traditions":_legacy_subpath(model,package_sha,path,msha),"foundation":_state("present" if foundation else "unavailable","Legacy source contains no Foundation record." if not foundation else "",path,value=foundation[0]["stable_id"] if foundation else None,include_value=bool(foundation)),"foundation_expressions":foundation,"active_path_expressions":[],"resources":resources},
      "combat":{"hit_points":{"current":stats.get("hp_current"),"maximum":stats.get("hp_max")},"armor_class":stats.get("ac_active"),"speed_ft":stats.get("speed_ft"),"attack_bonus":stats.get("technique_attack_bonus"),"save_dc":stats.get("save_dc"),"initiative_bonus":stats.get("initiative_bonus"),"saving_throws":_legacy_saves(stats),"runtime_contract":"not_duplicated"},
      "ability_scores":_ability_records_from_dict(stats.get("ability_scores") or {},stats.get("ability_modifiers") or {}),"skills":_skills_from_dict(stats.get("skills") or {},package_sha,path,msha),
      "spheres":spheres,"automatic_base_abilities":automatic_components,"automatic_sphere_component_receipts":list(sphere_packets.values()),"automatic_sphere_components":automatic_components,"insights":insights,"cultivation_insight_occurrences":insight_occurrences,"talents":talents,"actions":actions,"reactions":reactions,"methods":methods,"recorded_arts":recorded,"forged_techniques":forged,"equipment":equipment,"states":states,"companions":[],
      "provenance":{"source_package_sha256":package_sha,"selected_model_path":path,"selected_model_sha256":msha,"source_references":[source]},
      "readiness":{"gm_ready":True,"contract_valid":True,"combat_runtime_separate":True,"diagnostics":diagnostics},"incomplete_surfaces":incomplete,
      "field_states":{"automatic_base_abilities":_state("unavailable",incomplete[0]["reason"],path),"method_ap_authorized_paths":_state("unavailable",incomplete[1]["reason"],path),"active_path_expressions":_state("unavailable",incomplete[2]["reason"],path),"combat_runtime":_state("not_applicable","Combat Sheet/runtime model is a separate contract.",path)}
    }
    mappings=[
      {"source_path":"$.identity.CL","target_path":"$.cultivation.cultivation_level","state":"renamed","operation":"copied integer without recalculation"},
      {"source_path":"$.stats.hp_current/$.stats.hp_max","target_path":"$.combat.hit_points","state":"restructured","operation":"copied scalar current and maximum"},
      {"source_path":"$.stats.ac_active","target_path":"$.combat.armor_class","state":"renamed","operation":"copied"},
      {"source_path":"$.stats.speed_ft","target_path":"$.combat.speed_ft","state":"copied","operation":"copied"},
      {"source_path":"$.stats.ability_scores","target_path":"$.ability_scores","state":"restructured","operation":"converted ability map to typed records; modifiers copied or arithmetically derived from source scores"},
      {"source_path":"$.method","target_path":"$.methods/$.cultivation.primary_method","state":"restructured","operation":"preserved Method record; AP-authorized Paths marked unavailable"},
    ]
    return out,mappings,incomplete


def _fire_record_ids(model: dict[str, Any], key: str) -> list[str]:
    st=model.get("spheres_talents") or {}
    value=st.get(key)
    return [str(x) for x in value] if isinstance(value,list) else []


def _migrate_fire(selected: dict[str, Any], package_sha: str) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    model=selected["model"]; path=selected["path"]; msha=selected["model_sha256"]; manifest=selected["manifest"]
    identity=model.get("identity") or {}; stats=model.get("stats") or {}; ps=model.get("paths_subpaths_insights") or {}; source=_source(package_sha,path,msha)
    cl=int(identity.get("cultivation_level") or 0); active_path=str(identity.get("path") or (ps.get("path") or {}).get("display_name") or "")
    method=model.get("method") or {}; explicit_none=isinstance(method,dict) and method.get("state")=="none"
    paths=_empty_paths(active_path,cl,str(identity.get("key_ability") or (ps.get("path") or {}).get("key_ability") or ""),path,"unavailable")
    primary=stats.get("primary_resource") or {}; definitions=primary.get("definitions") or []
    definition=definitions[0] if definitions and isinstance(definitions[0],dict) else {}
    resource={"stable_id":str(definition.get("resource_id") or "tianxia.resource.qi"),"name":str(primary.get("name") or definition.get("name") or "Qi"),"current":primary.get("build_state_current") if isinstance(primary.get("build_state_current"),(int,float)) else definition.get("current"),"maximum":primary.get("maximum") if isinstance(primary.get("maximum"),(int,float)) else definition.get("max"),"state":"present","recovery":"","path_id":str(identity.get("path_id") or "tianxia.path.qi_cultivation"),"source":source}
    sphere_ids=_fire_record_ids(model,"sphere_record_ids")
    sphere_rows=((model.get("spheres_talents") or {}).get("spheres") or [])
    spheres=[{"stable_id":sid,"name":" ".join(x.capitalize() for x in sid.split(".")[-1].split("_")),"short_description":"","full_description":"","source":_source(package_sha,path,msha,record_id=sid),"acquisition_route":"source_record_id","state":"present","details":{}} for sid in sphere_ids]
    sphere_packets, automatic_components = _automatic_component_projection(model, sphere_rows)
    insights, insight_occurrences = _insight_projection(model, package_sha, path, msha)
    for sphere in spheres:
        packet=sphere_packets.get(sphere["stable_id"])
        if packet:
            sphere["automatic_component_authority"]=packet
            sphere["automatic_component_ids"]=list(packet.get("component_ids") or [])
    background_id=str((model.get("spheres_talents") or {}).get("background_talent_record_id") or "")
    talent_ids=_fire_record_ids(model,"learned_talent_record_ids")
    talents=[]
    for tid in ([background_id] if background_id else [])+talent_ids:
        action_match=next((x for x in model.get("actions") or [] if isinstance(x,dict) and (x.get("record_id")==tid or x.get("stable_id")==tid)),{})
        r=_display_record(action_match or {"record_id":tid,"display_name":" ".join(x.capitalize() for x in tid.split("_")[-4:])},package_sha,path,msha,fallback_id=tid,fallback_name=tid,acquisition_route="background_talent_acquisition" if tid==background_id else "learned_talent")
        r["ordinary_advancement_cost"]=0 if tid==background_id else 1; r["training_slot_cost"]=0
        talents.append(r)
    actions_all=[_action(x,package_sha,path,msha,i) for i,x in enumerate(model.get("actions") or [],1) if isinstance(x,dict)]
    reactions=[a for a in actions_all if "reaction" in a["economy"].lower()]; actions=[a for a in actions_all if a not in reactions]
    sub=[]; sp=ps.get("subpath")
    if isinstance(sp,dict) and sp:
        sub=[_display_record({**sp,"record_id":sp.get("subpath_id"),"display_name":sp.get("name")},package_sha,path,msha,fallback_id="subpath.fire",fallback_name="Subpath",acquisition_route="path_subpath_selection")]
    foundation=[]; foundation_state=model.get("foundation") or {}
    methods=[]
    if isinstance(method,dict) and method and not explicit_none:
        methods=[_display_record(method,package_sha,path,msha,fallback_id="method.fire",fallback_name="Method",acquisition_route="method_selection")]
    recorded_raw=model.get("recorded_arts")
    recorded=[]
    if isinstance(recorded_raw,list):
        recorded=[_display_record(x,package_sha,path,msha,fallback_id=f"recorded.{i}",fallback_name=f"Recorded Art {i}") for i,x in enumerate(recorded_raw,1)]
    forged_raw=model.get("forged_techniques")
    forged=[] if isinstance(forged_raw,dict) and forged_raw.get("state")=="none" else [_display_record(x,package_sha,path,msha,fallback_id=f"forged.{i}",fallback_name=f"Forged Technique {i}") for i,x in enumerate(forged_raw if isinstance(forged_raw,list) else [],1)]
    ers=model.get("equipment_resources_states") or {}; equipment=[_display_record(x,package_sha,path,msha,fallback_id=f"equipment.{i}",fallback_name=f"Equipment {i}") for i,x in enumerate(ers.get("equipment") or [],1)]; states=[_display_record(x,package_sha,path,msha,fallback_id=f"state.{i}",fallback_name=f"State {i}") for i,x in enumerate(ers.get("states") or [],1)]
    companions_raw=model.get("spirit_companions"); companions=[] if isinstance(companions_raw,dict) and companions_raw.get("state") in ("none","not_applicable") else [_display_record(x,package_sha,path,msha,fallback_id=f"companion.{i}",fallback_name=f"Companion {i}") for i,x in enumerate(companions_raw if isinstance(companions_raw,list) else [],1)]
    automatic_surface_state="present" if automatic_components else "unavailable"
    automatic_surface_reason="Canonical Sphere automatic-component packets are present." if automatic_components else "The C2C.1 fixture predates CAT2 automatic base-ability projection."
    incomplete=[{"surface":"automatic_base_abilities","state":automatic_surface_state,"reason":automatic_surface_reason,"source_path":path},{"surface":"current_primary_method","state":"explicit_none" if explicit_none else "unavailable","reason":str(method.get("reason") or "No supported current Primary Method record is present."),"source_path":path},{"surface":"method_ap_authorized_paths","state":"unavailable","reason":"No exact Method AP-authority list is encoded; migration does not infer one.","source_path":path},{"surface":"active_path_expressions","state":"unavailable","reason":"The C2C.1 fixture does not encode a distinct active Path-expression surface.","source_path":path}]
    diagnostics=[{"severity":"warning","code":"GM2_CURRENT_METHOD_AUTHORITY_INCOMPLETE","message":"The source explicitly has no selected Method while Qi Cultivation is historically advanced; migration preserves both facts and does not fabricate AP authority.","source_path":path}]
    if selected["runtime_package"]:
        diagnostics.append({"severity":"info","code":"GM2_COMBAT_RUNTIME_PRESENT_SEPARATE","message":"Combat runtime sidecars are present but are not copied into the GM transport model.","source_path":"combat/Combat_Sheet.json"})
    hp=stats.get("hit_points") or {}; ac=stats.get("armor_class") or {}; speed=stats.get("speed") or {}
    out={
      "schema":GM_V2,"schema_version":"2.0.0","metadata":_metadata(selected["profile"],package_sha,model,manifest,path,msha),
      "identity":{"character_id":str((model.get("metadata") or {}).get("project_id") or "c1a_fire_qi_proof"),"display_name":str(identity.get("display_name") or "Unnamed Character"),"species":str(identity.get("species") or ""),"creature_type":str(identity.get("creature_type") or ""),"size":str(identity.get("size") or ""),"title":_state("present" if identity.get("title") else "absent",str(identity.get("title_status") or "Owner omitted title."),path,value=identity.get("title"),include_value=bool(identity.get("title"))),"concept":str(identity.get("concept") or "")},
      "cultivation":{"cultivation_level":cl,"realm":str(identity.get("realm_display") or identity.get("realm") or ""),"paths":paths,"primary_method":_state("explicit_none" if explicit_none else ("present" if methods else "unavailable"),str(method.get("reason") or ""),path,value=methods[0]["stable_id"] if methods else None,include_value=bool(methods)),"subpaths_traditions":sub,"foundation":_state("explicit_none" if foundation_state.get("state") == "none" else ("present" if foundation else "unavailable"),str(foundation_state.get("reason") or "No exact Foundation record is available."),path,value=foundation[0]["stable_id"] if foundation else None,include_value=bool(foundation)),"foundation_expressions":foundation,"active_path_expressions":[],"resources":[resource]},
      "combat":{"hit_points":{"current":hp.get("build_state_current"),"maximum":hp.get("maximum")},"armor_class":ac.get("value"),"speed_ft":speed.get("walking_ft"),"attack_bonus":stats.get("technique_attack_bonus"),"save_dc":stats.get("technique_save_dc"),"initiative_bonus":stats.get("initiative_bonus"),"saving_throws":_fire_saves(stats),"runtime_contract":"not_duplicated"},
      "ability_scores":_ability_records_from_list(stats.get("abilities") or []),"skills":_skills_from_list(stats.get("skills") or [],package_sha,path,msha),"spheres":spheres,"automatic_base_abilities":automatic_components,"automatic_sphere_component_receipts":list(sphere_packets.values()),"automatic_sphere_components":automatic_components,"insights":insights,"cultivation_insight_occurrences":insight_occurrences,"talents":talents,"actions":actions,"reactions":reactions,"methods":methods,"recorded_arts":recorded,"forged_techniques":forged,"equipment":equipment,"states":states,"companions":companions,
      "provenance":{"source_package_sha256":package_sha,"selected_model_path":path,"selected_model_sha256":msha,"source_references":[source]},"readiness":{"gm_ready":True,"contract_valid":True,"combat_runtime_separate":True,"diagnostics":diagnostics},"incomplete_surfaces":incomplete,
      "field_states":{"automatic_base_abilities":_state("unavailable",incomplete[0]["reason"],path),"current_primary_method":_state(incomplete[1]["state"],incomplete[1]["reason"],path),"method_ap_authorized_paths":_state("unavailable",incomplete[2]["reason"],path),"active_path_expressions":_state("unavailable",incomplete[3]["reason"],path),"combat_runtime":_state("not_applicable","Combat Sheet/runtime model remains a separate contract.","combat/Combat_Sheet.json" if selected["runtime_package"] else path)}
    }
    mappings=[
      {"source_path":"$.identity.cultivation_level","target_path":"$.cultivation.cultivation_level","state":"renamed","operation":"copied integer"},
      {"source_path":"$.stats.hit_points.build_state_current/maximum","target_path":"$.combat.hit_points","state":"restructured","operation":"copied current and maximum"},
      {"source_path":"$.stats.armor_class.value","target_path":"$.combat.armor_class","state":"renamed","operation":"copied"},
      {"source_path":"$.stats.speed.walking_ft","target_path":"$.combat.speed_ft","state":"renamed","operation":"copied"},
      {"source_path":"$.stats.abilities[]","target_path":"$.ability_scores","state":"restructured","operation":"indexed exact source records by ability"},
      {"source_path":"$.stats.skills[]","target_path":"$.skills[]","state":"restructured","operation":"copied exact skill rows"},
      {"source_path":"$.paths_subpaths_insights","target_path":"$.cultivation.paths/$.cultivation.subpaths_traditions","state":"restructured","operation":"preserved active path and subpath; added dormant level-0 path records under owner ruling"},
      {"source_path":"$.method","target_path":"$.cultivation.primary_method","state":"explicit_none" if explicit_none else "unavailable","operation":"preserved explicit none/unavailable state"},
      {"source_path":"combat/*","target_path":"<excluded>","state":"not_applicable","operation":"Combat runtime remains a separate contract"},
    ]
    return out,mappings,incomplete


def normalize_view(model: dict[str, Any]) -> dict[str, Any]:
    insight_rows = model.get("insights") or []
    if not insight_rows:
        insight_rows, _ = _insight_projection(model, "", "paths_subpaths_insights", "")
    return {
        "schema": VIEW_V2,
        "schema_version": "2.0.0",
        "source_model_hash": sha256_bytes(canonical_bytes(model)),
        "identity": model["identity"],
        "core_stats": {
            "cultivation_level": model["cultivation"]["cultivation_level"],
            "realm": model["cultivation"]["realm"],
            "hit_points": model["combat"]["hit_points"],
            "armor_class": model["combat"]["armor_class"],
            "speed_ft": model["combat"]["speed_ft"],
            "attack_bonus": model["combat"]["attack_bonus"],
            "save_dc": model["combat"]["save_dc"],
            "resources": model["cultivation"]["resources"],
            "ability_scores": model["ability_scores"],
            "saving_throws": model["combat"]["saving_throws"],
            "skills": model["skills"],
        },
        "paths": model["cultivation"]["paths"],
        "cultivation": {
            "primary_method": model["cultivation"]["primary_method"],
            "foundation": model["cultivation"]["foundation"],
            "subpaths_traditions": model["cultivation"]["subpaths_traditions"],
            "foundation_expressions": model["cultivation"]["foundation_expressions"],
            "active_path_expressions": model["cultivation"]["active_path_expressions"],
            "resources": model["cultivation"]["resources"],
        },
        "sections": {
            "spheres": model["spheres"],
            "automatic_base_abilities": model["automatic_base_abilities"],
            "automatic_sphere_component_receipts": model.get("automatic_sphere_component_receipts") or [],
            "automatic_sphere_components": model.get("automatic_sphere_components") or [],
            "insights": insight_rows,
            "talents": model["talents"],
            "actions": model["actions"],
            "reactions": model["reactions"],
            "methods": model["methods"],
            "recorded_arts": model["recorded_arts"],
            "forged_techniques": model["forged_techniques"],
            "foundation_expressions": model["cultivation"]["foundation_expressions"],
            "active_path_expressions": model["cultivation"]["active_path_expressions"],
            "equipment": model["equipment"],
            "states": model["states"],
            "companions": model["companions"],
            "incomplete_surfaces": model["incomplete_surfaces"],
        },
        "diagnostics": model["readiness"]["diagnostics"],
        "renderable": bool(model["readiness"]["gm_ready"] and model["readiness"]["contract_valid"]),
    }


def migrate_package(path: Path) -> dict[str, Any]:
    audit = audit_package(path)
    package_sha = audit["package_sha256"]
    try:
        selected = select_candidate(path)
        profile = selected["profile"]
        if profile == "canonical_v2":
            model = selected["model"]
            minimum = ((model.get("metadata") or {}).get("minimum_consumer_version") or "0.0.0")
            if _semver_tuple(minimum) > _semver_tuple(CONSUMER_VERSION):
                raise GM2Error("GM2_CONSUMER_TOO_OLD", {"minimum_consumer_version": minimum, "consumer_version": CONSUMER_VERSION})
            readiness = model.get("readiness") or {}
            if readiness.get("gm_ready") is not True or readiness.get("contract_valid") is not True:
                raise GM2Error("GM2_MODEL_NOT_GM_READY", {"gm_ready": readiness.get("gm_ready"), "contract_valid": readiness.get("contract_valid")})
            if (model.get("combat") or {}).get("runtime_contract") != "not_duplicated":
                raise GM2Error("GM2_UNSUPPORTED_FIELD", {"field": "combat.runtime_contract", "required": "not_duplicated"})
            mappings=[]; omissions=[]; status="DIRECT_V2"
        elif profile == "legacy_phase2h_v1":
            model,mappings,omissions=_migrate_legacy(selected,package_sha); status="MIGRATED"
        elif profile in ("fire_qi_c2c1_v1","fire_qi_runtime_ready_v1"):
            model,mappings,omissions=_migrate_fire(selected,package_sha); status="MIGRATED"
        else:
            raise GM2Error("GM2_UNSUPPORTED_PROFILE", {"profile":profile})
        view=normalize_view(model)
        omission_rows = []
        for row in omissions:
            omission_rows.append({
                "target_path": str(row.get("target_path") or ("$." + str(row.get("surface") or "unknown"))),
                "state": str(row.get("state") or "unavailable"),
                "reason": str(row.get("reason") or "Not represented by the source model."),
                "source_path": str(row.get("source_path") or selected["path"]),
            })
        return {"schema":"Tianxia_GM_Migration_Result_v2","status":status,"source_profile":profile,"package_sha256":package_sha,"selected_candidate":{k:v for k,v in selected.items() if k not in ("model","manifest")},"model":model,"normalized_view":view,"field_mappings":mappings,"defaults_or_omissions":omission_rows,"diagnostics":model.get("readiness",{}).get("diagnostics",[]),"package_audit":audit}
    except GM2Error as exc:
        return {"schema":"Tianxia_GM_Migration_Result_v2","status":"REJECTED","source_profile":"rejected","package_sha256":package_sha,"selected_candidate":None,"field_mappings":[],"defaults_or_omissions":[],"diagnostics":[exc.response()],"error":exc.response(),"package_audit":audit}


def render_reference_html(result: dict[str, Any]) -> str:
    if result.get("status") == "REJECTED":
        err=result["error"]
        return f"<!doctype html><meta charset='utf-8'><title>GM Import Rejected</title><main><h1>Character not imported</h1><p><strong>{err['error_code']}</strong></p><p>{err['owner_message']}</p></main>\n"
    view=result["normalized_view"]; core=view["core_stats"]; ident=view["identity"]
    abilities="".join(f"<li>{ab}: {row['score']} ({row['modifier']:+d})</li>" if row['score'] is not None and row['modifier'] is not None else f"<li>{ab}: unavailable</li>" for ab,row in core["ability_scores"].items())
    skills="".join(f"<li>{x['name']}: {x['bonus'] if x['bonus'] is not None else 'unavailable'}</li>" for x in core["skills"])
    resources="".join(f"<li>{x['name']}: {x['current']}/{x['maximum']}</li>" for x in core["resources"])
    return f"<!doctype html><meta charset='utf-8'><title>{ident['display_name']}</title><main><h1>{ident['display_name']}</h1><p>CL {core['cultivation_level']} · {core['realm']}</p><dl><dt>HP</dt><dd>{core['hit_points']['current']}/{core['hit_points']['maximum']}</dd><dt>AC</dt><dd>{core['armor_class']}</dd><dt>Speed</dt><dd>{core['speed_ft']} ft</dd><dt>Attack</dt><dd>{core['attack_bonus']:+d}</dd><dt>Save DC</dt><dd>{core['save_dc']}</dd></dl><h2>Resources</h2><ul>{resources}</ul><h2>Abilities</h2><ul>{abilities}</ul><h2>Skills</h2><ul>{skills}</ul><p>Runtime combat model: separate contract; not embedded.</p></main>\n"


def write_result(package: Path, output_json: Path, output_html: Path | None = None) -> dict[str, Any]:
    result=migrate_package(package)
    output_json.parent.mkdir(parents=True,exist_ok=True)
    output_json.write_bytes(canonical_bytes(result))
    if output_html:
        output_html.parent.mkdir(parents=True,exist_ok=True)
        output_html.write_text(render_reference_html(result),encoding="utf-8")
    return result


if __name__ == "__main__":
    import argparse
    p=argparse.ArgumentParser(description="Read-only GM2 reference validator/migrator")
    p.add_argument("package",type=Path); p.add_argument("--output",type=Path,required=True); p.add_argument("--html",type=Path)
    args=p.parse_args(); result=write_result(args.package,args.output,args.html)
    print(json.dumps({"status":result["status"],"source_profile":result["source_profile"],"package_sha256":result["package_sha256"]},indent=2))
    raise SystemExit(0 if result["status"] != "REJECTED" else 2)
