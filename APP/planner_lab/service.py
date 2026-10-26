"""Small, production-service-backed AI Character Planner Lab.

The lab is an inspection and scenario harness. It does not maintain a second
catalog, rank builds, or turn planner prose into authority. All legality checks
are delegated to the real Stage 1 and complete-character services.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.core import Database, FoundryError, canonical_json, sha256_json
from character_builder.service import CharacterBuilderService
from character_creation.service import CharacterCreationExecutionService
from non_sphere_authority import NonSphereAuthorityService
from path_method_authority import (
    CANONICAL_PATH_IDS,
    PATH_DISPLAY_NAMES,
    compatibility_envelope,
    canonicalize_path_ids,
    method_granted_path_ids,
    method_path_compatibility,
    no_compatible_method_error,
)
from stage1.service import Stage1ClipboardService


class CharacterPlannerLab:
    """Use real production prompt, validation, review, and commit boundaries."""

    SCENARIOS = (
        {
            "scenario_id": "zero-owner-locks",
            "label": "Zero-owner-lock delegated Path character",
            "required_path_ids": [],
            "ai_final_path_ids": list(CANONICAL_PATH_IDS),
            "owner_reason": "Leave every advancing Path open; zero owner locks is a legal delegation state, not a final no-Path decision.",
            "ai_reason": "Choose a legal Method and final Path set from the complete offered envelope; the server derives any extra Method-granted Paths.",
        },
        {
            "scenario_id": "body-one-path",
            "label": "One-Path Body character",
            "required_path_ids": ["tianxia.path.body_refining"],
            "owner_reason": "A body-first character whose future Method route stays narrow and explicit.",
            "ai_reason": "Choose a Method with an explicit Body AP grant; do not infer compatibility from the name.",
        },
        {
            "scenario_id": "qi-one-path",
            "label": "One-Path Qi character",
            "required_path_ids": ["tianxia.path.qi_cultivation"],
            "owner_reason": "A conventional internal-circulation route with one required advancing track.",
            "ai_reason": "Prefer an offered Method whose authority grants Qi AP, while leaving later choices open.",
        },
        {
            "scenario_id": "dual-sword",
            "label": "Dual-Path sword character",
            "required_path_ids": ["tianxia.path.body_refining", "tianxia.path.qi_cultivation"],
            "owner_reason": "A sword practitioner whose bodily discipline and qi circulation reinforce one style.",
            "ai_reason": "Use a dual-track Method only when both explicit AP grants are present.",
        },
        {
            "scenario_id": "jiang-yun-all-three",
            "label": "All-three-Path Jiang Yun",
            "required_path_ids": list(CANONICAL_PATH_IDS),
            "owner_reason": "Preserve the owner’s integrated Body, Qi, and Spirit identity without claiming track ownership at level 0.",
            "ai_reason": "Select only a Method with explicit AP grants for all three required advancing Paths; access remains a separate check.",
        },
        {
            "scenario_id": "spirit-dream-investigator",
            "label": "Spirit dream investigator",
            "required_path_ids": ["tianxia.path.spirit_awakening"],
            "owner_reason": "A spirit-facing investigator centered on perception, dreams, and interpretation.",
            "ai_reason": "Keep the Method choice within the Spirit grant envelope and leave mechanics to the Factory.",
        },
        {
            "scenario_id": "scholar-support",
            "label": "Noncombat scholar/support character",
            "required_path_ids": ["tianxia.path.qi_cultivation"],
            "owner_reason": "A support-oriented scholar needs a lawful future route without a forced combat identity.",
            "ai_reason": "Use catalog descriptions for thematic review, but accept only explicit Method AP authority.",
        },
    )

    def __init__(
        self,
        db: Database,
        *,
        execution_service: CharacterCreationExecutionService | None = None,
    ):
        self.db = db
        self.authority = NonSphereAuthorityService(db)
        self.builder = CharacterBuilderService(db)
        self.stage1 = Stage1ClipboardService(db)
        self.execution = execution_service

    def _method_rows(self) -> list[dict[str, Any]]:
        return self.authority.method_catalog(initial_creation=True)["records"]

    def authority_envelope(self, required_path_ids: list[str] | None = None) -> dict[str, Any]:
        return compatibility_envelope(required_path_ids or [], self._method_rows())

    def method_review(self, required_path_ids: list[str], method_id: str) -> dict[str, Any]:
        required = canonicalize_path_ids(required_path_ids, allow_empty=False)
        method = self.authority.methods.get(method_id)
        if method is None:
            raise FoundryError(
                "NS1R_METHOD_ID_UNKNOWN",
                "The selected Method ID is not accepted authority.",
                details={"method_id": method_id},
            )
        compatibility = method_path_compatibility(required, method)
        return {
            "method_id": method_id,
            "name": method.get("name"),
            "source_description": method.get("acquisition", {}).get("becoming_primary") or method.get("name"),
            "explicit_granted_path_ids": compatibility["granted_path_ids"],
            "required_path_ids": compatibility["required_path_ids"],
            "missing_path_ids": compatibility["missing_path_ids"],
            "compatible": compatibility["compatible"],
            "initial_creation_selectable": bool(method.get("initial_creation_selectable")),
            "access": deepcopy(method.get("method_planning") or {}),
        }

    def choose_demonstration_method(self, required_path_ids: list[str]) -> str:
        """Choose a deterministic demonstrator, not a claimed best build."""
        required = canonicalize_path_ids(required_path_ids, allow_empty=False)
        rows = self._method_rows()
        compatible = [
            row for row in rows
            if method_path_compatibility(required, row)["compatible"]
        ]
        if not compatible:
            raise no_compatible_method_error(required)
        # Keep the scenarios reproducible while explicitly avoiding a thematic
        # or power ranking: authority order is the only tie-breaker.
        return sorted(compatible, key=lambda row: row["method_id"])[0]["method_id"]

    def scenario_report(self, scenario: dict[str, Any]) -> dict[str, Any]:
        required = canonicalize_path_ids(scenario["required_path_ids"], allow_empty=True)
        final_paths = canonicalize_path_ids(
            scenario.get("ai_final_path_ids") or required,
            allow_empty=False,
        )
        method_id = scenario.get("method_id") or self.choose_demonstration_method(final_paths)
        review = self.method_review(final_paths, method_id)
        paths = {
            row["path_id"]: {
                "name": row["display_name"],
                "source_description": row.get("path_profile", {}).get("primary_roles"),
            }
            for row in self.authority.path_catalog()["records"]
        }
        compatibility = self.authority_envelope(required)
        actual_advancing = list(review["explicit_granted_path_ids"])
        extra_grants = [path_id for path_id in actual_advancing if path_id not in final_paths]
        report = {
            "scenario_id": scenario["scenario_id"],
            "label": scenario["label"],
            "chosen_by_owner": {
                "path_ids": required,
                "reason": scenario["owner_reason"],
            },
            "chosen_by_ai": {
                "method_id": method_id,
                "path_ids": final_paths,
                "reason": scenario["ai_reason"],
                "selection_basis": "deterministic authority-order demonstrator; not a thematic or power ranking",
            },
            "actual_advancing_path_ids": actual_advancing,
            "extra_method_granted_path_ids": extra_grants,
            "automatic_grants": [
                {"path_id": path_id, "source": "method_explicit_ap_grant", "provenance": "automatic"}
                for path_id in extra_grants
            ],
            "unavailable_or_rejected": [],
            "unresolved_owner_decision": [
                "The owner still judges thematic coherence and access-story fit.",
                "The owner retains no hard-locked Path requirement in this scenario." if not required else "",
            ],
            "source_descriptions": {
                "paths": {path_id: paths.get(path_id) for path_id in final_paths},
                "method": review,
            },
            "authority_envelope": compatibility,
            "level_zero_note": "All three tracks remain present and dormant at attainment 0; the selected IDs describe Method requirements.",
        }
        report["unresolved_owner_decision"] = [item for item in report["unresolved_owner_decision"] if item]
        if not review["compatible"]:
            report["unavailable_or_rejected"].append({
                "reason": "Method lacks an explicit AP grant for every owner-required Path.",
                "expected_path_ids": required,
                "proposed_method_granted_path_ids": review["explicit_granted_path_ids"],
                "unsupported_path_ids": review["missing_path_ids"],
            })
        return report

    def scenario_reports(self) -> list[dict[str, Any]]:
        return [self.scenario_report(deepcopy(scenario)) for scenario in self.SCENARIOS]

    @staticmethod
    def render_report(reports: list[dict[str, Any]]) -> str:
        lines = ["AI CHARACTER PLANNER LAB", "", "The server validates legality; the owner judges thematic coherence.", ""]
        for report in reports:
            owner = report["chosen_by_owner"]
            ai = report["chosen_by_ai"]
            lines.extend([
                report["label"],
                f"  chosen by owner: {', '.join(owner['path_ids'])}",
                f"  chosen by AI: {ai['method_id']}",
                f"  exact compatibility: {report['source_descriptions']['method']['compatible']}",
                f"  owner reason: {owner['reason']}",
                f"  AI reason: {ai['reason']}",
                "  unresolved: owner thematic/access review remains",
                "",
            ])
        return "\n".join(lines)

    def corrected_request_contract(
        self,
        required_path_ids: list[str],
        *,
        method_id: str | None = None,
    ) -> dict[str, Any]:
        """Return the corrected request contract used for a real project.

        Callers that need executable hashes should use ``new_manual_run`` so
        Stage 1's production builder supplies the exact revision/content lock.
        """

        required = canonicalize_path_ids(required_path_ids, allow_empty=False)
        envelope = self.authority_envelope(required)
        selected_method = method_id or (envelope["compatible_method_ids"][0] if envelope["compatible_method_ids"] else None)
        if selected_method is None:
            raise no_compatible_method_error(required)
        review = self.method_review(required, selected_method)
        return {
            "schema": "TianxiaFoundry.PathMethodCorrectedRequest.v1",
            "decision_slots": {
                "path_choice": {
                    "label": "Advancing Path Requirements",
                    "min_selections": 1,
                    "max_selections": 3,
                    "required_choice_ids": required,
                },
                "method_choice": {
                    "selection_semantics": "method_acquisition_and_primary_method_authority",
                    "compatible_method_ids": envelope["compatible_method_ids"],
                },
            },
            "path_method_authority": envelope,
            "corrected_method_id": selected_method,
            "method_review": review,
            "request_identity_note": "The executable prompt/request hash is regenerated by the real Stage 1 builder for the active revision and content lock.",
        }

    def analyze_jiang_request(
        self,
        request: dict[str, Any],
        plan: dict[str, Any],
    ) -> dict[str, Any]:
        """Classify the supplied Jiang plan without importing it as authority."""

        prompt = request.get("stage1_prompt") or {}
        envelope = prompt.get("envelope") or {}
        slots = {row.get("slot_id"): row for row in envelope.get("decision_slots") or []}
        path_slot = slots.get("path_choice") or {}
        path_decision = next(
            (row for row in (plan.get("stage1_response", {}).get("response_payload", {}).get("decisions") or []) if row.get("slot_id") == "path_choice"),
            {},
        )
        required = list(path_slot.get("required_choice_ids") or path_decision.get("choice_ids") or [])
        proposed_paths = list(path_decision.get("choice_ids") or [])
        offered = {row.get("choice_id") for row in path_slot.get("choices") or []}
        method_id = (
            ((plan.get("stage2_proposal") or {}).get("catalog_priority_order") or {}).get("method_choice_id")
            or next(
                (row.get("choice_ids", [None])[0] for row in (plan.get("stage1_response", {}).get("response_payload", {}).get("decisions") or []) if row.get("slot_id") == "method_choice"),
                None,
            )
        )
        method_review = self.method_review(required or proposed_paths, method_id) if method_id else None
        return {
            "request_advertised_max_one": path_slot.get("max_selections") == 1,
            "request_advertised_max_selections": path_slot.get("max_selections"),
            "proposed_path_ids": proposed_paths,
            "offered_path_ids": sorted(offered),
            "out_of_envelope_path_ids": sorted(set(proposed_paths) - offered),
            "required_path_ids": required,
            "method_id": method_id,
            "method_path_review": method_review,
            "mismatches": {
                "cardinality": path_slot.get("max_selections") != len(proposed_paths),
                "method_path": bool(method_review and not method_review["compatible"]),
                "offered_ids": bool(set(proposed_paths) - offered),
            },
            "classification": "metadata_conflict_and_method_path_mismatch" if (path_slot.get("max_selections") == 1 and len(proposed_paths) > 1) else "server_validation_required",
        }

    def new_manual_run(self, project_id: str, *, idempotency_key: str) -> dict[str, Any]:
        if self.execution is None:
            raise FoundryError("PLN1_EXECUTION_SERVICE_REQUIRED", "A real CharacterCreationExecutionService is required for a complete planner-lab run.")
        return self.execution.start(project_id, execution_mode="MANUAL_CHAT", idempotency_key=idempotency_key)

    def parse_complete_response(self, response_text: str) -> dict[str, Any]:
        if self.execution is None:
            return CharacterCreationExecutionService._parse_plan(response_text)[0]
        return self.execution._parse_plan(response_text)[0]

    def submit_complete_response(self, run_id: str, response_text: str, request_sha256: str) -> dict[str, Any]:
        if self.execution is None:
            raise FoundryError("PLN1_EXECUTION_SERVICE_REQUIRED", "A real CharacterCreationExecutionService is required for complete-response validation.")
        return self.execution.submit_manual(run_id, response_text=response_text, request_sha256=request_sha256)

    def finalize_reviewed_plan(self, run_id: str) -> dict[str, Any]:
        if self.execution is None:
            raise FoundryError("PLN1_EXECUTION_SERVICE_REQUIRED", "A real CharacterCreationExecutionService is required for final-plan commit.")
        return self.execution.finalize(run_id)


PlannerLab = CharacterPlannerLab
