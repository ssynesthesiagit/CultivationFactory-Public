"""Fresh production-boundary acceptance for REC1-P1CR4.

The response is a deterministic, publication-safe equivalent of a delegated
Manual Chat answer.  The important boundary in this runner is the real
``manual-response-file`` API route; no private response bytes or provider key
are used.
"""

from __future__ import annotations

import argparse
import copy
import io
import json
import sys
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api import create_app
from app.core import Database, FoundryError, Settings, canonical_json, sha256_bytes, sha256_file, sha256_json
from canonical_catalog.service import CanonicalCatalogAuthorityService
from catalog.service import CatalogService
from character_creation.response_materialization import RESPONSE_SCHEMA
from character_builder import CharacterBuilderService
from character_sheet.service import CharacterSheetService
from project_store.service import ProjectStore
from vendor_adapter.service import FactoryAdapter


PINNED_FACTORY = ROOT / "BundledContent" / "Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip"
PINNED_FACTORY_SHA256 = "4daf167cf634f27efef4dd2f1c8700bb4b7037cc6234c32be1af90aea5916385"
TARGET_CL = 20
POWER_BAND = "rival/boss"
PATH_IDS = ["tianxia.path.body_refining", "tianxia.path.spirit_awakening"]
SUBPATH_IDS = [
    "tianxia.subpath.body.flesh_crucible",
    "tianxia.tradition.spirit.dreamweaver",
]
METHOD_ID = "METHOD-087"
FOUNDATION_ID = "ancient_desolate_sacred_body_v0_2C"
BACKGROUND_ID = "tianxia.background.abandoned_orphan"
BACKGROUND_SPHERE_ID = "tianxia.background_sphere.scoundrel"
BACKGROUND_TALENT_ID = "tianxia.background_talent.scoundrel.hidden_tool_cache"
ORIGIN_INSIGHT_ID = "tianxia.origin_insight.street_hardened"


def _project_snapshot(db: Database, project_id: str) -> dict[str, Any]:
    with db.connection() as conn:
        project = conn.execute(
            "SELECT revision,project_json FROM projects WHERE project_id=?",
            (project_id,),
        ).fetchone()
        events = [
            row[0]
            for row in conn.execute(
                "SELECT event_json FROM events WHERE project_id=? ORDER BY sequence_no",
                (project_id,),
            )
        ]
    return {
        "revision": project["revision"] if project else None,
        "project_json": project["project_json"] if project else None,
        "events": events,
    }


def _choice_by_id(options: dict[str, Any], slot_id: str, choice_id: str) -> dict[str, Any]:
    category = next(row for row in options["categories"] if row["slot_id"] == slot_id)
    for choice in category.get("choices") or []:
        if choice.get("choice_id") == choice_id:
            return choice
    raise FoundryError(
        "REC1_P1CR4_ACCEPTANCE_CHOICE_MISSING",
        "The pinned builder did not expose a required acceptance choice.",
        details={"slot_id": slot_id, "choice_id": choice_id},
        status_code=500,
    )


def _owner_path(row: dict[str, Any]) -> str | None:
    return row.get("owning_path_id") if isinstance(row.get("owning_path_id"), str) else None


def _build_project(builder: CharacterBuilderService, *, source_reference: str) -> dict[str, Any]:
    options = builder.options()
    subpath_category = next(row for row in options["categories"] if row["slot_id"] == "subpath_choice")
    for path_id, subpath_id in zip(PATH_IDS, SUBPATH_IDS):
        row = _choice_by_id(options, "subpath_choice", subpath_id)
        if _owner_path(row) != path_id:
            raise FoundryError(
                "REC1_P1CR4_ACCEPTANCE_SUBPATH_OWNER_INVALID",
                "A required acceptance Subpath is not owned by its selected Path.",
                details={"path_id": path_id, "subpath_id": subpath_id, "owner": _owner_path(row)},
                status_code=500,
            )
    method = _choice_by_id(options, "method_choice", METHOD_ID)
    route_options = (method.get("method_planning") or {}).get("owner_route_options") or []
    route = next((row for row in route_options if row.get("choice_id") == "route-personal-teacher"), None)
    if not route:
        raise FoundryError(
            "REC1_P1CR4_ACCEPTANCE_METHOD_ROUTE_MISSING",
            "METHOD-087 did not expose the required advertised access route.",
            details={"method_id": METHOD_ID, "route_options": route_options},
            status_code=500,
        )

    sphere_category = next(row for row in options["categories"] if row["slot_id"] == "sphere_priorities")
    planning_spheres = [
        row["choice_id"]
        for row in sorted(sphere_category.get("choices") or [], key=lambda value: value["choice_id"])
        if isinstance(row.get("choice_id"), str) and row.get("planning_priority_available") is not False
    ][:15]
    talent_category = next(row for row in options["categories"] if row["slot_id"] == "advancement_skeleton")
    planning_talents = [
        row["choice_id"]
        for row in sorted(talent_category.get("choices") or [], key=lambda value: value["choice_id"])
        if isinstance(row.get("choice_id"), str) and row.get("planning_priority_available") is not False
    ][:3]
    if len(planning_spheres) < 15 or len(planning_spheres) != len(set(planning_spheres)):
        raise FoundryError(
            "REC1_P1CR4_ACCEPTANCE_PLANNING_UNRESOLVED",
            "The pinned builder did not expose fifteen distinct Sphere planning priorities.",
            details={"sphere_priority_count": len(planning_spheres)},
            status_code=500,
        )
    item_category = next(row for row in options["categories"] if row["slot_id"] == "item_priorities")
    item_priority = next(
        row["choice_id"]
        for row in sorted(item_category.get("choices") or [], key=lambda value: value["choice_id"])
        if isinstance(row.get("choice_id"), str) and row.get("planning_priority_available") is not False
    )

    selections = {
        "path_choice": PATH_IDS,
        "method_choice": [METHOD_ID],
        "foundation_choice": [FOUNDATION_ID],
        "subpath_choice": SUBPATH_IDS,
        "background_choice": [BACKGROUND_ID],
        "background_sphere_choice": [BACKGROUND_SPHERE_ID],
        "background_talent_choice": [BACKGROUND_TALENT_ID],
        "origin_insight_choice": [ORIGIN_INSIGHT_ID],
    }
    for slot_id, values in selections.items():
        for choice_id in values:
            _choice_by_id(options, slot_id, choice_id)

    created = builder.create_project(
        working_name="",
        concept="",
        target_cl=TARGET_CL,
        power_band=POWER_BAND,
        source_reference=source_reference,
        creation_mode="detailed",
        ability_scores={},
        selections=selections,
        sphere_priority_ids=planning_spheres,
        talent_priority_ids=planning_talents,
        method_planning_mode="EXACT",
        method_route_choice=route["choice_id"],
        method_learning_note="I accept the advertised personal-teacher access route for this exact Method.",
        generation_route="ai_bootstrap",
    )
    created["acceptance_planning"] = {
        "sphere_priority_ids": planning_spheres,
        "talent_priority_ids": planning_talents,
        "item_priority_id": item_priority,
        "method_route": route,
    }
    return created


def _semantic_response(run: dict[str, Any], root: Path, *, planning: dict[str, Any]) -> dict[str, Any]:
    request = run["request"]
    envelope = request["delegated_choice_envelope"]
    choices = envelope.get("choices_by_slot") or {}
    allowed = envelope.get("allowed_choice_ids_by_slot") or {}
    selected_spheres = list(planning["sphere_priority_ids"][:10])
    if any(value not in (allowed.get("sphere_priorities") or []) for value in selected_spheres):
        raise FoundryError("REC1_P1CR4_ACCEPTANCE_SPHERE_AUTHORITY_INVALID", "The acceptance Sphere fixture is outside the frozen envelope.", status_code=500)

    catalog = CanonicalCatalogAuthorityService(root)
    authority = (
        (envelope.get("typed_choice_authority_by_slot") or {})
        .get("advancement_skeleton", {})
        .get("stage2_authority_by_choice")
        or {}
    )
    free_by_sphere: dict[str, list[tuple[int, str, str]]] = defaultdict(list)
    ordinary_candidates: list[tuple[int, str, str, str]] = []
    for talent_id, record_authority in sorted(authority.items()):
        if not isinstance(record_authority, dict):
            continue
        sphere_id = record_authority.get("sphere_id")
        if sphere_id not in selected_spheres:
            continue
        try:
            canonical_id = catalog.resolve_talent_id(talent_id)
            talent = catalog.get_talent(talent_id)
        except FoundryError:
            continue
        if talent.get("ordinary_talent") is not True or talent.get("creator_selectability_can_be_evaluated_safely") is not True:
            continue
        minimum_cl = int(record_authority.get("minimum_cl") or 1)
        allowed_kinds = set(record_authority.get("allowed_kinds") or [])
        if (
            "ai_bootstrap_talent_acquisition" in allowed_kinds
            and minimum_cl <= 1
            and record_authority.get("free_sphere_talent_eligible") is not False
        ):
            free_by_sphere[sphere_id].append((minimum_cl, canonical_id, talent_id))
        if "level_talent_acquisition" in allowed_kinds:
            ordinary_candidates.append((minimum_cl, canonical_id, talent_id, sphere_id))

    free_pairs: list[dict[str, str]] = []
    free_canonical_ids: set[str] = set()
    for sphere_id in selected_spheres:
        candidates = sorted(free_by_sphere.get(sphere_id) or [])
        candidate = next((row for row in candidates if row[1] not in free_canonical_ids), None)
        if not candidate:
            raise FoundryError(
                "REC1_P1CR4_ACCEPTANCE_FREE_TALENT_UNRESOLVED",
                "The pinned source authority cannot supply one legal free Talent for every selected Sphere.",
                details={"sphere_id": sphere_id},
                status_code=500,
            )
        free_pairs.append({"sphere_id": sphere_id, "talent_id": candidate[2]})
        free_canonical_ids.add(candidate[1])

    ordinary_by_canonical: dict[str, tuple[int, str, str, str]] = {}
    for row in sorted(ordinary_candidates):
        ordinary_by_canonical.setdefault(row[1], row)
    ordinary_pool = [row for row in ordinary_by_canonical.values() if row[1] not in free_canonical_ids]
    ordinary_ids: list[str] = []
    for effective_cl in range(1, TARGET_CL + 1):
        available = [row for row in ordinary_pool if row[0] <= effective_cl]
        if not available:
            raise FoundryError(
                "REC1_P1CR4_ACCEPTANCE_ORDINARY_TALENT_UNRESOLVED",
                "The pinned source authority cannot supply a causal ordinary-Talent sequence through CL20.",
                details={"effective_cl": effective_cl},
                status_code=500,
            )
        row = available[0]
        ordinary_pool.remove(row)
        ordinary_ids.append(row[2])

    progression_by_cl = {
        str(effective_cl): (
            PATH_IDS[0]
            if effective_cl < 4
            else PATH_IDS[{4: 0, 8: 1, 12: 0, 16: 1, 19: 0}.get(effective_cl, 1)]
        )
        for effective_cl in range(1, TARGET_CL + 1)
    }
    selected_milestones = [
        row
        for row in envelope.get("advancement_choice_milestones") or []
        if isinstance(row, dict)
        and row.get("path_id") in PATH_IDS
        and progression_by_cl.get(str(row.get("cl"))) == row.get("path_id")
    ]
    selected_milestones.sort(key=lambda row: (int(row.get("cl") or 0), PATH_IDS.index(row.get("path_id"))))
    insight_authority = (
        (envelope.get("typed_choice_authority_by_slot") or {})
        .get("insight_priorities", {})
        .get("stage2_authority_by_choice")
        or {}
    )
    insight_choices = choices.get("insight_priorities") or {}
    present_choice_ids = set(PATH_IDS) | set(SUBPATH_IDS) | {METHOD_ID, FOUNDATION_ID} | set(selected_spheres)
    present_choice_ids.update(row["talent_id"] for row in free_pairs)
    used_insights: set[str] = set()
    scores = {"STR": 8, "DEX": 14, "CON": 14, "INT": 15, "WIS": 12, "CHA": 8}
    insight_occurrences: list[dict[str, Any]] = []
    ability_changes: dict[str, dict[str, Any]] = {}
    asi_paths: set[str] = set()
    for milestone in selected_milestones:
        milestone_id = milestone.get("milestone_id")
        path_id = milestone.get("path_id")
        effective_cl = int(milestone.get("cl") or 0)
        if path_id not in asi_paths:
            ability = "INT" if path_id == PATH_IDS[0] else "WIS"
            ability_changes[str(milestone_id)] = {"deltas": {ability: 2}}
            asi_paths.add(path_id)
            scores[ability] += 2
            continue
        selected_insight: tuple[str, dict[str, Any]] | None = None
        for insight_id in sorted(allowed.get("insight_priorities") or []):
            if insight_id in used_insights:
                continue
            authority_row = insight_authority.get(insight_id) or {}
            allowed_cls = authority_row.get("allowed_cls") or authority_row.get("allowed_effective_cls")
            if isinstance(allowed_cls, list) and effective_cl not in allowed_cls:
                continue
            choice_row = insight_choices.get(insight_id) or {}
            required_ids = {
                row.get("target_id")
                for row in choice_row.get("prerequisites") or []
                if isinstance(row, dict) and row.get("operator") == "requires"
            }
            if not required_ids.issubset(present_choice_ids | used_insights):
                continue
            rule = authority_row.get("ability_change") or authority_row.get("insight_ability_change") or {}
            parameters: dict[str, Any] = {}
            if rule:
                amount = int(rule.get("amount") or 1)
                ability = next(
                    (
                        value
                        for value in rule.get("allowed_abilities") or []
                        if isinstance(value, str)
                        and scores.get(value, 0) + amount <= int(rule.get("cap") or 20)
                    ),
                    None,
                )
                if ability is None:
                    continue
                parameters = {"ability": ability}
            selected_insight = (insight_id, parameters)
            break
        if selected_insight is None:
            raise FoundryError(
                "REC1_P1CR4_ACCEPTANCE_INSIGHT_UNRESOLVED",
                "The pinned source authority cannot supply one distinct legal Insight for every selected Path milestone.",
                details={"milestone_id": milestone_id, "effective_cl": effective_cl},
                status_code=500,
            )
        insight_id, parameters = selected_insight
        used_insights.add(insight_id)
        present_choice_ids.add(insight_id)
        if parameters:
            scores[parameters["ability"]] += int(
                (insight_authority.get(insight_id) or {}).get("ability_change", {}).get("amount")
                or (insight_authority.get(insight_id) or {}).get("insight_ability_change", {}).get("amount")
                or 1
            )
        occurrence: dict[str, Any] = {"insight_id": insight_id, "milestone_id": milestone_id}
        if parameters:
            occurrence["parameters"] = parameters
        insight_occurrences.append(occurrence)

    response = {
        "schema": RESPONSE_SCHEMA,
        "request_sha256": request["request_sha256"],
        "selection_intent": {
            "by_slot": {
                "path_choice": PATH_IDS,
                "method_choice": [METHOD_ID],
                "foundation_choice": [FOUNDATION_ID],
                "subpath_choice": SUBPATH_IDS,
                "background_choice": [BACKGROUND_ID],
                "background_sphere_choice": [BACKGROUND_SPHERE_ID],
                "background_talent_choice": [BACKGROUND_TALENT_ID],
                "origin_insight_choice": [ORIGIN_INSIGHT_ID],
                "item_priorities": [planning["item_priority_id"]],
            }
        },
        "acquisition_intent": {
            "sphere_free_talent_pairs": free_pairs,
            "ordinary_talent_ids": ordinary_ids,
            "insight_occurrences": insight_occurrences,
        },
        "bounded_choices": {
            "ability_scores": {"STR": 8, "DEX": 14, "CON": 14, "INT": 15, "WIS": 12, "CHA": 8},
            "background_ability": "DEX",
            "ability_score_changes_by_milestone_id": ability_changes,
            "path_progression_by_cl": progression_by_cl,
        },
        "owner_descriptive_fields": {
            "identity": {"name": "REC1-P1CR4 Dual Path Response"},
            "concept": "A source-backed Body Refining and Spirit Awakening production acceptance character.",
        },
    }
    return response


def _request_schema(client: TestClient, run_id: str, headers: dict[str, str]) -> dict[str, Any]:
    package = client.get(f"/api/character-creation/runs/{run_id}/complete-request.zip", headers=headers)
    if package.status_code != 200:
        raise FoundryError("REC1_P1CR4_ACCEPTANCE_REQUEST_PACKAGE_INVALID", "The complete request endpoint did not return 200.", details={"status": package.status_code, "body": package.text[:2000]}, status_code=500)
    with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
        if archive.testzip() is not None or "RESPONSE_SCHEMA.json" not in archive.namelist():
            raise FoundryError("REC1_P1CR4_ACCEPTANCE_REQUEST_PACKAGE_INVALID", "The complete request ZIP failed its CRC/schema check.", status_code=500)
        return json.loads(archive.read("RESPONSE_SCHEMA.json"))["preferred_response"]


def _response_schema_slot(response_schema: dict[str, Any], slot_id: str) -> dict[str, Any]:
    selection = response_schema.get("properties", {}).get("selection_intent", {})
    by_slot = selection.get("properties", {}).get("by_slot", {}) if isinstance(selection, dict) else {}
    properties = by_slot.get("properties", {}) if isinstance(by_slot, dict) else {}
    slot_schema = properties.get(slot_id) if isinstance(properties, dict) else None
    if not isinstance(slot_schema, dict):
        raise FoundryError(
            "REC1_P1CR4_ACCEPTANCE_RESPONSE_SCHEMA_SLOT_MISSING",
            "The sealed preferred response schema does not expose the required selection slot.",
            details={"slot_id": slot_id},
            status_code=500,
        )
    return slot_schema


def _start_run(client: TestClient, builder: CharacterBuilderService, headers: dict[str, str], *, source: str) -> tuple[dict[str, Any], dict[str, Any]]:
    created = _build_project(builder, source_reference=source)
    project_id = created["project"]["project_id"]
    response = client.post(
        f"/api/projects/{project_id}/character-creation/runs",
        headers=headers,
        json={"execution_mode": "MANUAL_CHAT", "idempotency_key": f"p1cr4.{source.replace(' ', '-')}.{project_id[:8]}"},
    )
    if response.status_code != 200:
        raise FoundryError("REC1_P1CR4_ACCEPTANCE_RUN_START_FAILED", "The production run-start endpoint failed.", details={"status": response.status_code, "body": response.text[:1000]}, status_code=500)
    return created, response.json()


def _error_category(run: dict[str, Any]) -> str | None:
    error = run.get("submission_error") or ((run.get("validation") or {}).get("last_submission_error") or {})
    return error.get("category") or error.get("stage") if isinstance(error, dict) else None


def _run_diagnostic_checks(client: TestClient, builder: CharacterBuilderService, execution: Any, headers: dict[str, str], response: dict[str, Any]) -> dict[str, Any]:
    checks: dict[str, Any] = {}

    _created, malformed_start = _start_run(client, builder, headers, source="REC1-P1CR4 malformed JSON")
    malformed_run_id = malformed_start["run_id"]
    malformed = client.post(
        f"/api/character-creation/runs/{malformed_run_id}/manual-response-file?filename=malformed.json",
        headers={**headers, "Content-Type": "application/json"},
        content=b'{"schema":',
    )
    malformed_run = malformed.json()
    malformed_error = malformed_run.get("submission_error") or {}
    checks["malformed_json_category_and_line_column"] = (
        malformed.status_code == 200
        and malformed_run.get("status") == "NEEDS_REVIEW"
        and _error_category(malformed_run) == "JSON_SCHEMA"
        and isinstance(malformed_error.get("details", {}).get("line"), int)
        and isinstance(malformed_error.get("details", {}).get("column"), int)
    )

    _created, binding_start = _start_run(client, builder, headers, source="REC1-P1CR4 request binding")
    binding_run_id = binding_start["run_id"]
    binding_response = copy.deepcopy(response)
    binding_response["request_sha256"] = "0" * 64
    binding = client.post(
        f"/api/character-creation/runs/{binding_run_id}/manual-response-file",
        params={"filename": "binding-mismatch.json"},
        headers={**headers, "Content-Type": "application/json"},
        content=canonical_json(binding_response).encode("utf-8"),
    )
    # A request-binding mismatch is retryable: the manual-response-file route
    # records the failed upload while retaining WAITING_FOR_RESPONSE, so prove
    # the diagnostic through the real persisted-run GET boundary as well.
    binding_response_body = binding.json()
    binding_persisted = client.get(f"/api/character-creation/runs/{binding_run_id}", headers=headers)
    binding_run = binding_persisted.json() if binding_persisted.status_code == 200 else {}
    checks["request_binding_category"] = (
        binding.status_code == 409
        and binding_persisted.status_code == 200
        and binding_run.get("status") in {"WAITING_FOR_RESPONSE", "NEEDS_REVIEW"}
        and _error_category(binding_run) == "REQUEST_BINDING"
    )

    _created, semantic_start = _start_run(client, builder, headers, source="REC1-P1CR4 semantic legality")
    semantic_run_id = semantic_start["run_id"]
    semantic_internal = execution.get(semantic_run_id)
    semantic_response = copy.deepcopy(response)
    semantic_response["request_sha256"] = semantic_internal["request"]["request_sha256"]
    semantic_response["selection_intent"]["by_slot"]["path_choice"] = ["tianxia.path.qi_cultivation"]
    semantic = client.post(
        f"/api/character-creation/runs/{semantic_run_id}/manual-response-file?filename=semantic.json",
        headers={**headers, "Content-Type": "application/json"},
        content=canonical_json(semantic_response).encode("utf-8"),
    )
    semantic_run = semantic.json()
    checks["semantic_legality_category"] = (
        semantic.status_code == 200
        and semantic_run.get("status") == "NEEDS_REVIEW"
        and _error_category(semantic_run) in {"SEMANTIC_AUTHORITY", "LEGALITY"}
    )
    checks["all_diagnostic_categories_proven"] = all(checks.values())
    return {
        "checks": checks,
        "malformed": {"run_id": malformed_run_id, "status": malformed_run.get("status"), "error": malformed_error},
        "binding": {
            "run_id": binding_run_id,
            "submit_status": binding.status_code,
            "submit_error": binding_response_body,
            "persisted_get_status": binding_persisted.status_code,
            "status": binding_run.get("status"),
            "error": binding_run.get("submission_error") or ((binding_run.get("validation") or {}).get("last_submission_error") if isinstance(binding_run.get("validation"), dict) else None),
        },
        "semantic": {"run_id": semantic_run_id, "status": semantic_run.get("status"), "error": semantic_run.get("submission_error")},
    }


def _assert_finalized(
    *,
    settings: Settings,
    db: Database,
    execution: Any,
    finalized: dict[str, Any],
    project_id: str,
    response: dict[str, Any],
    planning: dict[str, Any],
) -> dict[str, Any]:
    if finalized.get("status") != "CLEAN_AND_FINALIZED":
        raise FoundryError("REC1_P1CR4_ACCEPTANCE_FINAL_STATUS_INVALID", "The production Finalize endpoint did not reach CLEAN_AND_FINALIZED.", details={"status": finalized.get("status")}, status_code=409)
    final_plan = finalized.get("final_plan") or {}
    resolution = final_plan.get("resolution") or {}
    selected = resolution.get("selected_choices_by_slot") or {}
    if set(resolution.get("actual_advancing_path_ids") or []) != set(PATH_IDS):
        raise FoundryError("REC1_P1CR4_ACCEPTANCE_PATHS_INVALID", "The final plan did not preserve exactly Body Refining and Spirit Awakening.", details={"paths": resolution.get("actual_advancing_path_ids")}, status_code=409)
    if (
        resolution.get("method_id") != METHOD_ID
        or resolution.get("foundation_id") != FOUNDATION_ID
        or list(selected.get("subpath_choice") or []) != SUBPATH_IDS
    ):
        raise FoundryError(
            "REC1_P1CR4_ACCEPTANCE_NONSPHERE_CHOICES_INVALID",
            "The final plan did not preserve the exact Method/Foundation/Subpath selections.",
            details={
                "method": resolution.get("method_id"),
                "foundation": resolution.get("foundation_id"),
                "subpaths": selected.get("subpath_choice"),
            },
            status_code=409,
        )
    catalog_authority = final_plan.get("catalog_response_authority") or {}
    accepted_spheres = list(catalog_authority.get("accepted_sphere_ids") or [])
    accepted_free = list(catalog_authority.get("accepted_free_sphere_talent_ids") or [])
    accepted_ordinary = list(catalog_authority.get("accepted_ordinary_talent_ids") or [])
    if len(accepted_spheres) < 10 or len(accepted_spheres) != len(set(accepted_spheres)) or len(accepted_free) != len(accepted_spheres) or len(accepted_ordinary) != TARGET_CL:
        raise FoundryError("REC1_P1CR4_ACCEPTANCE_CATALOG_COUNTS_INVALID", "The final canonical grant plan did not preserve the required Sphere/Talent counts.", details={"spheres": len(accepted_spheres), "free_talents": len(accepted_free), "ordinary_talents": len(accepted_ordinary)}, status_code=409)
    intent = (finalized.get("response") or {}).get("parsed_plan", {}).get("canonical_selection_intent") or {}
    if list((intent.get("planning_preferences_by_slot") or {}).get("item_priorities") or []) != [planning["item_priority_id"]]:
        raise FoundryError("REC1_P1CR4_ACCEPTANCE_ITEM_PLANNING_INVALID", "The item planning proposal was not retained as a planning-only semantic preference.", status_code=409)

    dry_run = finalized.get("dry_run") or {}
    if dry_run.get("deterministic") is not True or dry_run.get("independent_compilations") != 2:
        raise FoundryError("REC1_P1CR4_ACCEPTANCE_DETERMINISM_INVALID", "Finalize did not retain deterministic evidence from two isolated compilations.", details={"dry_run": dry_run}, status_code=409)
    portable = (finalized.get("outputs") or {}).get("portable_character") or {}
    audit = portable.get("audit") or {}
    package_path = Path(str(audit.get("path") or ""))
    package_sha = sha256_file(package_path) if package_path.is_file() else None
    if not package_path.is_file() or package_sha != audit.get("sha256") or package_path.stat().st_size != audit.get("bytes"):
        raise FoundryError("REC1_P1CR4_ACCEPTANCE_PACKAGE_INVALID", "Finalize did not produce an identity-verified portable Character package.", details={"path": str(package_path), "audit": audit}, status_code=409)
    if audit.get("crc_validation", {}).get("status") != "VALID" or audit.get("checksum_manifest", {}).get("coverage_status") != "EXACT":
        raise FoundryError("REC1_P1CR4_ACCEPTANCE_PACKAGE_AUDIT_INVALID", "The completed package lacks exact CRC/checksum coverage.", details={"audit": audit}, status_code=409)
    clean_import = portable.get("clean_import") or {}
    first = clean_import.get("first") or {}
    second = clean_import.get("second") or {}
    sheet_proof = clean_import.get("character_sheet") or {}
    gm_proof = clean_import.get("gm_model") or {}
    if (
        first.get("status") not in {"IMPORTED", "GM_SCREEN_SOURCE_CONSUMER_VERIFIED"}
        or second.get("status") not in {"ALREADY_INSTALLED_IDENTICAL", "GM_SCREEN_SOURCE_CONSUMER_VERIFIED"}
        or sheet_proof.get("semantic_equal") is not True
        or gm_proof.get("semantic_equal") is not True
    ):
        raise FoundryError("REC1_P1CR4_ACCEPTANCE_IMPORT_EQUALITY_INVALID", "Export/import/reimport did not prove semantic equality.", details={"clean_import": clean_import}, status_code=409)

    required_package_members = {
        "PACKAGE_MANIFEST.json",
        "SHA256SUMS.txt",
        "Tianxia_GM_Character_Model_v2.json",
        "Tianxia_GM_Character_View_Model_v2.json",
        "Tianxia_Owner_Character_Sheet_v1.json",
        "source/Character_Project.tianxia-project.zip",
        "READINESS.json",
    }
    with zipfile.ZipFile(package_path) as archive:
        members = set(archive.namelist())
        missing_members = sorted(required_package_members - members)
        if missing_members:
            raise FoundryError(
                "REC1_P1CR4_ACCEPTANCE_PACKAGE_MEMBERS_INVALID",
                "The completed ZIP is missing one or more authoritative acceptance members.",
                details={"missing_members": missing_members},
                status_code=409,
            )
        owner_sheet = json.loads(archive.read("Tianxia_Owner_Character_Sheet_v1.json"))
        gm_model = json.loads(archive.read("Tianxia_GM_Character_Model_v2.json"))
    owner_identity = owner_sheet.get("identity") if isinstance(owner_sheet, dict) else {}
    owner_identity = owner_identity if isinstance(owner_identity, dict) else {}
    gm_identity = gm_model.get("identity") if isinstance(gm_model, dict) else {}
    gm_identity = gm_identity if isinstance(gm_identity, dict) else {}
    owner_path_surface = owner_sheet.get("path_and_subpath") if isinstance(owner_sheet, dict) else {}
    owner_path_surface = owner_path_surface if isinstance(owner_path_surface, dict) else {}
    package_bindings = {
        (row.get("path_id"), row.get("subpath_id"))
        for row in owner_path_surface.get("bindings") or []
        if isinstance(row, dict)
    }
    expected_bindings = set(zip(PATH_IDS, SUBPATH_IDS))
    owner_spheres = owner_sheet.get("spheres_and_talents") if isinstance(owner_sheet, dict) else {}
    owner_spheres = owner_spheres if isinstance(owner_spheres, dict) else {}
    exported_sphere_ids = set(owner_spheres.get("sphere_record_ids") or [])
    exported_talent_ids = set(owner_spheres.get("learned_talent_record_ids") or [])
    exported_insight_ids = set(owner_spheres.get("cultivation_insight_record_ids") or [])
    exported_insight_occurrences = [
        row for row in owner_spheres.get("cultivation_insight_occurrences") or []
        if isinstance(row, dict)
    ]
    package_member_checks = {
        "required_members_present": not missing_members,
        "owner_edited_identity_exported": (
            owner_identity.get("display_name") == "REC1-P1CR4 Owner Edited Name"
            and owner_identity.get("concept") == "Owner-edited production concept."
        ),
        "gm_model_identity_exported": (
            gm_identity.get("display_name") == "REC1-P1CR4 Owner Edited Name"
            and gm_identity.get("concept") == "Owner-edited production concept."
        ),
        "both_path_subpath_bindings_exported": package_bindings == expected_bindings,
        "accepted_spheres_survive_export": set(accepted_spheres).issubset(exported_sphere_ids),
        "accepted_free_and_ordinary_talents_survive_export": set(accepted_free + accepted_ordinary).issubset(exported_talent_ids),
        "accepted_insights_survive_export": (
            bool(exported_insight_ids)
            and bool(exported_insight_occurrences)
            and {
                row.get("insight_id") for row in exported_insight_occurrences
                if isinstance(row.get("insight_id"), str)
            }.issubset(exported_insight_ids)
        ),
    }
    if not all(package_member_checks.values()):
        raise FoundryError(
            "REC1_P1CR4_ACCEPTANCE_PACKAGE_SURFACES_INVALID",
            "The completed ZIP did not preserve the owner-edited identity and required selection bindings.",
            details={"checks": package_member_checks, "bindings": sorted(package_bindings)},
            status_code=409,
        )

    reopened_db = Database(settings)
    reopened_db.migrate()
    reopened_project = ProjectStore(reopened_db).get_project(project_id)["project"]
    reopened_sheet = CharacterSheetService(reopened_db).sheet(project_id)
    identity = reopened_sheet.get("identity") or {}
    if identity.get("name") != "REC1-P1CR4 Owner Edited Name" or identity.get("concept") != "Owner-edited production concept.":
        raise FoundryError("REC1_P1CR4_ACCEPTANCE_REOPEN_INVALID", "The fresh ProjectStore/CharacterSheetService reopen did not preserve the owner edit.", details={"identity": identity}, status_code=409)
    return {
        "status": finalized.get("status"),
        "project_revision": reopened_project.get("revision"),
        "method_id": resolution.get("method_id"),
        "foundation_id": resolution.get("foundation_id"),
        "paths": list(resolution.get("actual_advancing_path_ids") or []),
        "subpaths": list(selected.get("subpath_choice") or []),
        "sphere_count": len(accepted_spheres),
        "free_talent_count": len(accepted_free),
        "ordinary_talent_count": len(accepted_ordinary),
        "dry_run": {key: dry_run.get(key) for key in ("deterministic", "independent_compilations", "candidate_identity")},
        "package": {"path": str(package_path), "bytes": package_path.stat().st_size, "sha256": package_sha, "audit_sha256": audit.get("sha256")},
        "package_members": {
            "required_members": sorted(required_package_members),
            "checks": package_member_checks,
            "owner_identity": {
                "display_name": owner_identity.get("display_name"),
                "concept": owner_identity.get("concept"),
            },
            "gm_identity": {
                "display_name": gm_identity.get("display_name"),
                "concept": gm_identity.get("concept"),
            },
            "path_subpath_bindings": [
                {"path_id": path_id, "subpath_id": subpath_id}
                for path_id, subpath_id in sorted(package_bindings)
            ],
            "sphere_count": len(exported_sphere_ids),
            "talent_count": len(exported_talent_ids),
            "insight_count": len(exported_insight_ids),
            "insight_occurrence_count": len(exported_insight_occurrences),
        },
        "import_reimport": {
            "first_status": first.get("status"),
            "second_status": second.get("status"),
            "character_sheet_semantic_equal": sheet_proof.get("semantic_equal"),
            "gm_model_semantic_equal": gm_proof.get("semantic_equal"),
        },
        "reopened_identity": identity,
        "reopened_project_revision": reopened_project.get("revision"),
        "response_sha256": sha256_json(response),
    }


def run_acceptance(*, data_dir: Path, report_path: Path) -> dict[str, Any]:
    if not PINNED_FACTORY.is_file() or sha256_file(PINNED_FACTORY) != PINNED_FACTORY_SHA256:
        raise FoundryError("REC1_P1CR4_ACCEPTANCE_FACTORY_INVALID", "The pinned Factory archive is missing or has an unexpected SHA-256.", details={"path": str(PINNED_FACTORY), "expected_sha256": PINNED_FACTORY_SHA256}, status_code=500)
    settings = Settings.from_env(ROOT, data_dir.resolve())
    db = Database(settings)
    db.migrate()
    configured = FactoryAdapter(db).configure(PINNED_FACTORY)
    CatalogService(db).rebuild_core(Path(configured["factory_root"]))
    app = create_app(settings)
    report: dict[str, Any]
    with TestClient(app) as client:
        headers = {"X-Foundry-Token": client.get("/api/session").json()["token"]}
        builder = app.state.character_builder
        execution = app.state.character_creation
        created, started = _start_run(client, builder, headers, source="REC1-P1CR4 production valid file")
        project_id = created["project"]["project_id"]
        run_id = started["run_id"]
        internal_run = execution.get(run_id)
        locks = {row.get("field"): row.get("value") for row in created["project"].get("user_locks") or [] if isinstance(row, dict)}
        if locks.get("character.identity.display_name") is not None or str(locks.get("concept") or ""):
            raise FoundryError("REC1_P1CR4_ACCEPTANCE_DELEGATED_FIELDS_NOT_BLANK", "The fresh acceptance project did not leave Name and Concept blank.", details={"name": locks.get("character.identity.display_name"), "concept": locks.get("concept")}, status_code=500)
        planning = created["acceptance_planning"]
        before_snapshot = _project_snapshot(db, project_id)
        response = _semantic_response(internal_run, ROOT, planning=planning)
        response_text = canonical_json(response)
        response_payload = response_text.encode("utf-8")
        response_schema = _request_schema(client, run_id, headers)
        response_schema_constraints = {
            "subpath_choice_minItems": _response_schema_slot(response_schema, "subpath_choice").get("minItems"),
            "subpath_choice_maxItems": _response_schema_slot(response_schema, "subpath_choice").get("maxItems"),
        }
        if not isinstance(response_schema_constraints["subpath_choice_maxItems"], int) or response_schema_constraints["subpath_choice_maxItems"] < 2:
            raise FoundryError(
                "REC1_P1CR4_ACCEPTANCE_SUBPATH_SCHEMA_CARDINALITY_INVALID",
                "The sealed preferred response schema must permit at least two Subpath or Tradition IDs.",
                details=response_schema_constraints,
                status_code=500,
            )
        schema_errors = list(Draft202012Validator(response_schema).iter_errors(response))
        if schema_errors:
            raise FoundryError("REC1_P1CR4_ACCEPTANCE_RESPONSE_SCHEMA_INVALID", "The deterministic file response does not validate against the sealed preferred schema.", details={"errors": [error.message for error in schema_errors[:10]]}, status_code=500)
        upload = client.post(
            f"/api/character-creation/runs/{run_id}/manual-response-file",
            params={"filename": "REC1-P1CR4-production-response.json"},
            headers={**headers, "Content-Type": "application/json"},
            content=response_payload,
        )
        if upload.status_code != 200:
            raise FoundryError("REC1_P1CR4_ACCEPTANCE_FILE_UPLOAD_FAILED", "The production valid-file endpoint did not return 200.", details={"status": upload.status_code, "body": upload.text[:1000]}, status_code=500)
        preview = upload.json()
        if preview.get("status") != "READY_FOR_REVIEW" or preview.get("blockers"):
            raise FoundryError("REC1_P1CR4_ACCEPTANCE_PREVIEW_NOT_CLEAN", "The valid production response did not produce a clean review candidate.", details={"status": preview.get("status"), "blockers": preview.get("blockers"), "submission_error": preview.get("submission_error")}, status_code=409)
        after_preview = _project_snapshot(db, project_id)
        if before_snapshot != after_preview:
            raise FoundryError("REC1_P1CR4_ACCEPTANCE_PREVIEW_MUTATED_PROJECT", "The file preview changed project mechanics before Finalize.", status_code=500)
        evidence_response = client.get(f"/api/character-creation/runs/{run_id}/evidence.json", headers=headers)
        if evidence_response.status_code != 200:
            raise FoundryError("REC1_P1CR4_ACCEPTANCE_EVIDENCE_ENDPOINT_FAILED", "The production evidence endpoint did not return 200.", status_code=500)
        evidence = evidence_response.json()
        provenance = evidence.get("source_provenance") or {}
        normalization = provenance.get("normalization") or {}
        expected_response_sha = sha256_bytes(response_payload)
        if not (
            provenance.get("filename") == "REC1-P1CR4-production-response.json"
            and provenance.get("raw_byte_count") == len(response_payload)
            and provenance.get("raw_bytes_sha256") == expected_response_sha
            and provenance.get("member_sha256") == expected_response_sha
            and normalization.get("normalized_text_bytes") == len(response_payload)
            and normalization.get("normalized_text_sha256") == expected_response_sha
            and evidence.get("response_binding", {}).get("submitted_request_sha256") == internal_run["request"]["request_sha256"]
        ):
            raise FoundryError("REC1_P1CR4_ACCEPTANCE_SOURCE_PROVENANCE_INVALID", "The evidence endpoint did not preserve exact uploaded-file provenance.", details={"provenance": provenance, "normalization": normalization}, status_code=409)

        owner = preview.get("owner_view") or {}
        planning_items = owner.get("planning_items") or []
        owner_scratch = (owner.get("scratch_candidate") or {}).get("sheet") or {}
        owner_subpath_bindings = owner.get("subpath_bindings") or []
        owner_projection_checks = {
            "delegated_name_visible": (
                owner.get("identity", {}).get("name") == "REC1-P1CR4 Dual Path Response"
                and owner.get("identity", {}).get("name_provenance") == "AI proposed"
            ),
            "delegated_concept_visible": (
                owner.get("identity", {}).get("concept") == "A source-backed Body Refining and Spirit Awakening production acceptance character."
                and owner.get("identity", {}).get("concept_provenance") == "AI proposed"
            ),
            "method_identity_and_owner_provenance_visible": (
                owner.get("method", {}).get("name") == "Wandering Reed-and-Lantern Method"
                and owner.get("method", {}).get("provenance") == "Owner"
                and owner.get("method", {}).get("access_required") is True
                and bool(owner.get("method", {}).get("access_text"))
                and any(row.get("choice_id") == "route-personal-teacher" for row in owner.get("method", {}).get("owner_route_options") or [])
            ),
            "method_planning_access_acquisition_are_separate": (
                owner.get("method", {}).get("planning_lock", {}).get("choice_ids") == [METHOD_ID]
                and owner.get("method", {}).get("planning_lock", {}).get("acquisition_authority") == "server_materialized_after_validated_response"
                and owner.get("method", {}).get("planning_lock", {}).get("access_authority", {}).get("present") is True
            ),
            "foundation_owner_provenance_visible": (
                owner.get("foundation", {}).get("provenance") == "Owner"
                and owner.get("foundation", {}).get("name") not in {None, "Foundation pending owner decision"}
            ),
            "both_path_owned_subpaths_visible": (
                {
                    (row.get("path_id"), row.get("choice_id"))
                    for row in owner_subpath_bindings
                } == set(zip(PATH_IDS, SUBPATH_IDS))
                and all(row.get("provenance") == "Owner" for row in owner_subpath_bindings)
            ),
            "sphere_priorities_visible": (
                len(owner.get("planning_preferences", {}).get("sphere_priorities") or []) == 15
                and all(row.get("planning_only") is True for row in owner.get("planning_preferences", {}).get("sphere_priorities") or [])
            ),
            "sphere_free_and_ordinary_talents_visible": (
                len(owner_scratch.get("spheres") or []) >= 10
                and len(owner_scratch.get("free_talents") or []) >= 10
                and len(owner_scratch.get("ordinary_talents") or []) >= TARGET_CL
            ),
            "insights_visible": bool(owner_scratch.get("insights") or []),
            "ai_planning_only_item_visible": (
                len(planning_items) == 1
                and planning_items[0].get("provenance") == "AI proposed"
                and planning_items[0].get("planning_only") is True
            ),
        }
        if not all(owner_projection_checks.values()):
            raise FoundryError(
                "REC1_P1CR4_ACCEPTANCE_OWNER_PROJECTION_INVALID",
                "The owner projection did not expose the exact Method, provenance, bindings, grants, insights, and planning-only item.",
                details={"checks": owner_projection_checks},
                status_code=409,
            )

        edit = client.post(
            f"/api/character-creation/runs/{run_id}/descriptive-fields",
            headers=headers,
            json={"name": "REC1-P1CR4 Owner Edited Name", "concept": "Owner-edited production concept."},
        )
        if edit.status_code != 200 or (edit.json().get("owner_descriptive_fields") or {}).get("accepted", {}).get("identity", {}).get("name") != "REC1-P1CR4 Owner Edited Name":
            raise FoundryError("REC1_P1CR4_ACCEPTANCE_OWNER_EDIT_INVALID", "The owner descriptive-field edit did not persist on the active run.", details={"status": edit.status_code, "body": edit.json()}, status_code=409)

        finalize_response = client.post(f"/api/character-creation/runs/{run_id}/finalize", headers=headers, json={})
        if finalize_response.status_code != 200:
            raise FoundryError("REC1_P1CR4_ACCEPTANCE_FINALIZE_ENDPOINT_FAILED", "The production Finalize endpoint did not return 200.", details={"status": finalize_response.status_code, "body": finalize_response.text[:1000]}, status_code=500)
        finalized = execution.get(run_id)
        final_evidence = _assert_finalized(settings=settings, db=db, execution=execution, finalized=finalized, project_id=project_id, response=response, planning=planning)
        diagnostics = _run_diagnostic_checks(client, builder, execution, headers, response)
        report = {
            "schema": "TianxiaFoundry.REC1P1CR4RealAcceptanceReport.v1",
            "status": "PASS",
            "project_id": project_id,
            "run_id": run_id,
            "factory_sha256": PINNED_FACTORY_SHA256,
            "response_filename": "REC1-P1CR4-production-response.json",
            "response_bytes": len(response_payload),
            "response_sha256": expected_response_sha,
            "normalized_response_sha256": normalization.get("normalized_text_sha256"),
            "response_schema": RESPONSE_SCHEMA,
            "response_schema_constraints": response_schema_constraints,
            "response_evidence": {
                "kind": "publication_safe_deterministic_equivalent",
                "owner_private_response_bytes_embedded": False,
                "owner_private_response_bytes_available": False,
                "bytes": len(response_payload),
                "sha256": expected_response_sha,
                "normalized_sha256": normalization.get("normalized_text_sha256"),
            },
            "project": {
                "target_cl": TARGET_CL,
                "power_band": POWER_BAND,
                "name_blank_before_response": True,
                "concept_blank_before_response": True,
                "paths": PATH_IDS,
                "subpaths": SUBPATH_IDS,
                "method_id": METHOD_ID,
                "foundation_id": FOUNDATION_ID,
                "sphere_priority_count": len(planning["sphere_priority_ids"]),
                "talent_priority_count": len(planning["talent_priority_ids"]),
            },
            "preview": {
                "status": preview.get("status"),
                "project_unchanged": before_snapshot == after_preview,
                "owner_method": owner.get("method"),
                "owner_projection_checks": owner_projection_checks,
                "owner_subpath_bindings": owner.get("subpath_bindings"),
                "planning_items": planning_items,
            },
            "owner_edit": edit.json().get("owner_descriptive_fields"),
            "source_provenance": provenance,
            "evidence_response_binding": evidence.get("response_binding"),
            "diagnostics": diagnostics,
            "finalization": final_evidence,
        }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = run_acceptance(data_dir=args.data.resolve(), report_path=args.report.resolve())
    except Exception as exc:
        report = {
            "schema": "TianxiaFoundry.REC1P1CR4RealAcceptanceReport.v1",
            "status": "FAIL",
            "error_type": type(exc).__name__,
            "error_code": getattr(exc, "code", None),
            "error": str(exc),
            "details": getattr(exc, "details", None),
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
