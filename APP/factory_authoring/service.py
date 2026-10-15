from __future__ import annotations

import json
import os
import re
import shutil
import stat
import secrets
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from app.core import Database, FoundryError, canonical_json, sha256_bytes, sha256_file, sha256_json
from ai_provider.service import GM_TACTICAL_AUTHORING_PURPOSE, LOCAL_GM_AUTHORING_MAX_OUTPUT_TOKENS
from non_sphere_authority.foundation_mechanics import has_acquired_foundation
from non_sphere_authority.method_mechanics import has_acquired_method
from character_sheet.service import CharacterSheetService
from factory_authoring.command4_actions import (
    Command4ActionProducer,
    _issue_authenticated_constructed_immortal_source,
)
from factory_authoring.theme_contract import (
    GM_THEME_RESPONSE_SCHEMA,
    GM_THEMES_RESPONSE_SCHEMA,
    validate_gm_themes,
)
from projector.service import ProjectionService
from project_store.service import ProjectStore
from security.integrity import IntegrityService
from security.local_identity import PrincipalProvider, ProcessPrincipalProvider

_AUTHORING_PROFILE = "Tianxia_Fire_Qi_GM_Tactical_Authoring_Profile_R1.json"
_WORKSPACE_PROFILE = "Tianxia_C2B2_Factory_Command_1_4_Workspace_Profile_R1.json"
_STATUS = "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE"
_LEGACY_PROFILE_ID = "Tianxia_Fire_Qi_GM_Tactical_Authoring_Profile_R1"
_GM_PROVISIONAL_CLASSIFICATION = "PROVISIONAL_GM_GUIDANCE"
_GM_ACTUAL_CLASSIFICATION = "ACTUAL_GM_AUTHORING"
SERVER_COMPOSITE_GUIDANCE_SCHEMA = "TianxiaFoundry.ServerDerivedCompositeGuidance.v1"
_GM_AUTHORSHIP_SCHEMA = "TianxiaFoundry.GMAuthorshipBinding.v1"
_GM_PROVISIONAL_STATUS = "PROVISIONAL"
_GM_ACTUAL_STATUS = "ACTUAL"
_GM_ARTIFACT_SCHEMA = "TianxiaFoundry.GMAuthoringArtifact.v1"
_GM_RECEIPT_SCHEMA = "TianxiaFoundry.GMAuthoringReceipt.v1"
_GM_SOURCE_SNAPSHOT_SCHEMA = "TianxiaFoundry.GMSelectedRecordSnapshot.v1"
_GM_OWNER_DECISION_SCHEMA = "TianxiaFoundry.GMOwnerRatificationDecision.v1"
_GM_ARTIFACT_ROOT_NAME = "factory_gm_authoring"
_GM_RECEIPT_INTEGRITY_DOMAIN = "tianxia.foundry.gm_authoring.receipt"
_GM_DECISION_INTEGRITY_DOMAIN = "tianxia.foundry.gm_authoring.owner_decision"
_GM_AUTHORING_PURPOSE = GM_TACTICAL_AUTHORING_PURPOSE
_GM_RESPONSE_SCHEMA_NAME = "tianxia_gm_tactical_authoring"
_GM_LOCAL_PROVIDER_IDS = frozenset({"local", "lemonade"})
# A harness-held agent may author GM artifacts through the same provider
# contract as a local model.  The local-only set above still governs local
# runtime identity checks.
_GM_AUTHORING_PROVIDER_IDS = _GM_LOCAL_PROVIDER_IDS | {"agent"}
_GM_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GM_PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
_GM_COMPOSITE_CONTRACT = "TianxiaFoundry.CandidateGMCompositeController.v1"

_GM_THEME_RESPONSE_SCHEMA = GM_THEME_RESPONSE_SCHEMA
_GM_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["dao", "i_ching"],
    "properties": {
        "dao": _GM_THEME_RESPONSE_SCHEMA,
        "i_ching": _GM_THEME_RESPONSE_SCHEMA,
        "gm_themes": GM_THEMES_RESPONSE_SCHEMA,
    },
}


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(value), encoding="utf-8", newline="\n")



def _advanced_system_result(snapshot: dict[str, Any], section: str, none_key: str) -> Any:
    """Return the acquired rows of an advanced system, else its typed absence.

    A Factory-constructed Forged Technique or a learned Recorded Art replaces
    the typed-none resolution; the audit then carries the acquired rows.
    """
    rows = snapshot.get(section)
    if isinstance(rows, list) and rows:
        return deepcopy(rows)
    explicit = snapshot.get("explicit_none_systems") or {}
    value = explicit.get(none_key) if isinstance(explicit, dict) else None
    if isinstance(value, dict):
        return deepcopy(value)
    return {"state": "none", "source_backed": False, "reason": f"No {section.replace('_', ' ')} projection is present."}

def _advanced_system_state(value: Any, *, present_state: str, system: str) -> dict[str, Any]:
    """Project an audit value into the read-only view's ``state`` shape.

    An audit carries a list of acquired rows when the system is present and a
    ``{"state": ...}`` object when it is a typed absence.  The sheet view must
    always expose ``state``; otherwise the display falls back to "not acquired"
    while the tabs list the acquired rows.
    """
    if isinstance(value, list) and value:
        names = [
            str(row.get("display_name") or row.get("name") or row.get("record_id"))
            for row in value
            if isinstance(row, dict) and (row.get("display_name") or row.get("name") or row.get("record_id"))
        ]
        return {
            "state": present_state,
            "count": len(value),
            "source_backed": True,
            "display_names": names,
            "note": f"{len(value)} {system}: {' · '.join(names)}" if names else f"{len(value)} {system}.",
        }
    if isinstance(value, dict) and value:
        return deepcopy(value)
    return {"state": "none", "source_backed": False, "reason": f"No {system} projection is present."}


class FactoryAuthoringWorkspaceService:
    """Build the bounded C2B.2 GM-authoring workspace through Command 1–4 inputs.

    This service reuses canonical project, projection, and Character Sheet read
    models. It does not run or replace the pinned Factory compiler, and it never
    claims the legacy executable Command 4, Command 5, or Command 6 seals.
    """

    def __init__(
        self,
        db: Database,
        *,
        principal_provider: PrincipalProvider | None = None,
        integrity: IntegrityService | None = None,
        final_character_workflow: Any | None = None,
    ):
        self.db = db
        self.principal_provider = principal_provider or ProcessPrincipalProvider()
        self.integrity = integrity or IntegrityService.for_database(db)
        self.projects = ProjectStore(
            db,
            principal_provider=self.principal_provider,
            integrity=self.integrity,
        )
        self.projections = ProjectionService(db)
        self.sheets = CharacterSheetService(db)
        if final_character_workflow is None:
            # Keep this import lazy: the workflow imports the authoring
            # controllers, which in turn refer back to this service module.
            from factory_authoring.final_character_workflow import FinalCharacterWorkflowService

            final_character_workflow = FinalCharacterWorkflowService(
                db,
                principal_provider=self.principal_provider,
                integrity=self.integrity,
            )
        self.final_character_workflow = final_character_workflow

    @property
    def _contracts_dir(self) -> Path:
        return Path(__file__).resolve().parent / "contracts"

    @staticmethod
    def _verify_sealed_json(path: Path, *, expected_schema: str, error_prefix: str) -> tuple[dict[str, Any], str]:
        if not path.is_file():
            raise FoundryError(f"{error_prefix}_MISSING", f"Required sealed contract is missing: {path.name}")
        sidecar = path.with_suffix(path.suffix + ".sha256")
        if not sidecar.is_file():
            raise FoundryError(f"{error_prefix}_SIDECAR_MISSING", f"Required detached checksum is missing: {sidecar.name}")
        try:
            digest, declared = sidecar.read_text(encoding="utf-8").strip().split(None, 1)
        except ValueError as exc:
            raise FoundryError(f"{error_prefix}_SIDECAR_INVALID", "The detached checksum sidecar is malformed.") from exc
        declared = declared.strip().lstrip("*")
        actual = sha256_file(path)
        if declared != path.name or digest.lower() != actual:
            raise FoundryError(
                f"{error_prefix}_STALE",
                "The sealed contract does not match its detached checksum.",
                details={"expected": digest.lower(), "actual": actual, "declared_name": declared},
            )
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != expected_schema:
            raise FoundryError(
                f"{error_prefix}_SCHEMA_UNSUPPORTED",
                "The sealed contract schema is unsupported.",
                details={"expected": expected_schema, "actual": payload.get("schema_version")},
            )
        internal = payload.get("seal_sha256")
        unsigned = dict(payload); unsigned.pop("seal_sha256", None)
        calculated = sha256_json(unsigned)
        if internal != calculated:
            raise FoundryError(
                f"{error_prefix}_INTERNAL_SEAL_INVALID",
                "The sealed contract internal hash is invalid.",
                details={"expected": internal, "actual": calculated},
            )
        return payload, actual

    def _authoring_profile(self) -> tuple[dict[str, Any], str]:
        return self._verify_sealed_json(
            self._contracts_dir / _AUTHORING_PROFILE,
            expected_schema="TianxiaFoundry.GMTacticalAuthoringProfile.v1",
            error_prefix="GM_AUTHORING_PROFILE",
        )

    def _workspace_profile(self) -> tuple[dict[str, Any], str]:
        return self._verify_sealed_json(
            self._contracts_dir / _WORKSPACE_PROFILE,
            expected_schema="TianxiaFoundry.FactoryAuthoringWorkspaceProfile.v1",
            error_prefix="FACTORY_WORKSPACE_PROFILE",
        )

    @staticmethod
    def _is_project_derived_profile(profile: Mapping[str, Any]) -> bool:
        return str(profile.get("profile_id") or "").startswith("Tianxia_Project_Derived_GM_Tactical_Authoring_")

    @classmethod
    def _is_legacy_profile(cls, profile: Mapping[str, Any]) -> bool:
        return profile.get("profile_id") == _LEGACY_PROFILE_ID

    @classmethod
    def _profile_authorship(cls, profile: Mapping[str, Any]) -> dict[str, Any] | None:
        """Return the explicit authorship binding without inferring one.

        The sealed historical profile predates this field and must remain byte
        compatible.  A missing binding therefore means historical compatibility
        only; a project-derived profile must carry an explicit provisional
        binding and a future provider-authored profile must carry an actual one.
        """
        value = profile.get("authorship")
        if value is None:
            return None
        return deepcopy(dict(value)) if isinstance(value, Mapping) else None

    @classmethod
    def _project_authoring_profile(
        cls,
        snapshot: dict[str, Any],
        sealed_profile: dict[str, Any],
        sealed_profile_sha: str,
        workspace_profile: dict[str, Any],
        workspace_profile_sha: str,
        *,
        force_derived: bool = False,
    ) -> tuple[dict[str, Any], str, dict[str, Any], str]:
        cards = cls._card_index(snapshot)
        selected_ids = set(cards)
        sealed_ids = set(workspace_profile.get("required_training_source_coverage") or [])
        if sealed_ids == selected_ids and not force_derived:
            return sealed_profile, sealed_profile_sha, workspace_profile, workspace_profile_sha

        grouped: dict[str, list[str]] = {}
        for record_id, card in cards.items():
            grouped.setdefault(str(card.get("section") or "selected_records"), []).append(record_id)
        training_sources = []
        for section in sorted(grouped):
            record_ids = sorted(grouped[section])
            training_sources.append({
                "source_id": f"gm.training.project.{sha256_json(record_ids)[:16]}",
                "name": f"{section.replace('_', ' ').title()} selected-record training",
                "source_category": "PROJECT_SELECTED_RECORD_TRAINING",
                "factory_source_type": "other",
                "classification": "GM_GUIDANCE_ONLY",
                "record_ids": record_ids,
                "summary": "Groups only records already selected in the revision-bound project snapshot; grants no mechanics or acquisitions.",
            })
        display_ids = sorted(
            record_id for record_id, card in cards.items()
            if (card.get("capabilities") or {}).get("combat_execution") != "NOT_APPLICABLE"
        ) or sorted(selected_ids)
        thematic_ids = sorted(
            record_id for record_id, card in cards.items()
            if str(card.get("section") or "") in {"path_subpath", "spheres", "talents", "path_features"}
        ) or sorted(selected_ids)
        unsigned = {
            "schema_version": "TianxiaFoundry.GMTacticalAuthoringProfile.v1",
            "profile_id": f"Tianxia_Project_Derived_GM_Tactical_Authoring_{sha256_json(sorted(selected_ids))[:16]}",
            "version": "1.1.0",
            "authority_classification": _GM_PROVISIONAL_CLASSIFICATION,
            "authorship": {
                "schema_version": _GM_AUTHORSHIP_SCHEMA,
                "status": _GM_PROVISIONAL_STATUS,
                "origin": "project_selected_record_template",
                "provider_id": None,
                "artifact_bound": False,
                "artifact_sha256": None,
                "owner_ratified": False,
                "source_record_ids": sorted(selected_ids),
            },
            "global_labels": ["GM_GUIDANCE_ONLY", "DISPLAY_ONLY_NOT_EXECUTION_AUTHORITY", _GM_PROVISIONAL_CLASSIFICATION],
            "scope": {
                "project_id_hardcoded": False,
                "event_id_hardcoded": False,
                "mechanical_authority": False,
                "execution_authority": False,
                "reusable_for_same_records": True,
                "supported_record_slice": "Exact records in the revision-bound typed project choice snapshot.",
            },
            "prohibitions": {
                "alter_advancement": True,
                "create_action_definitions": True,
                "create_method_manual_or_equipment": True,
                "invent_mechanics": True,
                "register_ai_policy": True,
            },
            "training_sources": training_sources,
            "dao_i_ching": {
                "classification": _GM_PROVISIONAL_CLASSIFICATION,
                "dao": {
                    "authoring_id": f"gm.dao.project.{sha256_json(thematic_ids)[:16]}",
                    "display_name": "Project-Derived Cultivation Theme",
                    "core_theme": "Portray the character through the exact selected path, spheres, talents, and features.",
                    "principles": ["Respect selected authority", "Do not infer unselected mechanics"],
                    "strengths": [], "risks": [],
                    "roleplay_expression": "Use selected record descriptions as portrayal context only.",
                    "tactical_expression": "This guidance grants no bonus, action, or effect.",
                    "gm_usage_notes": "Interpretive display guidance only.",
                    "relevant_record_ids": thematic_ids,
                    "mechanical_effects": [],
                },
                "i_ching": {
                    "authoring_id": f"gm.iching.project.{sha256_json(thematic_ids)[:16]}",
                    "display_name": "Project-Derived Change Theme",
                    "core_theme": "Frame change through the character's exact selected record authority.",
                    "principles": ["Preserve canonical selections", "Keep interpretation non-mechanical"],
                    "strengths": [], "risks": [],
                    "roleplay_expression": "Use the selected record set as narrative context.",
                    "tactical_expression": "This guidance grants no bonus, action, or effect.",
                    "gm_usage_notes": "Interpretive display guidance only.",
                    "relevant_record_ids": thematic_ids,
                    "mechanical_effects": [],
                },
            },
            "ai_behavior": {
                "profile_id": f"gm.ai.project.display.{sha256_json(display_ids)[:16]}",
                "role": "Descriptive assistant for exact selected records",
                "classification": "DISPLAY_ONLY_NOT_EXECUTION_AUTHORITY",
                "record_ids": display_ids,
                "preferred_patterns": ["Reference exact selected records without inventing mechanics."],
                "capability_dependencies": ["typed combat execution definitions", "legal candidate generation"],
                "fallback_behavior": "When typed legality is unavailable, choose no invented mechanic.",
                "not_executable_controller_policy": True,
                "prohibited_invented_mechanic_behavior": ["Do not invent values, targets, effects, costs, or timing."],
            },
        }
        profile = {**unsigned, "seal_sha256": sha256_json(unsigned)}
        dynamic_workspace = deepcopy(workspace_profile)
        dynamic_workspace["profile_id"] = f"{workspace_profile['profile_id']}.project-derived"
        dynamic_workspace["required_training_source_coverage"] = sorted(selected_ids)
        dynamic_workspace["authorship"] = deepcopy(unsigned["authorship"])
        semantics = dynamic_workspace.setdefault("semantics", {})
        semantics["gm_authoring"] = "PROVISIONAL_GM_GUIDANCE_ONLY"
        semantics["command5"] = "BLOCKED_UNTIL_ACTUAL_GM_AUTHORING"
        dynamic_workspace["legacy_boundaries"] = deepcopy(dynamic_workspace.get("legacy_boundaries") or {})
        dynamic_workspace["legacy_boundaries"]["eligible_for_later_command5_checkpoint"] = False
        dynamic_workspace["legacy_boundaries"]["explanation"] = (
            "Project-derived GM guidance is provisional. Actual model authorship, "
            "source binding, and owner ratification are required before Command 5."
        )
        workspace_unsigned = {key: value for key, value in dynamic_workspace.items() if key != "seal_sha256"}
        dynamic_workspace["seal_sha256"] = sha256_json(workspace_unsigned)
        return profile, sha256_json(profile), dynamic_workspace, sha256_json(dynamic_workspace)

    def _root(self, project_id: str) -> Path:
        return self.db.settings.data_dir / "factory_workspaces" / project_id

    def _pointer(self, project_id: str) -> Path:
        return self._root(project_id) / "current.json"

    def _gm_root(self, project_id: str) -> Path:
        if not isinstance(project_id, str) or _GM_PROJECT_ID_RE.fullmatch(project_id) is None:
            raise FoundryError("GM_AUTHORING_PROJECT_ID_INVALID", "The GM authoring project ID is invalid.")
        return self.db.settings.data_dir / _GM_ARTIFACT_ROOT_NAME / project_id

    @staticmethod
    def _gm_json_bytes(value: Mapping[str, Any]) -> bytes:
        return (canonical_json(dict(value)) + "\n").encode("utf-8")

    @staticmethod
    def _gm_read_json(path: Path, *, code: str = "GM_AUTHORING_ARTIFACT_INVALID") -> dict[str, Any]:
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
                raise ValueError("not a bounded regular file")
            flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(path, flags)
            try:
                with os.fdopen(fd, "rb") as source:
                    fd = -1
                    raw = source.read(2 * 1024 * 1024 + 1)
            finally:
                if fd >= 0:
                    os.close(fd)
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError("file too large")
            value = json.loads(raw.decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("object required")
            return value
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise FoundryError(code, "The server-owned GM authoring artifact is missing or invalid.", details={"path": path.name}) from exc

    @staticmethod
    def _gm_write_immutable_json(root: Path, name: str, value: Mapping[str, Any]) -> tuple[Path, str]:
        root.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(root, 0o700)
        except OSError:
            pass
        path = root / name
        payload = FactoryAuthoringWorkspaceService._gm_json_bytes(value)
        digest = sha256_bytes(payload)
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(path, flags, 0o600)
            try:
                with os.fdopen(fd, "wb") as target:
                    fd = -1
                    target.write(payload)
                    target.flush()
                    os.fsync(target.fileno())
            finally:
                if fd >= 0:
                    os.close(fd)
        except FileExistsError:
            try:
                if sha256_file(path) != digest:
                    raise FoundryError("GM_AUTHORING_IMMUTABLE_COLLISION", "An immutable GM authoring identity already names different bytes.", details={"path": path.name}, status_code=409)
            except OSError as exc:
                raise FoundryError("GM_AUTHORING_ARTIFACT_INVALID", "The immutable GM authoring artifact cannot be read.", details={"path": path.name}, status_code=409) from exc
        except OSError as exc:
            raise FoundryError("GM_AUTHORING_ARTIFACT_WRITE_FAILED", "The server-owned GM authoring artifact could not be persisted.", status_code=500) from exc
        return path, digest

    @staticmethod
    def _gm_write_pointer(path: Path, value: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(path.parent, 0o700)
        except OSError:
            pass
        temporary = path.with_name(path.name + ".new")
        payload = FactoryAuthoringWorkspaceService._gm_json_bytes(value)
        temporary.write_bytes(payload)
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        os.replace(temporary, path)

    @classmethod
    def _selected_record_snapshot(
        cls,
        project_id: str,
        project_revision: int,
        snapshot: Mapping[str, Any],
    ) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        sections = snapshot.get("selected_record_sections") if isinstance(snapshot, Mapping) else None
        if not isinstance(sections, Mapping):
            raise FoundryError("GM_AUTHORING_SOURCE_SNAPSHOT_INVALID", "The selected-record source snapshot is missing its typed sections.")
        for section_name, section_rows in sections.items():
            if not isinstance(section_rows, list):
                raise FoundryError("GM_AUTHORING_SOURCE_SNAPSHOT_INVALID", "A selected-record section is not a list.", details={"section": str(section_name)})
            for raw in section_rows:
                if not isinstance(raw, Mapping) or not isinstance(raw.get("record_id"), str) or not raw.get("record_id"):
                    raise FoundryError("GM_AUTHORING_SOURCE_SNAPSHOT_INVALID", "Every selected record requires a nonblank record ID.")
                record_id = str(raw["record_id"])
                if record_id in seen:
                    raise FoundryError("GM_AUTHORING_SOURCE_SNAPSHOT_INVALID", "A selected record ID occurs more than once.", details={"record_id": record_id})
                seen.add(record_id)
                rows.append({"section": str(section_name), "record": deepcopy(dict(raw))})
        rows.sort(key=lambda row: (str(row["record"]["record_id"]), row["section"]))
        return {
            "schema_version": _GM_SOURCE_SNAPSHOT_SCHEMA,
            "project_id": project_id,
            "project_revision": int(project_revision),
            "record_ids": [str(row["record"]["record_id"]) for row in rows],
            "records": rows,
            "selected_record_content_sha256": sha256_json(rows),
        }

    @staticmethod
    def _snapshot_from_gm_source(source: Mapping[str, Any]) -> dict[str, Any]:
        sections: dict[str, list[dict[str, Any]]] = {}
        for row in source.get("records") or []:
            if not isinstance(row, Mapping) or not isinstance(row.get("record"), Mapping):
                continue
            sections.setdefault(str(row.get("section") or "selected_records"), []).append(deepcopy(dict(row["record"])))
        return {"selected_record_sections": sections}

    @staticmethod
    def _gm_file_hash(path: Path, expected: str, *, label: str) -> str:
        if not isinstance(expected, str) or _GM_SHA256_RE.fullmatch(expected) is None:
            raise FoundryError("GM_AUTHORING_ARTIFACT_BINDING_INVALID", f"The {label} hash is malformed.")
        try:
            actual = sha256_file(path)
        except OSError as exc:
            raise FoundryError("GM_AUTHORING_ARTIFACT_MISSING", f"The server-owned {label} is missing.", details={"path": path.name}) from exc
        if actual != expected:
            raise FoundryError("GM_AUTHORING_ARTIFACT_STALE", f"The server-owned {label} changed after authoring.", details={"expected": expected, "actual": actual})
        return actual

    @staticmethod
    def _gm_compare(value: Any, expected: Any, code: str = "GM_AUTHORING_ARTIFACT_BINDING_INVALID") -> None:
        if value != expected:
            raise FoundryError(code, "The server-owned GM authoring bindings disagree.")

    @classmethod
    def _validate_gm_response(cls, response: Any, selected_ids: set[str]) -> dict[str, Any]:
        if not isinstance(response, Mapping):
            raise FoundryError("GM_AUTHORING_PROVIDER_RESPONSE_INVALID", "The local provider response must be one JSON object.")
        try:
            Draft202012Validator(_GM_RESPONSE_SCHEMA).validate(dict(response))
        except Exception as exc:
            raise FoundryError("GM_AUTHORING_PROVIDER_RESPONSE_INVALID", "The local provider response failed the strict GM authoring schema.", details={"reason": str(exc)}) from exc
        normalized = deepcopy(dict(response))
        for key in ("dao", "i_ching"):
            row = normalized[key]
            unknown = sorted(set(row["relevant_record_ids"]) - selected_ids)
            if unknown:
                raise FoundryError("GM_AUTHORING_PROVIDER_SOURCE_UNKNOWN", "The local provider referenced a record outside the selected source snapshot.", details={"kind": key, "record_ids": unknown})
            if row.get("mechanical_effects") != []:
                raise FoundryError("GM_AUTHORING_PROVIDER_MECHANICS_FORBIDDEN", "GM authoring responses cannot introduce mechanical effects.")
        if "gm_themes" in normalized:
            validate_gm_themes(normalized["gm_themes"], selected_ids)
        cls._reject_executable_claims(normalized)
        return normalized

    @classmethod
    def gm_tactical_prompt(
        cls,
        *,
        project_id: str,
        project_revision: int,
        records: list[Mapping[str, Any]],
        record_content_sha256: str,
    ) -> tuple[str, str]:
        """Build the exact bounded prompt contract shared by live and candidate GM authoring."""
        system_message = (
            "You are the local Tianxia GM authoring adapter. Return exactly one object matching the supplied schema. "
            "Use only the selected record content in the request. Produce descriptive Dao and I Ching text. "
            "Do not add mechanics, costs, bonuses, actions, effects, targets, or execution policy."
        )
        prompt_records = []
        for row in records:
            record = row.get("record") if isinstance(row.get("record"), Mapping) else row
            section = row.get("section")
            if section is None:
                section = record.get("section")
            projection = {
                "section": deepcopy(section),
                "record_id": deepcopy(record.get("record_id")),
            }
            for key in (
                "display_name",
                "one_line_description",
                "subsection",
                "acquisition_route",
                "parent_sphere_id",
                "acquisition_cl",
            ):
                value = record.get(key)
                if value not in (None, "", [], {}):
                    projection[key] = deepcopy(value)
            prompt_records.append(projection)
        prompt_text = canonical_json({
            "task": "Author descriptive GM guidance for this exact selected-record snapshot.",
            "source": {
                "project_id": project_id,
                "project_revision": int(project_revision),
                "records": prompt_records,
                "record_content_sha256": record_content_sha256,
            },
            "constraints": [
                "mechanical_effects must be []",
                "all relevant record IDs must be selected IDs",
                "do not invent source facts",
            ],
        })
        if len((prompt_text + system_message).encode("utf-8")) > 48 * 1024:
            raise FoundryError(
                "GM_AUTHORING_REQUEST_TOO_LARGE",
                "The selected source snapshot exceeds the bounded GM authoring request size.",
            )
        return system_message, prompt_text

    @classmethod
    def gm_tactical_contract(cls) -> dict[str, Any]:
        """Expose the existing schema and wire purpose without duplicating them."""
        return {
            "purpose": _GM_AUTHORING_PURPOSE,
            "response_schema_name": _GM_RESPONSE_SCHEMA_NAME,
            "response_schema": deepcopy(_GM_RESPONSE_SCHEMA),
            "response_schema_max_output_tokens": LOCAL_GM_AUTHORING_MAX_OUTPUT_TOKENS,
            "max_request_bytes": 65_536,
        }

    @classmethod
    def _actual_profile_from_response(
        cls,
        *,
        provisional_profile: Mapping[str, Any],
        response: Mapping[str, Any],
        project_id: str,
        project_revision: int,
        source_snapshot_sha256: str,
        selected_record_content_sha256: str,
        artifact_sha256: str,
        request_sha256: str,
        response_sha256: str,
        provider_id: str,
        model: str | None,
        owner_ratified: bool = False,
        owner_decision_id: str | None = None,
        profile_extension: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        profile = deepcopy(dict(provisional_profile))
        selected_ids = sorted((profile.get("authorship") or {}).get("source_record_ids") or [])
        authorship = {
            "schema_version": _GM_AUTHORSHIP_SCHEMA,
            "status": _GM_ACTUAL_STATUS,
            "origin": "provider_model_artifact",
            "provider_id": provider_id,
            "model": model,
            "artifact_bound": True,
            "artifact_sha256": artifact_sha256,
            "request_sha256": request_sha256,
            "response_sha256": response_sha256,
            "owner_ratified": owner_ratified,
            "owner_decision_id": owner_decision_id,
            "project_id": project_id,
            "project_revision": int(project_revision),
            "source_snapshot_sha256": source_snapshot_sha256,
            "selected_record_content_sha256": selected_record_content_sha256,
            "source_record_ids": selected_ids,
        }
        profile["profile_id"] = f"Tianxia_Actual_GM_Tactical_Authoring_{sha256_json({'project_id': project_id, 'revision': int(project_revision), 'artifact_sha256': artifact_sha256})[:32]}"
        profile["authority_classification"] = _GM_ACTUAL_CLASSIFICATION
        profile["authorship"] = authorship
        profile["global_labels"] = [
            "GM_GUIDANCE_ONLY", "DISPLAY_ONLY_NOT_EXECUTION_AUTHORITY", _GM_ACTUAL_CLASSIFICATION,
        ]
        profile["dao_i_ching"] = {
            "classification": _GM_ACTUAL_CLASSIFICATION,
            "dao": {
                "authoring_id": "gm.dao.actual." + sha256_json(response["dao"])[:24],
                **deepcopy(dict(response["dao"])),
            },
            "i_ching": {
                "authoring_id": "gm.iching.actual." + sha256_json(response["i_ching"])[:24],
                **deepcopy(dict(response["i_ching"])),
            },
        }
        display_ids = sorted(set(response["dao"]["relevant_record_ids"]) | set(response["i_ching"]["relevant_record_ids"]))
        ai = deepcopy(profile.get("ai_behavior") or {})
        ai.update({
            "profile_id": "gm.ai.actual.display." + sha256_json(response)[:24],
            "classification": "DISPLAY_ONLY_NOT_EXECUTION_AUTHORITY",
            "record_ids": display_ids,
            "role": "Actual model-authored descriptive assistant",
            "preferred_patterns": ["Use only the exact selected source records and preserve their non-executable boundary."],
            "not_executable_controller_policy": True,
            "fallback_behavior": "When typed legality is unavailable, choose no invented mechanic.",
        })
        profile["ai_behavior"] = ai
        if isinstance(profile_extension, Mapping):
            profile.update(deepcopy(dict(profile_extension)))
        unsigned = {key: value for key, value in profile.items() if key != "seal_sha256"}
        profile["seal_sha256"] = sha256_json(unsigned)
        return profile

    @classmethod
    def _actual_workspace_profile(
        cls,
        workspace_profile: Mapping[str, Any],
        profile: Mapping[str, Any],
        *,
        owner_ratified: bool,
    ) -> dict[str, Any]:
        value = deepcopy(dict(workspace_profile))
        value["profile_id"] = f"{workspace_profile.get('profile_id')}.actual-gm"
        value["required_training_source_coverage"] = sorted((profile.get("authorship") or {}).get("source_record_ids") or [])
        value["authorship"] = deepcopy(profile.get("authorship") or {})
        semantics = value.setdefault("semantics", {})
        semantics["gm_authoring"] = "ACTUAL_GM_AUTHORING" if owner_ratified else "ACTUAL_GM_AUTHORING_PENDING_OWNER_RATIFICATION"
        semantics["command5"] = "NOT_RUN"
        boundaries = value.setdefault("legacy_boundaries", {})
        boundaries["eligible_for_later_command5_checkpoint"] = bool(owner_ratified)
        boundaries["explanation"] = "Actual provider-authored GM guidance is source-bound; owner ratification remains a separate gate."
        unsigned = {key: item for key, item in value.items() if key != "seal_sha256"}
        value["seal_sha256"] = sha256_json(unsigned)
        return value

    def _persist_gm_authoring(
        self,
        project_id: str,
        project_revision: int,
        snapshot: Mapping[str, Any],
        *,
        prompt_text: str,
        system_message: str,
        provider_result: Mapping[str, Any],
        response: Mapping[str, Any] | None = None,
        provider_response: Mapping[str, Any] | None = None,
        authoring_contract: str | None = None,
        response_schema_name: str | None = None,
        response_schema: Mapping[str, Any] | None = None,
        profile_extension: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist one validated provider result as a server-owned GM artifact.

        Every object is content addressed and written with create-once semantics.
        The mutable pointer is the only index; it is itself hash sealed.  This
        keeps a provider result usable by read/build/status paths without making
        any caller supplied digest an authority claim.
        """
        settings = self.db.settings
        root = self._gm_root(project_id)
        source = self._selected_record_snapshot(project_id, project_revision, snapshot)
        source_dir = root / "sources"
        source_path, source_file_sha256 = self._gm_write_immutable_json(
            source_dir,
            f"source.{source['selected_record_content_sha256']}.json",
            source,
        )
        parsed = response if response is not None else provider_result.get("value")
        parsed = self._validate_gm_response(parsed, set(source["record_ids"]))
        original_provider = provider_response if isinstance(provider_response, Mapping) else provider_result
        effective_profile_extension = deepcopy(dict(profile_extension)) if isinstance(profile_extension, Mapping) else None
        if authoring_contract is not None:
            if effective_profile_extension is None:
                effective_profile_extension = {}
            effective_profile_extension["authoring_contract"] = authoring_contract
        provider_id = provider_result.get("provider_id")
        model = provider_result.get("model")
        if not isinstance(provider_id, str) or provider_id not in _GM_AUTHORING_PROVIDER_IDS:
            raise FoundryError("GM_AUTHORING_PROVIDER_INVALID", "Only the configured local provider or the Agent bridge may author a GM artifact.")
        if provider_result.get("purpose") != _GM_AUTHORING_PURPOSE:
            raise FoundryError("GM_AUTHORING_PROVIDER_EVIDENCE_INVALID", "The provider result purpose is not bound to GM tactical authoring.")
        if not isinstance(prompt_text, str) or not prompt_text.strip() or not isinstance(system_message, str) or not system_message.strip():
            raise FoundryError("GM_AUTHORING_REQUEST_INVALID", "The GM authoring request must include bounded prompt and system text.")
        provider_request_sha256 = provider_result.get("request_sha256")
        provider_response_sha256 = provider_result.get("response_sha256")
        provider_completion_sha256 = provider_result.get("completion_sha256")
        for name, value in (("request", provider_request_sha256), ("response", provider_response_sha256), ("completion", provider_completion_sha256)):
            if not isinstance(value, str) or _GM_SHA256_RE.fullmatch(value) is None:
                raise FoundryError("GM_AUTHORING_PROVIDER_EVIDENCE_INVALID", "The provider did not return complete hash evidence.", details={"field": f"{name}_sha256"})
        raw_response = original_provider.get("response_text")
        if not isinstance(raw_response, str) or not raw_response.strip():
            raw_response = canonical_json(parsed)
        try:
            provider_value = original_provider.get("value")
            if provider_response is None and json.loads(raw_response) != parsed:
                raise ValueError("response_text differs from parsed response")
            if provider_response is not None and json.loads(raw_response) != provider_value:
                raise ValueError("provider response_text differs from provider value")
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise FoundryError("GM_AUTHORING_PROVIDER_RESPONSE_INVALID", "The persisted provider response is not the validated JSON object.") from exc
        if sha256_bytes(raw_response.encode("utf-8")) != provider_completion_sha256:
            raise FoundryError("GM_AUTHORING_PROVIDER_EVIDENCE_INVALID", "The provider completion hash does not match its response text.")
        source_snapshot_sha256 = source_file_sha256
        content_sha256 = source["selected_record_content_sha256"]
        safe_result = {
            key: deepcopy(value)
            for key, value in provider_result.items()
            if key in {
                "provider_id", "purpose", "model", "request_sha256", "response_sha256", "completion_sha256",
                "finish_reason", "usage", "performance", "timings",
            }
        }
        if authoring_contract is not None:
            safe_result["authoring_contract"] = authoring_contract
            safe_result["provider_purpose"] = original_provider.get("purpose")
        request_doc = {
            "schema_version": "TianxiaFoundry.GMAuthoringRequest.v1",
            "project_id": project_id,
            "project_revision": int(project_revision),
            "purpose": _GM_AUTHORING_PURPOSE,
            "provider_id": provider_id,
            "model": model,
            "system_message": system_message,
            "prompt_text": prompt_text,
            "response_schema_name": response_schema_name or _GM_RESPONSE_SCHEMA_NAME,
            "response_schema": deepcopy(dict(response_schema)) if isinstance(response_schema, Mapping) else deepcopy(_GM_RESPONSE_SCHEMA),
            "provider_request_sha256": provider_request_sha256,
            "source_snapshot_sha256": source_snapshot_sha256,
            "selected_record_content_sha256": content_sha256,
        }
        if authoring_contract is not None:
            request_doc["authoring_contract"] = authoring_contract
        request_path, request_file_sha256 = self._gm_write_immutable_json(
            root / "requests",
            f"request.{provider_request_sha256}.json",
            request_doc,
        )
        response_doc = {
            "schema_version": "TianxiaFoundry.GMAuthoringResponse.v1",
            "project_id": project_id,
            "project_revision": int(project_revision),
            "provider_id": provider_id,
            "model": model,
            "provider_request_sha256": provider_request_sha256,
            "provider_response_sha256": provider_response_sha256,
            "provider_completion_sha256": provider_completion_sha256,
            "response_text": raw_response,
            "value": parsed,
            "provider_evidence": safe_result,
        }
        if authoring_contract is not None:
            response_doc["authoring_contract"] = authoring_contract
            response_doc["provider_response"] = deepcopy(dict(original_provider))
        response_path, response_file_sha256 = self._gm_write_immutable_json(
            root / "responses",
            f"response.{provider_response_sha256}.json",
            response_doc,
        )
        artifact_unsigned = {
            "schema_version": _GM_ARTIFACT_SCHEMA,
            "project_id": project_id,
            "project_revision": int(project_revision),
            "provider_id": provider_id,
            "model": model,
            "purpose": _GM_AUTHORING_PURPOSE,
            "request_file_sha256": request_file_sha256,
            "provider_request_sha256": provider_request_sha256,
            "response_file_sha256": response_file_sha256,
            "provider_response_sha256": provider_response_sha256,
            "provider_completion_sha256": provider_completion_sha256,
            "source_snapshot_sha256": source_snapshot_sha256,
            "selected_record_content_sha256": content_sha256,
            "record_ids": list(source["record_ids"]),
            "response": parsed,
        }
        if authoring_contract is not None:
            artifact_unsigned["authoring_contract"] = authoring_contract
            artifact_unsigned["provider_response"] = deepcopy(dict(original_provider))
        if effective_profile_extension is not None:
            artifact_unsigned["profile_extension"] = deepcopy(effective_profile_extension)
        artifact_unsigned["artifact_content_sha256"] = sha256_json(artifact_unsigned)
        artifact_path, artifact_sha256 = self._gm_write_immutable_json(
            root / "artifacts",
            f"artifact.{artifact_unsigned['artifact_content_sha256']}.json",
            artifact_unsigned,
        )
        sealed_profile, sealed_profile_sha = self._authoring_profile()
        base_workspace, base_workspace_sha = self._workspace_profile()
        provisional, _provisional_sha, _dynamic_workspace, _dynamic_workspace_sha = self._project_authoring_profile(
            dict(snapshot), sealed_profile, sealed_profile_sha, base_workspace, base_workspace_sha, force_derived=True,
        )
        profile = self._actual_profile_from_response(
            provisional_profile=provisional,
            response=parsed,
            project_id=project_id,
            project_revision=project_revision,
            source_snapshot_sha256=source_snapshot_sha256,
            selected_record_content_sha256=content_sha256,
            artifact_sha256=artifact_sha256,
            request_sha256=provider_request_sha256,
            response_sha256=provider_response_sha256,
            provider_id=provider_id,
            model=model if isinstance(model, str) else None,
            profile_extension=effective_profile_extension,
        )
        profile_sha256 = sha256_json(profile)
        profile_path, profile_file_sha256 = self._gm_write_immutable_json(
            root / "profiles",
            f"profile.{profile_sha256}.json",
            profile,
        )
        receipt_unsigned = {
            "schema_version": _GM_RECEIPT_SCHEMA,
            "project_id": project_id,
            "project_revision": int(project_revision),
            "profile_id": profile["profile_id"],
            "profile_sha256": profile_sha256,
            "profile_file_sha256": profile_file_sha256,
            "artifact_sha256": artifact_sha256,
            "artifact_content_sha256": artifact_unsigned["artifact_content_sha256"],
            "request_sha256": request_file_sha256,
            "provider_request_sha256": provider_request_sha256,
            "response_sha256": response_file_sha256,
            "provider_response_sha256": provider_response_sha256,
            "provider_completion_sha256": provider_completion_sha256,
            "source_snapshot_sha256": source_snapshot_sha256,
            "selected_record_content_sha256": content_sha256,
            "source_record_ids": list(source["record_ids"]),
            "provider_id": provider_id,
            "model": model,
            "owner_ratified": False,
            "owner_decision_id": None,
        }
        if authoring_contract is not None:
            receipt_unsigned["authoring_contract"] = authoring_contract
        envelope = self.integrity.sign(_GM_RECEIPT_INTEGRITY_DOMAIN, receipt_unsigned).as_dict()
        receipt_core = {**receipt_unsigned, "integrity": envelope}
        receipt_id = "gm-receipt." + sha256_json(receipt_core)
        receipt = {**receipt_core, "receipt_id": receipt_id, "receipt_sha256": sha256_json(receipt_core)}
        receipt_path, receipt_file_sha256 = self._gm_write_immutable_json(
            root / "receipts",
            f"{receipt_id}.json",
            receipt,
        )
        pointer_unsigned = {
            "schema_version": "TianxiaFoundry.GMAuthoringPointer.v1",
            "project_id": project_id,
            "project_revision": int(project_revision),
            "receipt_id": receipt_id,
            "receipt_sha256": receipt_file_sha256,
            "artifact_sha256": artifact_sha256,
            "profile_sha256": profile_sha256,
            "request_sha256": request_file_sha256,
            "response_sha256": response_file_sha256,
            "source_snapshot_sha256": source_snapshot_sha256,
            "selected_record_content_sha256": content_sha256,
            "owner_decision_id": None,
        }
        if authoring_contract is not None:
            pointer_unsigned["authoring_contract"] = authoring_contract
        pointer = {**pointer_unsigned, "pointer_sha256": sha256_json(pointer_unsigned)}
        self._gm_write_pointer(root / "current.json", pointer)
        binding = {
            **pointer,
            "verified": True,
            "receipt_file_sha256": receipt_file_sha256,
            "profile_id": profile["profile_id"],
            "source_record_ids": list(source["record_ids"]),
            "project_id": project_id,
            "project_revision": int(project_revision),
            "artifact_content_sha256": artifact_unsigned["artifact_content_sha256"],
            "provider_id": provider_id,
            "model": model,
            "provider_request_sha256": provider_request_sha256,
            "provider_response_sha256": provider_response_sha256,
            "owner_ratified": False,
            "owner_decision_id": None,
        }
        return {"profile": profile, "profile_sha256": profile_sha256, "binding": binding, "workspace_profile": self._actual_workspace_profile(base_workspace, profile, owner_ratified=False), "paths": {"source": str(source_path), "request": str(request_path), "response": str(response_path), "artifact": str(artifact_path), "profile": str(profile_path), "receipt": str(receipt_path)}}

    def _gm_pointer_exists(self, path: Path) -> bool:
        """Allow scoped adapters to answer pointer existence from their handle."""
        return path.is_file()

    def _load_gm_authoring(
        self,
        project_id: str,
        *,
        project_revision: int | None = None,
        snapshot: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        root = self._gm_root(project_id)
        pointer_path = root / "current.json"
        if not self._gm_pointer_exists(pointer_path):
            return None
        pointer = self._gm_read_json(pointer_path, code="GM_AUTHORING_POINTER_INVALID")
        pointer_unsigned = {key: value for key, value in pointer.items() if key != "pointer_sha256"}
        if (
            pointer.get("schema_version") != "TianxiaFoundry.GMAuthoringPointer.v1"
            or pointer.get("pointer_sha256") != sha256_json(pointer_unsigned)
            or pointer.get("project_id") != project_id
        ):
            raise FoundryError("GM_AUTHORING_POINTER_STALE", "The server-owned GM authoring pointer is stale or tampered.")
        for field in (
            "receipt_sha256", "artifact_sha256", "profile_sha256", "request_sha256", "response_sha256",
            "source_snapshot_sha256", "selected_record_content_sha256",
        ):
            if _GM_SHA256_RE.fullmatch(str(pointer.get(field) or "")) is None:
                raise FoundryError("GM_AUTHORING_POINTER_INVALID", "The server-owned GM authoring pointer contains a malformed hash.", details={"field": field})
        if project_revision is not None and pointer.get("project_revision") != int(project_revision):
            raise FoundryError("GM_AUTHORING_ARTIFACT_STALE", "The GM authoring artifact belongs to an older project revision.")
        receipt_id = pointer.get("receipt_id")
        if not isinstance(receipt_id, str) or re.fullmatch(r"gm-receipt\.[0-9a-f]{64}", receipt_id) is None:
            raise FoundryError("GM_AUTHORING_RECEIPT_INVALID", "The GM authoring pointer has no valid receipt identity.")
        receipt_path = root / "receipts" / f"{receipt_id}.json"
        receipt_file_sha256 = self._gm_file_hash(receipt_path, pointer.get("receipt_sha256"), label="receipt")
        receipt = self._gm_read_json(receipt_path, code="GM_AUTHORING_RECEIPT_INVALID")
        if receipt.get("schema_version") != _GM_RECEIPT_SCHEMA:
            raise FoundryError("GM_AUTHORING_RECEIPT_INVALID", "The GM authoring receipt schema is unsupported.")
        receipt_core = {key: value for key, value in receipt.items() if key not in {"receipt_id", "receipt_sha256"}}
        if receipt.get("receipt_id") != receipt_id or receipt.get("receipt_sha256") != sha256_json(receipt_core):
            raise FoundryError("GM_AUTHORING_RECEIPT_STALE", "The GM authoring receipt identity is invalid.")
        if receipt_id != "gm-receipt." + sha256_json(receipt_core):
            raise FoundryError("GM_AUTHORING_RECEIPT_STALE", "The GM authoring receipt identity is invalid.")
        unsigned = {key: value for key, value in receipt_core.items() if key != "integrity"}
        try:
            self.integrity.verify(_GM_RECEIPT_INTEGRITY_DOMAIN, unsigned, receipt.get("integrity") or {})
        except FoundryError:
            raise
        authoring_contract = unsigned.get("authoring_contract")
        if authoring_contract is not None and not isinstance(authoring_contract, str):
            raise FoundryError("GM_AUTHORING_RECEIPT_INVALID", "The GM authoring contract marker is malformed.")
        if pointer.get("authoring_contract") != authoring_contract:
            raise FoundryError("GM_AUTHORING_RECEIPT_POINTER_MISMATCH", "The GM pointer contract marker is not bound to the signed receipt.")
        self._gm_compare(unsigned.get("project_id"), project_id)
        self._gm_compare(unsigned.get("project_revision"), pointer.get("project_revision"))
        for field in ("artifact_sha256", "profile_sha256", "request_sha256", "response_sha256", "source_snapshot_sha256", "selected_record_content_sha256"):
            self._gm_compare(unsigned.get(field), pointer.get(field), "GM_AUTHORING_RECEIPT_POINTER_MISMATCH")
        for field in ("provider_request_sha256", "provider_response_sha256", "provider_completion_sha256", "artifact_content_sha256", "profile_sha256", "profile_file_sha256"):
            if _GM_SHA256_RE.fullmatch(str(unsigned.get(field) or "")) is None:
                raise FoundryError("GM_AUTHORING_RECEIPT_INVALID", "The GM authoring receipt contains a malformed hash.", details={"field": field})
        if unsigned.get("provider_id") not in _GM_AUTHORING_PROVIDER_IDS:
            raise FoundryError("GM_AUTHORING_RECEIPT_INVALID", "The GM authoring receipt names an unsupported provider.")
        if unsigned.get("owner_ratified") is not False or unsigned.get("owner_decision_id") is not None:
            raise FoundryError("GM_AUTHORING_RECEIPT_INVALID", "A GM authoring receipt cannot self-assert owner ratification.")
        source_sha256 = pointer.get("source_snapshot_sha256")
        source_path = root / "sources" / f"source.{pointer.get('selected_record_content_sha256')}.json"
        self._gm_file_hash(source_path, source_sha256, label="source snapshot")
        source = self._gm_read_json(source_path, code="GM_AUTHORING_SOURCE_SNAPSHOT_INVALID")
        if source.get("schema_version") != _GM_SOURCE_SNAPSHOT_SCHEMA or source.get("project_id") != project_id or source.get("project_revision") != pointer.get("project_revision"):
            raise FoundryError("GM_AUTHORING_SOURCE_SNAPSHOT_STALE", "The selected-record source snapshot is not bound to this project revision.")
        records = source.get("records")
        if not isinstance(records, list) or source.get("selected_record_content_sha256") != sha256_json(records):
            raise FoundryError("GM_AUTHORING_SOURCE_SNAPSHOT_INVALID", "The selected-record source snapshot content hash is invalid.")
        expected_record_ids: list[str] = []
        for row in records:
            record = row.get("record") if isinstance(row, Mapping) else None
            record_id = record.get("record_id") if isinstance(record, Mapping) else None
            if not isinstance(record_id, str) or not record_id:
                raise FoundryError("GM_AUTHORING_SOURCE_SNAPSHOT_INVALID", "The selected-record source snapshot contains a malformed record.")
            expected_record_ids.append(record_id)
        if source.get("record_ids") != expected_record_ids:
            raise FoundryError("GM_AUTHORING_SOURCE_SNAPSHOT_INVALID", "The selected-record source snapshot record index is invalid.")
        if unsigned.get("source_record_ids") != source.get("record_ids"):
            raise FoundryError("GM_AUTHORING_RECEIPT_POINTER_MISMATCH", "The GM authoring receipt does not cover the exact selected source records.")
        if snapshot is not None:
            current = self._selected_record_snapshot(project_id, int(pointer["project_revision"]), snapshot)
            if current["selected_record_content_sha256"] != source["selected_record_content_sha256"] or current["records"] != records:
                raise FoundryError("GM_AUTHORING_ARTIFACT_STALE", "The GM artifact is bound to different selected-record content.")
        request_file_sha256 = pointer.get("request_sha256")
        request_path = root / "requests" / f"request.{unsigned.get('provider_request_sha256')}.json"
        self._gm_file_hash(request_path, request_file_sha256, label="request")
        request = self._gm_read_json(request_path, code="GM_AUTHORING_REQUEST_INVALID")
        if (
            request.get("schema_version") != "TianxiaFoundry.GMAuthoringRequest.v1"
            or request.get("source_snapshot_sha256") != source_sha256
            or request.get("selected_record_content_sha256") != source["selected_record_content_sha256"]
            or request.get("project_id") != project_id
            or request.get("project_revision") != pointer["project_revision"]
            or request.get("purpose") != _GM_AUTHORING_PURPOSE
            or request.get("provider_id") != unsigned.get("provider_id")
            or request.get("model") != unsigned.get("model")
            or request.get("authoring_contract") != authoring_contract
        ):
            raise FoundryError("GM_AUTHORING_REQUEST_STALE", "The stored GM request is not bound to the selected source snapshot.")
        response_file_sha256 = pointer.get("response_sha256")
        response_path = root / "responses" / f"response.{unsigned.get('provider_response_sha256')}.json"
        self._gm_file_hash(response_path, response_file_sha256, label="response")
        response_doc = self._gm_read_json(response_path, code="GM_AUTHORING_RESPONSE_INVALID")
        response = self._validate_gm_response(response_doc.get("value"), set(source["record_ids"]))
        if (
            response_doc.get("schema_version") != "TianxiaFoundry.GMAuthoringResponse.v1"
            or response_doc.get("project_id") != project_id
            or response_doc.get("project_revision") != pointer["project_revision"]
            or response_doc.get("provider_id") != unsigned.get("provider_id")
            or response_doc.get("model") != unsigned.get("model")
            or response_doc.get("provider_request_sha256") != unsigned.get("provider_request_sha256")
            or response_doc.get("provider_response_sha256") != unsigned.get("provider_response_sha256")
            or response_doc.get("provider_completion_sha256") != unsigned.get("provider_completion_sha256")
            or response_doc.get("authoring_contract") != authoring_contract
            or response_doc.get("value") != response
        ):
            raise FoundryError("GM_AUTHORING_RESPONSE_STALE", "The stored GM response does not match its receipt.")
        artifact_sha256 = pointer.get("artifact_sha256")
        artifact_path = root / "artifacts" / f"artifact.{unsigned.get('artifact_content_sha256')}.json"
        self._gm_file_hash(artifact_path, artifact_sha256, label="artifact")
        artifact = self._gm_read_json(artifact_path, code="GM_AUTHORING_ARTIFACT_INVALID")
        artifact_core = {key: value for key, value in artifact.items() if key != "artifact_content_sha256"}
        if artifact.get("artifact_content_sha256") != sha256_json(artifact_core) or artifact.get("schema_version") != _GM_ARTIFACT_SCHEMA:
            raise FoundryError("GM_AUTHORING_ARTIFACT_STALE", "The GM authoring artifact content identity is invalid.")
        for field, expected in (("project_id", project_id), ("project_revision", pointer["project_revision"]), ("source_snapshot_sha256", source_sha256), ("selected_record_content_sha256", source["selected_record_content_sha256"]), ("request_file_sha256", request_file_sha256), ("response_file_sha256", response_file_sha256), ("provider_request_sha256", unsigned.get("provider_request_sha256")), ("provider_response_sha256", unsigned.get("provider_response_sha256"))):
            self._gm_compare(artifact.get(field), expected, "GM_AUTHORING_ARTIFACT_BINDING_INVALID")
        if artifact.get("authoring_contract") != authoring_contract:
            raise FoundryError("GM_AUTHORING_ARTIFACT_BINDING_INVALID", "The GM artifact contract marker is not bound to the signed receipt.")
        profile_extension = artifact.get("profile_extension")
        if authoring_contract is not None and (
            not isinstance(profile_extension, Mapping)
            or profile_extension.get("authoring_contract") != authoring_contract
        ):
            raise FoundryError("GM_AUTHORING_PROFILE_STALE", "The GM profile extension is not bound to the signed authoring contract.")
        if artifact.get("response") != response:
            raise FoundryError("GM_AUTHORING_ARTIFACT_RESPONSE_MISMATCH", "The GM artifact response differs from its response record.")
        base_profile, base_profile_sha = self._authoring_profile()
        base_workspace, base_workspace_sha = self._workspace_profile()
        provisional, _provisional_sha, _dynamic, _dynamic_sha = self._project_authoring_profile(
            dict(snapshot) if snapshot is not None else self._snapshot_from_gm_source(source),
            base_profile, base_profile_sha, base_workspace, base_workspace_sha, force_derived=True,
        )
        profile_path = root / "profiles" / f"profile.{unsigned.get('profile_sha256')}.json"
        profile_file_sha256 = self._gm_file_hash(profile_path, unsigned.get("profile_file_sha256"), label="profile")
        profile = self._gm_read_json(profile_path, code="GM_AUTHORING_PROFILE_INVALID")
        if sha256_json(profile) != unsigned.get("profile_sha256"):
            raise FoundryError("GM_AUTHORING_PROFILE_STALE", "The stored GM profile hash is invalid.")
        expected_profile = self._actual_profile_from_response(
            provisional_profile=provisional,
            response=response,
            project_id=project_id,
            project_revision=int(pointer["project_revision"]),
            source_snapshot_sha256=source_sha256,
            selected_record_content_sha256=source["selected_record_content_sha256"],
            artifact_sha256=artifact_sha256,
            request_sha256=unsigned.get("provider_request_sha256"),
            response_sha256=unsigned.get("provider_response_sha256"),
            provider_id=unsigned.get("provider_id"),
            model=unsigned.get("model") if isinstance(unsigned.get("model"), str) else None,
            profile_extension=artifact.get("profile_extension") if isinstance(artifact.get("profile_extension"), Mapping) else None,
        )
        if profile.get("profile_id") != unsigned.get("profile_id") or profile != expected_profile:
            raise FoundryError("GM_AUTHORING_PROFILE_STALE", "The stored GM profile does not reproduce from its authenticated artifact.")
        workspace_profile = self._actual_workspace_profile(base_workspace, profile, owner_ratified=False)
        binding = {
            **pointer,
            "verified": True,
            "receipt_file_sha256": receipt_file_sha256,
            "profile_id": profile["profile_id"],
            "profile_file_sha256": profile_file_sha256,
            "source_record_ids": list(source["record_ids"]),
            "project_id": project_id,
            "project_revision": int(pointer["project_revision"]),
            "artifact_content_sha256": artifact.get("artifact_content_sha256"),
            "provider_id": unsigned.get("provider_id"),
            "model": unsigned.get("model"),
            "provider_request_sha256": unsigned.get("provider_request_sha256"),
            "provider_response_sha256": unsigned.get("provider_response_sha256"),
            "owner_ratified": False,
            "owner_decision_id": None,
        }
        if authoring_contract is not None:
            binding["authoring_contract"] = authoring_contract
        owner_decision_id = pointer.get("owner_decision_id")
        if owner_decision_id is not None:
            if not isinstance(owner_decision_id, str) or re.fullmatch(r"gm-decision\.[0-9a-f]{64}", owner_decision_id) is None:
                raise FoundryError("GM_AUTHORING_OWNER_DECISION_INVALID", "The GM authoring pointer has an invalid owner-decision identity.")
            decision_path = root / "decisions" / f"{owner_decision_id}.json"
            decision = self._gm_read_json(decision_path, code="GM_AUTHORING_OWNER_DECISION_INVALID")
            decision_core = {key: value for key, value in decision.items() if key not in {"integrity", "decision_sha256"}}
            if decision.get("schema_version") != _GM_OWNER_DECISION_SCHEMA or decision.get("decision_id") != owner_decision_id or decision.get("decision") is not True or decision.get("decision_sha256") != sha256_json({**decision_core, "integrity": decision.get("integrity")}):
                raise FoundryError("GM_AUTHORING_OWNER_DECISION_INVALID", "The owner decision identity is invalid.")
            try:
                self.integrity.verify(_GM_DECISION_INTEGRITY_DOMAIN, decision_core, decision.get("integrity") or {})
            except FoundryError:
                raise
            for field in ("project_id", "project_revision", "receipt_id", "receipt_sha256", "artifact_sha256", "profile_sha256", "source_snapshot_sha256", "selected_record_content_sha256"):
                self._gm_compare(decision.get(field), binding.get(field), "GM_AUTHORING_OWNER_DECISION_BINDING_INVALID")
            if pointer.get("owner_decision_sha256") != decision.get("decision_sha256"):
                raise FoundryError("GM_AUTHORING_OWNER_DECISION_BINDING_INVALID", "The pointer does not bind the exact owner decision bytes.")
            binding["owner_ratified"] = True
            binding["owner_decision_id"] = owner_decision_id
            workspace_profile = self._actual_workspace_profile(base_workspace, profile, owner_ratified=True)
        self._validate_profile(profile, workspace_profile, dict(snapshot) if snapshot is not None else self._snapshot_from_gm_source(source), binding)
        return {"profile": profile, "profile_sha256": unsigned["profile_sha256"], "workspace_profile": workspace_profile, "workspace_profile_sha256": sha256_json(workspace_profile), "binding": binding, "receipt": receipt, "artifact": artifact, "source": source}

    @staticmethod
    def _gm_provider_wire_hash(
        prompt_text: str,
        system_message: str,
        settings: Mapping[str, Any],
    ) -> str:
        provider_id = str(settings.get("provider_id") or "local")
        model = str(settings.get("model") or "")
        maximum = settings.get("max_output_tokens")
        if type(maximum) is not int or maximum <= 0:
            maximum = LOCAL_GM_AUTHORING_MAX_OUTPUT_TOKENS
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": prompt_text},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": _GM_RESPONSE_SCHEMA_NAME,
                    "strict": True,
                    "schema": deepcopy(_GM_RESPONSE_SCHEMA),
                },
            },
            "max_tokens": min(maximum, LOCAL_GM_AUTHORING_MAX_OUTPUT_TOKENS),
            "stream": False,
            "temperature": 0,
            "chat_template_kwargs": {"enable_thinking": False},
            "cache_prompt": True,
        }
        return sha256_bytes(canonical_json(payload).encode("utf-8"))

    def _record_gm_attempt(
        self,
        project_id: str,
        *,
        prompt_text: str,
        system_message: str,
        provider_result: Mapping[str, Any] | None = None,
        error: FoundryError | None = None,
    ) -> None:
        """Keep a bounded immutable record when an explicit author attempt fails."""
        value = {
            "schema_version": "TianxiaFoundry.GMAuthoringAttempt.v1",
            "project_id": project_id,
            "purpose": _GM_AUTHORING_PURPOSE,
            "prompt_text": prompt_text,
            "system_message": system_message,
            "provider_result": {
                key: deepcopy(item)
                for key, item in (provider_result or {}).items()
                if key in {"provider_id", "model", "request_sha256", "response_sha256", "completion_sha256", "response_text", "finish_reason"}
            },
            "error": error.to_dict() if isinstance(error, FoundryError) else None,
        }
        digest = sha256_json(value)
        try:
            self._gm_write_immutable_json(
                self.db.settings.logs_dir / _GM_ARTIFACT_ROOT_NAME / project_id / "attempts",
                f"attempt.{digest}.json",
                value,
            )
        except (FoundryError, OSError):
            # The original provider error is authoritative for the request;
            # failure to add a secondary log must not turn it into a success.
            return

    def author_gm_tactical(self, project_id: str, provider: Any) -> dict[str, Any]:
        """Author GM guidance through the sealed composite-controller boundary."""
        project = self.projects.get_project(project_id)["project"]
        sheet_response = self.sheets.sheet(project_id)
        if sheet_response.get("build_status") != "CHARACTER_SHEET_READY":
            raise FoundryError("GM_AUTHORING_CHARACTER_SHEET_NOT_READY", "The owner-facing Character Sheet must be complete before GM authoring.")
        settings = getattr(provider, "_settings", lambda: None)()
        if not isinstance(settings, Mapping) or settings.get("provider_id") not in _GM_AUTHORING_PROVIDER_IDS:
            raise FoundryError("GM_AUTHORING_PROVIDER_INVALID", "GM tactical authoring requires the selected local provider or the Agent bridge.")
        snapshot = sheet_response.get("owner_character_sheet")
        source = self._selected_record_snapshot(project_id, int(project["revision"]), snapshot or {})
        from character_creation.candidate_gm_authoring import CandidateGMAuthoringService
        from factory_authoring.composite_controller import CompositeControllerAuthoring, _canonical_wire_bytes

        prepared = CompositeControllerAuthoring(workspace_service=self).prepare(
            project_id,
            theme_records=deepcopy(list(source.get("records") or [])),
        )
        request_wire = _canonical_wire_bytes(
            str(prepared["prompt_text"]),
            str(prepared["system_message"]),
            settings,
            prepared["response_schema"],
        )
        expected_request_sha256 = sha256_bytes(request_wire)
        provider_result = None
        try:
            provider_result = provider.complete_json(
                prompt_text=prepared["prompt_text"],
                system_message=prepared["system_message"],
                purpose=CompositeControllerAuthoring.purpose,
                substantive=True,
                response_schema=prepared["response_schema"],
                response_schema_name=prepared["response_schema_name"],
                response_schema_max_output_tokens=1024,
                max_request_bytes=prepared["max_request_bytes"],
                temperature=0,
                expected_request_sha256=expected_request_sha256,
            )
            if not isinstance(provider_result, Mapping) or provider_result.get("request_sha256") != expected_request_sha256:
                raise FoundryError("GM_AUTHORING_PROVIDER_REQUEST_EVIDENCE_INVALID", "The local provider returned request evidence different from the server-authorized request.")
            raw_response = provider_result.get("response_text")
            provider_value = provider_result.get("value")
            if not isinstance(raw_response, str) or not raw_response.strip():
                if not isinstance(provider_value, Mapping):
                    raise FoundryError("GM_AUTHORING_PROVIDER_RESPONSE_INVALID", "The local provider returned no composite controller JSON.")
                raw_response = canonical_json(provider_value)
            try:
                parsed = json.loads(raw_response)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise FoundryError("GM_AUTHORING_PROVIDER_RESPONSE_INVALID", "The local provider returned malformed composite controller JSON.") from exc
            if not isinstance(parsed, Mapping) or (isinstance(provider_value, Mapping) and dict(parsed) != dict(provider_value)):
                raise FoundryError("GM_AUTHORING_PROVIDER_RESPONSE_INVALID", "The local provider response text differs from its parsed composite controller.")
            completion_sha256 = provider_result.get("completion_sha256")
            if not isinstance(completion_sha256, str) or sha256_bytes(raw_response.encode("utf-8")) != completion_sha256:
                raise FoundryError("GM_AUTHORING_PROVIDER_EVIDENCE_INVALID", "The provider completion hash does not match its composite response bytes.")
            validated = CompositeControllerAuthoring._validate_response(prepared, dict(parsed))
            response, profile_extension = CandidateGMAuthoringService._server_response(
                prepared,
                validated,
                selected_record_ids=list(source["record_ids"]),
            )
            adapted_provider_result = {
                **dict(provider_result),
                "purpose": _GM_AUTHORING_PURPOSE,
                "value": response,
                "response_text": raw_response,
            }
            persisted = self._persist_gm_authoring(
                project_id,
                int(project["revision"]),
                snapshot,
                prompt_text=str(prepared["prompt_text"]),
                system_message=str(prepared["system_message"]),
                provider_result=adapted_provider_result,
                response=response,
                provider_response=provider_result,
                authoring_contract=_GM_COMPOSITE_CONTRACT,
                response_schema_name=prepared["response_schema_name"],
                response_schema=prepared["response_schema"],
                profile_extension=profile_extension,
            )
        except FoundryError as exc:
            self._record_gm_attempt(
                project_id,
                prompt_text=str(prepared["prompt_text"]),
                system_message=str(prepared["system_message"]),
                provider_result=provider_result,
                error=exc,
            )
            raise
        try:
            rebuilt = self.build(project_id)
        except (FoundryError, OSError) as rebuild_error:
            # Persistence completed before workspace construction.  Verify the
            # server-owned receipt again and keep the result actionable when a
            # provider-free rebuild can be retried; never present the partial
            # operation as a built or ratified workspace.
            try:
                loaded = self._load_gm_authoring(
                    project_id,
                    project_revision=int(project["revision"]),
                    snapshot=snapshot,
                )
            except (FoundryError, OSError):
                raise rebuild_error
            verified_binding = loaded.get("binding") if isinstance(loaded, Mapping) else None
            if not isinstance(verified_binding, Mapping):
                raise rebuild_error
            return {
                "status": "GM_AUTHORING_PERSISTED_REBUILD_PENDING",
                "provider_calls": 1,
                "provider_id": verified_binding.get("provider_id"),
                "model": verified_binding.get("model"),
                "receipt_id": verified_binding.get("receipt_id"),
                "artifact_sha256": verified_binding.get("artifact_sha256"),
                "profile_sha256": verified_binding.get("profile_sha256"),
                "source_snapshot_sha256": verified_binding.get("source_snapshot_sha256"),
                "selected_record_content_sha256": verified_binding.get("selected_record_content_sha256"),
                "gm_authoring": _GM_ACTUAL_CLASSIFICATION,
                "owner_ratified": verified_binding.get("owner_ratified") is True,
                "eligible_for_later_command5_checkpoint": False,
                "provider_free_rebuild_available": True,
                "workspace_status": "REBUILD_PENDING",
                "workspace_rebuild_status": "FAILED",
                "workspace_rebuild_error": {
                    "code": getattr(rebuild_error, "code", "FACTORY_WORKSPACE_BUILD_FAILED"),
                    "message": str(rebuild_error),
                },
            }
        return {
            "status": _GM_ACTUAL_CLASSIFICATION,
            "provider_calls": 1,
            "provider_id": persisted["binding"]["provider_id"],
            "model": persisted["binding"].get("model"),
            "receipt_id": persisted["binding"]["receipt_id"],
            "artifact_sha256": persisted["binding"]["artifact_sha256"],
            "profile_sha256": persisted["binding"]["profile_sha256"],
            "source_snapshot_sha256": persisted["binding"]["source_snapshot_sha256"],
            "selected_record_content_sha256": persisted["binding"]["selected_record_content_sha256"],
            "owner_ratified": False,
            "eligible_for_later_command5_checkpoint": False,
            "provider_free_rebuild_available": False,
            "workspace_id": rebuilt.get("workspace_id"),
            "workspace_sha256": rebuilt.get("workspace_sha256"),
            "workspace_status": rebuilt.get("workspace_status"),
        }

    def _gm_project_lock_hash(self, project_id: str) -> str:
        try:
            with self.db.connection() as conn:
                return self.projects.project_lock_proof(conn, project_id)["lock_proof_hash"]
        except FoundryError:
            raise
        except Exception as exc:
            raise FoundryError("GM_AUTHORING_PROJECT_LOCK_UNAVAILABLE", "The immutable project lock proof could not be loaded.") from exc

    @staticmethod
    def _gm_approval_binding(binding: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": "TianxiaFoundry.GMOwnerRatificationBinding.v1",
            "project_id": binding.get("project_id"),
            "project_revision": binding.get("project_revision"),
            "receipt_id": binding.get("receipt_id"),
            "receipt_sha256": binding.get("receipt_sha256"),
            "artifact_sha256": binding.get("artifact_sha256"),
            "profile_sha256": binding.get("profile_sha256"),
            "source_snapshot_sha256": binding.get("source_snapshot_sha256"),
            "selected_record_content_sha256": binding.get("selected_record_content_sha256"),
        }

    def _recover_gm_approval_evidence(
        self,
        approval: Any,
        *,
        challenge_id: str,
        nonce: str,
        operation: str,
        subject_type: str,
        subject_id: str,
        exact_bytes: bytes,
        binding: Mapping[str, Any],
        project_lock_hash: str,
        evidence_context: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        """Reuse only the authoritative evidence of this exact consumed challenge.

        Approval consumption is durable before the filesystem decision and
        workspace pointer can be completed. A retry may therefore recover the
        one evidence row, but only after checking the original nonce and asking
        the approval service to revalidate every exact-byte binding.
        """
        if not isinstance(challenge_id, str) or not challenge_id:
            return None
        with self.db.connection() as conn:
            challenge = conn.execute(
                "SELECT challenge_id,status,nonce_hash FROM exact_approval_challenges WHERE challenge_id=?",
                (challenge_id,),
            ).fetchone()
            if not challenge or challenge["status"] != "consumed":
                return None
            if challenge["nonce_hash"] != sha256_bytes(str(nonce).encode("utf-8")):
                raise FoundryError(
                    "APPROVAL_CHALLENGE_NONCE_INVALID",
                    "The consumed approval challenge nonce is invalid.",
                    status_code=403,
                )
            evidence_rows = conn.execute(
                "SELECT evidence_id FROM exact_approval_evidence WHERE challenge_id=? ORDER BY evidence_id",
                (challenge_id,),
            ).fetchall()
            if len(evidence_rows) != 1:
                raise FoundryError(
                    "GM_AUTHORING_APPROVAL_RECOVERY_INVALID",
                    "The consumed GM ratification challenge does not have exactly one authoritative evidence row.",
                    status_code=409,
                )
            return approval.verify_evidence(
                conn,
                evidence_rows[0]["evidence_id"],
                operation=operation,
                subject_type=subject_type,
                subject_id=subject_id,
                exact_bytes=exact_bytes,
                binding=dict(binding),
                project_lock_hash=project_lock_hash,
                principal_id=approval.principal().principal_id,
                evidence_context=dict(evidence_context),
            )

    def _require_gm_workspace_ready(self, project_id: str) -> dict[str, Any]:
        """Require a verified, materialized workspace before a new approval use."""
        workspace = self.status(project_id)
        if (
            workspace.get("available") is not True
            or workspace.get("workspace_status") != _STATUS
        ):
            raise FoundryError(
                "GM_AUTHORING_WORKSPACE_NOT_READY",
                "The verified GM authoring workspace must be rebuilt before owner ratification.",
                details={
                    "workspace_status": workspace.get("workspace_status"),
                    "provider_free_rebuild_available": workspace.get("provider_free_rebuild_available") is True,
                },
                status_code=409,
            )
        return workspace

    def issue_gm_authoring_ratification_challenge(self, project_id: str, ttl_seconds: int = 300) -> dict[str, Any]:
        project = self.projects.get_project(project_id)["project"]
        sheet_response = self.sheets.sheet(project_id)
        loaded = self._load_gm_authoring(
            project_id,
            project_revision=int(project["revision"]),
            snapshot=sheet_response.get("owner_character_sheet"),
        )
        if loaded is None or (loaded.get("binding") or {}).get("authoring_contract") != _GM_COMPOSITE_CONTRACT:
            raise FoundryError("GM_AUTHORING_RECEIPT_NOT_FOUND", "No server-owned GM authoring receipt is available for ratification.")
        binding = loaded["binding"]
        if binding.get("owner_ratified") is True:
            raise FoundryError("GM_AUTHORING_ALREADY_RATIFIED", "This GM authoring receipt has already been ratified.", status_code=409)
        self._require_gm_workspace_ready(project_id)
        from security.approval_challenges import ApprovalChallengeService

        exact_bytes = self._gm_json_bytes(loaded["profile"])
        challenge = ApprovalChallengeService(
            self.db,
            principal_provider=self.principal_provider,
            integrity=self.integrity,
        ).issue(
            operation="gm_authoring_owner_ratify",
            subject_type="gm_authoring_receipt",
            subject_id=str(binding["receipt_id"]),
            exact_bytes=exact_bytes,
            binding=self._gm_approval_binding(binding),
            project_lock_hash=self._gm_project_lock_hash(project_id),
            ttl_seconds=ttl_seconds,
        )
        return {"status": "GM_AUTHORING_RATIFICATION_CHALLENGE_ISSUED", "receipt_id": binding["receipt_id"], "challenge": challenge["challenge"]}

    def ratify_gm_authoring(self, project_id: str, receipt_id: str, challenge_id: str, nonce: str) -> dict[str, Any]:
        project = self.projects.get_project(project_id)["project"]
        sheet_response = self.sheets.sheet(project_id)
        loaded = self._load_gm_authoring(
            project_id,
            project_revision=int(project["revision"]),
            snapshot=sheet_response.get("owner_character_sheet"),
        )
        if (
            loaded is None
            or loaded["binding"].get("authoring_contract") != _GM_COMPOSITE_CONTRACT
            or loaded["binding"].get("receipt_id") != receipt_id
        ):
            raise FoundryError("GM_AUTHORING_RECEIPT_NOT_FOUND", "The requested server-owned GM authoring receipt is not current.", status_code=404)
        binding = loaded["binding"]
        if binding.get("owner_ratified") is True:
            rebuilt = self.build(project_id)
            return {
                "status": "GM_AUTHORING_OWNER_RATIFIED",
                "receipt_id": receipt_id,
                "decision_id": binding.get("owner_decision_id"),
                "artifact_sha256": binding["artifact_sha256"],
                "profile_sha256": binding["profile_sha256"],
                "workspace_id": rebuilt.get("workspace_id"),
                "workspace_sha256": rebuilt.get("workspace_sha256"),
                "owner_ratified": True,
                "eligible_for_later_command5_checkpoint": True,
            }
        from security.approval_challenges import ApprovalChallengeService

        approval = ApprovalChallengeService(
            self.db,
            principal_provider=self.principal_provider,
            integrity=self.integrity,
        )
        exact_bytes = self._gm_json_bytes(loaded["profile"])
        approval_binding = self._gm_approval_binding(binding)
        project_lock_hash = self._gm_project_lock_hash(project_id)
        evidence_context = {"receipt_id": receipt_id, "artifact_sha256": binding["artifact_sha256"]}
        evidence = self._recover_gm_approval_evidence(
            approval,
            challenge_id=challenge_id,
            nonce=nonce,
            operation="gm_authoring_owner_ratify",
            subject_type="gm_authoring_receipt",
            subject_id=receipt_id,
            exact_bytes=exact_bytes,
            binding=approval_binding,
            project_lock_hash=project_lock_hash,
            evidence_context=evidence_context,
        )
        if evidence is None:
            # A fresh consume is allowed only while the current authenticated
            # workspace is ready.  Consumed evidence above is the deliberate
            # recovery path for a previously interrupted decision/pointer/build
            # sequence and must remain replayable without consuming twice.
            self._require_gm_workspace_ready(project_id)
            evidence = approval.consume(
                challenge_id=challenge_id,
                nonce=nonce,
                operation="gm_authoring_owner_ratify",
                subject_type="gm_authoring_receipt",
                subject_id=receipt_id,
                exact_bytes=exact_bytes,
                binding=approval_binding,
                project_lock_hash=project_lock_hash,
                evidence_context=evidence_context,
            )
        decision_unsigned = {
            "schema_version": _GM_OWNER_DECISION_SCHEMA,
            "decision_id": None,
            "project_id": project_id,
            "project_revision": int(project["revision"]),
            "receipt_id": receipt_id,
            "receipt_sha256": binding["receipt_sha256"],
            "artifact_sha256": binding["artifact_sha256"],
            "profile_sha256": binding["profile_sha256"],
            "source_snapshot_sha256": binding["source_snapshot_sha256"],
            "selected_record_content_sha256": binding["selected_record_content_sha256"],
            "decision": True,
            "approval_evidence_id": evidence.get("evidence_id"),
            "principal": deepcopy(evidence.get("principal") or {}),
        }
        decision_id = "gm-decision." + sha256_json({key: value for key, value in decision_unsigned.items() if key != "decision_id"})
        decision_unsigned["decision_id"] = decision_id
        envelope = self.integrity.sign(_GM_DECISION_INTEGRITY_DOMAIN, decision_unsigned).as_dict()
        decision = {**decision_unsigned, "integrity": envelope, "decision_sha256": sha256_json({**decision_unsigned, "integrity": envelope})}
        self._gm_write_immutable_json(self._gm_root(project_id) / "decisions", f"{decision_id}.json", decision)
        pointer_path = self._gm_root(project_id) / "current.json"
        pointer = self._gm_read_json(pointer_path, code="GM_AUTHORING_POINTER_INVALID")
        pointer_unsigned = {key: value for key, value in pointer.items() if key != "pointer_sha256"}
        if pointer.get("pointer_sha256") != sha256_json(pointer_unsigned) or pointer.get("receipt_id") != receipt_id:
            raise FoundryError("GM_AUTHORING_POINTER_STALE", "The GM authoring pointer changed while ratification was being completed.", status_code=409)
        pointer_unsigned["owner_decision_id"] = decision_id
        pointer_unsigned["owner_decision_sha256"] = decision["decision_sha256"]
        pointer = {**pointer_unsigned, "pointer_sha256": sha256_json(pointer_unsigned)}
        self._gm_write_pointer(pointer_path, pointer)
        # The decision is a separate authority record, but the workspace
        # manifest is also an immutable snapshot. Rebuild it provider-free so
        # reads immediately consume the new decision binding instead of
        # treating the previous pending manifest as stale.
        rebuilt = self.build(project_id)
        return {"status": "GM_AUTHORING_OWNER_RATIFIED", "receipt_id": receipt_id, "decision_id": decision_id, "artifact_sha256": binding["artifact_sha256"], "profile_sha256": binding["profile_sha256"], "workspace_id": rebuilt.get("workspace_id"), "workspace_sha256": rebuilt.get("workspace_sha256"), "owner_ratified": True, "eligible_for_later_command5_checkpoint": True}

    @staticmethod
    def _card_index(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
        cards = [
            row for rows in (snapshot.get("selected_record_sections") or {}).values()
            for row in (rows or []) if isinstance(row, dict)
        ]
        return {str(row.get("record_id")): row for row in cards if row.get("record_id")}

    @staticmethod
    def _reject_executable_claims(value: Any, *, path: str = "$") -> None:
        forbidden_keys = {
            "action_definition", "action_intent", "attack_roll", "damage_dice", "save_dc",
            "target_scoring", "decision_weights", "legal_candidate", "controller_policy",
            "range_ft", "area_geometry", "condition_definition", "resource_cost",
        }
        if isinstance(value, dict):
            for key, item in value.items():
                if key in forbidden_keys:
                    raise FoundryError(
                        "GM_AUTHORING_EXECUTABLE_CLAIM_FORBIDDEN",
                        "GM authoring may not contain executable combat fields.",
                        details={"path": f"{path}/{key}"},
                    )
                FactoryAuthoringWorkspaceService._reject_executable_claims(item, path=f"{path}/{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                FactoryAuthoringWorkspaceService._reject_executable_claims(item, path=f"{path}/{index}")

    @classmethod
    def _validate_profile(
        cls,
        profile: dict[str, Any],
        workspace_profile: dict[str, Any],
        snapshot: dict[str, Any],
        artifact_binding: Mapping[str, Any] | None = None,
    ) -> None:
        diagnostics: list[dict[str, Any]] = []
        selected = cls._card_index(snapshot)
        selected_ids = set(selected)
        profile_id = profile.get("profile_id")
        legacy_profile = cls._is_legacy_profile(profile)
        derived_profile = cls._is_project_derived_profile(profile)
        classification = profile.get("authority_classification")
        authorship = profile.get("authorship")
        if derived_profile:
            expected_id = "Tianxia_Project_Derived_GM_Tactical_Authoring_" + sha256_json(sorted(selected_ids))[:16]
            if profile_id != expected_id or classification != _GM_PROVISIONAL_CLASSIFICATION:
                diagnostics.append({"code": "GM_AUTHORING_PROVISIONAL_IDENTITY_INVALID"})
            if (
                not isinstance(authorship, Mapping)
                or authorship.get("schema_version") != _GM_AUTHORSHIP_SCHEMA
                or authorship.get("status") != _GM_PROVISIONAL_STATUS
                or authorship.get("origin") != "project_selected_record_template"
                or authorship.get("provider_id") is not None
                or authorship.get("artifact_bound") is not False
                or authorship.get("artifact_sha256") is not None
                or authorship.get("owner_ratified") is not False
                or authorship.get("source_record_ids") != sorted(selected_ids)
            ):
                diagnostics.append({"code": "GM_AUTHORING_PROVISIONAL_BINDING_INVALID"})
        elif legacy_profile:
            if classification != "OWNER_RATIFIED_GM_AUTHORING":
                diagnostics.append({"code": "GM_AUTHORING_AUTHORITY_CLASS_INVALID"})
        elif classification != _GM_ACTUAL_CLASSIFICATION:
            diagnostics.append({"code": "GM_AUTHORING_AUTHORITY_CLASS_INVALID"})
        else:
            source_ids = authorship.get("source_record_ids") if isinstance(authorship, Mapping) else None
            artifact_sha256 = authorship.get("artifact_sha256") if isinstance(authorship, Mapping) else None
            if (
                not isinstance(authorship, Mapping)
                or authorship.get("schema_version") != _GM_AUTHORSHIP_SCHEMA
                or authorship.get("status") != _GM_ACTUAL_STATUS
                or not isinstance(authorship.get("provider_id"), str)
                or not authorship.get("provider_id").strip()
                or authorship.get("artifact_bound") is not True
                or not isinstance(artifact_sha256, str)
                or len(artifact_sha256) != 64
                or any(character not in "0123456789abcdef" for character in artifact_sha256)
                or type(authorship.get("owner_ratified")) is not bool
                or source_ids != sorted(selected_ids)
            ):
                diagnostics.append({"code": "GM_AUTHORING_ACTUAL_BINDING_INVALID"})
            if artifact_binding is None or artifact_binding.get("verified") is not True:
                diagnostics.append({"code": "GM_AUTHORING_ACTUAL_ARTIFACT_UNVERIFIED"})
            else:
                expected_content_sha = cls._selected_record_snapshot("validation", 0, snapshot)["selected_record_content_sha256"]
                required_binding = {
                    "profile_id": profile_id,
                    "profile_sha256": sha256_json(profile),
                    "artifact_sha256": artifact_sha256,
                    "source_record_ids": sorted(selected_ids),
                    "selected_record_content_sha256": expected_content_sha,
                    "project_id": authorship.get("project_id"),
                    "project_revision": authorship.get("project_revision"),
                }
                for field, expected in required_binding.items():
                    if artifact_binding.get(field) != expected:
                        diagnostics.append({"code": "GM_AUTHORING_ACTUAL_ARTIFACT_BINDING_MISMATCH", "field": field})

        training = profile.get("training_sources") or []
        source_ids = [row.get("source_id") for row in training if isinstance(row, dict)]
        if len(source_ids) != len(set(source_ids)):
            diagnostics.append({"code": "GM_AUTHORING_TRAINING_SOURCE_DUPLICATE"})
        covered: list[str] = []
        for row in training:
            if not isinstance(row, dict):
                diagnostics.append({"code": "GM_AUTHORING_TRAINING_SOURCE_INVALID"}); continue
            if row.get("classification") != "GM_GUIDANCE_ONLY" or row.get("factory_source_type") != "other":
                diagnostics.append({"code": "GM_AUTHORING_TRAINING_SOURCE_CLASS_INVALID", "source_id": row.get("source_id")})
            records = [str(value) for value in row.get("record_ids") or []]
            if not records or not row.get("summary"):
                diagnostics.append({"code": "GM_AUTHORING_TRAINING_SOURCE_UNPROVEN", "source_id": row.get("source_id")})
            unknown = sorted(set(records) - selected_ids)
            if unknown:
                diagnostics.append({"code": "GM_AUTHORING_TRAINING_SOURCE_RECORD_UNKNOWN", "source_id": row.get("source_id"), "records": unknown})
            covered.extend(records)
        required_coverage = set(workspace_profile.get("required_training_source_coverage") or [])
        if set(covered) != required_coverage or len(covered) != len(set(covered)):
            diagnostics.append({
                "code": "GM_AUTHORING_TRAINING_SOURCE_COVERAGE_INVALID",
                "missing": sorted(required_coverage - set(covered)),
                "extra": sorted(set(covered) - required_coverage),
                "duplicates": sorted({value for value in covered if covered.count(value) > 1}),
            })

        dao = (profile.get("dao_i_ching") or {}).get("dao")
        iching = (profile.get("dao_i_ching") or {}).get("i_ching")
        theme_classification = (
            "OWNER_RATIFIED_GM_AUTHORING"
            if legacy_profile
            else _GM_PROVISIONAL_CLASSIFICATION
            if derived_profile
            else _GM_ACTUAL_CLASSIFICATION
        )
        if (profile.get("dao_i_ching") or {}).get("classification") != theme_classification:
            diagnostics.append({"code": "GM_AUTHORING_THEME_CLASS_INVALID"})
        if not isinstance(dao, dict) or (legacy_profile and dao.get("authoring_id") != "gm.dao.refinement_through_controlled_flame") or not dao.get("authoring_id"):
            diagnostics.append({"code": "GM_AUTHORING_DAO_REQUIRED"})
        if not isinstance(iching, dict) or (legacy_profile and iching.get("authoring_id") != "gm.iching.hexagram_30_li") or not iching.get("authoring_id"):
            diagnostics.append({"code": "GM_AUTHORING_ICHING_REQUIRED"})
        for kind, row in (("dao", dao), ("i_ching", iching)):
            if isinstance(row, dict) and row.get("mechanical_effects") not in ([], None):
                diagnostics.append({"code": "GM_AUTHORING_THEME_MECHANICAL_EFFECT_FORBIDDEN", "kind": kind})
            if isinstance(row, dict):
                unknown = sorted(set(row.get("relevant_record_ids") or []) - selected_ids)
                if unknown:
                    diagnostics.append({"code": "GM_AUTHORING_THEME_RECORD_UNKNOWN", "kind": kind, "records": unknown})

        ai = profile.get("ai_behavior")
        if not isinstance(ai, dict) or ai.get("not_executable_controller_policy") is not True:
            diagnostics.append({"code": "GM_AUTHORING_AI_PROFILE_REQUIRED"})
        elif ai.get("classification") != "DISPLAY_ONLY_NOT_EXECUTION_AUTHORITY":
            diagnostics.append({"code": "GM_AUTHORING_AI_PROFILE_CLASS_INVALID"})
        elif sorted(set(ai.get("record_ids") or []) - selected_ids):
            diagnostics.append({"code": "GM_AUTHORING_AI_PROFILE_RECORD_UNKNOWN"})

        try:
            cls._reject_executable_claims(profile)
        except FoundryError as exc:
            diagnostics.append(exc.to_dict()["error"])
        serialized = canonical_json(profile).casefold()
        for forbidden in workspace_profile.get("forbidden_promotions") or []:
            if str(forbidden).casefold() in serialized:
                diagnostics.append({"code": "GM_AUTHORING_FALSE_READINESS_PROMOTION", "value": forbidden})
        if diagnostics:
            raise FoundryError(
                "GM_AUTHORING_PROFILE_BLOCKED",
                "The bounded GM tactical authoring profile failed validation.",
                details={"diagnostics": diagnostics},
            )

    @staticmethod
    def _portable_identity(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: FactoryAuthoringWorkspaceService._portable_identity(item) for key, item in value.items() if key not in {"path", "workspace_path"}}
        if isinstance(value, list):
            return [FactoryAuthoringWorkspaceService._portable_identity(item) for item in value]
        return deepcopy(value)

    @staticmethod
    def _bound_records(record_ids: list[str], cards: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        rows = []
        for record_id in record_ids:
            card = cards[record_id]
            rows.append({
                "record_id": record_id,
                "display_name": card.get("display_name"),
                "record_hash": card.get("record_hash"),
                "source_packet_ids": sorted(card.get("source_packet_ids") or []),
                "source": deepcopy(card.get("source")),
                "capabilities": deepcopy(card.get("capabilities")),
                "display_only_not_execution_authority": bool(card.get("display_only_not_execution_authority")),
            })
        return rows

    @staticmethod
    def _validation(status: str, *, valid: bool, diagnostics: list[dict[str, Any]] | None = None, **extra: Any) -> dict[str, Any]:
        return {"schema_version": "TianxiaFoundry.FactoryWorkspaceValidation.v1", "status": status, "valid": valid, "diagnostics": diagnostics or [], **extra}

    def _documents(
        self,
        *,
        project: dict[str, Any],
        sheet_response: dict[str, Any],
        profile: dict[str, Any],
        profile_sha: str,
        workspace_profile: dict[str, Any],
        workspace_profile_sha: str,
        projection_artifacts: dict[str, dict[str, Any]],
        artifact_binding: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        snapshot = sheet_response["owner_character_sheet"]
        cards = self._card_index(snapshot)
        identity = snapshot["identity"]
        ledger = deepcopy(projection_artifacts["Character_Master_Ledger.json"])
        packets = deepcopy(projection_artifacts["Rules_Selection_Packets.json"])
        projection_status = sheet_response["provenance"]["advancement_projection"]["projection"]
        canonical_training_sources = snapshot.get("training_sources") or []
        if not isinstance(canonical_training_sources, list):
            raise FoundryError(
                "FACTORY_WORKSPACE_TRAINING_SOURCES_INVALID",
                "The owner Character Sheet training-source projection must be a list.",
            )
        canonical_training_sources = deepcopy(canonical_training_sources)
        provisional = self._is_project_derived_profile(profile)
        actual = profile.get("authority_classification") == _GM_ACTUAL_CLASSIFICATION
        authored = provisional or actual
        authorship = self._profile_authorship(profile) if authored else None
        gm_authoring_status = (
            "PROVISIONAL_GM_GUIDANCE_ONLY"
            if provisional
            else "ACTUAL_GM_AUTHORING"
            if actual
            else "COMPLETE_AS_WORKSPACE_INPUT"
        )
        training_classification = (
            _GM_PROVISIONAL_CLASSIFICATION
            if provisional
            else _GM_ACTUAL_CLASSIFICATION
            if actual
            else "OWNER_RATIFIED_GM_AUTHORING"
        )

        training_sources = []
        for row in profile["training_sources"]:
            records = self._bound_records(row["record_ids"], cards)
            training_sources.append({
                **deepcopy(row),
                "allocation_id": f"allocation:{row['source_id']}",
                "type": row["factory_source_type"],
                "gained_at_cl": min((cards[r].get("acquisition_cl") or 0) for r in row["record_ids"]),
                "contents": {"record_ids": list(row["record_ids"]), "record_bindings": records, "recorded_arts": [], "methods": [], "warnings": ["GM guidance only; grants no additional mechanics."], "recipes": [], "theory": [], "false_routes": []},
                "restrictions": ["Does not create acquisitions or executable mechanics."],
                "risks": ["Do not infer teachers, sects, manuals, locations, or historical events."],
                "mechanics_granted": list(row["record_ids"]),
                "source_packet_ids": sorted({packet for record in records for packet in record["source_packet_ids"]}),
                "authority": {"profile_id": profile["profile_id"], "profile_sha256": profile_sha, "classification": row["classification"]},
            })

        dao_i_ching = deepcopy(profile["dao_i_ching"])
        dao_i_ching["profile_identity"] = {"profile_id": profile["profile_id"], "profile_sha256": profile_sha}
        ai_behavior = deepcopy(profile["ai_behavior"])
        ai_behavior["profile_identity"] = {"profile_id": profile["profile_id"], "profile_sha256": profile_sha}
        if authored:
            dao_i_ching["authorship"] = deepcopy(authorship)
            ai_behavior["authorship"] = deepcopy(authorship)

        capability_rows = deepcopy(snapshot["capability_status"]["records"])
        for row in capability_rows:
            row["gm_display"] = "SUPPORTED"
            row["combat_execution_preserved"] = row.get("combat_execution")
            row["ai_policy_preserved"] = row.get("ai_policy")
        selected_method = deepcopy(snapshot.get("method") or {})
        method_audit = (
            selected_method
            if has_acquired_method(selected_method)
            else deepcopy((snapshot.get("explicit_none_systems") or {}).get("method") or {"state": "none", "source_backed": True})
        )
        selected_foundation = deepcopy(snapshot.get("foundation") or {})
        foundation_audit = (
            selected_foundation
            if has_acquired_foundation(selected_foundation)
            else deepcopy((snapshot.get("explicit_none_systems") or {}).get("foundation") or {"state": "none", "source_backed": True})
        )
        action_cards = [deepcopy(card) for card in cards.values()]
        authenticated_immortal_sources: dict[str, Any] = {}
        for card in action_cards:
            record_id = card.get("record_id")
            if isinstance(record_id, str) and record_id.startswith("tianxia.constructed.immortal_art."):
                from .immortal_art_mechanics import load_immortal_action_binding

                binding = load_immortal_action_binding(self.db, project["project_id"], record_id)
                if binding is None or card.get("record_hash") != binding["record_hash"] or card.get("source") != binding["source"] or card.get("display_name") != binding["name"]:
                    raise FoundryError("COMMAND4_IMMORTAL_SOURCE_INVALID", "The selected card does not match its recompiled project-locked Immortal Art.", details={"record_id": record_id})
                card["full_description"] = binding["full_description"]
                card["constructed_immortal_source_binding"] = binding
                proof_candidate = {
                    "record_id": record_id,
                    "record_hash": card.get("record_hash"),
                    "source": deepcopy(card.get("source")),
                    "name": card.get("display_name"),
                    "full_description": binding["full_description"],
                    "source_packet_ids": deepcopy(card.get("source_packet_ids")),
                    "missing_fields": ["unambiguous_locked_mechanics_source"],
                    "constructed_immortal_source_binding": deepcopy(binding),
                }
                try:
                    from .command4_provider import _resolve_constructed_immortal_source_proof

                    proof = _resolve_constructed_immortal_source_proof(
                        self.db,
                        project["project_id"],
                        proof_candidate,
                        packets.get("packets"),
                    )
                except FoundryError as exc:
                    # Preserve the candidate as display-only when acquisition
                    # proof is absent or stale.  A caught proof error must
                    # never become an implicit source authorization.
                    card["_source_authority_error"] = {
                        "code": exc.code,
                        "message": exc.message,
                        "details": deepcopy(exc.details),
                    }
                else:
                    authenticated_immortal_sources[record_id] = _issue_authenticated_constructed_immortal_source(proof)
            elif isinstance(record_id, str) and record_id.startswith("tianxia.constructed.forged_technique."):
                from .forged_action_mechanics import load_forged_action_binding

                binding = load_forged_action_binding(self.db, project["project_id"], record_id)
                if binding is not None:
                    if card.get("record_hash") != binding["record_hash"] or card.get("source") != binding["source"] or card.get("display_name") != binding["name"]:
                        raise FoundryError("COMMAND4_FORGED_MECHANICS_UNRESOLVED", "The selected card does not match its recompiled project-locked Forge design.", details={"record_id": record_id})
                    card["full_description"] = binding["full_description"]
                    card["constructed_forged_source_binding"] = binding
        action_documents = Command4ActionProducer.produce(
            action_cards,
            project_id=project["project_id"],
            project_revision=project["revision"],
            projection_provenance=projection_artifacts["Projection_Provenance_Map.json"],
            native_authority_root=self.db.settings.root_dir,
            _authenticated_constructed_immortal_sources=authenticated_immortal_sources,
        )

        command1 = {
            "Build_Request.json": {"schema_version": "TianxiaFoundry.C2B2BuildRequest.v1", "project_id": project["project_id"], "project_revision": project["revision"], "character_name": identity["display_name"], "target_cl": identity["cultivation_level"], "target_realm": identity["realm"], "requested_boundary": "GM tactical authoring and Command 1–4 workspace inputs only", "command5_authorized": False, "command6_authorized": False},
            "Inspiration_Source_Evidence.json": {"schema_version": "TianxiaFoundry.C2B2SourceEvidence.v1", "canonical_project": self._portable_identity(sheet_response["provenance"]["advancement_projection"]), "owner_sheet": self._portable_identity(sheet_response["sheet_artifact"]), "selected_record_bindings": self._bound_records(sorted(cards), cards), "gm_authoring_profile": {"profile_id": profile["profile_id"], "sha256": profile_sha}},
            "Character_Blueprint.json": {"schema_version": "TianxiaFoundry.C2B2CharacterBlueprint.v1", "identity": deepcopy(identity), "background_origin": deepcopy(snapshot["background_and_origin"]), "path_subpath": deepcopy(snapshot["path_and_subpath"]), "sphere_talent_ids": deepcopy(snapshot["spheres_and_talents"]), "authority":"canonical advancement and owner locks"},
            "Selection_Plan.json": {"schema_version": "TianxiaFoundry.C2B2SelectionPlan.v1", "owner_choice_locks": deepcopy(snapshot["advancement_history"]["owner_choice_locks"]), "selected_record_ids": sorted(cards), "gm_authoring_additions": ["training sources", "Dao/I Ching", "descriptive AI behavior"]},
            "Surface_Coverage_Plan.json": {"schema_version": "TianxiaFoundry.C2B2SurfaceCoveragePlan.v1", "capability_rows": capability_rows, "gm_display": "SUPPORTED", "combat_execution": "NOT_ATTEMPTED_OR_UNSUPPORTED", "pending_execution_surfaces": deepcopy(snapshot["capability_status"]["pending_execution_surfaces"])},
            "Open_Questions.json": {"schema_version": "TianxiaFoundry.C2B2OpenQuestions.v1", "resolved_for_c2b2": [], "deferred": workspace_profile["later_combat_execution_fields"], "blocking_for_c2b2": []},
            "Command_1_Audit.md": "# Command 1 Audit\n\nStatus: COMMAND_1_BLUEPRINT_LOCKED\n\nCanonical project, owner locks, selected records, and C2B.2 scope are locked. No mechanic or advancement history was changed.\n",
        }
        command2 = {
            "Rules_Selection_Packets.json": packets,
            "Canonical_Advancement_Ledger.json": deepcopy(ledger["advancement"]),
            "Canonical_Stats_Resource_Block.json": {"schema_version": "TianxiaFoundry.C2B2StatsResourceBlock.v1", "character": deepcopy(ledger["character"]), "core_stats": deepcopy(ledger["core_stats"]), "resources": deepcopy(ledger["resources"]), "typed_none": deepcopy(ledger["typed_none"])},
            "Advancement_Reconciliation.json": {"schema_version": "TianxiaFoundry.C2B2AdvancementReconciliation.v1", "status": "COMMAND_2_ADVANCEMENT_LEDGER_SEALED", "project_revision": project["revision"], "event_count": ledger["advancement"]["event_count"], "event_head_hash": ledger["advancement"]["event_head_hash"], "projection_id": projection_status.get("projection_id"), "canonical_preserved": True},
            "Command_2_Audit.md": "# Command 2 Audit\n\nStatus: COMMAND_2_ADVANCEMENT_LEDGER_SEALED\n\nThe accepted C2A-R.1 advancement projection is reused byte-for-byte.\n",
        }
        command3 = {
            "Subsystem_Completion_Ledger.json": {"schema_version": "TianxiaFoundry.C2B2SubsystemCompletion.v1", "status":"COMMAND_3_CHASSIS_COMPLETE", "advancement":"ADVANCEMENT_READY", "character_sheet":"CHARACTER_SHEET_READY", "gm_authoring":gm_authoring_status, "combat_execution":"NOT_ATTEMPTED", "typed_none": deepcopy(snapshot["explicit_none_systems"])},
            "Feature_Execution_Coverage_Plan.json": {"schema_version":"TianxiaFoundry.C2B2FeatureCoveragePlan.v1", "records": capability_rows, "display_descriptions_are_not_execution_authority": True, "later_execution_surfaces": workspace_profile["later_combat_execution_fields"]},
            "Foundation_Lifecycle_Audit.json": {"schema_version":"TianxiaFoundry.C2B2TypedNoneAudit.v1", "system":"foundation", "result": foundation_audit},
            "Background_Origin_Method_Audit.json": {"schema_version":"TianxiaFoundry.C2B2BackgroundOriginMethodAudit.v1", "background_origin":deepcopy(snapshot["background_and_origin"]), "method":method_audit, "valid":True},
            "Recorded_Art_Roster_Plan.json": {"schema_version":"TianxiaFoundry.C2B2RecordedArtPlan.v1", "recorded_arts":_advanced_system_result(snapshot, "recorded_arts", "manuals"), "planned_records":[]},
            "Blueprint_Deviation_Reconciliation.json": {"schema_version":"TianxiaFoundry.C2B2BlueprintDeviation.v1", "deviations":[], "canonical_choice_changes":False},
            "Command_3_Audit.md": "# Command 3 Audit\n\nStatus: COMMAND_3_CHASSIS_COMPLETE\n\nCharacter chassis, typed-none systems, source-backed display coverage, and later execution dependencies are reconciled.\n",
        }
        training_source_document = {
            "schema_version": "TianxiaFoundry.GMTrainingSources.v1",
            "classification": training_classification,
            "training_sources": training_sources,
        }
        if authored:
            training_source_document["authorship"] = deepcopy(authorship)
        if canonical_training_sources:
            # The canonical source rows are executable-history provenance.  Keep
            # them byte-equivalent to the owner sheet and visible to downstream
            # consumers, while retaining the profile rows as separate GM-only
            # guidance so their classifications cannot bleed across boundaries.
            training_source_document.update({
                "classification": (
                    "MIXED_CANONICAL_ADVANCEMENT_AND_PROVISIONAL_GM_GUIDANCE"
                    if provisional
                    else "MIXED_CANONICAL_ADVANCEMENT_AND_ACTUAL_GM_AUTHORING"
                    if actual
                    else "MIXED_CANONICAL_ADVANCEMENT_AND_GM_GUIDANCE"
                ),
                "training_sources": [*canonical_training_sources, *training_sources],
                "canonical_training_sources": canonical_training_sources,
                "guidance_training_sources": deepcopy(training_sources),
                "source_provenance": {
                    "canonical_training_sources": {
                        "classification": "CANONICAL_ADVANCEMENT_PROJECTION",
                        "source": "owner_character_sheet.training_sources",
                    },
                    "guidance_training_sources": {
                        "classification": "GM_GUIDANCE_ONLY",
                        "source": "gm_authoring_profile.training_sources",
                    },
                },
            })
            if authored:
                training_source_document["source_provenance"]["authorship"] = deepcopy(authorship)
        actual_owner_ratified = bool(artifact_binding.get("owner_ratified")) if actual and isinstance(artifact_binding, Mapping) else False
        command4 = {
            "Training_Sources.json": training_source_document,
            "Dao_I_Ching_GM_Authoring.json": {"schema_version":"TianxiaFoundry.GMDaoIChingAuthoring.v1", **dao_i_ching},
            "Descriptive_AI_Behavior.json": {"schema_version":"TianxiaFoundry.GMDescriptiveAIProfile.v1", **ai_behavior},
            "Action_Authoring_Candidates.json": action_documents["Action_Authoring_Candidates.json"],
            "Complete_Action_Surface.json": action_documents["Complete_Action_Surface.json"],
            "Executable_Action_Audit.json": action_documents["Executable_Action_Audit.json"],
            "Talent_Execution_Coverage_Audit.json": {
                **action_documents["Talent_Execution_Coverage_Audit.json"],
                "selected_record_capabilities": capability_rows,
                "gm_display_complete": True,
            },
            "Recorded_Art_Audit.json": {
                "schema_version":"TianxiaFoundry.C2B2TypedNoneAudit.v1",
                "system":"recorded_arts",
                "result":_advanced_system_result(snapshot, "recorded_arts", "manuals"),
                # The fixed Command 1–4 artifact set has no separate Immortal
                # Art file.  Keep the canonical end-game projection beside the
                # related recorded-art audit so the read-only view can expose
                # it without changing the sealed workspace manifest.
                "immortal_arts": _advanced_system_result(snapshot, "immortal_arts", "immortal_arts"),
                "immortal_arts_provenance": {
                    "source": "owner_character_sheet.immortal_arts",
                    "classification": "CANONICAL_ADVANCEMENT_PROJECTION",
                    "display_only_not_execution_authority": True,
                },
            },
            "Forged_Technique_Audit.json": {"schema_version":"TianxiaFoundry.C2B2TypedNoneAudit.v1", "system":"forged_techniques", "result":_advanced_system_result(snapshot, "forged_techniques", "forged_techniques")},
            "Behavior_and_Dao_Audit.json": {"schema_version":"TianxiaFoundry.C2B2BehaviorDaoAudit.v1", "status":"PROVISIONAL_GM_GUIDANCE_ONLY" if provisional else "ACTUAL_GM_AUTHORING" if actual else "GM_AUTHORING_COMPLETE", "dao_id":dao_i_ching["dao"]["authoring_id"], "i_ching_id":dao_i_ching["i_ching"]["authoring_id"], "ai_profile_id":ai_behavior["profile_id"], "mechanical_effect_count":0, "controller_policy_registered":False, **({"authorship": deepcopy(authorship), "owner_ratified": actual_owner_ratified if actual else bool(authorship.get("owner_ratified")) if isinstance(authorship, Mapping) else False, "artifact_bound": False if not isinstance(authorship, Mapping) else bool(authorship.get("artifact_bound"))} if authored else {})},
            "Command_4_Audit.md": (
                "# Command 4 Workspace Input Audit\n\nStatus: GM_AUTHORING_PROVISIONAL_INPUT_EXECUTION_DEFERRED\n\n"
                "Project-derived text is provisional display guidance. Actual model authorship, source binding, and owner ratification remain required.\n"
                if provisional else
                "# Command 4 Workspace Input Audit\n\nStatus: GM_AUTHORING_ACTUAL_INPUT_EXECUTION_DEFERRED\n\n"
                "Actual model-authored GM guidance is bound to its source records and artifact receipt. Owner ratification and executable Command 4 remain separately gated.\n"
                if actual else
                "# Command 4 Workspace Input Audit\n\nStatus: GM_AUTHORING_INPUT_COMPLETE_EXECUTION_DEFERRED\n\nTraining sources, Dao/I Ching, and descriptive AI behavior are complete. The pinned legacy executable Command 4 seal was not run and is not claimed.\n"
            ),
        }
        actual_artifact_bound = bool(authorship.get("artifact_bound")) if actual and isinstance(authorship, Mapping) else False
        validations = {
            "Command_1.validation.json": self._validation("COMMAND_1_BLUEPRINT_LOCKED", valid=True),
            "Command_2.validation.json": self._validation("COMMAND_2_ADVANCEMENT_LEDGER_SEALED", valid=True),
            "Command_3.validation.json": self._validation("COMMAND_3_CHASSIS_COMPLETE", valid=True),
            "Command_4.validation.json": self._validation("PROVISIONAL_GM_GUIDANCE_ONLY_EXECUTION_DEFERRED" if provisional else "ACTUAL_GM_AUTHORING_EXECUTION_DEFERRED" if actual else "GM_AUTHORING_INPUT_COMPLETE_EXECUTION_DEFERRED", valid=True, legacy_pinned_command4_pass=False, executable_combat_not_attempted=True, actual_gm_authoring=actual, owner_ratified=actual_owner_ratified if actual else (False if provisional else True), artifact_bound=actual_artifact_bound if actual else False),
            "C2B2_Workspace.validation.json": self._validation(_STATUS, valid=True, eligible_for_later_command5_checkpoint=(actual and actual_owner_ratified and actual_artifact_bound) if authored else True, legacy_command5_eligible=False, command5_invoked=False, command6_invoked=False, gm_export_available=False, gm_authoring_status=gm_authoring_status, actual_gm_authoring=actual, owner_ratified=actual_owner_ratified if actual else (False if provisional else True), artifact_bound=actual_artifact_bound if actual else False),
        }
        documents: dict[str, Any] = {}
        for prefix, rows in (("Command_1", command1),("Command_2",command2),("Command_3",command3),("Command_4",command4),("Validation",validations)):
            for name, value in rows.items(): documents[f"{prefix}/{name}"] = value
        documents["Workspace_Manifest.json"] = {
            "schema_version":"TianxiaFoundry.FactoryCommand1To4Workspace.v1",
            "workspace_status":_STATUS,
            "workspace_role":"deterministic existing-Factory authoring input workspace; not a legacy Command 4/5/6 seal",
            "project_id":project["project_id"], "project_revision":project["revision"],
            "event_count":ledger["advancement"]["event_count"], "event_head_hash":ledger["advancement"]["event_head_hash"],
            "replay_state_hash":ledger["advancement"].get("final_replay_state_hash"),
            "projection_id":projection_status.get("projection_id"),
            "character_sheet_sha256":sheet_response["sheet_artifact"]["sha256"],
            "gm_authoring_profile":{"id":profile["profile_id"],"sha256":profile_sha,"classification":profile["authority_classification"], **({"authorship": deepcopy(authorship)} if authored else {})},
            "workspace_profile":{"id":workspace_profile["profile_id"],"sha256":workspace_profile_sha},
            "required_training_source_coverage": sorted(workspace_profile.get("required_training_source_coverage") or []),
            "readiness":deepcopy(workspace_profile["semantics"]),
            "legacy_boundaries":deepcopy(workspace_profile["legacy_boundaries"]),
            "cpk1":{"status":"CANDIDATE_NON_AUTHORITATIVE","schemas_registered":False,"runtime_integrated":False},
        }
        if authored:
            documents["Workspace_Manifest.json"]["gm_authorship"] = deepcopy(authorship)
        if actual and isinstance(artifact_binding, Mapping):
            documents["Workspace_Manifest.json"]["gm_artifact_binding"] = {
                key: deepcopy(artifact_binding.get(key))
                for key in (
                    "receipt_id", "receipt_sha256", "artifact_sha256", "profile_sha256", "request_sha256",
                    "response_sha256", "source_snapshot_sha256", "selected_record_content_sha256",
                    "owner_decision_id", "owner_ratified", "project_id", "project_revision", "profile_id",
                )
            }
        return documents

    @staticmethod
    def _validate_documents(
        documents: dict[str, Any],
        workspace_profile: dict[str, Any],
        profile: Mapping[str, Any] | None = None,
        artifact_binding: Mapping[str, Any] | None = None,
    ) -> None:
        diagnostics: list[dict[str, Any]] = []
        required = set(workspace_profile.get("required_artifacts") or []) - {"SHA256SUMS.txt"}
        if set(documents) != required:
            diagnostics.append({"code":"FACTORY_WORKSPACE_ARTIFACT_SET_MISMATCH","missing":sorted(required-set(documents)),"extra":sorted(set(documents)-required)})
        manifest = documents.get("Workspace_Manifest.json") or {}
        if manifest.get("workspace_status") != _STATUS:
            diagnostics.append({"code":"FACTORY_WORKSPACE_STATUS_INVALID"})
        if (manifest.get("legacy_boundaries") or {}).get("pinned_command4_executable_status") != "NOT_RUN":
            diagnostics.append({"code":"FACTORY_WORKSPACE_FALSE_COMMAND4_CLAIM"})
        validation = documents.get("Validation/C2B2_Workspace.validation.json") or {}
        if validation.get("valid") is not True or validation.get("command5_invoked") is not False or validation.get("command6_invoked") is not False:
            diagnostics.append({"code":"FACTORY_WORKSPACE_VALIDATION_INVALID"})
        training = documents.get("Command_4/Training_Sources.json", {}).get("training_sources") or []
        if not training:
            diagnostics.append({"code":"FACTORY_WORKSPACE_TRAINING_SOURCES_MISSING"})
        if not documents.get("Command_4/Dao_I_Ching_GM_Authoring.json"):
            diagnostics.append({"code":"FACTORY_WORKSPACE_DAO_ICHING_MISSING"})
        ai=documents.get("Command_4/Descriptive_AI_Behavior.json") or {}
        if ai.get("not_executable_controller_policy") is not True:
            diagnostics.append({"code":"FACTORY_WORKSPACE_AI_PROFILE_MISSING"})
        manifest_profile = manifest.get("gm_authoring_profile") or {}
        classification = manifest_profile.get("classification")
        manifest_authorship = manifest.get("gm_authorship")
        if manifest_authorship is None:
            manifest_authorship = manifest_profile.get("authorship")
        if profile is not None:
            if (
                manifest_profile.get("id") != profile.get("profile_id")
                or manifest_profile.get("classification") != profile.get("authority_classification")
            ):
                diagnostics.append({"code": "FACTORY_WORKSPACE_GM_PROFILE_IDENTITY_INVALID"})
            expected_authorship = profile.get("authorship")
            if expected_authorship is not None and manifest_authorship != expected_authorship:
                diagnostics.append({"code": "FACTORY_WORKSPACE_GM_AUTHORSHIP_BINDING_INVALID"})
        training_document = documents.get("Command_4/Training_Sources.json") or {}
        dao_document = documents.get("Command_4/Dao_I_Ching_GM_Authoring.json") or {}
        behavior_document = documents.get("Command_4/Behavior_and_Dao_Audit.json") or {}
        command4_validation = documents.get("Validation/Command_4.validation.json") or {}
        c2b2_validation = documents.get("Validation/C2B2_Workspace.validation.json") or {}
        if classification == _GM_PROVISIONAL_CLASSIFICATION:
            expected = {
                "schema_version": _GM_AUTHORSHIP_SCHEMA,
                "status": _GM_PROVISIONAL_STATUS,
                "origin": "project_selected_record_template",
                "provider_id": None,
                "artifact_bound": False,
                "artifact_sha256": None,
                "owner_ratified": False,
            }
            if not isinstance(manifest_authorship, Mapping) or any(manifest_authorship.get(key) != value for key, value in expected.items()):
                diagnostics.append({"code": "FACTORY_WORKSPACE_PROVISIONAL_AUTHORSHIP_INVALID"})
            covered_record_ids = sorted({
                str(record)
                for row in training_document.get("training_sources") or []
                if isinstance(row, Mapping)
                for record in row.get("record_ids") or []
            })
            if not isinstance(manifest_authorship, Mapping) or manifest_authorship.get("source_record_ids") != covered_record_ids:
                diagnostics.append({"code": "FACTORY_WORKSPACE_PROVISIONAL_SOURCE_BINDING_INVALID"})
            if training_document.get("classification") not in {_GM_PROVISIONAL_CLASSIFICATION, "MIXED_CANONICAL_ADVANCEMENT_AND_PROVISIONAL_GM_GUIDANCE"}:
                diagnostics.append({"code": "FACTORY_WORKSPACE_PROVISIONAL_TRAINING_INVALID"})
            if dao_document.get("classification") != _GM_PROVISIONAL_CLASSIFICATION:
                diagnostics.append({"code": "FACTORY_WORKSPACE_PROVISIONAL_THEME_INVALID"})
            if behavior_document.get("status") != "PROVISIONAL_GM_GUIDANCE_ONLY":
                diagnostics.append({"code": "FACTORY_WORKSPACE_PROVISIONAL_BEHAVIOR_INVALID"})
            if command4_validation.get("status") != "PROVISIONAL_GM_GUIDANCE_ONLY_EXECUTION_DEFERRED":
                diagnostics.append({"code": "FACTORY_WORKSPACE_PROVISIONAL_COMMAND4_INVALID"})
            if (
                c2b2_validation.get("gm_authoring_status") != "PROVISIONAL_GM_GUIDANCE_ONLY"
                or c2b2_validation.get("actual_gm_authoring") is not False
                or c2b2_validation.get("owner_ratified") is not False
                or c2b2_validation.get("artifact_bound") is not False
                or c2b2_validation.get("eligible_for_later_command5_checkpoint") is not False
            ):
                diagnostics.append({"code": "FACTORY_WORKSPACE_PROVISIONAL_VALIDATION_INVALID"})
            for marker in (
                "OWNER_RATIFIED_GM_AUTHORING",
                "GM_AUTHORING_COMPLETE",
                "COMPLETE_AS_WORKSPACE_INPUT",
                "GM_AUTHORING_INPUT_COMPLETE_EXECUTION_DEFERRED",
                "NON_EXECUTABLE_GM_GUIDANCE_COMPLETE",
                "MIXED_CANONICAL_ADVANCEMENT_AND_GM_GUIDANCE",
            ):
                if marker in canonical_json(documents):
                    diagnostics.append({"code": "FACTORY_WORKSPACE_PROVISIONAL_FALSE_COMPLETION", "marker": marker})
        elif classification == _GM_ACTUAL_CLASSIFICATION:
            actual_valid = (
                isinstance(manifest_authorship, Mapping)
                and manifest_authorship.get("schema_version") == _GM_AUTHORSHIP_SCHEMA
                and manifest_authorship.get("status") == _GM_ACTUAL_STATUS
                and isinstance(manifest_authorship.get("provider_id"), str)
                and bool(manifest_authorship.get("provider_id").strip())
                and manifest_authorship.get("artifact_bound") is True
                and isinstance(manifest_authorship.get("artifact_sha256"), str)
                and len(manifest_authorship.get("artifact_sha256")) == 64
                and all(character in "0123456789abcdef" for character in manifest_authorship.get("artifact_sha256"))
                and type(manifest_authorship.get("owner_ratified")) is bool
            )
            if not actual_valid:
                diagnostics.append({"code": "FACTORY_WORKSPACE_ACTUAL_AUTHORSHIP_INVALID"})
            if not isinstance(artifact_binding, Mapping) or artifact_binding.get("verified") is not True:
                diagnostics.append({"code": "FACTORY_WORKSPACE_ACTUAL_ARTIFACT_UNVERIFIED"})
            else:
                manifest_binding = manifest.get("gm_artifact_binding")
                for field in (
                    "receipt_id", "receipt_sha256", "artifact_sha256", "profile_sha256", "request_sha256",
                    "response_sha256", "source_snapshot_sha256", "selected_record_content_sha256", "owner_decision_id",
                    "owner_ratified", "project_id", "project_revision", "profile_id",
                ):
                    if not isinstance(manifest_binding, Mapping) or manifest_binding.get(field) != artifact_binding.get(field):
                        diagnostics.append({"code": "FACTORY_WORKSPACE_ACTUAL_ARTIFACT_BINDING_INVALID", "field": field})
            if training_document.get("classification") not in {_GM_ACTUAL_CLASSIFICATION, "MIXED_CANONICAL_ADVANCEMENT_AND_ACTUAL_GM_AUTHORING"}:
                diagnostics.append({"code": "FACTORY_WORKSPACE_ACTUAL_TRAINING_INVALID"})
            if dao_document.get("classification") != _GM_ACTUAL_CLASSIFICATION:
                diagnostics.append({"code": "FACTORY_WORKSPACE_ACTUAL_THEME_INVALID"})
            if behavior_document.get("status") != _GM_ACTUAL_CLASSIFICATION:
                diagnostics.append({"code": "FACTORY_WORKSPACE_ACTUAL_BEHAVIOR_INVALID"})
            if command4_validation.get("status") != "ACTUAL_GM_AUTHORING_EXECUTION_DEFERRED":
                diagnostics.append({"code": "FACTORY_WORKSPACE_ACTUAL_COMMAND4_INVALID"})
            # The immutable provider-authored profile remains byte-stable and
            # therefore may still say ``owner_ratified: false``. A ratified
            # workspace derives this state from the separately authenticated
            # owner-decision binding.
            owner_ratified = (
                bool(artifact_binding.get("owner_ratified"))
                if isinstance(artifact_binding, Mapping) and artifact_binding.get("verified") is True
                else bool(manifest_authorship.get("owner_ratified")) if isinstance(manifest_authorship, Mapping) else False
            )
            if (
                c2b2_validation.get("gm_authoring_status") != _GM_ACTUAL_CLASSIFICATION
                or c2b2_validation.get("actual_gm_authoring") is not True
                or c2b2_validation.get("artifact_bound") is not True
                or c2b2_validation.get("owner_ratified") is not owner_ratified
                or c2b2_validation.get("eligible_for_later_command5_checkpoint") is not owner_ratified
            ):
                diagnostics.append({"code": "FACTORY_WORKSPACE_ACTUAL_VALIDATION_INVALID"})
        serialized=canonical_json(documents).casefold()
        if "command_5_gm_screen_candidate_ready" in serialized or "simulated_consumer_pass_real_gmscreen_acceptance_required" in serialized:
            diagnostics.append({"code":"FACTORY_WORKSPACE_FALSE_LATER_SEAL"})
        if diagnostics:
            raise FoundryError("FACTORY_WORKSPACE_BUILD_BLOCKED","The Command 1–4 workspace failed cross-file validation.",details={"diagnostics":diagnostics})

    def build(self, project_id: str) -> dict[str, Any]:
        project = self.projects.get_project(project_id)["project"]
        sheet_response = self.sheets.sheet(project_id)
        if sheet_response.get("build_status") != "CHARACTER_SHEET_READY":
            raise FoundryError("FACTORY_WORKSPACE_CHARACTER_SHEET_NOT_READY","The owner-facing Character Sheet must be complete before C2B.2 authoring.")
        snapshot = sheet_response["owner_character_sheet"]
        gm_loaded = self._load_gm_authoring(
            project_id,
            project_revision=int(project["revision"]),
            snapshot=snapshot,
        )
        profile, profile_sha = self._authoring_profile()
        workspace_profile, workspace_profile_sha = self._workspace_profile()
        artifact_binding = None
        if gm_loaded is not None:
            profile = gm_loaded["profile"]
            profile_sha = gm_loaded["profile_sha256"]
            workspace_profile = gm_loaded["workspace_profile"]
            workspace_profile_sha = gm_loaded["workspace_profile_sha256"]
            artifact_binding = gm_loaded["binding"]
        else:
            existing_pointer = self._pointer(project_id)
            if existing_pointer.is_file():
                try:
                    existing = self._gm_read_json(existing_pointer)
                    if existing.get("gm_authoring_actual") is True or existing.get("gm_authoring_status") == _GM_ACTUAL_CLASSIFICATION:
                        raise FoundryError("GM_AUTHORING_ARTIFACT_MISSING", "The workspace advertises actual GM authorship without a server-owned receipt.")
                except FoundryError:
                    raise
                except (OSError, ValueError, json.JSONDecodeError):
                    pass
            profile, profile_sha, workspace_profile, workspace_profile_sha = self._project_authoring_profile(
                snapshot,
                profile,
                profile_sha,
                workspace_profile,
                workspace_profile_sha,
            )
        self._validate_profile(profile, workspace_profile, snapshot, artifact_binding)
        artifact_names=("Character_Master_Ledger.json","Rules_Selection_Packets.json","Projection_Provenance_Map.json","Projection_Coverage_Report.json","Projection_Diagnostics.json")
        projection_artifacts={name:json.loads(self.projections.artifact(project_id,name).read_text(encoding="utf-8")) for name in artifact_names}
        documents=self._documents(project=project,sheet_response=sheet_response,profile=profile,profile_sha=profile_sha,workspace_profile=workspace_profile,workspace_profile_sha=workspace_profile_sha,projection_artifacts=projection_artifacts,artifact_binding=artifact_binding)
        self._validate_documents(documents, workspace_profile, profile, artifact_binding)
        # A producer repair can change documents without changing the project
        # revision or profile. Include the complete output in the identity so
        # rebuilding preserves the old version and installs the repaired one.
        workspace_id=sha256_json({"project_id":project_id,"project_revision":project["revision"],"event_head_hash":documents["Workspace_Manifest.json"]["event_head_hash"],"character_sheet_sha256":sheet_response["sheet_artifact"]["sha256"],"profile_sha256":profile_sha,"workspace_profile_sha256":workspace_profile_sha,"documents_sha256":sha256_json(documents)})
        root=self._root(project_id); target=root/workspace_id; staging=root/(workspace_id+".staging")
        shutil.rmtree(staging,ignore_errors=True); staging.mkdir(parents=True,exist_ok=True)
        for rel,value in documents.items():
            path=staging/rel
            if rel.endswith(".md"):
                path.parent.mkdir(parents=True,exist_ok=True); path.write_text(str(value),encoding="utf-8",newline="\n")
            else: _write_json(path,value)
        checks=[]
        for path in sorted(staging.rglob("*")):
            if path.is_file(): checks.append(f"{sha256_file(path)}  {path.relative_to(staging).as_posix()}")
        (staging/"SHA256SUMS.txt").write_text("\n".join(checks)+"\n",encoding="utf-8",newline="\n")
        if target.exists(): shutil.rmtree(staging)
        else: staging.replace(target)
        file_hashes={path.relative_to(target).as_posix():sha256_file(path) for path in sorted(target.rglob("*")) if path.is_file()}
        workspace_sha=sha256_json(file_hashes)
        pointer={"schema_version":"TianxiaFoundry.FactoryWorkspacePointer.v1","project_id":project_id,"workspace_id":workspace_id,"workspace_status":_STATUS,"workspace_path":str(target),"workspace_sha256":workspace_sha,"manifest_sha256":file_hashes["Workspace_Manifest.json"],"gm_authoring_profile_sha256":profile_sha,"command5_invoked":False,"command6_invoked":False,"gm_export_available":False}
        if self._is_project_derived_profile(profile):
            pointer.update({
                "gm_authoring_status": "PROVISIONAL_GM_GUIDANCE_ONLY",
                "gm_authorship_status": _GM_PROVISIONAL_STATUS,
                "gm_authoring_actual": False,
                "gm_authoring_profile_classification": profile["authority_classification"],
                "eligible_for_later_command5_checkpoint": False,
            })
        elif profile.get("authority_classification") == _GM_ACTUAL_CLASSIFICATION:
            authorship = self._profile_authorship(profile) or {}
            owner_ratified = bool(artifact_binding.get("owner_ratified")) if isinstance(artifact_binding, Mapping) else False
            pointer.update({
                "gm_authoring_status": _GM_ACTUAL_CLASSIFICATION,
                "gm_authorship_status": _GM_ACTUAL_STATUS,
                "gm_authoring_actual": True,
                "gm_authoring_profile_classification": profile["authority_classification"],
                "eligible_for_later_command5_checkpoint": owner_ratified,
            })
            if isinstance(artifact_binding, Mapping):
                pointer.update({
                    "gm_receipt_id": artifact_binding.get("receipt_id"),
                    "gm_receipt_sha256": artifact_binding.get("receipt_sha256"),
                    "gm_artifact_sha256": artifact_binding.get("artifact_sha256"),
                    "gm_profile_sha256": artifact_binding.get("profile_sha256"),
                    "gm_request_sha256": artifact_binding.get("request_sha256"),
                    "gm_response_sha256": artifact_binding.get("response_sha256"),
                    "gm_source_snapshot_sha256": artifact_binding.get("source_snapshot_sha256"),
                    "gm_selected_record_content_sha256": artifact_binding.get("selected_record_content_sha256"),
                    "gm_owner_decision_id": artifact_binding.get("owner_decision_id"),
                })
        root.mkdir(parents=True,exist_ok=True); pointer_tmp=root/"current.json.tmp"; _write_json(pointer_tmp,pointer); pointer_tmp.replace(self._pointer(project_id))
        return {**pointer,"artifact_hashes":file_hashes,"readiness":workspace_profile["semantics"],"legacy_boundaries":workspace_profile["legacy_boundaries"]}

    def author_command4(self, project_id: str, provider: Any) -> dict[str, Any]:
        """Explicitly invoke bounded Command 4 provider authoring.

        The output root is deliberately server-owned beneath the configured
        logs directory; callers cannot redirect provider evidence or overlays
        to an arbitrary filesystem path.  Workspace construction remains a
        separate explicit operation and never calls this method implicitly.
        """

        from factory_authoring.command4_provider import Command4ProviderAuthoring

        output_root = (self.db.settings.logs_dir / "factory_command4_authoring").resolve()
        result = Command4ProviderAuthoring(workspace_service=self).author(project_id, provider, output_root)
        if isinstance(result, Mapping) and result.get("valid") is True:
            workflow = getattr(self, "final_character_workflow", None)
            if workflow is not None:
                receipt = workflow.record_action_workspace(project_id, result)
                if receipt is not None:
                    return {**result, "final_character_component": receipt}
        return result

    def author_composite_controller(self, project_id: str, provider: Any) -> dict[str, Any]:
        """Explicitly invoke the provider-free-prepared local controller target.

        Workspace construction and Command 5 remain separate operations; this
        method is the only service entry point that can request the future
        ``composite_controller`` provider proposal.
        """

        from factory_authoring.composite_controller import CompositeControllerAuthoring

        output_root = (self.db.settings.logs_dir / "factory_composite_controller").resolve()
        result = CompositeControllerAuthoring(workspace_service=self).author(project_id, provider, output_root)
        if isinstance(result, Mapping) and result.get("valid") is True:
            workflow = getattr(self, "final_character_workflow", None)
            if workflow is not None:
                receipt = workflow.record_composite_controller(project_id, result)
                if receipt is not None:
                    return {**result, "final_character_component": receipt}
        return result

    def status(self, project_id: str) -> dict[str, Any]:
        pointer=self._pointer(project_id)
        if not pointer.is_file():
            gm_pointer = self._gm_root(project_id) / "current.json"
            if gm_pointer.is_file():
                try:
                    project = self.projects.get_project(project_id)["project"]
                    sheet_response = self.sheets.sheet(project_id)
                    loaded = self._load_gm_authoring(
                        project_id,
                        project_revision=int(project["revision"]),
                        snapshot=sheet_response.get("owner_character_sheet"),
                    )
                    binding = loaded.get("binding") if isinstance(loaded, Mapping) else None
                    if not isinstance(binding, Mapping):
                        raise FoundryError("GM_AUTHORING_ARTIFACT_MISSING", "The server-owned GM receipt could not be loaded.")
                    return {
                        "project_id": project_id,
                        "workspace_status": "REBUILD_PENDING",
                        "workspace_id": None,
                        "workspace_sha256": None,
                        "available": False,
                        "provider_free_rebuild_available": True,
                        "gm_authoring_status": _GM_ACTUAL_CLASSIFICATION,
                        "gm_authorship_status": _GM_ACTUAL_STATUS,
                        "gm_authoring_actual": True,
                        "gm_authoring_profile_classification": _GM_ACTUAL_CLASSIFICATION,
                        "gm_receipt_id": binding.get("receipt_id"),
                        "gm_receipt_sha256": binding.get("receipt_sha256"),
                        "gm_artifact_sha256": binding.get("artifact_sha256"),
                        "gm_profile_sha256": binding.get("profile_sha256"),
                        "gm_source_snapshot_sha256": binding.get("source_snapshot_sha256"),
                        "gm_selected_record_content_sha256": binding.get("selected_record_content_sha256"),
                        "gm_owner_decision_id": binding.get("owner_decision_id"),
                        "gm_owner_ratified": binding.get("owner_ratified") is True,
                        "eligible_for_later_command5_checkpoint": binding.get("owner_ratified") is True,
                        "command5_invoked": False,
                        "command6_invoked": False,
                        "gm_export_available": False,
                        "blockers": ["The provider-free Factory workspace rebuild is pending."],
                    }
                except (FoundryError, OSError, ValueError, json.JSONDecodeError) as exc:
                    return {"project_id":project_id,"workspace_status":"STALE","available":False,"gm_authoring":"STALE","blockers":[str(exc)],"command5_invoked":False,"command6_invoked":False,"gm_export_available":False}
            return {"project_id":project_id,"workspace_status":"NOT_ATTEMPTED","available":False,"command5_invoked":False,"command6_invoked":False,"gm_export_available":False}
        try:
            payload=self._gm_read_json(pointer, code="FACTORY_WORKSPACE_POINTER_INVALID")
            workspace=Path(payload.get("workspace_path") or "")
            if not workspace.is_dir():
                raise FoundryError("FACTORY_WORKSPACE_STALE", "The recorded Factory workspace directory is missing.")
            manifest=workspace/"Workspace_Manifest.json"
            if not manifest.is_file() or sha256_file(manifest)!=payload.get("manifest_sha256"):
                raise FoundryError("FACTORY_WORKSPACE_STALE", "The Factory workspace manifest is stale.")
            manifest_payload=self._gm_read_json(manifest, code="FACTORY_WORKSPACE_MANIFEST_INVALID")
            manifest_profile = manifest_payload.get("gm_authoring_profile") if isinstance(manifest_payload, Mapping) else None
            actual = (
                payload.get("gm_authoring_actual") is True
                or payload.get("gm_authoring_status") == _GM_ACTUAL_CLASSIFICATION
                or payload.get("gm_receipt_id") is not None
                or (self._gm_root(project_id) / "current.json").is_file()
                or isinstance(manifest_profile, Mapping)
                and manifest_profile.get("classification") == _GM_ACTUAL_CLASSIFICATION
            )
            if actual:
                project = self.projects.get_project(project_id)["project"]
                sheet_response = self.sheets.sheet(project_id)
                loaded = self._load_gm_authoring(project_id, project_revision=int(project["revision"]), snapshot=sheet_response.get("owner_character_sheet"))
                if loaded is None:
                    raise FoundryError("GM_AUTHORING_ARTIFACT_MISSING", "The workspace advertises actual GM authorship without a server-owned receipt.")
                binding = loaded["binding"]
                manifest_binding = manifest_payload.get("gm_artifact_binding")
                binding_expected = (
                    payload.get("gm_receipt_id") is not None
                    or isinstance(manifest_profile, Mapping)
                    and manifest_profile.get("classification") == _GM_ACTUAL_CLASSIFICATION
                )
                if binding_expected and not isinstance(manifest_binding, Mapping):
                    raise FoundryError("GM_AUTHORING_MANIFEST_BINDING_INVALID", "The workspace manifest has no server-owned GM artifact binding.")
                if isinstance(manifest_binding, Mapping):
                    for field in ("receipt_id", "receipt_sha256", "artifact_sha256", "profile_sha256", "source_snapshot_sha256", "selected_record_content_sha256", "owner_decision_id", "owner_ratified"):
                        if manifest_binding.get(field) != binding.get(field):
                            if binding_expected:
                                raise FoundryError("GM_AUTHORING_MANIFEST_BINDING_INVALID", "The workspace pointer or manifest disagrees with the verified GM receipt.", details={"field": field})
                pointer_fields = {
                    "gm_receipt_id": "receipt_id",
                    "gm_receipt_sha256": "receipt_sha256",
                    "gm_artifact_sha256": "artifact_sha256",
                    "gm_profile_sha256": "profile_sha256",
                    "gm_request_sha256": "request_sha256",
                    "gm_response_sha256": "response_sha256",
                    "gm_source_snapshot_sha256": "source_snapshot_sha256",
                    "gm_selected_record_content_sha256": "selected_record_content_sha256",
                    "gm_owner_decision_id": "owner_decision_id",
                }
                if binding_expected and any(payload.get(pointer_field) != binding.get(binding_field) for pointer_field, binding_field in pointer_fields.items()):
                    raise FoundryError("GM_AUTHORING_POINTER_BINDING_INVALID", "The workspace pointer does not match its server-owned GM receipt.")
                payload = {
                    **payload,
                    "gm_authoring_status": _GM_ACTUAL_CLASSIFICATION,
                    "gm_authorship_status": _GM_ACTUAL_STATUS,
                    "gm_authoring_actual": True,
                    "gm_authoring_profile_classification": _GM_ACTUAL_CLASSIFICATION,
                    "eligible_for_later_command5_checkpoint": binding.get("owner_ratified") is True,
                    "gm_owner_decision_id": binding.get("owner_decision_id"),
                    "gm_receipt_id": binding.get("receipt_id"),
                    "gm_receipt_sha256": binding.get("receipt_sha256"),
                    "gm_artifact_sha256": binding.get("artifact_sha256"),
                    "gm_profile_sha256": binding.get("profile_sha256"),
                    "gm_source_snapshot_sha256": binding.get("source_snapshot_sha256"),
                    "gm_selected_record_content_sha256": binding.get("selected_record_content_sha256"),
                    "gm_owner_ratified": binding.get("owner_ratified") is True,
                }
                workspace_bound = isinstance(manifest_binding, Mapping) and binding_expected
                if workspace_bound:
                    workspace_bound = all(
                        manifest_binding.get(field) == binding.get(field)
                        for field in ("receipt_id", "receipt_sha256", "artifact_sha256", "profile_sha256", "source_snapshot_sha256", "selected_record_content_sha256", "owner_decision_id", "owner_ratified")
                    ) and all(
                        payload.get(pointer_field) == binding.get(binding_field)
                        for pointer_field, binding_field in pointer_fields.items()
                    )
                if not workspace_bound:
                    payload.update({"workspace_status": "REBUILD_PENDING", "workspace_id": None, "workspace_sha256": None, "provider_free_rebuild_available": True})
            return {**payload,"available":payload.get("workspace_status") != "REBUILD_PENDING","provider_free_rebuild_available":payload.get("provider_free_rebuild_available", False),"blockers":["The provider-free Factory workspace rebuild is pending."] if payload.get("workspace_status") == "REBUILD_PENDING" else []}
        except (FoundryError, OSError, ValueError, json.JSONDecodeError) as exc:
            return {"project_id":project_id,"workspace_status":"STALE","available":False,"gm_authoring":"STALE","blockers":[str(exc)],"command5_invoked":False,"command6_invoked":False,"gm_export_available":False}

    def view(self, project_id: str) -> dict[str, Any]:
        """Return a bounded, non-executable GM-authoring sheet projection."""
        status = self.status(project_id)
        public_status = {
            key: deepcopy(value)
            for key, value in status.items()
            if key not in {"workspace_path", "artifact_hashes"}
        }
        if status.get("available") is not True:
            return {
                "schema_version": "TianxiaFoundry.GMAuthoringSheetView.v1",
                **public_status,
                "authority": {
                    "classification": "DISPLAY_ONLY_NOT_EXECUTION_AUTHORITY",
                    "mechanical_authority": False,
                    "execution_authority": False,
                },
            }

        workspace = Path(status["workspace_path"])
        file_hashes = {
            path.relative_to(workspace).as_posix(): sha256_file(path)
            for path in sorted(workspace.rglob("*"))
            if path.is_file()
        }
        if sha256_json(file_hashes) != status.get("workspace_sha256"):
            raise FoundryError(
                "FACTORY_WORKSPACE_VIEW_STALE",
                "The GM-authoring workspace changed after it was sealed; rebuild it before displaying guidance.",
                status_code=409,
            )

        def document(relative_path: str) -> dict[str, Any]:
            path = workspace / relative_path
            if not path.is_file():
                raise FoundryError(
                    "FACTORY_WORKSPACE_VIEW_DOCUMENT_MISSING",
                    "A required GM-authoring display document is missing.",
                    details={"document": relative_path},
                    status_code=409,
                )
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise FoundryError(
                    "FACTORY_WORKSPACE_VIEW_DOCUMENT_INVALID",
                    "A required GM-authoring display document is invalid.",
                    details={"document": relative_path},
                    status_code=409,
                ) from exc
            if not isinstance(value, dict):
                raise FoundryError(
                    "FACTORY_WORKSPACE_VIEW_DOCUMENT_INVALID",
                    "A required GM-authoring display document must be a JSON object.",
                    details={"document": relative_path},
                    status_code=409,
                )
            return value

        training = document("Command_4/Training_Sources.json")
        dao_i_ching = document("Command_4/Dao_I_Ching_GM_Authoring.json")
        recorded = document("Command_4/Recorded_Art_Audit.json")
        forged = document("Command_4/Forged_Technique_Audit.json")
        immortal_arts = recorded.get("immortal_arts")
        if immortal_arts is None:
            # Keep older hand-built workspaces readable while current builds
            # expose the canonical sheet projection above.
            immortal_arts = {
                "state": "not_projected",
                "source_backed": False,
                "note": "Immortal Art projection is absent from this legacy workspace artifact.",
            }
        return {
            "schema_version": "TianxiaFoundry.GMAuthoringSheetView.v1",
            **public_status,
            "authority": {
                "classification": "DISPLAY_ONLY_NOT_EXECUTION_AUTHORITY",
                "capability_status": "GM_GUIDANCE_ONLY",
                "mechanical_authority": False,
                "execution_authority": False,
                "not_a_combat_macro": True,
            },
            **({"gm_authorship": deepcopy(dao_i_ching.get("authorship") or {})} if status.get("gm_authoring_status") else {}),
            "training_sources": deepcopy(training.get("training_sources") or []),
            "dao_i_ching": {
                "classification": dao_i_ching.get("classification"),
                "dao": deepcopy(dao_i_ching.get("dao") or {}),
                "i_ching": deepcopy(dao_i_ching.get("i_ching") or {}),
            },
            "advanced_systems": {
                "recorded_arts": _advanced_system_state(recorded.get("result"), present_state="acquired", system="recorded arts"),
                "forged_techniques": _advanced_system_state(forged.get("result"), present_state="acquired", system="forged techniques"),
                "immortal_arts": _advanced_system_state(immortal_arts, present_state="projected", system="immortal arts"),
            },
        }
