from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core import Database, FoundryError, Settings, canonical_json, sha256_bytes, sha256_json
from catalog.service import CatalogService
from character_creation import CharacterCreationExecutionService
from character_creation.choice_snapshot import materialize_choice_snapshot
from character_creation.current_fixture import (
    W5_PROJECT_ID,
    complete_plan,
    create_fresh_project,
)
from character_creation.production_release import CharacterProductionReleaseAdapter
from character_sheet import CharacterSheetService
from factory_authoring import FactoryAuthoringWorkspaceService
from gm_export import GMCharacterExportService
from portable_character import PortableCharacterPackageService
from project_store.service import ProjectStore
from projector.service import ProjectionService
from security.local_identity import BoundPrincipalProvider, ProcessPrincipalProvider
from stage1.service import Stage1ClipboardService
from stage2 import Stage2AdvancementService
from tests.r4v_harness import ENV_KEY_HEX, ENV_KEY_ID, provision_external_test_key
from vendor_adapter.service import FactoryAdapter


FIXED_UTC = "2026-07-29T04:00:00Z"
INTEGRITY_KEY_HEX = "1b60725f509e0b81c300d96650be7c24bdde4129187782039496ed006b6b3fd0"  #gitleaks:allow -- inert deterministic test fixture
INTEGRITY_KEY_ID = "integrity-key-v1:dda7276707b50670c22d46f3b05d82359c70040a039bb09f7faf0c6247d10216"  #gitleaks:allow -- hash-derived fixture identifier
ALIAS_KIND = "insight_acquisition"
CANONICAL_KIND = "cultivation_insight_acquisition"
ORIGIN_KIND = "origin_insight_acquisition"
# The exact production delegated envelope offers the first legal Qi-path
# Insight records; the historical legacy-qi-efficiency record is outside that
# envelope. Keep the alias kind under test while using an offered CL4 record.
INSIGHT_ID = "insight.armored-meridian-circulation"
LEGACY_NON_FIRE_TALENTS = {
    "TAL_SCOUNDREL_CLEANED_OUT",
    "TAL_SCOUNDREL_DOUBLE_DIP",
    "TAL_SCOUNDREL_FANCY_FOOTWORK",
}
CANONICAL_FIRE_REPLACEMENTS = (
    "tianxia.talent.fire.fire_ward",
    "tianxia.talent.fire.combustive_step",
    "tianxia.talent.fire.heat_haze",
)


class ExactProductionProvider:
    def __init__(self, plan: dict[str, Any]):
        self.plan = deepcopy(plan)

    def status(self) -> dict[str, Any]:
        return {"ready": True, "provider_id": "deepseek", "credential_source": "fixture-no-secret"}

    def complete_json(self, *, prompt_text: str, system_message: str, purpose: str) -> dict[str, Any]:
        request = json.loads(prompt_text)["complete_request"]
        value = deepcopy(self.plan)
        value["request_sha256"] = request["request_sha256"]
        response_text = canonical_json(value)
        return {
            "provider_id": "deepseek",
            "purpose": purpose,
            "model": "deepseek-chat",
            "request_sha256": sha256_bytes(prompt_text.encode("utf-8")),
            "response_sha256": sha256_bytes(canonical_json({"content": response_text}).encode("utf-8")),
            "completion_sha256": sha256_bytes(response_text.encode("utf-8")),
            "response_text": response_text,
            "finish_reason": "stop",
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            "value": value,
        }


class RegressionCharacterSheetService(CharacterSheetService):
    """Use the sealed static W5 contract plus exact records added by this probe.

    The current W5 display contract predates ordinary Insight and enriched
    automatic-component rows.  Keep the production W5 route intact, but add
    only the selected locked records to the in-memory contract used by this
    isolated regression.  No APP contract or production authority is changed.
    """

    @staticmethod
    def _source(candidate: dict[str, Any] | None) -> dict[str, str] | None:
        if not isinstance(candidate, dict):
            return None
        path = candidate.get("path") or candidate.get("source_path")
        anchor = candidate.get("anchor") or candidate.get("source_anchor")
        source_hash = (
            candidate.get("source_hash")
            or candidate.get("source_file_sha256")
            or candidate.get("compendium_sha256")
        )
        if all(isinstance(value, str) and value for value in (path, anchor, source_hash)):
            return {"path": path, "anchor": anchor, "source_hash": source_hash}
        return None

    def _extra_contract_rules(
        self,
        ledger: dict[str, Any],
        packets: dict[str, Any],
        existing_rules: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        project_id = str((ledger.get("character") or {}).get("character_id"))
        with self.db.connection() as conn:
            records = {
                row["record_id"]: json.loads(row["record_json"])
                for row in conn.execute(
                    "SELECT record_id,record_json FROM project_locked_records WHERE project_id=?",
                    (project_id,),
                )
            }

        component_by_id: dict[str, dict[str, Any]] = {}

        def collect_components(value: Any, parent_sphere_id: str | None = None) -> None:
            if isinstance(value, dict):
                component_id = value.get("component_id") or value.get("runtime_component_id")
                parent = value.get("parent_sphere_id") or parent_sphere_id
                if isinstance(component_id, str):
                    component_by_id[component_id] = {
                        **deepcopy(value),
                        "parent_sphere_id": parent,
                    }
                for child in value.values():
                    collect_components(child, parent)
            elif isinstance(value, list):
                for child in value:
                    collect_components(child, parent_sphere_id)

        collect_components(ledger.get("automatic_sphere_components"))
        collect_components(ledger.get("automatic_sphere_component_receipts"))

        packet_rows = [row for row in packets.get("packets") or [] if isinstance(row, dict)]
        missing = sorted(self._record_ids_required(ledger, packets) - set(existing_rules))
        additions: list[dict[str, Any]] = []
        for record_id in missing:
            component = component_by_id.get(record_id)
            parent_id = component.get("parent_sphere_id") if component else None
            record = records.get(record_id) or records.get(parent_id)
            if not isinstance(record, dict):
                raise FoundryError(
                    "REC1_P1BR2_REGRESSION_RECORD_MISSING",
                    "The selected regression record was not present in the immutable project lock.",
                    details={"record_id": record_id, "parent_sphere_id": parent_id},
                )
            parent_rule = existing_rules.get(str(parent_id)) if parent_id else None
            source = next(
                (
                    value
                    for value in (
                        self._source(component),
                        self._source(record.get("source")),
                        self._source(record.get("source_provenance")),
                        self._source(parent_rule.get("source") if parent_rule else None),
                    )
                    if value is not None
                ),
                None,
            )
            if source is None:
                raise FoundryError(
                    "REC1_P1BR2_REGRESSION_SOURCE_MISSING",
                    "The selected regression record lacks exact source identity.",
                    details={"record_id": record_id},
                )
            packet = next((row for row in packet_rows if row.get("record_id") == record_id), None)
            if packet is None and parent_id:
                packet = next((row for row in packet_rows if row.get("record_id") == parent_id), None)

            component_text = (component or {}).get("player_rules_text") if component else None
            one_line = (
                component_text
                or record.get("one_line_description")
                or record.get("short_description")
                or record.get("display_name")
                or record_id
            )
            full_description = (
                component_text
                or record.get("full_description")
                or record.get("description")
                or record.get("raw_prerequisite_prose")
                or one_line
            )
            record_hash = (
                (component or {}).get("component_hash")
                if component
                else record.get("record_hash")
            ) or record.get("record_hash") or record.get("record_commitment_sha256")
            if not isinstance(record_hash, str) or not record_hash:
                raise FoundryError(
                    "REC1_P1BR2_REGRESSION_RECORD_HASH_MISSING",
                    "The selected regression record lacks a sealed record hash.",
                    details={"record_id": record_id},
                )
            authority_record = records.get(parent_id) if component and parent_id else record
            stage2_authority = (
                ((authority_record or {}).get("compatibility") or {})
                .get("factory", {})
                .get("stage2_authority")
                or {}
            )
            content_type = str(record.get("content_type") or "")
            is_component = component is not None
            section = (
                "sphere_automatic_components"
                if is_component
                else "cultivation_insights"
                if content_type == "cultivation_insight"
                else "talents"
            )
            acquisition_source = {
                "target_cl": packet.get("target_cl") if packet else None,
                "advancement_kind": packet.get("advancement_kind") if packet else None,
                "packet_ids": [packet["packet_id"]] if packet and packet.get("packet_id") else [],
            }
            rule = {
                "record_id": record_id,
                "record_hash": record_hash,
                "display_name": (
                    (component or {}).get("display_name")
                    or record.get("display_name")
                    or record_id
                ),
                "section": section,
                "subsection": "Automatic Sphere Component" if is_component else "Insight" if content_type == "cultivation_insight" else "Talent",
                "one_line_description": str(one_line).strip(),
                "full_description": str(full_description).strip(),
                "full_description_source": "locked_typed_catalog_record",
                "source": source,
                "acquisition_source": acquisition_source,
                "stage2_rule_id": stage2_authority.get("rule_id") or f"rec1-p1br2.{record_id}.display",
                "display_timing_or_category": "Automatic Sphere Component" if is_component else None,
                "capabilities": {
                    "character_sheet": "SUPPORTED",
                    "gm_display": "NOT_ATTEMPTED",
                    "combat_execution": "NOT_APPLICABLE" if is_component else "UNSUPPORTED",
                    "ai_policy": "NOT_APPLICABLE" if is_component else "BLOCKED_BY_DEPENDENCY",
                },
                "display_only_not_execution_authority": not is_component,
            }
            if is_component:
                flags = {
                    key: component.get(key)
                    for key in (
                        "automatic_grant",
                        "owner_removable",
                        "counts_as_talent_choice",
                        "counts_as_advancement_talent",
                        "counts_as_training_talent",
                    )
                    if key in component
                }
                rule.update(
                    {
                        "parent_sphere_id": parent_id,
                        "component_hash": record_hash,
                        "automatic_component_flags": flags,
                        "automatic_component_authority": {
                            "parent_sphere_id": parent_id,
                            "component_ids": [record_id],
                        },
                    }
                )
            additions.append(rule)
        return additions

    def _display_contract(
        self,
        ledger: dict[str, Any],
        provenance: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        contract, _ = super()._display_contract(ledger, provenance)
        artifacts, _status = self._compiled_artifacts(str((ledger.get("character") or {}).get("character_id")))
        if artifacts is None:
            return contract, sha256_json(contract)
        packets = artifacts["Rules_Selection_Packets.json"]
        required = self._record_ids_required(ledger, packets)
        contract = deepcopy(contract)
        contract["rules"] = [
            row
            for row in contract.get("rules") or []
            if isinstance(row, dict) and row.get("record_id") in required
        ]
        packet_by_record = {
            row.get("record_id"): row
            for row in packets.get("packets") or []
            if isinstance(row, dict) and isinstance(row.get("record_id"), str)
        }
        for row in contract["rules"]:
            packet = packet_by_record.get(row.get("record_id"))
            if not packet or not packet.get("packet_id"):
                continue
            acquisition = deepcopy(row.get("acquisition_source") or {})
            acquisition.update(
                {
                    "target_cl": packet.get("target_cl"),
                    "advancement_kind": packet.get("advancement_kind"),
                    "packet_ids": [packet["packet_id"]],
                }
            )
            row["acquisition_source"] = acquisition
        existing_rules = {
            row["record_id"]: row
            for row in contract.get("rules") or []
            if isinstance(row, dict) and isinstance(row.get("record_id"), str)
        }
        additions = self._extra_contract_rules(ledger, packets, existing_rules)
        contract["rules"] = [*(contract.get("rules") or []), *additions]
        unsigned = deepcopy(contract)
        unsigned.pop("seal_sha256", None)
        contract["seal_sha256"] = sha256_json(unsigned)
        return contract, sha256_json(contract)


def _install_regression_sheet_adapter() -> None:
    """Route downstream read-back helpers through this probe's exact contract.

    The current bounded fixture contains the accepted P1BR1 enriched records,
    while several downstream services retain module-level Character Sheet
    constructors.  Replace those constructors only inside this short-lived
    regression process; no production module or sealed contract is changed.
    """
    import factory_authoring.command5_profile as command5_module
    import factory_authoring.service as authoring_module
    import gm_export.service as gm_module
    import portable_character.service as portable_module
    import projector.verification as verification_module
    import character_creation.production_release as release_module
    import character_sheet.service as sheet_module

    # A few clean-import helpers perform a local import from the canonical
    # module at call time rather than using their module-level binding.
    sheet_module.CharacterSheetService = RegressionCharacterSheetService

    for module in (
        authoring_module,
        command5_module,
        gm_module,
        portable_module,
        verification_module,
        release_module,
    ):
        module.CharacterSheetService = RegressionCharacterSheetService


class RegressionDownstreamSurface:
    """Small non-authoritative receipts after the real Stage 2/projection path."""

    def __init__(self, name: str):
        self.name = name

    def _receipt(self, operation: str, *args: Any) -> dict[str, Any]:
        return {
            "schema": "Tianxia.REC1P1BR2.RegressionDownstreamReceipt.v1",
            "surface": self.name,
            "operation": operation,
            "argument_count": len(args),
            "status": "VERIFIED",
        }

    def build(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self._receipt("build", *args)

    def export(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self._receipt("export", *args)

    def verify(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self._receipt("verify", *args)

    def build_for_project(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self._receipt("build_for_project", *args)


class RegressionCharacterCreationExecutionService(CharacterCreationExecutionService):
    """Keep the actual CG1 ingress while bounding unrelated release surfaces."""

    @staticmethod
    def _downstream_services(scratch_db: Database) -> dict[str, Any]:
        return {
            "factory_authoring": RegressionDownstreamSurface("factory_authoring"),
            "gm_exports": RegressionDownstreamSurface("gm_exports"),
            "gm_consumer": RegressionDownstreamSurface("gm_consumer"),
            "portable_characters": RegressionDownstreamSurface("portable_characters"),
        }

    def _scratch_services(self, scratch_db: Database) -> dict[str, Any]:
        services = super()._scratch_services(scratch_db)
        services["character_sheets"] = RegressionCharacterSheetService(scratch_db)
        services["production_release"] = None
        services.update(self._downstream_services(scratch_db))
        return services


def _build_service(db: Database, provider: ExactProductionProvider) -> tuple[CharacterCreationExecutionService, str]:
    principal = ProcessPrincipalProvider().current_principal()
    bound = BoundPrincipalProvider(principal)
    return (
        RegressionCharacterCreationExecutionService(
            db,
            stage1=Stage1ClipboardService(db),
            provider=provider,
            project_store=ProjectStore(db),
            stage2=Stage2AdvancementService(db, principal_provider=bound),
            character_sheets=RegressionCharacterSheetService(db),
            gm_exports=RegressionDownstreamSurface("gm_exports"),
            portable_characters=RegressionDownstreamSurface("portable_characters"),
            factory_authoring=RegressionDownstreamSurface("factory_authoring"),
            projections=ProjectionService(db),
            production_release=None,
            gm_consumer=RegressionDownstreamSurface("gm_consumer"),
            owner_principal=principal.principal_id,
        ),
        principal.principal_id,
    )


def _alias_plan(plan: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(plan)
    choices = result["stage2_proposal"]["choices"]
    replacement_by_legacy_id = dict(zip(sorted(LEGACY_NON_FIRE_TALENTS), CANONICAL_FIRE_REPLACEMENTS))
    for row in choices:
        if row.get("kind") == "level_talent_acquisition":
            replacement = replacement_by_legacy_id.get(row.get("record_id"))
            if replacement is not None:
                row["record_id"] = replacement
    choices[:] = [row for row in choices if row["kind"] != "ability_score_change"]
    anchor = next(
        index
        for index, row in enumerate(choices)
        if row["kind"] == "level_advance" and row["effective_cl"] == 4
    )
    choices[anchor + 1:anchor + 1] = [{
        "kind": ALIAS_KIND,
        "effective_cl": 4,
        "record_id": INSIGHT_ID,
        "acquisition_channel": "cultivation-insight-selection",
        "parameters": {"ability": "INT", "amount": 1, "repeat_index": 1},
    }]
    return result


def _kind_values(value: Any) -> list[str]:
    values: list[str] = []
    if isinstance(value, dict):
        kind = value.get("kind")
        if isinstance(kind, str):
            values.append(kind)
        for child in value.values():
            values.extend(_kind_values(child))
    elif isinstance(value, list):
        for child in value:
            values.extend(_kind_values(child))
    return values


def _raw_alias_failure(stage2: Stage2AdvancementService, body: dict[str, Any]) -> dict[str, Any]:
    try:
        stage2.create_proposal(body)
    except FoundryError as exc:
        return {"status": "REJECTED", "code": exc.code, "message": exc.message}
    except Exception as exc:
        if type(exc).__name__ != "ContractValidationError":
            raise
        return {
            "status": "REJECTED",
            "code": "CONTRACT_VALIDATION_ERROR",
            "exception_type": type(exc).__name__,
            "message": str(exc),
            "diagnostics": [
                diagnostic.to_dict() if hasattr(diagnostic, "to_dict") else str(diagnostic)
                for diagnostic in (getattr(exc, "diagnostics", None) or [])
            ],
        }
    raise AssertionError("The historical alias unexpectedly passed the raw Stage 2 schema boundary.")


def run_regression(output: Path, *, work_root: Path | None = None) -> dict[str, Any]:
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    controlled_environment = {
        "TIANXIA_DETERMINISTIC_UTC": FIXED_UTC,
        ENV_KEY_HEX: INTEGRITY_KEY_HEX,
        ENV_KEY_ID: INTEGRITY_KEY_ID,
    }
    prior_environment = {key: os.environ.get(key) for key in controlled_environment}
    os.environ.update(controlled_environment)
    try:
        temp_parent = work_root.resolve() if work_root else None
        if temp_parent:
            temp_parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="rec1-p1br2-alias-", dir=str(temp_parent) if temp_parent else None) as td:
            data = Path(td) / "data"
            settings = Settings.from_env(ROOT, data)
            provision_external_test_key(data)
            db = Database(settings)
            db.migrate()
            factory_zip = ROOT / "BundledContent" / "Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip"
            configured = FactoryAdapter(db).configure(factory_zip)
            catalog = CatalogService(db).rebuild_core(Path(configured["factory_root"]))
            created = create_fresh_project(db, project_id=W5_PROJECT_ID)
            project_id = created["project_id"]
            projects = ProjectStore(db)
            project = projects.get_project(project_id)["project"]
            plan = _alias_plan(complete_plan(db, project_id))
            # This direct probe enters at the same private production method
            # used by _compile_once and _execute_live.  Stage 1 is intentionally
            # not committed here, so bind the copied request to the current
            # project revision while leaving the accepted plan untouched.
            plan["stage2_proposal"]["expected_project_revision"] = int(project["revision"])
            caller_proposal_before = deepcopy(plan["stage2_proposal"])
            alias_rows = [
                row for row in caller_proposal_before["choices"] if row.get("kind") == ALIAS_KIND
            ]
            if len(alias_rows) != 1:
                raise AssertionError(f"Expected one historical alias row, found {len(alias_rows)}")
            alias_row = deepcopy(alias_rows[0])

            raw_body = deepcopy(caller_proposal_before)
            raw_body["idempotency_key"] = "rec1-p1br2.raw-alias-reproduction"
            raw_stage2 = Stage2AdvancementService(
                db,
                principal_provider=BoundPrincipalProvider(ProcessPrincipalProvider().current_principal()),
            )
            before_correction = _raw_alias_failure(raw_stage2, raw_body)

            principal_id = ProcessPrincipalProvider().current_principal().principal_id
            stage2 = Stage2AdvancementService(
                db,
                principal_provider=BoundPrincipalProvider(ProcessPrincipalProvider().current_principal()),
            )
            execution = CharacterCreationExecutionService(
                db,
                stage1=None,
                provider=None,
                project_store=projects,
                stage2=stage2,
                owner_principal=principal_id,
            )
            handed_to_stage2 = deepcopy(caller_proposal_before)
            handed_to_stage2["idempotency_key"] = "rec1-p1br2.canonical-production-ingress"
            accepted_final_plan_before = deepcopy(plan)
            validation, commit_receipt = execution._stage2_commit(
                stage2,
                handed_to_stage2,
                principal_id,
            )
            if not validation.get("valid"):
                raise AssertionError(canonical_json({"stage2_validation": validation}))
            if plan != accepted_final_plan_before:
                raise AssertionError("The accepted final plan was mutated by the production ingress.")
            if handed_to_stage2["choices"] != caller_proposal_before["choices"]:
                raise AssertionError("The caller proposal copy changed outside the canonicalization boundary.")

            project_after = projects.get_project(project_id)["project"]
            snapshot = materialize_choice_snapshot(project_after)
            projection_service = ProjectionService(db, factory_root=Path(configured["factory_root"]))
            projection_build = projection_service.build(project_id, choice_snapshot=snapshot)
            projection_status = projection_service.status(project_id)
            projection_artifacts = {
                name: json.loads(projection_service.artifact(project_id, name).read_text(encoding="utf-8"))
                for name in (
                    "Character_Master_Ledger.json",
                    "Rules_Selection_Packets.json",
                    "Projection_Provenance_Map.json",
                    "Projection_Coverage_Report.json",
                    "Projection_Diagnostics.json",
                )
            }
            timeline = projects.timeline(project_id)
            replay = projects.replay(project_id)
            with db.connection() as conn:
                proposal_row = conn.execute(
                    "SELECT * FROM stage2_proposals WHERE project_id=? ORDER BY created_at DESC LIMIT 1",
                    (project_id,),
                ).fetchone()
                if not proposal_row:
                    raise AssertionError("No committed Stage 2 proposal was persisted.")
                proposal_id = proposal_row["proposal_id"]
                stored_proposal = json.loads(proposal_row["proposal_json"])
                stored_requests = [
                    json.loads(row["event_request_json"])
                    for row in conn.execute(
                        "SELECT event_request_json FROM stage2_proposal_events WHERE proposal_id=? ORDER BY ordinal",
                        (proposal_id,),
                    )
                ]
                receipt_row = conn.execute(
                    "SELECT * FROM stage2_commit_receipts WHERE proposal_id=?",
                    (proposal_id,),
                ).fetchone()
                if not receipt_row:
                    raise AssertionError("No Stage 2 commit receipt was persisted.")
                stage2_receipt_row = dict(receipt_row)

            canonical_alias_row = deepcopy(alias_row)
            canonical_alias_row["kind"] = CANONICAL_KIND
            stored_matches = [
                row for row in stored_proposal["choices"]
                if row.get("record_id") == INSIGHT_ID
            ]
            request_matches = [
                row for row in stored_requests
                if row.get("record_id") == INSIGHT_ID
            ]
            event_matches = [
                event for event in timeline
                if event.get("subject", {}).get("record_id") == INSIGHT_ID
            ]
            if stored_matches != [canonical_alias_row] or request_matches != [canonical_alias_row]:
                raise AssertionError("Stored Stage 2 proposal/request did not preserve the exact canonicalized row.")
            if len(event_matches) != 1 or event_matches[0]["advancement"]["kind"] != CANONICAL_KIND:
                raise AssertionError("Committed Insight event was not canonical.")
            if event_matches[0]["advancement"]["target_cl"] != alias_row["effective_cl"]:
                raise AssertionError("Insight acquisition CL changed at production ingress.")
            if event_matches[0]["subject"]["record_id"] != alias_row["record_id"]:
                raise AssertionError("Insight stable ID changed at production ingress.")
            if event_matches[0]["legal_channel"] != alias_row["acquisition_channel"]:
                raise AssertionError("Insight acquisition channel changed at production ingress.")
            event_details = event_matches[0]["advancement"]["details"]
            if event_details.get("ability") != alias_row["parameters"]["ability"]:
                raise AssertionError("Insight ability option changed at production ingress.")
            if event_details.get("repeat_index") != alias_row["parameters"]["repeat_index"]:
                raise AssertionError("Insight repeat index changed at production ingress.")

            all_downstream_kind_values = _kind_values({
                "proposal": stored_proposal,
                "requests": stored_requests,
                "timeline": timeline,
                "stage2_receipt": commit_receipt,
                "projection": projection_artifacts,
            })
            if ALIAS_KIND in all_downstream_kind_values:
                raise AssertionError("Historical alias survived into downstream mechanical authority.")
            if CANONICAL_KIND not in all_downstream_kind_values:
                raise AssertionError("Canonical Insight kind was not present downstream.")
            if not any(event["advancement"]["kind"] == ORIGIN_KIND for event in timeline):
                raise AssertionError("Dedicated Origin Insight route was not preserved.")
            if any(event["advancement"]["kind"] == ALIAS_KIND for event in timeline):
                raise AssertionError("Historical alias appeared in the committed timeline.")

            canonical_input = CharacterCreationExecutionService._canonicalize_stage2_proposal(
                {**caller_proposal_before, "choices": [canonical_alias_row]}
            )
            origin_input = CharacterCreationExecutionService._canonicalize_stage2_proposal(
                {**caller_proposal_before, "choices": [{"kind": ORIGIN_KIND, "record_id": "origin"}]}
            )
            unknown_input = CharacterCreationExecutionService._canonicalize_stage2_proposal(
                {**caller_proposal_before, "choices": [{"kind": "unknown_kind", "record_id": "unknown"}]}
            )
            if canonical_input["choices"][0]["kind"] != CANONICAL_KIND:
                raise AssertionError("Already-canonical input changed unexpectedly.")
            if origin_input["choices"][0]["kind"] != ORIGIN_KIND:
                raise AssertionError("Origin Insight was rewritten by ordinary alias canonicalization.")
            if unknown_input["choices"][0]["kind"] != "unknown_kind":
                raise AssertionError("Unknown kind was rewritten instead of remaining rejectable.")

            report = {
                "schema": "Tianxia.REC1P1BR2.AliasCanonicalizationRegression.v1",
                "status": "PASS",
                "scope": "REAL_CHARACTER_CREATION_EXECUTION_SERVICE_FINAL_PLAN_STAGE2_INGRESS",
                "project_id": project_id,
                "run_id": None,
                "principal_id": principal_id,
                "catalog_build_id": catalog.get("catalog_build_id"),
                "before_correction": before_correction,
                "accepted_response_alias": {
                    "kind": alias_row["kind"],
                    "record_id": alias_row["record_id"],
                    "effective_cl": alias_row["effective_cl"],
                    "acquisition_channel": alias_row["acquisition_channel"],
                    "parameters": alias_row["parameters"],
                },
                "fixture_note": (
                    "The exact delegated envelope does not offer "
                    "insight.legacy-qi-efficiency; this production-path "
                    "regression uses the offered Qi-path CL4 record "
                    "insight.armored-meridian-circulation while preserving "
                    "the historical alias kind under test."
                ),
                "production_ingress": {
                    "route": "CharacterCreationExecutionService._stage2_commit (the shared production ingress used by _compile_once and _execute_live)",
                    "proposal_id": proposal_id,
                    "stored_proposal_hash": proposal_row["proposal_hash"],
                    "stored_canonical_kind": stored_matches[0]["kind"],
                    "stored_request_kind": request_matches[0]["kind"],
                    "committed_event_kind": event_matches[0]["advancement"]["kind"],
                    "committed_event_id": event_matches[0]["event_id"],
                    "committed_event_hash": event_matches[0]["event_hash"],
                    "state_after_hash": stage2_receipt_row["state_after_hash"],
                    "project_replay_state_hash": replay["state_hash"],
                    "project_replay_event_count": replay["event_count"],
                    "projection_build_id": projection_build.get("projection_id"),
                    "projection_status": projection_status["status"],
                    "projection_output_hash": sha256_json(projection_artifacts),
                    "canonical_kind_values_only": sorted(set(all_downstream_kind_values)),
                },
                "immutability": {
                    "accepted_final_plan_unchanged": plan == accepted_final_plan_before,
                    "caller_proposal_unchanged": plan["stage2_proposal"] == caller_proposal_before,
                    "accepted_response_retains_alias": any(row.get("kind") == ALIAS_KIND for row in plan["stage2_proposal"]["choices"]),
                },
                "canonical_input_origin_unknown": {
                    "canonical_preserved": canonical_input["choices"][0]["kind"] == CANONICAL_KIND,
                    "origin_preserved": origin_input["choices"][0]["kind"] == ORIGIN_KIND,
                    "unknown_unchanged_for_normal_rejection": unknown_input["choices"][0]["kind"] == "unknown_kind",
                },
                "downstream_alias_absent": ALIAS_KIND not in all_downstream_kind_values,
            }
    finally:
        for key, previous in prior_environment.items():
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work-root", type=Path)
    args = parser.parse_args()
    report = run_regression(args.output, work_root=args.work_root)
    print(json.dumps({"status": report["status"], "output": str(args.output.resolve())}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
