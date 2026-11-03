from __future__ import annotations

import gc
import hashlib
import json
import shutil
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from jsonschema import Draft202012Validator, RefResolver

from app.core import Database, FoundryError, canonical_json, sha256_file, sha256_json, utcnow
from character_creation.choice_snapshot import materialize_choice_snapshot, valid_choice_snapshot
from contracts.registry import SchemaRegistry
from non_sphere_authority.foundation_mechanics import has_acquired_foundation
from non_sphere_authority.method_mechanics import has_acquired_method
from project_store.service import ProjectStore
from projector.reducer import EffectiveStateReducer

ARTIFACT_MEDIA = {
    "Character_Master_Ledger.json": "application/json",
    "Rules_Selection_Packets.json": "application/json",
    "Projection_Provenance_Map.json": "application/json",
    "Projection_Coverage_Report.json": "application/json",
    "Projection_Diagnostics.json": "application/json",
}
FORBIDDEN_EXACT = {
    "not recorded", "not itemized", "unnamed talent", "unknown", "tbd",
    "placeholder", "sheet", "technique", "ability",
}


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _leaf_pointers(value: Any, pointer: str = "") -> list[str]:
    if isinstance(value, dict):
        if not value:
            return [pointer]
        out: list[str] = []
        for key in sorted(value):
            out.extend(_leaf_pointers(value[key], pointer + "/" + _escape(str(key))))
        return out
    if isinstance(value, list):
        if not value:
            return [pointer]
        out: list[str] = []
        for index, item in enumerate(value):
            out.extend(_leaf_pointers(item, pointer + f"/{index}"))
        return out
    return [pointer]


def _placeholder_findings(value: Any, pointer: str = "") -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            findings.extend(_placeholder_findings(item, pointer + "/" + _escape(str(key))))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            findings.extend(_placeholder_findings(item, pointer + f"/{index}"))
    elif isinstance(value, str):
        normalized = " ".join(value.strip().lower().split())
        if normalized in FORBIDDEN_EXACT or "placeholder" in normalized:
            findings.append({"code": "PROJECTION_PLACEHOLDER_FORBIDDEN", "pointer": pointer or "", "value": value})
    return findings


def _schema_diagnostics(instance: Any, schema: dict[str, Any], *, schema_path: Path) -> list[dict[str, Any]]:
    resolver = RefResolver(base_uri=schema_path.resolve().as_uri(), referrer=schema)
    validator = Draft202012Validator(schema, resolver=resolver)
    diagnostics: list[dict[str, Any]] = []
    for error in sorted(validator.iter_errors(instance), key=lambda e: (list(e.absolute_path), e.message)):
        pointer = "".join("/" + _escape(str(part)) for part in error.absolute_path)
        schema_pointer = "".join("/" + _escape(str(part)) for part in error.absolute_schema_path)
        diagnostics.append({"code": "FACTORY_LEDGER_SCHEMA", "pointer": pointer, "schema_pointer": schema_pointer, "message": error.message})
    return diagnostics


def _title_authority_diagnostic(ledger: dict[str, Any], packets: dict[str, Any]) -> dict[str, Any] | None:
    """Check the reducer's title projection without revalidating its locks.

    ``v3_bridge`` is the authority that authenticates title locks.  This
    stage-aware check only makes sure the two emitted projections agree and
    that their status explains whether a title is present.  Keeping this as a
    projection check prevents the old unconditional "title is fabricated"
    finding from rejecting an authenticated server-derived or owner-locked
    title.
    """

    character = ledger.get("character") or {}
    title = character.get("title")
    title_status = character.get("title_status")
    owner_selections = packets.get("owner_selections") or {}
    packet_title = owner_selections.get("title") if isinstance(owner_selections, dict) else None
    title_is_valid = (
        (
            title is None
            and title_status == "OPTIONAL_OMITTED_BY_OWNER"
            and packet_title is None
        )
        or (
            isinstance(title, str)
            and bool(title.strip())
            and isinstance(title_status, str)
            and title_status in {"SELECTED", "OWNER_LOCKED"}
            and packet_title == title
        )
    )
    if title_is_valid:
        return None
    return {
        "code": "PROJECTION_CHARACTER_TITLE_AUTHORITY_INVALID",
        "pointer": "/character/title",
        "message": "The character title, title status, and rules-selection owner title do not form one validated projection.",
        "title_status": title_status,
        "title_present": title is not None,
        "packet_title_matches": packet_title == title,
    }


def _stage_aware_diagnostics(ledger: dict[str, Any], packets: dict[str, Any], reduced: Any) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    readiness = ledger.get("readiness") or {}
    if readiness.get("active_profile") != "ADVANCEMENT_READY" or readiness.get("advancement") != "ADVANCEMENT_READY":
        diagnostics.append({"code": "PROJECTION_ADVANCEMENT_READINESS_INVALID", "pointer": "/readiness", "message": "The bounded v3 bridge must declare ADVANCEMENT_READY."})
    choice_snapshot = reduced.typed_choice_snapshot or {}
    snapshot_binding = ledger.get("typed_choice_snapshot") or {}
    character = ledger.get("character") or {}
    advancement = ledger.get("advancement") or {}
    levels = advancement.get("levels") or []
    snapshot_valid = valid_choice_snapshot(choice_snapshot)
    snapshot_binding_valid = bool(
        snapshot_binding.get("schema") == "TianxiaFoundry.TypedProjectChoiceSnapshotBinding.v1"
        and snapshot_binding.get("snapshot_sha256") == choice_snapshot.get("snapshot_sha256")
        and snapshot_binding.get("canonical_project_id") == choice_snapshot.get("canonical_project_id")
        and snapshot_binding.get("project_revision") == choice_snapshot.get("project_revision")
        and snapshot_binding.get("content_lock_hash") == choice_snapshot.get("content_lock_hash")
        and snapshot_binding.get("event_stream") == choice_snapshot.get("event_stream")
        and snapshot_binding.get("typed_lock_count") == len(choice_snapshot.get("typed_locks") or [])
    )
    typed_none = ledger.get("typed_none") or {}
    method_projection = ledger.get("method") or {}
    method_authority_valid = (
        typed_none.get("method", {}).get("state") == "none"
        or has_acquired_method(method_projection)
    )
    foundation_projection = ledger.get("foundation") or {}
    foundation_authority_valid = (
        typed_none.get("foundation", {}).get("state") == "none"
        or has_acquired_foundation(foundation_projection)
    )
    required = {
        "identity": bool(
            character.get("name")
            and character.get("species")
            and snapshot_valid
            and snapshot_binding_valid
            and choice_snapshot.get("canonical_project_id") == character.get("character_id")
        ),
        "owner_selections": bool(snapshot_valid and snapshot_binding_valid and choice_snapshot.get("typed_locks")),
        "universal_baseline": all(key in (ledger.get("core_stats") or {}) for key in ("ac_base", "initiative_bonus", "speed_ft")),
        "ability_progression": bool((ledger.get("core_stats") or {}).get("ability_scores") and (ledger.get("advancement") or {}).get("levels")),
        "hp_progression": bool((ledger.get("core_stats") or {}).get("hp_generation")),
        "resource_progression": bool(ledger.get("resources")),
        "advancement_history": bool(
            levels
            and len(levels) == int(character.get("cl") or 0)
            and advancement.get("event_count") == len(reduced.event_ids)
        ),
        "background_origin": bool(ledger.get("background_origin")),
        "paths_subpaths": _paths_subpaths_semantic_node_proven(ledger),
        "spheres_talents": bool(ledger.get("spheres") and ledger.get("talents")),
        "typed_none": (
            ("equipment" in typed_none or (isinstance(ledger.get("equipment"), list) and bool(ledger.get("equipment"))))
            and ("manuals" in typed_none or bool(ledger.get("training_sources")) or (isinstance(ledger.get("recorded_arts"), list) and bool(ledger.get("recorded_arts"))))
            and ("forged_techniques" in typed_none or (isinstance(ledger.get("forged_techniques"), list) and bool(ledger.get("forged_techniques"))))
            and method_authority_valid
            and foundation_authority_valid
        ),
        "provenance": bool(reduced.provenance),
        "coverage": bool(reduced.capability_coverage),
    }
    expected = set((reduced.validation_profile or {}).get("required_semantic_nodes") or [])
    for node in sorted(expected):
        if not required.get(node, False):
            finding = {"code": "PROJECTION_REQUIRED_FIELD_AUTHORITY_MISSING", "pointer": f"/semantic/{node}", "message": "A required ADVANCEMENT_READY semantic node is absent or unproven."}
            if node in {"identity", "owner_selections"}:
                finding["authority_checks"] = {
                    "character_name_present": bool(character.get("name")),
                    "character_species_present": bool(character.get("species")),
                    "full_snapshot_valid": snapshot_valid,
                    "ledger_snapshot_binding_valid": snapshot_binding_valid,
                    "canonical_project_identity_matches": choice_snapshot.get("canonical_project_id") == character.get("character_id"),
                    "typed_locks_present": bool(choice_snapshot.get("typed_locks")),
                }
            diagnostics.append(finding)
    if packets.get("schema_version") != "TianxiaFoundry.RulesSelectionPackets.v2" or len(packets.get("packets") or []) != len(reduced.event_ids):
        diagnostics.append({"code": "PROJECTION_RULES_PACKETS_INCOMPLETE", "pointer": "/rules_selection_packets", "message": "The v3 rules-selection packets do not cover the complete canonical event stream."})
    title_diagnostic = _title_authority_diagnostic(ledger, packets)
    if title_diagnostic is not None:
        diagnostics.append(title_diagnostic)
    later = ledger.get("later_stage_readiness") or {}
    for stage in ("character_sheet", "gm_screen", "combat"):
        if (later.get(stage) or {}).get("status") != "NOT_ATTEMPTED":
            diagnostics.append({"code": "PROJECTION_LATER_STAGE_STATUS_INVALID", "pointer": f"/later_stage_readiness/{stage}", "message": "Later-stage work must remain NOT_ATTEMPTED at C2A-R.1."})
    return diagnostics


def _paths_subpaths_semantic_node_proven(ledger: dict[str, Any]) -> bool:
    """Prove Path authority even when the first Subpath milestone is pending."""

    path_selections = ledger.get("path_selections")
    subpaths = ledger.get("subpaths")
    if not isinstance(path_selections, list) or not path_selections:
        return False
    if isinstance(subpaths, list) and subpaths:
        return True
    if subpaths != []:
        return False
    authority = ledger.get("subpath_authority")
    character = ledger.get("character") or {}
    return (
        isinstance(authority, dict)
        and authority.get("status") == "NOT_YET_DUE"
        and authority.get("first_selection_cl") == 3
        and type(character.get("cl")) is int
        and 0 < character["cl"] < authority["first_selection_cl"]
        and authority.get("selected_path_ids") == [
            row.get("path_id") for row in path_selections
        ]
    )


def _stage_aware_coverage(ledger: dict[str, Any], packets: dict[str, Any], reduced: Any) -> dict[str, Any]:
    mappings = reduced.provenance
    destination_coverage = sorted({pointer for item in mappings.values() for pointer in item.get("destination_pointers", [])})
    required_nodes = list((reduced.validation_profile or {}).get("required_semantic_nodes") or [])
    return {
        "schema_version": "TianxiaFoundry.ProjectionCoverage.v2",
        "validation_profile": "ADVANCEMENT_READY",
        "readiness": deepcopy(reduced.readiness),
        "required_semantic_nodes": [{"node": node, "state": "PROVEN"} for node in required_nodes],
        "semantic_provenance_entry_count": len(mappings),
        "destination_coverage": destination_coverage,
        "rules_selection_packet_count": len(packets.get("packets") or []),
        "record_capability_coverage": deepcopy(reduced.capability_coverage),
        "later_stage_status": deepcopy(ledger.get("later_stage_readiness") or {}),
        "required_provenance_complete": True,
        "unproven_required_nodes": [],
        "blocked_required_sections": [],
    }


class ProjectionService:
    def __init__(self, db: Database, *, factory_root: Path | None = None):
        self.db = db
        self.projects = ProjectStore(db)
        self.registry = SchemaRegistry(db.settings.root_dir)
        self.reducer = EffectiveStateReducer(self.registry)
        self.factory_root = factory_root.resolve() if factory_root else None
        # Raw ``project_locked_records`` rows bound by non-Sphere authority
        # events, captured by the most recent ``_inputs`` load for the bridge.
        self._last_locked_target_rows: dict[str, dict[str, Any]] = {}

    def _resolved_artifact_path(
        self,
        project_id: str,
        projection_id: str,
        artifact_name: str,
        stored_path: str,
    ) -> Path:
        """Resolve a sealed artifact after a supported data-root relocation."""
        stored = Path(stored_path)
        try:
            if stored.is_file():
                return stored
        except OSError:
            # A foreign Windows absolute path is one invalid filename on
            # POSIX and may exceed NAME_MAX before existence can be checked.
            pass
        generated = (
            self.db.settings.data_dir
            / "projects"
            / project_id
            / "projections"
            / projection_id
            / "generated"
        ).resolve()
        candidate = (generated / artifact_name).resolve()
        if candidate.parent != generated:
            raise FoundryError(
                "PROJECTION_ARTIFACT_PATH_INVALID",
                "The sealed projection artifact path is outside the current project projection directory.",
                details={"artifact_name": artifact_name},
            )
        return candidate

    def _factory_root(self) -> Path:
        if self.factory_root and self.factory_root.exists():
            return self.factory_root
        config_path = self.db.settings.vendor_dir / "factory_adapter.json"
        if config_path.is_file():
            config = json.loads(config_path.read_text(encoding="utf-8"))
            configured = Path(config.get("factory_root", ""))
            if configured.is_dir():
                return configured.resolve()
        raise FoundryError("PROJECTION_FACTORY_NOT_CONFIGURED", "A copied HF05ZVK-R1H Factory root is required for ledger schema validation.")

    def _ledger_schema_path(self) -> Path:
        path = self._factory_root() / "04_SCHEMAS" / "character_master_ledger.schema.json"
        if not path.is_file():
            raise FoundryError("PROJECTION_FACTORY_SCHEMA_MISSING", "The copied Factory ledger schema was not found.", details={"path": str(path)})
        return path

    def _ledger_schema(self) -> dict[str, Any]:
        return json.loads(self._ledger_schema_path().read_text(encoding="utf-8"))

    @staticmethod
    def _event_string_values(value: Any) -> set[str]:
        values: set[str] = set()
        if isinstance(value, str):
            values.add(value)
        elif isinstance(value, list):
            for item in value:
                values.update(ProjectionService._event_string_values(item))
        elif isinstance(value, dict):
            for item in value.values():
                values.update(ProjectionService._event_string_values(item))
        return values

    @staticmethod
    def _content_binding_tuple(binding: Any) -> tuple[str, str, str, str] | None:
        if not isinstance(binding, dict):
            return None
        values = tuple(binding.get(key) for key in ("record_hash", "pack_id", "pack_version", "pack_hash"))
        if any(not isinstance(value, str) or not value for value in values):
            return None
        return values  # type: ignore[return-value]

    @staticmethod
    def _binding_matches_record(record: Any, binding: Any) -> bool:
        if not isinstance(record, dict):
            return False
        record_binding = record.get("content_binding")
        expected = ProjectionService._content_binding_tuple(binding)
        actual = ProjectionService._content_binding_tuple({
            "record_hash": record.get("record_hash"),
            **(record_binding if isinstance(record_binding, dict) else {}),
        })
        return expected is not None and actual == expected

    @staticmethod
    def _binding_matches_raw_row(raw_record: Any, raw_row: dict[str, Any], binding: Any) -> bool:
        if not isinstance(raw_record, dict) or raw_record.get("record_id") != raw_row.get("record_id"):
            return False
        record_binding = raw_record.get("content_binding")
        if not isinstance(record_binding, dict):
            return False
        if (
            raw_record.get("record_hash") != raw_row.get("record_hash")
            or record_binding.get("pack_id") != raw_row.get("pack_id")
            or record_binding.get("pack_version") != raw_row.get("pack_version")
        ):
            return False
        return ProjectionService._content_binding_tuple({
            "record_hash": raw_row.get("record_hash"),
            "pack_id": raw_row.get("pack_id"),
            "pack_version": raw_row.get("pack_version"),
            "pack_hash": record_binding.get("pack_hash"),
        }) == ProjectionService._content_binding_tuple(binding)

    @staticmethod
    def _binding_is_in_content_lock(project: dict[str, Any], binding: Any) -> bool:
        expected = ProjectionService._content_binding_tuple(binding)
        if expected is None:
            return False
        _record_hash, pack_id, pack_version, pack_hash = expected
        return any(
            isinstance(pack, dict)
            and pack.get("pack_id") == pack_id
            and pack.get("version") == pack_version
            and pack.get("content_hash") == pack_hash
            for pack in (project.get("content_lock") or {}).get("packs", [])
        )

    @staticmethod
    def _select_event_bound_record(
        *,
        current_record: dict[str, Any] | None,
        raw_record: dict[str, Any],
        raw_row: dict[str, Any],
        event_bindings: list[Any],
        project: dict[str, Any],
        lock_proof_verified: bool,
    ) -> dict[str, Any] | None:
        """Prefer reconstructed authority, with a proof-bound historical fallback."""
        if not event_bindings:
            return current_record if current_record is not None else raw_record
        if current_record is not None and all(
            ProjectionService._binding_matches_record(current_record, binding)
            for binding in event_bindings
        ):
            return current_record
        if (
            not lock_proof_verified
            or not all(ProjectionService._binding_matches_raw_row(raw_record, raw_row, binding) for binding in event_bindings)
            or not all(ProjectionService._binding_is_in_content_lock(project, binding) for binding in event_bindings)
        ):
            return current_record
        return raw_record

    @staticmethod
    def _normalize_historical_subpath_owner(
        *,
        record: dict[str, Any],
        current_record: dict[str, Any] | None,
        raw_row: dict[str, Any],
        events: list[dict[str, Any]],
        project: dict[str, Any],
        lock_proof_verified: bool,
    ) -> dict[str, Any]:
        """Project a legacy Subpath owner only from matching sealed evidence."""
        if not lock_proof_verified or record.get("content_type") != "subpath":
            return record
        if record.get("owning_path_id") is not None or record.get("parent_path_id") is not None:
            return record
        authority = (
            (record.get("compatibility") or {})
            .get("factory", {})
            .get("stage2_authority")
            or {}
        )
        owner_path_id = authority.get("parent_path_id")
        if (
            authority.get("authority_complete") is not True
            or not isinstance(owner_path_id, str)
            or not owner_path_id
            or "subpath_acquisition" not in (authority.get("allowed_kinds") or [])
            or not isinstance(record.get("dependencies"), list)
            or owner_path_id not in record["dependencies"]
        ):
            return record
        if not isinstance(current_record, dict):
            return record
        if (
            current_record.get("record_id") != record.get("record_id")
            or current_record.get("content_type") != "subpath"
            or current_record.get("owning_path_id") != owner_path_id
            or current_record.get("parent_path_id") != owner_path_id
        ):
            return record
        matching_events = [
            event
            for event in events
            if (event.get("subject") or {}).get("record_id") == record.get("record_id")
        ]
        if len(matching_events) != 1:
            return record
        event = matching_events[0]
        if (
            (event.get("subject") or {}).get("content_type") != "subpath"
            or (event.get("advancement") or {}).get("kind") != "subpath_acquisition"
            or not ProjectionService._binding_matches_raw_row(
                record,
                raw_row,
                event.get("content_binding"),
            )
            or not ProjectionService._binding_is_in_content_lock(project, event.get("content_binding"))
        ):
            return record
        evidence = event.get("source_evidence")
        if (
            not isinstance(evidence, list)
            or not evidence
            or any(
                not isinstance(item, dict)
                or any(not isinstance(item.get(key), str) or not item.get(key) for key in ("source_id", "source_hash", "source_path"))
                for item in evidence
            )
        ):
            return record
        outputs = ((event.get("advancement") or {}).get("calculation") or {}).get("outputs") or {}
        if outputs.get("record_id") != record.get("record_id"):
            return record
        normalized = deepcopy(record)
        normalized["owning_path_id"] = owner_path_id
        normalized["parent_path_id"] = owner_path_id
        return normalized

    def _inputs(
        self,
        project_id: str,
        *,
        private_record_resolver: Callable[[Any, str, str], dict[str, Any] | None] | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, dict[str, Any]], str]:
        """Load only event-referenced records while streaming the exact full-lock input hash."""
        envelope = self.projects.get_project(project_id)
        project = deepcopy(envelope["project"])
        # Project identity and revision are server-owned envelope fields. The
        # working name is display content only and must never substitute for ID.
        for key in ("project_id", "revision", "working_name"):
            if key in envelope:
                project[key] = deepcopy(envelope[key])
        events = self.projects.timeline(project_id)
        referenced = set().union(*(self._event_string_values(event) for event in events)) if events else set()
        referenced_record_ids = {
            event.get("subject", {}).get("record_id")
            for event in events
            if isinstance(event.get("subject"), dict) and isinstance(event["subject"].get("record_id"), str)
        }
        # Subpath-granted features are referenced by the authenticated
        # calculation output rather than as independent advancement subjects.
        # They are still required locked-record inputs for capability coverage
        # and must be loaded from the same immutable snapshot.
        for event in events:
            advancement = event.get("advancement")
            calculation = advancement.get("calculation") if isinstance(advancement, dict) else None
            inputs = calculation.get("inputs") if isinstance(calculation, dict) else None
            if (
                isinstance(advancement, dict)
                and advancement.get("kind") == "training_source_access"
                and isinstance(inputs, dict)
                and isinstance(inputs.get("target_record_ids"), list)
            ):
                referenced_record_ids.update(
                    target_record_id
                    for target_record_id in inputs["target_record_ids"]
                    if isinstance(target_record_id, str)
                )
            outputs = (
                (calculation.get("outputs") or {})
                if isinstance(calculation, dict)
                else {}
            )
            if isinstance(advancement, dict) and advancement.get("kind") == "subpath_acquisition":
                granted = outputs.get("granted_feature_record_ids") or []
                referenced_record_ids.update(record_id for record_id in granted if isinstance(record_id, str))
            # A level event's subject is only the representative feature; the
            # calculation lists every feature the Path grants at that level and
            # the sheet renders all of them from the same immutable snapshot.
            automatic = outputs.get("automatic_feature_record_ids") or []
            referenced_record_ids.update(record_id for record_id in automatic if isinstance(record_id, str))
        event_bindings_by_record_id: dict[str, list[Any]] = {}
        events_by_record_id: dict[str, list[dict[str, Any]]] = {}
        # Non-Sphere authority events (Method access) bind a complete immutable
        # target set whose members are exact ``project_locked_records`` rows.
        # Their subject record therefore has two legitimate representations:
        # the proof-bound registry projection used by ``method_acquisition``
        # and the raw locked row the authority service actually bound.  Keep
        # the raw rows for those subjects so the bridge validates each event
        # against the representation its own bindings name.
        target_set_record_ids: set[str] = set()
        locked_target_rows: dict[str, dict[str, Any]] = {}
        for event in events:
            subject = event.get("subject")
            if isinstance(subject, dict) and isinstance(subject.get("record_id"), str):
                event_bindings_by_record_id.setdefault(subject["record_id"], []).append(event.get("content_binding"))
                events_by_record_id.setdefault(subject["record_id"], []).append(event)
                binding = event.get("content_binding")
                if isinstance(binding, dict) and binding.get("pack_id") == "project.locked.target-set":
                    target_set_record_ids.add(subject["record_id"])
        background_event_record_ids = {
            event.get("subject", {}).get("record_id")
            for event in events
            if event.get("advancement", {}).get("kind") in {
                "background_sphere_acquisition",
                "background_talent_acquisition",
            }
            and isinstance(event.get("subject", {}).get("record_id"), str)
        }
        authority_record_ids = {
            record_id
            for record_id in referenced_record_ids
            if record_id.startswith(("METHOD-", "tianxia.path.", "tianxia.background.", "tianxia.background_", "tianxia.origin_insight."))
            or (
                record_id.startswith(("tianxia.subpath.", "tianxia.tradition.", "ancient_", "FOUNDATION_"))
                and ".feature." not in record_id
            )
            or record_id in background_event_record_ids
        }
        records: dict[str, dict[str, Any]] = {}
        locked_record_json: dict[str, str] = {}
        with self.db.connection() as conn:
            # Foundation IDs are source-owned stable IDs and cannot be
            # recognized safely by a namespace prefix.  The exact immutable
            # snapshot row is the authority boundary, so use its typed
            # content_type to route arbitrary Foundation IDs through the
            # proof-bound NS1R projection below.  Without this, materialized
            # Foundation events can pass Stage 2 while the final projector
            # feeds the pre-typed snapshot row to the authority validator.
            snapshot_foundation_ids: set[str] = set()
            referenced_ids = sorted(referenced_record_ids)
            # Keep this typed-ID probe bounded to event-referenced rows.  A
            # project snapshot can contain hundreds of megabytes of catalog
            # material, but arbitrary Foundation routing needs only the exact
            # selected rows to establish its authority class.
            for start in range(0, len(referenced_ids), 400):
                chunk = referenced_ids[start:start + 400]
                if not chunk:
                    continue
                placeholders = ",".join("?" for _ in chunk)
                for row in conn.execute(
                    f"SELECT record_id,record_json FROM project_locked_records WHERE project_id=? AND record_id IN ({placeholders})",
                    (project_id, *chunk),
                ):
                    if json.loads(row["record_json"]).get("content_type") == "foundation":
                        snapshot_foundation_ids.add(row["record_id"])
            authority_record_ids.update(referenced_record_ids & snapshot_foundation_ids)
            authority_proof_verified = bool(authority_record_ids)
            if authority_proof_verified:
                self.projects.project_lock_proof(conn, project_id)

            def resolve_record_after_proof(record_id: str) -> dict[str, Any] | None:
                if record_id.startswith("METHOD-"):
                    # The event commits the derivation version. A revised
                    # request or today's default must never rewrite replay.
                    return self.projects._resolve_event_bound_method_after_proof(
                        conn, project_id, record_id, event_bindings_by_record_id.get(record_id, []),
                    )
                if private_record_resolver is not None and record_id.startswith("tianxia.path."):
                    private_record = private_record_resolver(conn, project_id, record_id)
                    if private_record is not None:
                        return private_record
                record = self.projects._resolve_locked_record_after_proof(conn, project_id, record_id)
                if isinstance(record, dict) and record.get("content_type") == "foundation":
                    return self.projects._resolve_event_bound_foundation_after_proof(
                        conn, project_id, record_id, event_bindings_by_record_id.get(record_id, []),
                    )
                return record

            for row in conn.execute(
                "SELECT record_id,pack_id,pack_version,record_hash,record_json FROM project_locked_records WHERE project_id=? ORDER BY record_id",
                (project_id,),
            ):
                locked_record_json[row["record_id"]] = row["record_json"]
                if row["record_id"] in target_set_record_ids:
                    locked_target_rows[row["record_id"]] = {
                        "record": json.loads(row["record_json"]),
                        "row": {
                            "record_id": row["record_id"],
                            "pack_id": row["pack_id"],
                            "pack_version": row["pack_version"],
                            "record_hash": row["record_hash"],
                        },
                    }
                if row["record_id"] in referenced_record_ids:
                    raw_record = json.loads(row["record_json"])
                    if authority_proof_verified and row["record_id"] in background_event_record_ids:
                        current_record = self.projects._resolve_project_locked_background_content_after_proof(
                            conn, project_id, row["record_id"]
                        ) or resolve_record_after_proof(row["record_id"])
                    else:
                        current_record = (
                            resolve_record_after_proof(row["record_id"])
                            if authority_proof_verified and row["record_id"] in authority_record_ids
                            else raw_record
                        )
                    record = self._select_event_bound_record(
                        current_record=current_record,
                        raw_record=raw_record,
                        raw_row={
                            "record_id": row["record_id"],
                            "pack_id": row["pack_id"],
                            "pack_version": row["pack_version"],
                            "record_hash": row["record_hash"],
                        },
                        event_bindings=event_bindings_by_record_id.get(row["record_id"], []),
                        project=project,
                        lock_proof_verified=authority_proof_verified,
                    )
                    if record is raw_record:
                        record = self._normalize_historical_subpath_owner(
                            record=record,
                            current_record=current_record,
                            raw_row={
                                "record_id": row["record_id"],
                                "pack_id": row["pack_id"],
                                "pack_version": row["pack_version"],
                                "record_hash": row["record_hash"],
                            },
                            events=events_by_record_id.get(row["record_id"], []),
                            project=project,
                            lock_proof_verified=authority_proof_verified,
                        )
                    if record is not None:
                        records[row["record_id"]] = record
                    if record is not None and authority_proof_verified and row["record_id"] in authority_record_ids:
                        locked_record_json[row["record_id"]] = canonical_json(record)
            # Some authenticated non-sphere records, notably the exact Method
            # selected during normal creation, are intentionally not HF2 rows.
            # Prove the complete immutable project lock before reconstructing
            # those deterministic projections; never make the projector a live
            # catalog lookup boundary.
            for record_id in sorted(referenced_record_ids - records.keys()):
                if authority_proof_verified and record_id in background_event_record_ids:
                    projected = self.projects._resolve_project_locked_background_content_after_proof(
                        conn, project_id, record_id
                    ) or resolve_record_after_proof(record_id)
                else:
                    projected = (
                        resolve_record_after_proof(record_id)
                        if authority_proof_verified
                        else self.projects._resolve_locked_record(conn, project_id, record_id)
                    )
                if projected is not None:
                    records[record_id] = projected
                    locked_record_json[record_id] = canonical_json(projected)
        digest = hashlib.sha256()
        digest.update(b'{"events":')
        digest.update(canonical_json(events).encode("utf-8"))
        digest.update(b',"locked_records":{')
        for index, record_id in enumerate(sorted(locked_record_json)):
            if index:
                digest.update(b",")
            digest.update(canonical_json(record_id).encode("utf-8"))
            digest.update(b":")
            digest.update(locked_record_json[record_id].encode("utf-8"))
        digest.update(b'},"project":')
        digest.update(canonical_json(project).encode("utf-8"))
        digest.update(b"}")
        self._last_locked_target_rows = locked_target_rows
        return project, events, records, digest.hexdigest()

    @staticmethod
    def _coverage(ledger: dict[str, Any], packets: dict[str, Any], provenance: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
        required = list(schema.get("required", []))
        sections: dict[str, dict[str, Any]] = {}
        totals = {"required": len(required), "projected": 0, "explicit_none": 0, "blocked": 0, "unproven": 0}
        for key in schema.get("properties", {}):
            exists = key in ledger
            value = ledger.get(key)
            leaves = _leaf_pointers(value, f"/{key}") if exists else []
            missing_provenance = [p for p in leaves if f"/ledger{p}" not in provenance]
            if not exists:
                state = "blocked" if key in required else "not_projected_optional"
            elif value is None or value == [] or value == {}:
                state = "explicit_none"
            else:
                state = "projected"
            if state in totals:
                totals[state] += 1
            if missing_provenance:
                totals["unproven"] += len(missing_provenance)
            sections[key] = {
                "required": key in required,
                "state": state,
                "leaf_count": len(leaves),
                "unproven_leaf_count": len(missing_provenance),
                "unproven_pointers": missing_provenance,
            }
        packet_leaves = _leaf_pointers(packets, "")
        packet_missing = [p for p in packet_leaves if f"/rules_selection_packets{p}" not in provenance]
        return {
            "schema_version": "TianxiaFoundry.ProjectionCoverage.v1",
            "factory_schema": schema.get("$id") or "HF05ZVK-R1F.character_master_ledger",
            "totals": totals,
            "sections": sections,
            "rules_selection_packets": {
                "leaf_count": len(packet_leaves),
                "unproven_leaf_count": len(packet_missing),
                "unproven_pointers": packet_missing,
            },
            "required_provenance_complete": totals["blocked"] == 0 and totals["unproven"] == 0 and not packet_missing,
        }

    def _build_for_character_creation(
        self,
        project_id: str,
        *,
        stage2_service: Any,
        force: bool = False,
        choice_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build with delegated Path authority only through the active Stage 2 facade."""
        resolver = getattr(stage2_service, "_resolve_record_after_proof", None)
        if not callable(resolver):
            return self.build(project_id, force=force, choice_snapshot=choice_snapshot)
        return self._build(
            project_id,
            force=force,
            choice_snapshot=choice_snapshot,
            private_record_resolver=resolver,
        )

    def build(self, project_id: str, *, force: bool = False, choice_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._build(project_id, force=force, choice_snapshot=choice_snapshot)

    def _build(
        self,
        project_id: str,
        *,
        force: bool = False,
        choice_snapshot: dict[str, Any] | None = None,
        private_record_resolver: Callable[[Any, str, str], dict[str, Any] | None] | None = None,
    ) -> dict[str, Any]:
        project, events, records, input_hash = self._inputs(
            project_id,
            private_record_resolver=private_record_resolver,
        )
        if not events:
            raise FoundryError("PROJECTION_EVENT_STREAM_EMPTY", "A project with no committed canonical events cannot be projected.")
        content_lock_hash = sha256_json(project["content_lock"])
        head_hash = events[-1]["event_hash"]
        choice_snapshot = deepcopy(choice_snapshot) if choice_snapshot is not None else materialize_choice_snapshot(project)
        if (
            not valid_choice_snapshot(choice_snapshot)
            or choice_snapshot.get("canonical_project_id") != project_id
        ):
            raise FoundryError("PROJECTION_TYPED_CHOICE_SNAPSHOT_INVALID", "Projection requires one valid typed choice snapshot bound to the canonical project identity.")
        projection_identity = {"project_id": project_id, "revision": project["revision"], "input_hash": input_hash, "typed_choice_snapshot_sha256": choice_snapshot["snapshot_sha256"]}
        if any(len(event.get("advancement", {}).get("calculation", {}).get("outputs", {}).get("resources_after") or {}) > 1 for event in events):
            # Keep earlier primary-only artifacts intact and create a versioned
            # successor when the authoritative event stream contains more pools.
            projection_identity["resource_projection_revision"] = "all-authoritative-pools.v1"
        projection_id = sha256_json(projection_identity)
        generated_dir = self.db.settings.data_dir / "projects" / project_id / "projections" / projection_id / "generated"
        with self.db.connection() as conn:
            existing = conn.execute("SELECT status,generated_dir FROM projection_runs WHERE projection_id=?", (projection_id,)).fetchone()
        if existing and existing["status"] == "READY" and not force:
            return self.status(project_id, projection_id=projection_id)
        if generated_dir.parent.exists() and force:
            shutil.rmtree(generated_dir.parent)
        generated_dir.mkdir(parents=True, exist_ok=True)
        diagnostics: list[dict[str, Any]] = []
        try:
            reduced = self.reducer.reduce(
                project=project,
                events=events,
                locked_records=records,
                choice_snapshot=choice_snapshot,
                locked_target_rows=self._last_locked_target_rows,
                factory_root=self._factory_root(),
            )
            # The complete immutable catalog snapshot is large and no longer needed
            # after deterministic reduction. Release it before artifact persistence and
            # status readback so clean-root imports remain bounded on owner hardware.
            del records
            gc.collect()
            ledger = reduced.ledger
            packets = reduced.rules_selection_packets
            schema = self._ledger_schema()
            if reduced.event_schema_version == "TianxiaFoundry.AdvancementEvent.v3":
                diagnostics.extend(_stage_aware_diagnostics(ledger, packets, reduced))
                coverage = _stage_aware_coverage(ledger, packets, reduced)
                provenance_schema = "TianxiaFoundry.ProjectionProvenanceMap.v2"
            else:
                diagnostics.extend(_schema_diagnostics(ledger, schema, schema_path=self._ledger_schema_path()))
                coverage = self._coverage(ledger, packets, reduced.provenance, schema)
                if not coverage["required_provenance_complete"]:
                    diagnostics.append({
                        "code": "PROJECTION_PROVENANCE_INCOMPLETE",
                        "pointer": "/",
                        "message": "One or more required sections or leaves lack stable provenance.",
                        "coverage_totals": coverage["totals"],
                    })
                provenance_schema = "TianxiaFoundry.ProjectionProvenanceMap.v1"
            diagnostics.extend(_placeholder_findings(ledger, "/ledger"))
            diagnostics.extend(_placeholder_findings(packets, "/rules_selection_packets"))
            provenance = {
                "schema_version": provenance_schema,
                "project_id": project_id,
                "project_revision": project["revision"],
                "projection_input_hash": input_hash,
                "event_head_hash": head_hash,
                "selected_record_ids": reduced.selected_record_ids,
                "event_ids": reduced.event_ids,
                "event_schema_version": reduced.event_schema_version,
                "typed_choice_snapshot_sha256": choice_snapshot["snapshot_sha256"],
                "typed_choice_snapshot": deepcopy(choice_snapshot),
                "readiness": deepcopy(reduced.readiness),
                "mappings": {key: reduced.provenance[key] for key in sorted(reduced.provenance)},
            }
            if reduced.project_display_contract is not None:
                provenance["project_display_contract"] = deepcopy(reduced.project_display_contract)
            projection_diagnostics = {
                "schema_version": "TianxiaFoundry.ProjectionDiagnostics.v1",
                "project_id": project_id,
                "project_revision": project["revision"],
                "projection_id": projection_id,
                "input_hash": input_hash,
                "valid": not diagnostics,
                "diagnostics": diagnostics,
                "operations_applied": reduced.operations_applied,
                "event_schema_version": reduced.event_schema_version,
                "readiness": deepcopy(reduced.readiness),
                "later_stage_diagnostics": deepcopy((ledger.get("later_stage_readiness") or {})) if reduced.event_schema_version.endswith(".v3") else {},
            }
            documents = {
                "Character_Master_Ledger.json": ledger,
                "Rules_Selection_Packets.json": packets,
                "Projection_Provenance_Map.json": provenance,
                "Projection_Coverage_Report.json": coverage,
                "Projection_Diagnostics.json": projection_diagnostics,
            }
            for name, document in documents.items():
                (generated_dir / name).write_text(canonical_json(document), encoding="utf-8", newline="\n")
            status = "READY" if not diagnostics else "BLOCKED"
            with self.db.transaction() as conn:
                conn.execute("DELETE FROM projection_artifacts WHERE projection_id=?", (projection_id,))
                conn.execute(
                    """INSERT OR REPLACE INTO projection_runs(
                    projection_id,project_id,project_revision,content_lock_hash,event_head_hash,status,generated_dir,
                    ledger_sha256,rules_packets_sha256,provenance_sha256,coverage_sha256,diagnostics_sha256,
                    command5_status,command6_status,created_at,completed_at,diagnostics_json)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        projection_id, project_id, project["revision"], content_lock_hash, head_hash, status, str(generated_dir),
                        sha256_file(generated_dir / "Character_Master_Ledger.json"),
                        sha256_file(generated_dir / "Rules_Selection_Packets.json"),
                        sha256_file(generated_dir / "Projection_Provenance_Map.json"),
                        sha256_file(generated_dir / "Projection_Coverage_Report.json"),
                        sha256_file(generated_dir / "Projection_Diagnostics.json"),
                        "NOT_RUN", "NOT_RUN", utcnow(), utcnow(), canonical_json(diagnostics),
                    ),
                )
                for name in documents:
                    path = generated_dir / name
                    conn.execute(
                        "INSERT INTO projection_artifacts(projection_id,artifact_name,path,sha256,bytes,media_type) VALUES(?,?,?,?,?,?)",
                        (projection_id, name, str(path), sha256_file(path), path.stat().st_size, ARTIFACT_MEDIA[name]),
                    )
                conn.execute(
                    "UPDATE projects SET compatibility_projection_status=? WHERE project_id=?",
                    ("COMMAND_5_INPUT_READY" if status == "READY" else "PROJECTION_BLOCKED", project_id),
                )
            if diagnostics:
                raise FoundryError("PROJECTION_BLOCKED", "Projection produced blocked diagnostics and is not eligible for Factory compilation.", details={"projection_id": projection_id, "diagnostics": diagnostics})
            return self.status(project_id, projection_id=projection_id)
        except FoundryError:
            raise
        except Exception as exc:
            with self.db.transaction() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO projection_runs(
                    projection_id,project_id,project_revision,content_lock_hash,event_head_hash,status,generated_dir,
                    command5_status,command6_status,created_at,completed_at,diagnostics_json)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (projection_id, project_id, project["revision"], content_lock_hash, head_hash, "FAILED", str(generated_dir), "NOT_RUN", "NOT_RUN", utcnow(), utcnow(), canonical_json([{"code": "PROJECTION_INTERNAL_ERROR", "message": str(exc)}])),
                )
            raise

    def status(self, project_id: str, *, projection_id: str | None = None) -> dict[str, Any]:
        self.projects.get_project(project_id)
        with self.db.connection() as conn:
            if projection_id:
                row = conn.execute("SELECT * FROM projection_runs WHERE project_id=? AND projection_id=?", (project_id, projection_id)).fetchone()
            else:
                row = conn.execute("SELECT * FROM projection_runs WHERE project_id=? ORDER BY created_at DESC LIMIT 1", (project_id,)).fetchone()
            if not row:
                return {"project_id": project_id, "status": "NOT_BUILT", "eligible_for_command5": False}
            artifacts = [dict(r) for r in conn.execute("SELECT artifact_name,path,sha256,bytes,media_type FROM projection_artifacts WHERE projection_id=? ORDER BY artifact_name", (row["projection_id"],))]
        integrity: list[dict[str, Any]] = []
        for item in artifacts:
            path = self._resolved_artifact_path(
                project_id,
                row["projection_id"],
                item["artifact_name"],
                item["path"],
            )
            actual = sha256_file(path) if path.is_file() else None
            integrity.append({"artifact_name": item["artifact_name"], "expected_sha256": item["sha256"], "actual_sha256": actual, "valid": actual == item["sha256"]})
        return {
            "project_id": project_id,
            "projection_id": row["projection_id"],
            "project_revision": row["project_revision"],
            "status": row["status"],
            "eligible_for_command5": row["status"] == "READY" and all(x["valid"] for x in integrity),
            "event_head_hash": row["event_head_hash"],
            "content_lock_hash": row["content_lock_hash"],
            "command5_status": row["command5_status"],
            "command6_status": row["command6_status"],
            "diagnostics": json.loads(row["diagnostics_json"]),
            "artifacts": artifacts,
            "artifact_integrity": integrity,
        }

    def artifact(self, project_id: str, artifact_name: str) -> Path:
        if artifact_name not in ARTIFACT_MEDIA:
            raise FoundryError("PROJECTION_ARTIFACT_NOT_ALLOWED", "That projection artifact is not available.", status_code=404)
        with self.db.connection() as conn:
            row = conn.execute(
                """SELECT a.path,a.sha256,r.projection_id FROM projection_artifacts a JOIN projection_runs r ON r.projection_id=a.projection_id
                WHERE r.project_id=? AND a.artifact_name=? ORDER BY r.created_at DESC LIMIT 1""",
                (project_id, artifact_name),
            ).fetchone()
        if not row:
            raise FoundryError("PROJECTION_ARTIFACT_NOT_FOUND", "Build the projection before downloading this artifact.", status_code=404)
        path = self._resolved_artifact_path(
            project_id,
            row["projection_id"],
            artifact_name,
            row["path"],
        )
        if not path.is_file() or sha256_file(path) != row["sha256"]:
            raise FoundryError("PROJECTION_ARTIFACT_TAMPERED", "The generated artifact is missing or differs from the sealed projection hash.", details={"artifact_name": artifact_name})
        return path
