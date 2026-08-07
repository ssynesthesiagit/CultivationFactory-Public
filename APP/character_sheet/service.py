from __future__ import annotations

import json
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.core import Database, FoundryError, canonical_json, sha256_file, sha256_json
from project_store.service import ProjectStore
from projector.service import ProjectionService


_DISPLAY_CONTRACT_NAME = "Tianxia_Fire_Qi_Character_Sheet_Display_Contract_R1.json"
_READINESS_PROFILE_NAME = "Tianxia_Character_Sheet_Readiness_Profile_R1.json"
_OWNER_SHEET_FILENAME = "Tianxia_Owner_Character_Sheet_v1.json"

_FORBIDDEN_DISPLAY_TOKENS = (
    "[object Object]",
    "TBD",
    "TODO",
    "placeholder",
    "lorem ipsum",
)

_LEGACY_REQUIRED_GM_SECTIONS = (
    "character",
    "core_stats",
    "background_origin",
    "path_selections",
    "spheres",
    "talents",
    "resources",
    "actions",
)


class CharacterSheetService:
    """Deterministic owner-facing character read model.

    Mechanical state comes only from the canonical project, committed events,
    and the sealed projector artifacts. Source-backed display prose is governed
    by a small checksummed display contract and never promoted to execution
    authority.
    """

    def __init__(self, db: Database):
        self.db = db
        self.projects = ProjectStore(db)
        self.projections = ProjectionService(db)

    @property
    def _contracts_dir(self) -> Path:
        return Path(__file__).resolve().parent / "contracts"

    @staticmethod
    def _user_locks(project: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for item in project.get("user_locks") or []:
            if isinstance(item, dict) and isinstance(item.get("field"), str):
                result[item["field"]] = item.get("value")
        return result

    @staticmethod
    def _owner_lock_rows(project: dict[str, Any]) -> list[dict[str, Any]]:
        rows = [dict(item) for item in project.get("user_locks") or [] if isinstance(item, dict)]
        rows.sort(key=lambda item: (int(item.get("created_revision") or 0), str(item.get("lock_id") or "")))
        return rows

    @staticmethod
    def _verify_sealed_json(path: Path, *, expected_schema: str, error_prefix: str) -> tuple[dict[str, Any], str]:
        if not path.is_file():
            raise FoundryError(f"{error_prefix}_MISSING", f"Required sealed Character Sheet contract is missing: {path.name}")
        sidecar = path.with_suffix(path.suffix + ".sha256")
        if not sidecar.is_file():
            raise FoundryError(f"{error_prefix}_SIDECAR_MISSING", f"Required detached checksum is missing: {sidecar.name}")
        try:
            digest, declared_name = sidecar.read_text(encoding="utf-8").strip().split(None, 1)
            declared_name = declared_name.strip().lstrip("*")
        except ValueError as exc:
            raise FoundryError(f"{error_prefix}_SIDECAR_INVALID", "The detached checksum sidecar is malformed.") from exc
        actual = sha256_file(path)
        if declared_name != path.name or digest.lower() != actual:
            raise FoundryError(
                f"{error_prefix}_STALE",
                "The sealed Character Sheet contract does not match its detached checksum.",
                details={"path": str(path), "expected": digest.lower(), "actual": actual, "declared_name": declared_name},
            )
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != expected_schema:
            raise FoundryError(
                f"{error_prefix}_SCHEMA_UNSUPPORTED",
                "The Character Sheet contract schema is unsupported.",
                details={"expected": expected_schema, "actual": payload.get("schema_version")},
            )
        internal = payload.get("seal_sha256")
        unsigned = dict(payload)
        unsigned.pop("seal_sha256", None)
        calculated = sha256_json(unsigned)
        if not isinstance(internal, str) or internal != calculated:
            raise FoundryError(
                f"{error_prefix}_INTERNAL_SEAL_INVALID",
                "The Character Sheet contract internal seal is invalid.",
                details={"expected": internal, "actual": calculated},
            )
        return payload, actual

    def _display_contract(
        self,
        ledger: dict[str, Any],
        provenance: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        project_contract = provenance.get("project_display_contract")
        if project_contract:
            unsigned = dict(project_contract)
            seal = unsigned.pop("seal_sha256", None)
            snapshot = provenance.get("typed_choice_snapshot") or {}
            if (
                project_contract.get("schema_version") != "TianxiaFoundry.CharacterSheetDisplayContract.v1"
                or project_contract.get("canonical_project_id") != (ledger.get("character") or {}).get("character_id")
                or project_contract.get("typed_choice_snapshot_sha256") != snapshot.get("snapshot_sha256")
                or seal != sha256_json(unsigned)
            ):
                raise FoundryError(
                    "CHARACTER_SHEET_DISPLAY_CONTRACT_STALE",
                    "The project-derived Character Sheet display contract is not bound to the exact typed choice snapshot.",
                )
            return deepcopy(project_contract), sha256_json(project_contract)
        return self._verify_sealed_json(
            self._contracts_dir / _DISPLAY_CONTRACT_NAME,
            expected_schema="TianxiaFoundry.CharacterSheetDisplayContract.v1",
            error_prefix="CHARACTER_SHEET_DISPLAY_CONTRACT",
        )

    def _readiness_profile(self) -> tuple[dict[str, Any], str]:
        return self._verify_sealed_json(
            self._contracts_dir / _READINESS_PROFILE_NAME,
            expected_schema="TianxiaFoundry.CharacterSheetReadinessProfile.v1",
            error_prefix="CHARACTER_SHEET_READINESS_PROFILE",
        )

    def _blueprint(self, project_id: str) -> dict[str, Any] | None:
        with self.db.connection() as conn:
            row = conn.execute(
                """SELECT p.projection_json,p.projection_hash,c.committed_at,c.approved_by
                   FROM stage1_blueprint_heads h
                   JOIN stage1_blueprint_commits c ON c.commit_id=h.commit_id
                   JOIN stage1_blueprint_projections p ON p.commit_id=c.commit_id
                   WHERE h.project_id=?""",
                (project_id,),
            ).fetchone()
        if not row:
            return None
        payload = json.loads(row["projection_json"])
        intent = payload.get("intent_state") or {}
        decisions = intent.get("decisions") or []
        selected: dict[str, list[dict[str, Any]]] = {}
        for decision in decisions:
            if not isinstance(decision, dict):
                continue
            records = decision.get("record_snapshots") or []
            normalized_records: list[dict[str, Any]] = []
            for record in records:
                if not isinstance(record, dict):
                    continue
                choice = record.get("choice_snapshot")
                if isinstance(choice, dict):
                    item = dict(choice)
                    item.setdefault("choice_id", record.get("record_id"))
                    item["authority_snapshot"] = {
                        key: record.get(key)
                        for key in ("record_id", "record_hash", "pack_id", "pack_version", "pack_hash", "choice_snapshot_hash")
                        if record.get(key) is not None
                    }
                    normalized_records.append(item)
                else:
                    normalized_records.append(dict(record))
            selected[str(decision.get("slot_id") or "unknown")] = normalized_records
        return {
            "status": "BLUEPRINT_COMMITTED",
            "projection_hash": row["projection_hash"],
            "committed_at": row["committed_at"],
            "approved_by": row["approved_by"],
            "mechanical_authority": False,
            "selected_records": selected,
            "planner_rationale": intent.get("planner_rationale") or "",
            "authored_notes": intent.get("authored_notes") or [],
        }

    def _compiled_artifacts(self, project_id: str) -> tuple[dict[str, dict[str, Any]] | None, dict[str, Any]]:
        try:
            status = self.projections.status(project_id)
        except FoundryError as exc:
            if exc.code in {"PROJECTION_NOT_FOUND", "PROJECT_NOT_FOUND"}:
                return None, {"status": "NOT_COMPILED", "eligible_for_command5": False}
            raise
        if status.get("status") != "READY":
            return None, status
        names = (
            "Character_Master_Ledger.json",
            "Rules_Selection_Packets.json",
            "Projection_Provenance_Map.json",
            "Projection_Coverage_Report.json",
            "Projection_Diagnostics.json",
        )
        artifacts: dict[str, dict[str, Any]] = {}
        try:
            for name in names:
                artifacts[name] = json.loads(self.projections.artifact(project_id, name).read_text(encoding="utf-8"))
        except (FoundryError, OSError, json.JSONDecodeError):
            return None, status
        return artifacts, status

    @staticmethod
    def _legacy_completed_gm_ready(ledger: dict[str, Any] | None, projection_status: dict[str, Any]) -> bool:
        """Preserve genuinely complete historical v1 export behavior.

        This is deliberately stricter than the legacy eligible_for_command5 bit:
        a stage-aware ledger is never treated as GM-ready, and every historical
        complete section must be materially populated.
        """
        if not ledger or ledger.get("readiness"):
            return False
        if not projection_status.get("eligible_for_command5"):
            return False
        if projection_status.get("command5_status") not in {None, "NOT_RUN", "COMMAND_5_GM_SCREEN_CANDIDATE_READY"}:
            return False
        return all(ledger.get(key) not in (None, "", [], {}) for key in _LEGACY_REQUIRED_GM_SECTIONS)

    @staticmethod
    def _record_ids_required(ledger: dict[str, Any], packets: dict[str, Any]) -> set[str]:
        required = {
            str(packet.get("record_id"))
            for packet in packets.get("packets") or []
            if isinstance(packet, dict)
            and packet.get("record_id")
            and packet.get("advancement_kind") != "non_sphere_method_access"
        }
        for feature in ledger.get("features") or []:
            if isinstance(feature, dict) and feature.get("feature_id"):
                required.add(str(feature["feature_id"]))
        return required

    @staticmethod
    def _build_record_cards(
        ledger: dict[str, Any],
        packets: dict[str, Any],
        contract: dict[str, Any],
        contract_sha256: str,
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
        rules = contract.get("rules") or []
        by_record: dict[str, dict[str, Any]] = {}
        duplicate_ids: list[str] = []
        for rule in rules:
            if not isinstance(rule, dict) or not isinstance(rule.get("record_id"), str):
                raise FoundryError("CHARACTER_SHEET_DISPLAY_MAPPING_INVALID", "A display-contract rule lacks a stable record ID.")
            record_id = rule["record_id"]
            if record_id in by_record:
                duplicate_ids.append(record_id)
            by_record[record_id] = rule
        if duplicate_ids:
            raise FoundryError(
                "CHARACTER_SHEET_DUPLICATE_DISPLAY_MAPPING",
                "A selected record would be rendered more than once.",
                details={"record_ids": sorted(set(duplicate_ids))},
            )

        required = CharacterSheetService._record_ids_required(ledger, packets)
        mapped = set(by_record)
        missing = sorted(required - mapped)
        if missing:
            raise FoundryError(
                "CHARACTER_SHEET_DISPLAY_MAPPING_MISSING",
                "One or more selected records have no sealed Character Sheet display mapping.",
                details={"record_ids": missing},
            )
        unexpected = sorted(mapped - required)
        if unexpected:
            raise FoundryError(
                "CHARACTER_SHEET_DISPLAY_MAPPING_UNSELECTED",
                "The display contract contains a record not selected by this character.",
                details={"record_ids": unexpected},
            )

        packet_by_id = {
            str(packet.get("packet_id")): packet
            for packet in packets.get("packets") or []
            if isinstance(packet, dict) and packet.get("packet_id")
        }
        cards: list[dict[str, Any]] = []
        for record_id in sorted(required):
            rule = by_record[record_id]
            source = rule.get("source") or {}
            if not all(isinstance(source.get(key), str) and source.get(key) for key in ("path", "anchor", "source_hash")):
                raise FoundryError(
                    "CHARACTER_SHEET_DESCRIPTION_UNPROVEN",
                    "A Character Sheet display description lacks exact source identity.",
                    details={"record_id": record_id},
                )
            one_line = rule.get("one_line_description")
            full = rule.get("full_description")
            if not isinstance(one_line, str) or not one_line.strip() or not isinstance(full, str) or not full.strip():
                raise FoundryError(
                    "CHARACTER_SHEET_DESCRIPTION_UNPROVEN",
                    "A Character Sheet display description is missing or empty.",
                    details={"record_id": record_id},
                )
            packet_ids = list((rule.get("acquisition_source") or {}).get("packet_ids") or [])
            absent_packets = sorted(packet_id for packet_id in packet_ids if packet_id not in packet_by_id)
            if absent_packets and (ledger.get("advancement") or {}).get("historical_prefix_preserved") is False:
                acquisition_source = rule.get("acquisition_source") or {}
                matches = [
                    packet
                    for packet in packet_by_id.values()
                    if packet.get("record_id") == record_id
                    and packet.get("advancement_kind") == acquisition_source.get("advancement_kind")
                    and packet.get("target_cl") == acquisition_source.get("target_cl")
                ]
                if len(matches) == 1:
                    # Current project identities necessarily produce new event and
                    # packet hashes. Rebind only by the exact stable record, typed
                    # acquisition kind, and CL; historical packages retain their
                    # sealed packet IDs unchanged.
                    packet_ids = [matches[0]["packet_id"]]
                    absent_packets = []
            if absent_packets:
                raise FoundryError(
                    "CHARACTER_SHEET_PACKET_BINDING_MISSING",
                    "A display mapping refers to a source packet that is not in the canonical projection.",
                    details={"record_id": record_id, "packet_ids": absent_packets},
                )
            capabilities = deepcopy(rule.get("capabilities") or {})
            if capabilities.get("character_sheet") != "SUPPORTED":
                raise FoundryError(
                    "CHARACTER_SHEET_CAPABILITY_UNSUPPORTED",
                    "A selected record is not declared supported for owner-facing Character Sheet display.",
                    details={"record_id": record_id, "capability": capabilities.get("character_sheet")},
                )
            combat = capabilities.get("combat_execution")
            if combat not in {"SUPPORTED", "NOT_APPLICABLE"} and rule.get("display_only_not_execution_authority") is not True:
                raise FoundryError(
                    "CHARACTER_SHEET_FALSE_EXECUTION_CLAIM",
                    "Display prose would be promoted to combat authority without a typed execution definition.",
                    details={"record_id": record_id, "combat_execution": combat},
                )
            acquisition = deepcopy(rule.get("acquisition_source") or {})
            cards.append({
                "record_id": record_id,
                "record_hash": rule.get("record_hash"),
                "display_name": rule.get("display_name"),
                "section": rule.get("section"),
                "subsection": rule.get("subsection"),
                "acquisition_cl": acquisition.get("target_cl"),
                "acquisition_route": acquisition.get("advancement_kind"),
                "source_packet_ids": packet_ids,
                "timing_or_category": rule.get("display_timing_or_category"),
                "one_line_description": one_line.strip(),
                "full_description": full.strip(),
                "full_description_source": rule.get("full_description_source"),
                "source": {
                    "path": source["path"],
                    "anchor": source["anchor"],
                    "sha256": source["source_hash"],
                },
                "stage2_rule_id": rule.get("stage2_rule_id"),
                "display_contract": {
                    "contract_id": contract.get("contract_id"),
                    "contract_sha256": contract_sha256,
                },
                "capabilities": capabilities,
                "display_only_not_execution_authority": bool(rule.get("display_only_not_execution_authority")),
                "combat_execution_note": (
                    "Typed combat execution is available."
                    if combat == "SUPPORTED"
                    else "Combat execution is not yet typed; this description is display-only."
                    if combat != "NOT_APPLICABLE"
                    else "No combat execution definition is applicable."
                ),
            })
        cards.sort(key=lambda item: (
            str(item.get("section") or ""),
            -1 if item.get("acquisition_cl") is None else int(item.get("acquisition_cl")),
            str(item.get("display_name") or "").casefold(),
            item["record_id"],
        ))
        return cards, {card["record_id"]: card for card in cards}

    @staticmethod
    def _skills(core: dict[str, Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        multipliers = core.get("skill_proficiency_multipliers") or {}
        bonuses = core.get("skills") or {}
        sources = core.get("skill_sources") or {}
        ability_map = core.get("skill_ability_map") or {}
        for skill in sorted(set(bonuses) | set(multipliers) | set(sources), key=str.casefold):
            multiplier = int(multipliers.get(skill) or 0)
            rows.append({
                "skill": skill,
                "ability": ability_map.get(skill),
                "bonus": bonuses.get(skill),
                "proficiency": "expertise" if multiplier >= 2 else "proficient" if multiplier == 1 else "untrained",
                "proficiency_multiplier": multiplier,
                "sources": sorted(str(value) for value in sources.get(skill) or []),
            })
        return rows

    @staticmethod
    def _card_groups(cards: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for card in cards:
            groups.setdefault(str(card.get("section") or "other"), []).append(card)
        return {key: groups[key] for key in sorted(groups)}

    @staticmethod
    def _validate_snapshot(snapshot: dict[str, Any], required_record_ids: set[str], profile: dict[str, Any]) -> None:
        diagnostics: list[dict[str, Any]] = []
        readiness = snapshot.get("readiness") or {}
        expected = profile.get("stage_semantics") or {}
        for key, value in expected.items():
            if readiness.get(key) != value:
                diagnostics.append({"code": "CHARACTER_SHEET_READINESS_MISMATCH", "field": key, "expected": value, "actual": readiness.get(key)})
        section_rows = snapshot.get("selected_record_sections") or {}
        cards = [card for section in section_rows.values() for card in (section or [])]
        ids = [card.get("record_id") for card in cards if isinstance(card, dict)]
        if len(ids) != len(set(ids)):
            diagnostics.append({"code": "CHARACTER_SHEET_DUPLICATE_RECORD_PRESENTATION"})
        if set(ids) != required_record_ids:
            diagnostics.append({
                "code": "CHARACTER_SHEET_RECORD_COVERAGE_MISMATCH",
                "missing": sorted(required_record_ids - set(ids)),
                "extra": sorted(set(ids) - required_record_ids),
            })
        for card in cards:
            if not isinstance(card, dict):
                diagnostics.append({"code": "CHARACTER_SHEET_RECORD_CARD_INVALID"})
                continue
            source = card.get("source") or {}
            if not source.get("path") or not source.get("anchor") or not source.get("sha256"):
                diagnostics.append({"code": "CHARACTER_SHEET_DESCRIPTION_UNPROVEN", "record_id": card.get("record_id")})
            capabilities = card.get("capabilities") or {}
            if capabilities.get("combat_execution") not in {"SUPPORTED", "NOT_APPLICABLE"} and not card.get("display_only_not_execution_authority"):
                diagnostics.append({"code": "CHARACTER_SHEET_FALSE_EXECUTION_CLAIM", "record_id": card.get("record_id")})
        typed_none = snapshot.get("explicit_none_systems") or {}
        selected_method = snapshot.get("method") or {}
        method_acquired = (
            selected_method.get("state") == "acquired"
            and bool(selected_method.get("record_id"))
        )
        for name in ("method", "foundation", "manuals", "equipment", "forged_techniques"):
            if name == "method" and method_acquired:
                continue
            row = typed_none.get(name) or {}
            if row.get("state") != "none" or row.get("source_backed") is not True:
                diagnostics.append({"code": "CHARACTER_SHEET_TYPED_NONE_INVALID", "system": name})
        if snapshot.get("later_stage_status", {}).get("gm_screen", {}).get("status") != "NOT_ATTEMPTED":
            diagnostics.append({"code": "CHARACTER_SHEET_FALSE_GM_READINESS"})
        if snapshot.get("later_stage_status", {}).get("combat", {}).get("status") != "NOT_ATTEMPTED":
            diagnostics.append({"code": "CHARACTER_SHEET_FALSE_COMBAT_READINESS"})
        serialized = canonical_json(snapshot)
        for token in _FORBIDDEN_DISPLAY_TOKENS:
            if token.casefold() in serialized.casefold():
                diagnostics.append({"code": "CHARACTER_SHEET_FORBIDDEN_PLACEHOLDER", "token": token})
        if diagnostics:
            raise FoundryError(
                "CHARACTER_SHEET_BUILD_BLOCKED",
                "The owner-facing Character Sheet failed its readiness contract.",
                details={"diagnostics": diagnostics},
            )

    def _snapshot_dir(self, project_id: str, sheet_id: str) -> Path:
        return self.db.settings.data_dir / "character_sheets" / project_id / sheet_id

    def _factory_workspace_status(self, project_id: str) -> dict[str, Any]:
        pointer = self.db.settings.data_dir / "factory_workspaces" / project_id / "current.json"
        if not pointer.is_file():
            return {
                "status": "NOT_ATTEMPTED",
                "gm_authoring": "NOT_ATTEMPTED",
                "command5": "NOT_RUN",
                "command6": "NOT_RUN",
                "gm_export_available": False,
            }
        try:
            payload = json.loads(pointer.read_text(encoding="utf-8"))
            manifest_path = Path(str(payload.get("workspace_path") or "")) / "Workspace_Manifest.json"
            if not manifest_path.is_file() or sha256_file(manifest_path) != payload.get("manifest_sha256"):
                raise ValueError("stale workspace manifest")
        except (OSError, ValueError, json.JSONDecodeError):
            return {
                "status": "STALE",
                "gm_authoring": "STALE",
                "command5": "NOT_RUN",
                "command6": "NOT_RUN",
                "gm_export_available": False,
            }
        candidate_status = "NOT_RUN"
        candidate_details = None
        candidate_pointer = self.db.settings.data_dir / "factory_candidates" / project_id / "current.json"
        if candidate_pointer.is_file():
            try:
                candidate = json.loads(candidate_pointer.read_text(encoding="utf-8"))
                candidate_zip = Path(str(candidate.get("candidate_zip") or ""))
                model_path = Path(str(candidate.get("gm_model_path") or ""))
                if (
                    candidate.get("status") == "GM_MODEL_CANDIDATE_READY"
                    and candidate_zip.is_file()
                    and sha256_file(candidate_zip) == candidate.get("candidate_sha256")
                    and model_path.is_file()
                    and sha256_file(model_path) == candidate.get("gm_model_sha256")
                ):
                    candidate_status = "GM_MODEL_CANDIDATE_READY"
                    candidate_details = {
                        "build_profile": (candidate.get("build_profile") or {}).get("profile_id"),
                        "candidate_sha256": candidate.get("candidate_sha256"),
                        "gm_model_sha256": candidate.get("gm_model_sha256"),
                        "consumer_verification": "NOT_ATTEMPTED",
                    }
                else:
                    candidate_status = "STALE"
            except (OSError, ValueError, json.JSONDecodeError):
                candidate_status = "STALE"
        return {
            "status": payload.get("workspace_status"),
            "workspace_id": payload.get("workspace_id"),
            "workspace_sha256": payload.get("workspace_sha256"),
            "gm_authoring": "COMPLETE_AS_WORKSPACE_INPUT",
            "command5": candidate_status,
            "command5_candidate": candidate_details,
            "command6": "NOT_RUN",
            "gm_screen_consumer_verification": "NOT_ATTEMPTED",
            "gm_export_available": False,
            "eligible_for_later_command5_checkpoint": candidate_status == "NOT_RUN",
            "legacy_command5_eligible": False,
        }

    def _build_snapshot(
        self,
        *,
        project: dict[str, Any],
        artifacts: dict[str, dict[str, Any]],
        projection_status: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        ledger = artifacts["Character_Master_Ledger.json"]
        packets = artifacts["Rules_Selection_Packets.json"]
        provenance = artifacts["Projection_Provenance_Map.json"]
        coverage = artifacts["Projection_Coverage_Report.json"]
        projection_diagnostics = artifacts["Projection_Diagnostics.json"]
        if (ledger.get("readiness") or {}).get("advancement") != "ADVANCEMENT_READY":
            raise FoundryError(
                "CHARACTER_SHEET_ADVANCEMENT_NOT_READY",
                "The deterministic advancement projection must be ADVANCEMENT_READY before the owner-facing sheet can be built.",
                details={"readiness": ledger.get("readiness")},
            )
        if projection_diagnostics.get("valid") is not True:
            raise FoundryError("CHARACTER_SHEET_PROJECTION_BLOCKED", "The advancement projection contains blocking diagnostics.")

        contract, contract_sha = self._display_contract(ledger, provenance)
        profile, profile_sha = self._readiness_profile()
        cards, cards_by_id = self._build_record_cards(ledger, packets, contract, contract_sha)
        required_record_ids = self._record_ids_required(ledger, packets)
        groups = self._card_groups(cards)
        character = deepcopy(ledger.get("character") or {})
        core = deepcopy(ledger.get("core_stats") or {})
        background_origin = deepcopy(ledger.get("background_origin") or {})
        owner_locks = self._owner_lock_rows(project)

        title = character.get("title")
        title_status = character.get("title_status") or ("SELECTED" if title else "OPTIONAL_OMITTED_BY_OWNER")
        ability_scores = core.get("ability_scores") or {}
        ability_modifiers = core.get("ability_modifiers") or {}
        ability_rows = [
            {"ability": ability, "score": ability_scores.get(ability), "modifier": ability_modifiers.get(ability)}
            for ability in ("STR", "DEX", "CON", "INT", "WIS", "CHA")
        ]
        background = background_origin.get("background") or {}
        origin = background_origin.get("origin_insight") or {}
        background_card = cards_by_id.get(str(background.get("background_id")))
        origin_card = cards_by_id.get(str(origin.get("origin_insight_id")))
        path_rows = deepcopy(ledger.get("path_selections") or [])
        subpath_rows = deepcopy(ledger.get("subpaths") or [])
        path_card = cards_by_id.get(str(character.get("path_id")))
        subpath_card = cards_by_id.get(str((subpath_rows[0] if subpath_rows else {}).get("subpath_id")))

        canonical_allocations = []
        for packet in sorted(packets.get("packets") or [], key=lambda row: int(row.get("sequence") or 0)):
            canonical_allocations.append({
                "sequence": packet.get("sequence"),
                "target_cl": packet.get("target_cl"),
                "advancement_kind": packet.get("advancement_kind"),
                "record_id": packet.get("record_id"),
                "display_name": packet.get("display_name"),
                "event_id": packet.get("event_id"),
                "event_hash": packet.get("event_hash"),
                "packet_id": packet.get("packet_id"),
                "stage2_rule_id": packet.get("stage2_rule_id"),
            })

        artifact_hashes = {item["artifact_name"]: item["sha256"] for item in projection_status.get("artifacts") or []}
        sheet_identity_input = {
            "project_id": project["project_id"],
            "project_revision": project["revision"],
            "projection_id": projection_status.get("projection_id"),
            "display_contract_sha256": contract_sha,
            "readiness_profile_sha256": profile_sha,
            "advancement_artifact_hashes": artifact_hashes,
        }
        sheet_id = sha256_json(sheet_identity_input)

        snapshot: dict[str, Any] = {
            "schema_version": "TianxiaFoundry.OwnerCharacterSheet.v1",
            "sheet_id": sheet_id,
            "sheet_role": "deterministic owner-facing projection; not canonical advancement or combat authority",
            "readiness": {
                "advancement": "ADVANCEMENT_READY",
                "character_sheet": "CHARACTER_SHEET_READY",
                "gm_screen": "NOT_ATTEMPTED",
                "combat": "NOT_ATTEMPTED",
            },
            "identity": {
                "display_name": character.get("name"),
                "title": title,
                "title_status": title_status,
                "concept": character.get("concept"),
                "species": character.get("species"),
                "creature_type": character.get("creature_type"),
                "size": character.get("size"),
                "cultivation_level": character.get("cl"),
                "realm": character.get("realm"),
                "realm_display": f"{character.get('realm')} Realm" if character.get("realm") else None,
                "path": character.get("path"),
                "path_id": character.get("path_id"),
                "key_ability": character.get("key_ability"),
                "proficiency_bonus": character.get("pb"),
            },
            "ability_scores_and_statistics": {
                "abilities": ability_rows,
                "armor_class": {
                    "value": core.get("ac_active"),
                    "base_value": core.get("ac_base"),
                    "calculation": "10 + Dexterity modifier while unarmored and without another applicable AC calculation",
                    "formula_trace": deepcopy((core.get("ac_generation") or {}).get("trace")),
                    "conditional_note": "Qi Armor is a conditional +3 AC bonus and does not replace the base calculation.",
                    "authority": deepcopy((ledger.get("authority_identities") or {}).get("core_baseline_pack")),
                },
                "initiative": {
                    "bonus": core.get("initiative_bonus"),
                    "check": "1d20 + initiative bonus",
                    "ability": "DEX",
                    "formula_trace": deepcopy((core.get("initiative_generation") or {}).get("trace")),
                    "situational_note": "Street-Hardened can grant Advantage under its authenticated trigger; it does not replace the Dexterity formula.",
                    "authority": deepcopy((ledger.get("authority_identities") or {}).get("core_baseline_pack")),
                },
                "speed": {"walking_ft": core.get("speed_ft"), "generation": deepcopy(core.get("speed_generation"))},
                "hit_points": {"maximum": core.get("hp_max"), "build_state_current": core.get("hp_current"), "progression": deepcopy(core.get("hp_generation"))},
                "primary_resource": {
                    "name": core.get("primary_resource_name"),
                    "maximum": core.get("primary_resource_max"),
                    "build_state_current": core.get("primary_resource_current"),
                    "current_state_note": "This is the deterministic build-state value, not mutable GM-session tracking.",
                    "definitions": deepcopy(ledger.get("resources") or []),
                },
                "technique_attack_bonus": core.get("technique_attack_bonus"),
                "technique_save_dc": core.get("save_dc"),
                "skills": self._skills(core),
            },
            "background_and_origin": {
                "background": background,
                "background_record_id": background_card.get("record_id") if background_card else None,
                "origin_insight": origin,
                "origin_record_id": origin_card.get("record_id") if origin_card else None,
                "background_talent_record_id": next(
                    (row.get("talent_id") for row in ledger.get("talents") or [] if row.get("acquisition_type") == "background_talent"),
                    None,
                ),
                "background_talent_separate_from_learned_talents": True,
                "deception_expertise_result": {
                    "selected_skill": "Deception",
                    "result": origin.get("result"),
                    "sources": (core.get("skill_sources") or {}).get("Deception") or [],
                },
            },
            "path_and_subpath": {
                "path": path_rows[0] if path_rows else None,
                "path_record_id": path_card.get("record_id") if path_card else None,
                "subpath": subpath_rows[0] if subpath_rows else None,
                "subpath_record_id": subpath_card.get("record_id") if subpath_card else None,
                "path_feature_record_ids": [card["record_id"] for card in groups.get("path_features", [])],
                "advancement_feature_record_ids": [card["record_id"] for card in groups.get("advancement_features", [])],
                "source_granted_subpath_feature_record_ids": [
                    row.get("feature_id") for row in ledger.get("features") or [] if row.get("category") == "subpath_feature"
                ],
                "cinder_touch_record_id": next(
                    (row.get("feature_id") for row in ledger.get("features") or [] if row.get("feature_id") == "tianxia.subpath.qi.cinder_heart_cultivator.feature.cinder_touch"),
                    None,
                ),
            },
            "spheres_and_talents": {
                "sphere_record_ids": [card["record_id"] for card in groups.get("spheres", [])],
                "learned_talent_record_ids": [card["record_id"] for card in groups.get("talents", [])],
                "background_talent_record_id": next(
                    (row.get("talent_id") for row in ledger.get("talents") or [] if row.get("acquisition_type") == "background_talent"),
                    None,
                ),
            },
            "owner_facing_action_feature_index": [
                {"record_id": card["record_id"], "display_name": card["display_name"], "timing_or_category": card.get("timing_or_category")}
                for card in cards
                if card.get("timing_or_category") in {"Action", "Bonus Action", "Reaction", "Passive", "Feature"}
            ],
            "advancement_history": {
                "event_count": (ledger.get("advancement") or {}).get("event_count"),
                "event_head_hash": (ledger.get("advancement") or {}).get("event_head_hash"),
                "levels": deepcopy((ledger.get("advancement") or {}).get("levels") or []),
                "canonical_allocations": canonical_allocations,
                "owner_choice_locks": [row for row in owner_locks if int(row.get("created_revision") or 0) == 27],
                "all_owner_locks": owner_locks,
                "typed_choice_snapshot": deepcopy(ledger.get("typed_choice_snapshot") or {}),
            },
            "explicit_none_systems": deepcopy(ledger.get("typed_none") or {}),
            "method": deepcopy(ledger.get("method") or {}),
            "selected_record_sections": groups,
            "selected_record_identity_index": [card["record_id"] for card in cards],
            "capability_status": {
                "summary": {
                    "advancement": "complete",
                    "character_sheet": "complete",
                    "gm_authoring": "pending",
                    "combat_execution": "pending",
                },
                "records": [
                    {
                        "record_id": card["record_id"],
                        "display_name": card["display_name"],
                        "character_sheet": card["capabilities"].get("character_sheet"),
                        "gm_display": card["capabilities"].get("gm_display"),
                        "combat_execution": card["capabilities"].get("combat_execution"),
                        "ai_policy": card["capabilities"].get("ai_policy"),
                        "display_only_not_execution_authority": card["display_only_not_execution_authority"],
                    }
                    for card in cards
                ],
                "pending_execution_surfaces": [
                    "Burn", "Fire Terrain", "typed actions", "typed reactions", "concentration",
                    "movement effects", "damage prevention", "modifiers", "procedures",
                ],
            },
            "later_stage_status": {
                "gm_screen": {
                    "status": "NOT_ATTEMPTED",
                    "next_step": "C2B.2 GM tactical authoring and Factory workspace completion",
                    "pending": deepcopy((ledger.get("later_stage_readiness") or {}).get("gm_screen", {}).get("pending") or []),
                },
                "combat": {
                    "status": "NOT_ATTEMPTED",
                    "pending": deepcopy((ledger.get("later_stage_readiness") or {}).get("combat", {}).get("pending") or []),
                },
            },
            "section_provenance": {
                "identity_and_core": {
                    "owner_lock_ids": [row.get("lock_id") for row in owner_locks if str(row.get("field", "")).startswith("character.")],
                    "core_baseline_authority": deepcopy((ledger.get("authority_identities") or {}).get("core_baseline_pack")),
                    "projection_mappings": [key for key in sorted((provenance.get("mappings") or {})) if key.startswith("/character") or key.startswith("/core_stats")],
                },
                "selected_records": [
                    {
                        "record_id": card["record_id"],
                        "record_hash": card["record_hash"],
                        "source": card["source"],
                        "stage2_rule_id": card["stage2_rule_id"],
                        "source_packet_ids": card["source_packet_ids"],
                        "display_contract_sha256": contract_sha,
                    }
                    for card in cards
                ],
                "advancement": {
                    "event_ids": deepcopy(provenance.get("event_ids") or []),
                    "event_head_hash": provenance.get("event_head_hash"),
                    "projection_input_hash": provenance.get("projection_input_hash"),
                },
                "explicit_none": [
                    {
                        "system": key,
                        "record_id": f"tianxia.c1a.none.{key}",
                        "source_backed": value.get("source_backed"),
                        "reason_code": value.get("reason_code"),
                    }
                    for key, value in sorted((ledger.get("typed_none") or {}).items())
                ],
            },
            "diagnostics": {
                "valid": True,
                "blocking": [],
                "notices": [
                    "GM tactical authoring has not been attempted.",
                    "Combat execution definitions have not been compiled.",
                    "Display descriptions are not executable combat authority unless explicitly marked SUPPORTED.",
                ],
                "advancement_projection": {
                    "projection_status": projection_status.get("status"),
                    "legacy_factory_authoring_input_signal": bool(projection_status.get("eligible_for_command5")),
                    "legacy_signal_is_not_gm_export_readiness": True,
                    "coverage_valid": coverage.get("valid"),
                    "diagnostics_valid": projection_diagnostics.get("valid"),
                },
            },
            "authority_and_artifact_identity": {
                "project_id": project["project_id"],
                "project_revision": project["revision"],
                "event_count": (ledger.get("advancement") or {}).get("event_count"),
                "event_head_hash": projection_status.get("event_head_hash"),
                "content_lock_hash": projection_status.get("content_lock_hash"),
                "typed_choice_snapshot_sha256": (provenance.get("typed_choice_snapshot") or {}).get("snapshot_sha256"),
                "projection_id": projection_status.get("projection_id"),
                "advancement_artifact_hashes": artifact_hashes,
                "display_contract": {
                    "contract_id": contract.get("contract_id"),
                    "version": contract.get("version"),
                    "sha256": contract_sha,
                    "internal_seal_sha256": contract.get("seal_sha256"),
                },
                "readiness_profile": {
                    "profile_id": profile.get("profile_id"),
                    "version": profile.get("version"),
                    "sha256": profile_sha,
                    "internal_seal_sha256": profile.get("seal_sha256"),
                },
                "upstream_authorities": deepcopy(ledger.get("authority_identities") or {}),
            },
        }
        self._validate_snapshot(snapshot, required_record_ids, profile)

        output_dir = self._snapshot_dir(project["project_id"], sheet_id)
        output_file = output_dir / _OWNER_SHEET_FILENAME
        expected_text = canonical_json(snapshot) + "\n"
        if output_file.is_file() and output_file.read_text(encoding="utf-8") == expected_text:
            artifact_sha = sha256_file(output_file)
        else:
            staging = output_dir.with_name(output_dir.name + ".staging")
            shutil.rmtree(staging, ignore_errors=True)
            staging.mkdir(parents=True, exist_ok=True)
            staging_file = staging / _OWNER_SHEET_FILENAME
            staging_file.write_text(expected_text, encoding="utf-8", newline="\n")
            artifact_sha = sha256_file(staging_file)
            (staging / f"{_OWNER_SHEET_FILENAME}.sha256").write_text(
                f"{artifact_sha}  {_OWNER_SHEET_FILENAME}\n", encoding="utf-8", newline="\n"
            )
            output_dir.parent.mkdir(parents=True, exist_ok=True)
            if output_dir.exists():
                shutil.rmtree(output_dir)
            staging.replace(output_dir)
        return snapshot, {
            "sheet_id": sheet_id,
            "path": str(output_file),
            "sha256": artifact_sha,
            "bytes": output_file.stat().st_size,
            "display_contract_sha256": contract_sha,
            "readiness_profile_sha256": profile_sha,
        }

    @staticmethod
    def _compact_sections(snapshot: dict[str, Any] | None) -> dict[str, Any]:
        if not snapshot:
            return {}
        return {
            "identity_core": {"status": "ready", "label": "Character Sheet Ready", "data": snapshot.get("identity")},
            "abilities_statistics": {"status": "ready", "label": "Character Sheet Ready", "data": snapshot.get("ability_scores_and_statistics")},
            "background_origin": {"status": "ready", "label": "Character Sheet Ready", "data": snapshot.get("background_and_origin")},
            "path_subpath": {"status": "ready", "label": "Character Sheet Ready", "data": snapshot.get("path_and_subpath")},
            "spheres_talents": {"status": "ready", "label": "Character Sheet Ready", "data": snapshot.get("spheres_and_talents")},
            "selected_records": {"status": "ready", "label": "Source-backed descriptions and capability badges", "data": snapshot.get("selected_record_sections")},
            "actions_features": {"status": "ready", "label": "Display category index; combat typing remains pending", "data": snapshot.get("owner_facing_action_feature_index")},
            "advancement": {"status": "ready", "label": "CL1–CL5 history complete", "data": snapshot.get("advancement_history")},
            "explicit_none": {"status": "ready", "label": "Authenticated intentional absence", "data": snapshot.get("explicit_none_systems")},
            "capabilities": {"status": "ready", "label": "Readiness and capability status", "data": snapshot.get("capability_status")},
            "diagnostics": {"status": "ready", "label": "No Character Sheet blockers", "data": snapshot.get("diagnostics")},
        }

    def list_characters(self) -> list[dict[str, Any]]:
        rows = []
        for wrapper in self.projects.list_projects():
            project_id = wrapper.get("project_id") or wrapper.get("project", {}).get("project_id")
            if not project_id:
                continue
            sheet = self.sheet(str(project_id), compact=True)
            rows.append({
                "project_id": sheet["project_id"],
                "name": sheet["name"],
                "lifecycle": sheet["lifecycle"],
                "build_status": sheet["build_status"],
                "readiness": sheet["readiness"],
                "target_cl": sheet["identity"].get("target_cl"),
                "current_cl": sheet["identity"].get("current_cl"),
                "path": sheet["identity"].get("path"),
                "updated_at": sheet["updated_at"],
                "can_export_gm": sheet["gm_export"]["available"],
                "plain_summary": sheet["plain_summary"],
            })
        rows.sort(key=lambda item: (str(item.get("name") or "").casefold(), item["project_id"]))
        return rows

    def sheet(self, project_id: str, *, compact: bool = False) -> dict[str, Any]:
        wrapper = self.projects.get_project(project_id)
        project = wrapper["project"]
        lifecycle = wrapper.get("builder_lifecycle") or self.projects.builder_lifecycle(project_id)
        locks = self._user_locks(project)
        blueprint = self._blueprint(project_id)
        artifacts, projection_status = self._compiled_artifacts(project_id)
        factory_workspace = self._factory_workspace_status(project_id)
        ledger = (artifacts or {}).get("Character_Master_Ledger.json")
        compiled_character = (ledger or {}).get("character") or {}
        compiled_path = compiled_character.get("path")
        compiled_subpaths = (ledger or {}).get("subpaths") or []
        path_from_blueprint = None
        subpath_from_blueprint = None
        if blueprint:
            path_rows = blueprint["selected_records"].get("path_choice") or []
            subpath_rows = blueprint["selected_records"].get("subpath_choice") or []
            path_from_blueprint = (path_rows[0].get("canonical_name") or path_rows[0].get("name")) if path_rows else None
            subpath_from_blueprint = (subpath_rows[0].get("canonical_name") or subpath_rows[0].get("name")) if subpath_rows else None

        snapshot: dict[str, Any] | None = None
        sheet_artifact: dict[str, Any] | None = None
        legacy_gm_ready = self._legacy_completed_gm_ready(ledger, projection_status)
        if ledger and (ledger.get("readiness") or {}).get("advancement") == "ADVANCEMENT_READY":
            snapshot, sheet_artifact = self._build_snapshot(project=project, artifacts=artifacts or {}, projection_status=projection_status)
            build_status = "CHARACTER_SHEET_READY"
        elif legacy_gm_ready:
            build_status = "GM_READY"
        elif ledger:
            build_status = "ADVANCEMENT_READY"
        elif blueprint:
            build_status = "BLUEPRINT"
        elif lifecycle.get("persistence_state") == "temporary":
            build_status = "TEMPORARY"
        else:
            build_status = "SAVED_DRAFT"

        status_copy = {
            "TEMPORARY": "Temporary character intake. Save Draft to retain it.",
            "SAVED_DRAFT": "Saved draft. The character has not completed Stage 1 yet.",
            "BLUEPRINT": "Character plan accepted and saved. Advancement compilation is still required.",
            "ADVANCEMENT_READY": "Advancement is deterministic and ready. The owner-facing Character Sheet is not complete yet.",
            "CHARACTER_SHEET_READY": (
                "Character Sheet Ready. GM tactical authoring and the Factory Command 1–4 input workspace are complete; "
                "GM Screen verification remains unattempted."
                if factory_workspace.get("status") == "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE"
                else "Character Sheet Ready. GM tactical authoring is the next step; GM export remains unavailable."
            ),
            "GM_READY": "Historical completed character is GM-ready under its validated legacy contract.",
        }[build_status]

        if snapshot:
            snap_identity = snapshot["identity"]
            identity = {
                "name": snap_identity.get("display_name"),
                "title": snap_identity.get("title"),
                "title_status": snap_identity.get("title_status"),
                "concept": snap_identity.get("concept"),
                "target_cl": locks.get("target_cl"),
                "current_cl": snap_identity.get("cultivation_level"),
                "target_realm": locks.get("target_realm"),
                "current_realm": snap_identity.get("realm"),
                "path": snap_identity.get("path"),
                "subpath": ((snapshot.get("path_and_subpath") or {}).get("subpath") or {}).get("name"),
                "species": snap_identity.get("species"),
                "creature_type": snap_identity.get("creature_type"),
                "size": snap_identity.get("size"),
                "key_ability": snap_identity.get("key_ability"),
            }
            readiness = deepcopy(snapshot["readiness"])
        else:
            identity = {
                "name": compiled_character.get("name") or project.get("name"),
                "title": compiled_character.get("title"),
                "concept": compiled_character.get("concept") or locks.get("concept"),
                "target_cl": locks.get("target_cl"),
                "current_cl": compiled_character.get("cl"),
                "target_realm": locks.get("target_realm"),
                "current_realm": compiled_character.get("realm"),
                "path": compiled_path or path_from_blueprint,
                "subpath": ((compiled_subpaths[0].get("name") if isinstance(compiled_subpaths[0], dict) else compiled_subpaths[0]) if compiled_subpaths else subpath_from_blueprint),
                "species": compiled_character.get("species"),
                "key_ability": compiled_character.get("key_ability"),
            }
            readiness = {
                "advancement": "ADVANCEMENT_READY" if ledger else "NOT_ATTEMPTED",
                "character_sheet": "NOT_ATTEMPTED",
                "gm_screen": "GM_READY" if legacy_gm_ready else "NOT_ATTEMPTED",
                "combat": "NOT_ATTEMPTED",
            }

        from portable_character.service import PortableCharacterPackageService
        portable_verified = PortableCharacterPackageService(self.db).verified_status(project_id)
        source_consumer_verified = bool(portable_verified and portable_verified.get("status") == "GM_SCREEN_SOURCE_CONSUMER_VERIFIED")
        gm_available = source_consumer_verified or legacy_gm_ready or (
            projection_status.get("command5_status") == "COMMAND_5_GM_SCREEN_CANDIDATE_READY"
            and projection_status.get("command6_status") == "SIMULATED_CONSUMER_PASS_REAL_GMSCREEN_ACCEPTANCE_REQUIRED"
        )
        if source_consumer_verified:
            readiness["gm_screen"] = "GM_READY_SOURCE_VERIFIED"
            readiness["combat"] = "NOT_ATTEMPTED"
            status_copy = "Character Sheet Ready. GM model built, exact bundled GM Screen source consumer verified, and Character ZIP ready. Native owner acceptance and combat execution remain pending."
        if gm_available:
            gm_blockers = []
        elif not ledger:
            gm_blockers = [
                "The mechanical projection has not been compiled yet.",
                "GM tactical authoring and verified GM model compilation have not been completed.",
            ]
        else:
            if factory_workspace.get("command5") == "GM_MODEL_CANDIDATE_READY":
                gm_blockers = [
                    "GM tactical authoring is complete, and the Character/GM Command 5 candidate and schema-valid GM model candidate are complete.",
                    "GM Screen consumer verification has not been attempted, so export remains unavailable.",
                ]
            elif factory_workspace.get("status") == "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE":
                gm_blockers = [
                    "GM tactical authoring and the Factory Command 1–4 input workspace are complete, but Command 5 and Command 6 have not been run.",
                    "The final GM Screen model and consumer verification do not exist yet.",
                ]
            else:
                gm_blockers = [
                    "GM tactical authoring and verified GM model compilation have not been completed.",
                    "Advancement projection eligibility is only a legacy Factory-authoring input signal, not GM export readiness.",
                ]

        result = {
            "schema_version": "TianxiaFoundry.OwnerCharacterSheetServiceResponse.v2",
            "project_id": project_id,
            "name": identity["name"],
            "updated_at": project.get("updated_at"),
            "lifecycle": lifecycle,
            "build_status": build_status,
            "readiness": readiness,
            "plain_summary": status_copy,
            "identity": identity,
            "sheet_artifact": sheet_artifact,
            "owner_character_sheet": None if compact else snapshot,
            "provenance": {
                "owner_locks": {"status": "available", "label": "Chosen by owner", "data": locks},
                "ai_blueprint": {"status": "available" if blueprint else "not_available", "label": "Accepted character plan" if blueprint else "Not accepted yet", "data": blueprint},
                "advancement_projection": {
                    "status": "available" if ledger else "not_compiled",
                    "label": "Advancement Ready" if ledger else "Not compiled yet",
                    "projection": projection_status,
                    "legacy_factory_authoring_input_signal": bool(projection_status.get("eligible_for_command5")),
                    "not_a_gm_export_gate": True,
                },
                "mechanical_projection": {
                    "status": "available" if ledger else "not_compiled",
                    "label": "Advancement Ready" if ledger else "Not compiled yet",
                    "projection": projection_status,
                    "deprecated_alias_for": "advancement_projection",
                },
                "character_sheet_projection": {
                    "status": "available" if snapshot else "not_compiled",
                    "label": "Character Sheet Ready" if snapshot else "Not compiled yet",
                    "artifact": sheet_artifact,
                },
            },
            "sections": {} if compact else self._compact_sections(snapshot),
            "factory_workspace": factory_workspace,
            "gm_export": {
                "available": gm_available,
                "label": "Export Character ZIP for GM Screen",
                "blockers": gm_blockers,
                "readiness": "GM_READY_SOURCE_VERIFIED" if source_consumer_verified else ("GM_READY" if legacy_gm_ready else "NOT_ATTEMPTED"),
                "source_consumer_verified": source_consumer_verified,
                "native_or_interactive_acceptance": (portable_verified or {}).get("native_or_interactive_acceptance", "NOT_RUN") if source_consumer_verified else "NOT_RUN",
                "combat": (portable_verified or {}).get("combat", "NOT_ATTEMPTED") if source_consumer_verified else "NOT_ATTEMPTED",
                "next_step": (
                    None
                    if gm_available
                    else "Proceed to the separately authorized Command 6 consumer-verification and portable-package checkpoint."
                    if factory_workspace.get("command5") == "GM_MODEL_CANDIDATE_READY"
                    else "Proceed to the separately authorized Command 5 candidate checkpoint."
                    if factory_workspace.get("status") == "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE"
                    else "Complete C2B.2 GM tactical authoring and the existing Factory workspace lifecycle."
                ),
            },
            "advanced_details": {
                "projection_status": projection_status,
                "legacy_eligible_for_command5": bool(projection_status.get("eligible_for_command5")),
                "legacy_completed_gm_compatibility": legacy_gm_ready,
                "portable_character_verification": portable_verified,
            },
        }
        return result
