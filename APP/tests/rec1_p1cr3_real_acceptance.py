"""Run the real REC1-P1CR3 semantic-response lifecycle.

This is an operator-facing acceptance runner rather than a fake-pipeline unit
fixture.  It creates a fresh target-CL-20 project through the current Builder,
uses the pinned Factory archive, submits only the preferred semantic response,
and requires the production release/clean-import/GM-source-consumer gates
before writing a machine-readable report.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import zipfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api import create_app
from app.core import Database, FoundryError, Settings, canonical_json, sha256_file, sha256_json
from canonical_catalog.service import CanonicalCatalogAuthorityService
from catalog.service import CatalogService
from character_creation.response_materialization import RESPONSE_SCHEMA
from character_builder import CharacterBuilderService
from character_sheet.service import CharacterSheetService
from project_store.service import ProjectStore
from stage1.service import Stage1ClipboardService
from vendor_adapter.service import FactoryAdapter


PINNED_FACTORY = ROOT / "BundledContent" / "Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip"
PINNED_FACTORY_SHA256 = "4daf167cf634f27efef4dd2f1c8700bb4b7037cc6234c32be1af90aea5916385"
TARGET_CL = 20
POWER_BAND = "rival/boss"
PROGRESSION_PATH = "tianxia.path.qi_cultivation"
SELECTED_PATH_IDS = [PROGRESSION_PATH]
BACKGROUND_ID = "tianxia.background.abandoned_orphan"
BACKGROUND_SPHERE_ID = "tianxia.background_sphere.scoundrel"
BACKGROUND_TALENT_ID = "tianxia.background_talent.scoundrel.hidden_tool_cache"
ORIGIN_INSIGHT_ID = "tianxia.origin_insight.street_hardened"
SUBPATH_ID = "tianxia.subpath.qi.cinder_heart_cultivator"
BACKGROUND_CANONICAL_SPHERE_ID = "tianxia.sphere.scoundrel"
SEMANTIC_SPHERE_COUNT = 11
BACKGROUND_SPHERE_COUNT = 1
TOTAL_SPHERE_COUNT = SEMANTIC_SPHERE_COUNT + BACKGROUND_SPHERE_COUNT
SEMANTIC_FREE_TALENT_COUNT = SEMANTIC_SPHERE_COUNT
ORDINARY_TALENT_COUNT = TARGET_CL
SPHERE_ACQUISITION_KINDS = {
    "ai_bootstrap_sphere_acquisition",
    "sect_trial_sphere_acquisition",
}
FREE_TALENT_ACQUISITION_KINDS = {
    "ai_bootstrap_talent_acquisition",
    "sect_trial_talent_acquisition",
}


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


def _build_project(builder: CharacterBuilderService) -> dict[str, Any]:
    sphere_category = next(
        row for row in builder.options()["categories"] if row["slot_id"] == "sphere_priorities"
    )
    sphere_priority_ids = [
        row["choice_id"]
        for row in sorted(sphere_category.get("choices") or [], key=lambda value: value["choice_id"])
        if isinstance(row.get("choice_id"), str)
    ][:15]
    if len(sphere_priority_ids) < 15:
        raise FoundryError(
            "REC1_P1CR3_ACCEPTANCE_PRIORITIES_UNRESOLVED",
            "The pinned catalog exposes fewer than 15 legal Sphere planning priorities.",
            details={"count": len(sphere_priority_ids)},
            status_code=500,
        )
    return builder.create_project(
        working_name="",
        concept="",
        target_cl=TARGET_CL,
        power_band=POWER_BAND,
        source_reference="REC1-P1CR3 real semantic response acceptance",
        creation_mode="detailed",
        ability_scores={},
        selections={
            "path_choice": SELECTED_PATH_IDS,
            "subpath_choice": [SUBPATH_ID],
            "background_choice": [BACKGROUND_ID],
            "background_sphere_choice": [BACKGROUND_SPHERE_ID],
            "background_talent_choice": [BACKGROUND_TALENT_ID],
            "origin_insight_choice": [ORIGIN_INSIGHT_ID],
        },
        sphere_priority_ids=sphere_priority_ids,
        talent_priority_ids=[],
        generation_route="ai_bootstrap",
    )


def _semantic_acquisitions(
    envelope: dict[str, Any],
    catalog: CanonicalCatalogAuthorityService,
    priority_ids: list[str],
) -> tuple[list[dict[str, str]], list[str], list[dict[str, Any]], list[str]]:
    """Choose a deterministic source-authorized 12-Sphere CL20 fixture.

    Planning priorities are intentionally kept separate from actual acquisition
    intent.  The first twelve of the fifteen frozen owner priorities are used as
    the acceptance fixture's acquired canonical Spheres, and the source
    authority supplies one CL1 free Talent per Sphere plus one causal ordinary
    Talent at each effective CL.
    """
    if len(priority_ids) < 15 or len(priority_ids) != len(set(priority_ids)):
        raise FoundryError(
            "REC1_P1CR3_ACCEPTANCE_PRIORITIES_INVALID",
            "The frozen acceptance request does not contain at least fifteen distinct Sphere planning priorities.",
            details={"count": len(priority_ids)},
            status_code=500,
        )
    selected_spheres = priority_ids[:SEMANTIC_SPHERE_COUNT]
    if len(selected_spheres) != len(set(selected_spheres)):
        raise FoundryError(
            "REC1_P1CR3_ACCEPTANCE_SPHERES_INVALID",
            "The deterministic acceptance fixture selected duplicate canonical Spheres.",
            status_code=500,
        )
    if BACKGROUND_CANONICAL_SPHERE_ID in selected_spheres:
        raise FoundryError(
            "REC1_P1CR3_ACCEPTANCE_BACKGROUND_SPHERE_DUPLICATED",
            "The semantic Sphere fixture cannot reacquire the authenticated Background Sphere.",
            details={"background_sphere_id": BACKGROUND_CANONICAL_SPHERE_ID, "semantic_spheres": selected_spheres},
            status_code=500,
        )

    authority = (
        envelope.get("typed_choice_authority_by_slot") or {}
    ).get("advancement_skeleton", {}).get("stage2_authority_by_choice") or {}
    free_by_sphere: dict[str, list[tuple[int, str, str]]] = {}
    ordinary_candidates: list[tuple[int, str, str, str]] = []
    selected_sphere_set = set(selected_spheres)
    for talent_id, record_authority in sorted(authority.items()):
        if not isinstance(record_authority, dict):
            continue
        sphere_id = record_authority.get("sphere_id")
        if sphere_id not in selected_sphere_set:
            continue
        minimum_cl = int(record_authority.get("minimum_cl") or 1)
        try:
            canonical_id = catalog.resolve_talent_id(talent_id)
            talent = catalog.get_talent(talent_id)
        except FoundryError:
            continue
        if not isinstance(canonical_id, str) or talent.get("owning_canonical_sphere_id") != sphere_id:
            continue
        if (
            "ai_bootstrap_talent_acquisition" in (record_authority.get("allowed_kinds") or [])
            and minimum_cl <= 1
            and record_authority.get("free_sphere_talent_eligible") is not False
            and talent.get("ordinary_talent") is True
            and talent.get("creator_selectability_can_be_evaluated_safely") is True
        ):
            free_by_sphere.setdefault(sphere_id, []).append((minimum_cl, canonical_id, talent_id))
        if (
            "level_talent_acquisition" in (record_authority.get("allowed_kinds") or [])
            and talent.get("ordinary_talent") is True
            and talent.get("creator_selectability_can_be_evaluated_safely") is True
        ):
            ordinary_candidates.append((minimum_cl, canonical_id, talent_id, sphere_id))

    free_pairs: list[dict[str, str]] = []
    free_canonical_ids: set[str] = set()
    for sphere_id in selected_spheres:
        candidates = sorted(free_by_sphere.get(sphere_id) or [])
        if not candidates:
            raise FoundryError(
                "REC1_P1CR3_ACCEPTANCE_FREE_TALENT_UNRESOLVED",
                "The pinned source authority cannot supply a legal CL1 free Talent for every selected Sphere.",
                details={"sphere_id": sphere_id},
                status_code=500,
            )
        _minimum_cl, canonical_id, talent_id = candidates[0]
        free_pairs.append({"sphere_id": sphere_id, "talent_id": talent_id})
        free_canonical_ids.add(canonical_id)

    ordinary_by_canonical: dict[str, tuple[int, str, str, str]] = {}
    for row in sorted(ordinary_candidates):
        ordinary_by_canonical.setdefault(row[1], row)
    ordinary_pool = [
        row for canonical_id, row in sorted(ordinary_by_canonical.items())
        if canonical_id not in free_canonical_ids
    ]
    if len(ordinary_pool) < TARGET_CL:
        raise FoundryError(
            "REC1_P1CR3_ACCEPTANCE_ORDINARY_TALENT_UNRESOLVED",
            "The pinned source authority cannot supply twenty distinct ordinary Talents for CL1–CL20.",
            details={"count": len(ordinary_pool), "required": TARGET_CL},
            status_code=500,
        )
    ordinary_by_cl: list[dict[str, Any]] = []
    remaining = list(ordinary_pool)
    for effective_cl in range(1, TARGET_CL + 1):
        available = [row for row in remaining if row[0] <= effective_cl]
        if not available:
            raise FoundryError(
                "REC1_P1CR3_ACCEPTANCE_ORDINARY_TALENT_ORDER_UNRESOLVED",
                "The pinned source authority cannot provide a causal ordinary-Talent sequence through CL20.",
                details={"effective_cl": effective_cl},
                status_code=500,
            )
        minimum_cl, canonical_id, talent_id, sphere_id = available[0]
        remaining.remove(available[0])
        ordinary_by_cl.append(
            {
                "effective_cl": effective_cl,
                "minimum_cl": minimum_cl,
                "talent_id": talent_id,
                "canonical_talent_id": canonical_id,
                "sphere_id": sphere_id,
            }
        )

    return free_pairs, [row["talent_id"] for row in ordinary_by_cl], ordinary_by_cl, selected_spheres


def _choice_record_id(row: dict[str, Any]) -> str | None:
    record_id = row.get("record_id")
    if isinstance(record_id, str):
        return record_id
    subject = row.get("subject")
    if isinstance(subject, dict) and isinstance(subject.get("record_id"), str):
        return subject["record_id"]
    return None


def _sphere_acquisition_evidence(
    *,
    choices: list[dict[str, Any]],
    response_pairs: list[dict[str, Any]],
    accepted_spheres: list[str],
    accepted_free: list[str],
    accepted_ordinary: list[str],
    accepted_background_spheres: list[str],
    planning_priorities: list[str],
) -> dict[str, Any]:
    """Prove the total Sphere accounting without excluding Background events."""
    sphere_rows = [
        row for row in choices
        if row.get("kind") in SPHERE_ACQUISITION_KINDS
    ]
    background_rows = [
        row for row in choices
        if row.get("kind") == "background_sphere_acquisition"
    ]
    free_rows = [
        row for row in choices
        if row.get("kind") in FREE_TALENT_ACQUISITION_KINDS
    ]
    ordinary_rows = [row for row in choices if row.get("kind") == "level_talent_acquisition"]
    semantic_ids = [_choice_record_id(row) for row in sphere_rows]
    semantic_ids = [value for value in semantic_ids if isinstance(value, str)]
    background_ids = [_choice_record_id(row) for row in background_rows]
    background_ids = [value for value in background_ids if isinstance(value, str)]
    free_ids = [_choice_record_id(row) for row in free_rows]
    free_ids = [value for value in free_ids if isinstance(value, str)]
    ordinary_ids = [_choice_record_id(row) for row in ordinary_rows]
    ordinary_ids = [value for value in ordinary_ids if isinstance(value, str)]
    response_sphere_ids = [
        row.get("sphere_id")
        for row in response_pairs
        if isinstance(row, dict) and isinstance(row.get("sphere_id"), str)
    ]
    response_free_ids = [
        row.get("talent_id")
        for row in response_pairs
        if isinstance(row, dict) and isinstance(row.get("talent_id"), str)
    ]
    total_ids = [BACKGROUND_CANONICAL_SPHERE_ID, *semantic_ids]
    unselected_priorities = [
        value for value in planning_priorities
        if value not in set(semantic_ids)
    ]
    evidence = {
        "sphere_acquisition_event_count": len(sphere_rows) + len(background_rows),
        "background_sphere_acquisition_event_count": len(background_rows),
        "semantic_sphere_acquisition_event_count": len(sphere_rows),
        "semantic_free_talent_pair_count": len(response_pairs),
        "free_talent_acquisition_event_count": len(free_rows),
        "ordinary_talent_acquisition_event_count": len(ordinary_rows),
        "planning_priority_count": len(planning_priorities),
        "planning_priority_ids": list(planning_priorities),
        "unselected_priority_count": len(unselected_priorities),
        "unselected_priority_ids": unselected_priorities,
        "semantic_sphere_ids": semantic_ids,
        "background_sphere_choice_ids": background_ids,
        "background_canonical_sphere_id": BACKGROUND_CANONICAL_SPHERE_ID,
        "known_sphere_ids": total_ids,
        "accepted_sphere_ids": list(accepted_spheres),
        "accepted_background_sphere_ids": list(accepted_background_spheres),
        "response_sphere_ids": response_sphere_ids,
        "response_free_talent_ids": response_free_ids,
        "materialized_free_talent_ids": free_ids,
        "materialized_ordinary_talent_ids": ordinary_ids,
        "ordinary_effective_cls": [row.get("effective_cl") for row in ordinary_rows],
    }
    checks = {
        "total_sphere_acquisition_event_count": evidence["sphere_acquisition_event_count"] == TOTAL_SPHERE_COUNT,
        "background_sphere_acquisition_count": evidence["background_sphere_acquisition_event_count"] == BACKGROUND_SPHERE_COUNT,
        "semantic_sphere_acquisition_count": evidence["semantic_sphere_acquisition_event_count"] == SEMANTIC_SPHERE_COUNT,
        "semantic_free_talent_pair_count": evidence["semantic_free_talent_pair_count"] == SEMANTIC_FREE_TALENT_COUNT,
        "materialized_free_talent_count": evidence["free_talent_acquisition_event_count"] == SEMANTIC_FREE_TALENT_COUNT,
        "ordinary_talent_count": evidence["ordinary_talent_acquisition_event_count"] == ORDINARY_TALENT_COUNT,
        "planning_priorities_at_least_fifteen": len(planning_priorities) >= 15,
        "planning_priorities_distinct": len(planning_priorities) == len(set(planning_priorities)),
        "background_choice_is_authenticated": set(background_ids) == {BACKGROUND_SPHERE_ID},
        "semantic_spheres_distinct": len(semantic_ids) == len(set(semantic_ids)),
        "semantic_spheres_not_background": BACKGROUND_CANONICAL_SPHERE_ID not in set(semantic_ids),
        "known_spheres_distinct": len(total_ids) == len(set(total_ids)) == TOTAL_SPHERE_COUNT,
        "accepted_semantic_spheres_match": set(accepted_spheres) == set(semantic_ids) and len(accepted_spheres) == SEMANTIC_SPHERE_COUNT,
        "accepted_background_sphere_matches": accepted_background_spheres == [BACKGROUND_SPHERE_ID],
        "response_pairs_match_semantic_spheres": set(response_sphere_ids) == set(semantic_ids) and len(response_sphere_ids) == SEMANTIC_SPHERE_COUNT,
        "response_pairs_distinct": len(response_sphere_ids) == len(set(response_sphere_ids)) and len(response_free_ids) == len(set(response_free_ids)),
        "free_talent_rows_match_response": set(free_ids) == set(response_free_ids) and set(response_free_ids) == set(accepted_free),
        "ordinary_rows_match_final_plan": set(ordinary_ids) == set(accepted_ordinary) and len(accepted_ordinary) == ORDINARY_TALENT_COUNT,
        "ordinary_talent_ordered_cl1_to_cl20": evidence["ordinary_effective_cls"] == list(range(1, ORDINARY_TALENT_COUNT + 1)),
        "background_not_in_planning_priorities": BACKGROUND_CANONICAL_SPHERE_ID not in set(planning_priorities),
        "semantic_spheres_are_planned": set(semantic_ids).issubset(set(planning_priorities)),
        "planning_priorities_remain_non_acquisitive": len(unselected_priorities) >= 4,
    }
    evidence["checks"] = checks
    evidence["valid"] = all(checks.values())
    if not evidence["valid"]:
        raise FoundryError(
            "REC1_P1CR3_ACCEPTANCE_SPHERE_ACCOUNTING_INVALID",
            "The acceptance fixture did not prove exactly one Background Sphere plus eleven semantic Sphere acquisitions.",
            details=evidence,
            status_code=409,
        )
    return evidence


def _semantic_response(run: dict[str, Any], root: Path) -> dict[str, Any]:
    request = run["request"]
    envelope = request["delegated_choice_envelope"]
    catalog = CanonicalCatalogAuthorityService(root)
    priority_ids = next(
        (
            list((lock.get("value") or {}).get("sphere_priority_ids") or [])
            for lock in (request.get("stage1_prompt") or {}).get("envelope", {}).get("user_locks") or []
            if isinstance(lock, dict) and lock.get("field") == "character_sheet.planning_preferences"
        ),
        [],
    )
    priority_ids = [value for value in priority_ids if isinstance(value, str)]
    free_pairs, ordinary_ids, _ordinary_by_cl, selected_spheres = _semantic_acquisitions(
        envelope,
        catalog,
        priority_ids,
    )

    milestones = [
        row
        for row in envelope.get("advancement_choice_milestones") or []
        if isinstance(row, dict) and row.get("path_id") == PROGRESSION_PATH
    ]
    asi_deltas = (
        {"INT": 2},
        {"WIS": 2},
        {"CHA": 2},
        {"STR": 2},
        {"CON": 2},
    )
    if len(milestones) > len(asi_deltas):
        raise FoundryError(
            "REC1_P1CR3_ACCEPTANCE_MILESTONE_SET_UNEXPECTED",
            "The pinned Path authority exposes more ASI milestones than this bounded acceptance response defines.",
            details={"milestone_count": len(milestones)},
            status_code=500,
        )
    milestones.sort(key=lambda row: int(row.get("cl") or 0))
    if not milestones:
        raise FoundryError(
            "REC1_P1CR3_ACCEPTANCE_MILESTONE_SET_UNEXPECTED",
            "The pinned Path authority did not expose an advancement milestone for the selected CL20 route.",
            status_code=500,
        )
    insight_authority = (
        envelope["typed_choice_authority_by_slot"]
        ["insight_priorities"]["stage2_authority_by_choice"]
    )
    allowed_insight_ids = set(envelope["allowed_choice_ids_by_slot"].get("insight_priorities") or [])
    insight_occurrences: list[dict[str, Any]] = []
    used_insights: set[str] = set()
    present_choice_ids = set(SELECTED_PATH_IDS) | set(selected_spheres)
    present_choice_ids.update(pair["talent_id"] for pair in free_pairs)
    scores = {"STR": 8, "DEX": 14, "CON": 14, "INT": 15, "WIS": 12, "CHA": 8}
    scores["INT"] += int(asi_deltas[0].get("INT") or 0)
    # The first source milestone is represented as the one permitted ASI;
    # later milestones demonstrate the semantic Insight-occurrence route.
    for milestone in milestones[1:]:
        effective_cl = int(milestone["cl"])
        selected_insight: tuple[str, dict[str, Any], str | None] | None = None
        for insight_id in sorted(allowed_insight_ids):
            if insight_id in used_insights:
                continue
            authority_row = insight_authority.get(insight_id) or {}
            allowed_cls = authority_row.get("allowed_cls") or authority_row.get("allowed_effective_cls")
            if isinstance(allowed_cls, list) and effective_cl not in allowed_cls:
                continue
            choice_row = (envelope.get("choices_by_slot") or {}).get("insight_priorities", {}).get(insight_id) or {}
            prerequisites = choice_row.get("prerequisites") or []
            required_ids = {
                row.get("target_id")
                for row in prerequisites
                if isinstance(row, dict) and row.get("operator") == "requires"
            }
            if not required_ids.issubset(present_choice_ids | used_insights):
                continue
            rule = authority_row.get("ability_change") or authority_row.get("insight_ability_change") or {}
            ability = None
            if rule:
                amount = int(rule.get("amount") or 1)
                ability = next(
                    (
                        value
                        for value in rule.get("allowed_abilities") or []
                        if isinstance(value, str) and scores.get(value, 0) + amount <= int(rule.get("cap") or 20)
                    ),
                    None,
                )
                if ability is None:
                    continue
            selected_insight = (insight_id, authority_row, ability)
            break
        if selected_insight is None:
            raise FoundryError(
                "REC1_P1CR3_ACCEPTANCE_INSIGHT_SET_UNRESOLVED",
                "The current pinned catalog cannot supply a distinct source-authorized Insight for every remaining milestone.",
                details={"effective_cl": effective_cl},
                status_code=500,
            )
        insight_id, authority_row, ability = selected_insight
        rule = authority_row.get("ability_change") or authority_row.get("insight_ability_change") or {}
        parameters = {"ability": ability} if rule and ability else {}
        if rule and ability:
            scores[ability] += int(rule.get("amount") or 1)
        used_insights.add(insight_id)
        occurrence = {"insight_id": insight_id, "milestone_id": milestone["milestone_id"]}
        if parameters:
            occurrence["parameters"] = parameters
        insight_occurrences.append(occurrence)
        present_choice_ids.add(insight_id)
    response = {
        "schema": RESPONSE_SCHEMA,
        "request_sha256": request["request_sha256"],
        "selection_intent": {
            "by_slot": {
                "path_choice": SELECTED_PATH_IDS,
            },
        },
        "acquisition_intent": {
            "sphere_free_talent_pairs": free_pairs,
            "ordinary_talent_ids": ordinary_ids,
            "insight_occurrences": insight_occurrences,
        },
        "bounded_choices": {
            "ability_scores": {
                "STR": 8,
                "DEX": 14,
                "CON": 14,
                "INT": 15,
                "WIS": 12,
                "CHA": 8,
            },
            "background_ability": "DEX",
            "ability_score_changes_by_milestone_id": {
                milestones[0]["milestone_id"]: {"deltas": asi_deltas[0]}
            },
        },
        "owner_descriptive_fields": {
            "identity": {"name": "REC1-P1CR3 CL20 Semantic Acceptance"},
            "concept": "A real source-backed CL20 semantic-response acceptance character.",
        },
    }
    return response


def _forbidden_response_keys(value: Any, *, path: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    forbidden_exact = {
        "target_cl", "stage1_response", "stage2_proposal", "kind",
        "acquisition_channel", "effective_cl", "event_kinds", "event_ids",
        "event_hash", "receipt", "response_sha256", "plan_sha256",
    }
    findings: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            folded = key_text.casefold()
            mechanical_hash_or_event = (
                folded != "request_sha256"
                and ("event" in folded or "receipt" in folded or folded.endswith("_hash") or folded == "hash")
            )
            if folded in forbidden_exact or mechanical_hash_or_event:
                findings.append({"path": ".".join((*path, key_text)), "key": key_text})
            findings.extend(_forbidden_response_keys(child, path=(*path, key_text)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_forbidden_response_keys(child, path=(*path, str(index))))
    return findings


def _milestone_resolution_evidence(
    *,
    envelope: dict[str, Any],
    parsed_plan: dict[str, Any],
    response: dict[str, Any],
    selected_path_id: str,
) -> dict[str, Any]:
    milestones = [
        row for row in envelope.get("advancement_choice_milestones") or []
        if isinstance(row, dict) and row.get("path_id") == selected_path_id
    ]
    milestones.sort(key=lambda row: int(row.get("cl") or 0))
    expected = {str(row["milestone_id"]): row for row in milestones if isinstance(row.get("milestone_id"), str)}
    bounded = response.get("bounded_choices") or {}
    asi_by_milestone = bounded.get("ability_score_changes_by_milestone_id") or {}
    insights_by_milestone = {
        row.get("milestone_id"): row
        for row in (response.get("acquisition_intent") or {}).get("insight_occurrences") or []
        if isinstance(row, dict) and isinstance(row.get("milestone_id"), str)
    }
    choices = [row for row in (parsed_plan.get("stage2_proposal") or {}).get("choices") or [] if isinstance(row, dict)]
    resolutions: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for milestone_id, milestone in expected.items():
        cl = int(milestone.get("cl") or 0)
        feature_id = milestone.get("feature_record_id")
        asi_rows = [
            row for row in choices
            if row.get("kind") == "ability_score_change"
            and row.get("effective_cl") == cl
            and row.get("record_id") == feature_id
        ]
        insight = insights_by_milestone.get(milestone_id)
        insight_rows = [
            row for row in choices
            if row.get("kind") == "cultivation_insight_acquisition"
            and row.get("effective_cl") == cl
            and isinstance(insight, dict)
            and row.get("record_id") == insight.get("insight_id")
        ]
        if milestone_id in asi_by_milestone:
            resolution = "ability_score_change"
            count = len(asi_rows)
        elif insight is not None:
            resolution = "cultivation_insight_acquisition"
            count = len(insight_rows)
        else:
            resolution = "missing"
            count = 0
        resolutions.append({"milestone_id": milestone_id, "effective_cl": cl, "resolution": resolution, "row_count": count})
        if count != 1:
            failures.append(resolutions[-1])
    resolved_ids = [row["milestone_id"] for row in resolutions if row["resolution"] != "missing"]
    exact = (
        len(resolutions) == len(expected)
        and len(resolved_ids) == len(set(resolved_ids)) == len(expected)
        and not failures
        and sorted(row["effective_cl"] for row in resolutions) == sorted(int(row.get("cl") or 0) for row in expected.values())
    )
    return {
        "expected_milestone_ids": list(expected),
        "expected_effective_cls": [int(row.get("cl") or 0) for row in expected.values()],
        "resolutions": resolutions,
        "failures": failures,
        "exact": exact,
    }


def _surface_sphere_ids(value: dict[str, Any]) -> list[str]:
    """Extract canonical known Sphere IDs from an owner/GM surface."""
    current: Any = value
    if isinstance(current, dict) and isinstance(current.get("owner_character_sheet"), dict):
        current = current["owner_character_sheet"]
    if not isinstance(current, dict):
        return []
    spheres_and_talents = current.get("spheres_and_talents")
    if isinstance(spheres_and_talents, dict) and isinstance(spheres_and_talents.get("sphere_record_ids"), list):
        return [row for row in spheres_and_talents["sphere_record_ids"] if isinstance(row, str)]
    rows: Any = current.get("spheres")
    if not isinstance(rows, list):
        sections = current.get("sections")
        rows = sections.get("spheres") if isinstance(sections, dict) else None
    if not isinstance(rows, list):
        return []
    result: list[str] = []
    for row in rows:
        if isinstance(row, str):
            result.append(row)
        elif isinstance(row, dict):
            for key in ("stable_id", "canonical_sphere_id", "sphere_id", "record_id"):
                if isinstance(row.get(key), str):
                    result.append(row[key])
                    break
    return result


def _package_sphere_surfaces(package: Path, expected_ids: list[str]) -> dict[str, Any]:
    if not package.is_file():
        raise FoundryError(
            "REC1_P1CR3_ACCEPTANCE_SPHERE_PACKAGE_MISSING",
            "A required package surface for Sphere-count evidence is missing.",
            details={"path": str(package)},
            status_code=409,
        )
    members = {
        "package_owner_sheet": "Tianxia_Owner_Character_Sheet_v1.json",
        "package_gm_model": "Tianxia_GM_Character_Model_v2.json",
        "package_gm_view": "Tianxia_GM_Character_View_Model_v2.json",
    }
    with zipfile.ZipFile(package) as archive:
        documents = {
            label: json.loads(archive.read(member))
            for label, member in members.items()
        }
    expected = list(expected_ids)
    result = {
        label: {
            "count": len(ids := _surface_sphere_ids(document)),
            "distinct_count": len(set(ids)),
            "ids": ids,
            "count_equal": len(ids) == TOTAL_SPHERE_COUNT and set(ids) == set(expected),
        }
        for label, document in documents.items()
    }
    if not all(row["count_equal"] and row["distinct_count"] == TOTAL_SPHERE_COUNT for row in result.values()):
        raise FoundryError(
            "REC1_P1CR3_ACCEPTANCE_SPHERE_SURFACE_INVALID",
            "A downstream package, GM model, or GM view did not preserve exactly twelve known Spheres.",
            details={"expected_ids": expected, "surfaces": result},
            status_code=409,
        )
    return result


def _event_replay_sphere_evidence(db: Database, project_id: str, expected_ids: list[str]) -> dict[str, Any]:
    events = ProjectStore(db).timeline(project_id)
    sphere_kinds = SPHERE_ACQUISITION_KINDS | {"background_sphere_acquisition"}
    sphere_events = [
        event for event in events
        if (event.get("advancement") or {}).get("kind") in sphere_kinds
    ]
    event_ids = [
        (event.get("subject") or {}).get("record_id")
        for event in sphere_events
        if isinstance((event.get("subject") or {}).get("record_id"), str)
    ]
    replay = ProjectStore(db).replay(project_id)
    replay_ids = [
        value for value in ((replay.get("state") or {}).get("selections") or {}).get("sphere", [])
        if isinstance(value, str)
    ]
    result = {
        "sphere_acquisition_event_count": len(sphere_events),
        "background_sphere_event_count": sum(
            1 for event in sphere_events
            if (event.get("advancement") or {}).get("kind") == "background_sphere_acquisition"
        ),
        "semantic_sphere_event_count": sum(
            1 for event in sphere_events
            if (event.get("advancement") or {}).get("kind") in SPHERE_ACQUISITION_KINDS
        ),
        "event_sphere_ids": event_ids,
        "replay_sphere_ids": replay_ids,
        "replay_state_hash": replay.get("state_hash"),
        "event_ids_equal": len(event_ids) == len(set(event_ids)) == TOTAL_SPHERE_COUNT and set(event_ids) == set(expected_ids),
        "replay_ids_equal": len(replay_ids) == len(set(replay_ids)) == TOTAL_SPHERE_COUNT and set(replay_ids) == set(expected_ids),
        "event_count_equal": len(sphere_events) == TOTAL_SPHERE_COUNT,
        "background_count_equal": sum(
            1 for event in sphere_events
            if (event.get("advancement") or {}).get("kind") == "background_sphere_acquisition"
        ) == BACKGROUND_SPHERE_COUNT,
        "semantic_count_equal": sum(
            1 for event in sphere_events
            if (event.get("advancement") or {}).get("kind") in SPHERE_ACQUISITION_KINDS
        ) == SEMANTIC_SPHERE_COUNT,
    }
    if not all(result[key] is True for key in ("event_ids_equal", "replay_ids_equal", "event_count_equal", "background_count_equal", "semantic_count_equal")):
        raise FoundryError(
            "REC1_P1CR3_ACCEPTANCE_EVENT_REPLAY_SPHERES_INVALID",
            "Committed events and replay state did not preserve exactly twelve canonical Spheres.",
            details=result,
            status_code=409,
        )
    return result


def _acceptance_evidence(
    *,
    settings: Settings,
    db: Database,
    execution: Any,
    initial_run: dict[str, Any],
    finalized: dict[str, Any],
    response: dict[str, Any],
    browser: str | None,
) -> dict[str, Any]:
    """Assert every acceptance claim before emitting a PASS report."""
    if finalized.get("status") != "CLEAN_AND_FINALIZED":
        raise FoundryError(
            "REC1_P1CR3_ACCEPTANCE_FINAL_STATUS_INVALID",
            "The completed acceptance run did not reach CLEAN_AND_FINALIZED.",
            details={"status": finalized.get("status")},
            status_code=409,
        )
    run = execution.get(initial_run["run_id"])
    project = ProjectStore(db).get_project(initial_run["project_id"])["project"]
    locks = {
        lock.get("field"): lock.get("value")
        for lock in project.get("user_locks") or []
        if isinstance(lock, dict)
    }
    if locks.get("character.identity.display_name") is not None or str(locks.get("concept") or ""):
        raise FoundryError(
            "REC1_P1CR3_ACCEPTANCE_DELEGATED_FIELDS_NOT_BLANK",
            "The acceptance project did not leave delegated Name and Concept blank in owner locks.",
            details={"name": locks.get("character.identity.display_name"), "concept": locks.get("concept")},
            status_code=409,
        )
    if locks.get("power_band") != POWER_BAND:
        raise FoundryError(
            "REC1_P1CR3_ACCEPTANCE_POWER_BAND_INVALID",
            "The acceptance project did not persist the exact rival/boss power band.",
            details={"power_band": locks.get("power_band")},
            status_code=409,
        )
    planning = locks.get("character_sheet.planning_preferences") or {}
    priorities = [value for value in planning.get("sphere_priority_ids") or [] if isinstance(value, str)]
    if len(priorities) < 15 or len(priorities) != len(set(priorities)):
        raise FoundryError(
            "REC1_P1CR3_ACCEPTANCE_PRIORITY_ASSERTION_FAILED",
            "The finalized project does not contain at least fifteen distinct legal Sphere priorities.",
            details={"count": len(priorities)},
            status_code=409,
        )
    envelope = (run.get("request") or {}).get("delegated_choice_envelope") or {}
    delegated_fields = envelope.get("delegated_fields") or {}
    if (delegated_fields.get("identity.name") or {}).get("state") != "delegated" or (delegated_fields.get("concept") or {}).get("state") != "delegated":
        raise FoundryError(
            "REC1_P1CR3_ACCEPTANCE_DELEGATION_ASSERTION_FAILED",
            "The frozen request did not classify blank Name and Concept as delegated fields.",
            details={"delegated_fields": delegated_fields},
            status_code=409,
        )

    forbidden_keys = _forbidden_response_keys(response)
    if forbidden_keys:
        raise FoundryError(
            "REC1_P1CR3_ACCEPTANCE_RESPONSE_MECHANICAL_FIELDS_PRESENT",
            "The preferred response recursively contains backend mechanical authority fields.",
            details={"findings": forbidden_keys},
            status_code=409,
        )

    parsed_plan = (run.get("response") or {}).get("parsed_plan") or {}
    stage2 = parsed_plan.get("stage2_proposal") or {}
    choices = [row for row in stage2.get("choices") or [] if isinstance(row, dict)]
    final_plan = run.get("final_plan") or {}
    catalog_authority = final_plan.get("catalog_response_authority") or {}
    accepted_spheres = list(catalog_authority.get("accepted_sphere_ids") or [])
    accepted_free = list(catalog_authority.get("accepted_free_sphere_talent_ids") or [])
    accepted_ordinary = list(catalog_authority.get("accepted_ordinary_talent_ids") or [])
    accepted_background_spheres = list(catalog_authority.get("accepted_background_sphere_ids") or [])
    if final_plan.get("target_cl") != TARGET_CL or (parsed_plan.get("target_cl") != TARGET_CL):
        raise FoundryError(
            "REC1_P1CR3_ACCEPTANCE_TARGET_CL_INVALID",
            "The server-owned materialized and accepted plans are not bound to CL20.",
            details={"parsed_target_cl": parsed_plan.get("target_cl"), "final_plan_target_cl": final_plan.get("target_cl")},
            status_code=409,
        )
    acquisition = response.get("acquisition_intent") or {}
    response_pairs = [
        value for value in acquisition.get("sphere_free_talent_pairs") or []
        if isinstance(value, dict)
    ]
    sphere_accounting = _sphere_acquisition_evidence(
        choices=choices,
        response_pairs=response_pairs,
        accepted_spheres=accepted_spheres,
        accepted_free=accepted_free,
        accepted_ordinary=accepted_ordinary,
        accepted_background_spheres=accepted_background_spheres,
        planning_priorities=priorities,
    )
    milestone_evidence = _milestone_resolution_evidence(
        envelope=envelope,
        parsed_plan=parsed_plan,
        response=response,
        selected_path_id=PROGRESSION_PATH,
    )
    if milestone_evidence["exact"] is not True:
        raise FoundryError(
            "REC1_P1CR3_ACCEPTANCE_MILESTONE_RESOLUTION_INVALID",
            "Advertised advancement milestones do not map exactly once to materialized ASI or Insight rows.",
            details=milestone_evidence,
            status_code=409,
        )

    outputs = finalized.get("outputs") or {}
    portable = outputs.get("portable_character") or {}
    audit = portable.get("audit") or {}
    package_path = Path(str(audit.get("path") or ""))
    if not package_path.is_file():
        raise FoundryError(
            "REC1_P1CR3_ACCEPTANCE_PACKAGE_MISSING",
            "The finalized acceptance output does not point to a physical portable package.",
            details={"path": str(package_path)},
            status_code=409,
        )
    package_sha256 = sha256_file(package_path)
    package_bytes = package_path.stat().st_size
    if package_sha256 != audit.get("sha256") or package_bytes != audit.get("bytes"):
        raise FoundryError(
            "REC1_P1CR3_ACCEPTANCE_PACKAGE_IDENTITY_INVALID",
            "The finalized package bytes do not equal the audited package identity.",
            details={"actual_sha256": package_sha256, "audit_sha256": audit.get("sha256"), "actual_bytes": package_bytes, "audit_bytes": audit.get("bytes")},
            status_code=409,
        )
    inventory = audit.get("member_inventory") or []
    if len(inventory) != audit.get("entry_count") or audit.get("crc_validation", {}).get("status") != "VALID" or audit.get("checksum_manifest", {}).get("coverage_status") != "EXACT":
        raise FoundryError(
            "REC1_P1CR3_ACCEPTANCE_PACKAGE_AUDIT_INVALID",
            "The finalized package report does not contain exact member/checksum/CRC evidence.",
            details={"entry_count": audit.get("entry_count"), "inventory_count": len(inventory), "crc": audit.get("crc_validation"), "checksums": audit.get("checksum_manifest")},
            status_code=409,
        )
    clean_import = portable.get("clean_import") or {}
    sheet_proof = clean_import.get("character_sheet") or {}
    gm_proof = clean_import.get("gm_model") or {}
    consumer_proof = clean_import.get("consumer") or {}
    if (
        sheet_proof.get("semantic_equal") is not True
        or gm_proof.get("semantic_equal") is not True
        or not gm_proof.get("source_model_semantic_hash")
        or not gm_proof.get("package_view_semantic_hash")
        or consumer_proof.get("status") != "GM_SCREEN_SOURCE_CONSUMER_VERIFIED"
    ):
        raise FoundryError(
            "REC1_P1CR3_ACCEPTANCE_SEMANTIC_EQUALITY_INVALID",
            "The finalized clean-root proof does not assert Character Sheet and GM semantic equality.",
            details={"character_sheet": sheet_proof, "gm_model": gm_proof, "consumer": consumer_proof},
            status_code=409,
        )
    consumer_report = outputs.get("gm_consumer") or {}
    browser_runtime = consumer_report.get("browser_runtime") or {}
    browser_runtime_valid = (
        consumer_report.get("status") == "GM_SCREEN_SOURCE_CONSUMER_VERIFIED"
        and isinstance(browser_runtime, dict)
        and browser_runtime.get("runtime_kind") in {"explicit_executable", "discovered_executable", "playwright_default_headless_shell"}
        and isinstance(browser_runtime.get("resolved_executable"), str)
        and Path(browser_runtime["resolved_executable"]).is_file()
    )
    if browser:
        browser_runtime_valid = browser_runtime_valid and browser_runtime.get("requested_executable") == browser
    if not browser_runtime_valid:
        raise FoundryError(
            "REC1_P1CR3_ACCEPTANCE_BROWSER_RUNTIME_INVALID",
            "The fresh acceptance did not preserve exact-consumer runtime identity and verified status.",
            details={"consumer_status": consumer_report.get("status"), "browser_runtime": browser_runtime, "requested_browser": browser},
            status_code=409,
        )
    registration = portable.get("registration") or {}
    installed_path = Path(str(registration.get("package_path") or ""))
    if registration.get("status") != "GM_SCREEN_SOURCE_CONSUMER_VERIFIED" or not installed_path.is_file() or sha256_file(installed_path) != package_sha256:
        raise FoundryError(
            "REC1_P1CR3_ACCEPTANCE_REGISTRATION_INVALID",
            "The finalized verified installation does not equal the completed package.",
            details={"registration": registration, "installed_path": str(installed_path)},
            status_code=409,
        )
    combat = (portable.get("clean_import") or {}).get("combat") or {}
    if combat.get("equality") is not True:
        raise FoundryError(
            "REC1_P1CR3_ACCEPTANCE_COMBAT_EVIDENCE_INVALID",
            "The acceptance fixture did not preserve the raw producer/package/installed combat equality proof.",
            details={"combat": combat},
            status_code=409,
        )

    fresh_db = Database(settings)
    fresh_db.migrate()
    fresh_store = ProjectStore(fresh_db)
    lifecycle = fresh_store.builder_lifecycle(initial_run["project_id"])
    save_receipt = (
        fresh_store.save_builder_draft(initial_run["project_id"])
        if lifecycle.get("persistence_state") == "temporary"
        else lifecycle
    )
    reopened_db = Database(settings)
    reopened_db.migrate()
    reopened_store = ProjectStore(reopened_db)
    reopened_sheet = CharacterSheetService(reopened_db).sheet(initial_run["project_id"])
    reopened_project = reopened_store.get_project(initial_run["project_id"])["project"]
    response_identity = (response.get("owner_descriptive_fields") or {}).get("identity") or {}
    response_name = str(response_identity.get("name") or "").strip()
    response_concept = str((response.get("owner_descriptive_fields") or {}).get("concept") or "").strip()
    reopened_identity = reopened_sheet.get("identity") or {}
    reopened_spheres = ((reopened_sheet.get("owner_character_sheet") or {}).get("spheres_and_talents") or {}).get("sphere_record_ids") or []
    reopened_talents = ((reopened_sheet.get("owner_character_sheet") or {}).get("spheres_and_talents") or {}).get("learned_talent_record_ids") or []
    expected_sphere_ids = [
        *accepted_spheres,
        BACKGROUND_CANONICAL_SPHERE_ID,
    ]
    reopened_sphere_surface = {
        "count": len(reopened_spheres),
        "distinct_count": len(set(reopened_spheres)),
        "ids": list(reopened_spheres),
        "count_equal": len(reopened_spheres) == TOTAL_SPHERE_COUNT and set(reopened_spheres) == set(expected_sphere_ids),
    }
    if not reopened_sphere_surface["count_equal"] or reopened_sphere_surface["distinct_count"] != TOTAL_SPHERE_COUNT:
        raise FoundryError(
            "REC1_P1CR3_ACCEPTANCE_REOPENED_SPHERES_INVALID",
            "The reopened Character Sheet did not preserve exactly twelve distinct canonical Spheres.",
            details={"expected_ids": expected_sphere_ids, "reopened": reopened_sphere_surface},
            status_code=409,
        )
    event_replay_spheres = _event_replay_sphere_evidence(
        db,
        initial_run["project_id"],
        expected_sphere_ids,
    )
    clean_import_package_path = Path(str((clean_import.get("first") or {}).get("package_path") or ""))
    package_spheres = _package_sphere_surfaces(package_path, expected_sphere_ids)
    clean_import_spheres = _package_sphere_surfaces(clean_import_package_path, expected_sphere_ids)
    sphere_surfaces = {
        "producer_sheet": package_spheres["package_owner_sheet"],
        "reopened_sheet": reopened_sphere_surface,
        **package_spheres,
        **{
            f"clean_import_{key.removeprefix('package_')}": value
            for key, value in clean_import_spheres.items()
        },
    }
    live_reopen = {
        "project_id": reopened_project.get("project_id"),
        "revision": reopened_project.get("revision"),
        "save_receipt": save_receipt,
        "sheet_build_status": reopened_sheet.get("build_status"),
        "name": reopened_identity.get("name"),
        "concept": reopened_identity.get("concept"),
        "target_cl": reopened_identity.get("target_cl"),
        "current_cl": reopened_identity.get("current_cl"),
        "sphere_count": len(reopened_spheres),
        "sphere_ids": list(reopened_spheres),
        "talent_count": len(reopened_talents),
        "name_equal": reopened_identity.get("name") == response_name,
        "concept_equal": reopened_identity.get("concept") == response_concept,
        "target_cl_equal": reopened_identity.get("target_cl") == TARGET_CL,
        "current_cl_equal": reopened_identity.get("current_cl") == TARGET_CL,
        "sphere_count_equal": reopened_sphere_surface["count_equal"],
        "talent_count_equal": len(reopened_talents) == len(accepted_ordinary) + len(accepted_free),
    }
    if not all(live_reopen[key] is True for key in ("name_equal", "concept_equal", "target_cl_equal", "current_cl_equal", "sphere_count_equal", "talent_count_equal")):
        raise FoundryError(
            "REC1_P1CR3_ACCEPTANCE_FRESH_REOPEN_INVALID",
            "A fresh Database/ProjectStore/CharacterSheetService reopen did not reproduce the delegated identity and accepted counts.",
            details=live_reopen,
            status_code=409,
        )

    dry_run = finalized.get("dry_run") or {}
    preview_evidence = {
        "deterministic": dry_run.get("deterministic") is True,
        "independent_compilations": dry_run.get("independent_compilations"),
        "independent_compilations_equal": dry_run.get("independent_compilations") == 2,
        "candidate_identity": dry_run.get("candidate_identity"),
        "initial_candidate_identity": (initial_run.get("dry_run") or {}).get("candidate_identity"),
        "identity_map": deepcopy(dry_run.get("identities") or {}),
        "initial_identity_map": deepcopy((initial_run.get("dry_run") or {}).get("identities") or {}),
        "identity_map_equal": dry_run.get("identities") == (initial_run.get("dry_run") or {}).get("identities"),
        "candidate_identity_equal": dry_run.get("candidate_identity") == (initial_run.get("dry_run") or {}).get("candidate_identity"),
    }
    if not all(preview_evidence[key] is True for key in ("deterministic", "independent_compilations_equal", "identity_map_equal", "candidate_identity_equal")):
        raise FoundryError(
            "REC1_P1CR3_ACCEPTANCE_PREVIEW_IDENTITY_INVALID",
            "The final dry-run evidence did not preserve deterministic two-compilation identity maps.",
            details=preview_evidence,
            status_code=409,
        )
    return {
        "project": {
            "delegated_name": True,
            "delegated_concept": True,
            "power_band": POWER_BAND,
            "sphere_priority_count": len(priorities),
        },
        "materialized": {
            "target_cl": parsed_plan.get("target_cl"),
            "sphere_count": sphere_accounting["sphere_acquisition_event_count"],
            "background_sphere_count": sphere_accounting["background_sphere_acquisition_event_count"],
            "semantic_sphere_count": sphere_accounting["semantic_sphere_acquisition_event_count"],
            "free_talent_count": sphere_accounting["semantic_free_talent_pair_count"],
            "ordinary_talent_count": sphere_accounting["ordinary_talent_acquisition_event_count"],
            "ordinary_effective_cls": sphere_accounting["ordinary_effective_cls"],
            "accepted_final_plan_target_cl": final_plan.get("target_cl"),
        },
        "package": {
            "filename": package_path.name,
            "path": str(package_path),
            "installed_path": str(installed_path),
            "bytes": package_bytes,
            "sha256": package_sha256,
            "member_count": len(inventory),
            "checksum_count": audit.get("checksum_count"),
            "member_inventory_sha256": audit.get("member_inventory_sha256"),
            "crc_status": audit.get("crc_validation", {}).get("status"),
            "checksum_coverage": audit.get("checksum_manifest", {}).get("coverage_status"),
        },
        "semantic_equality": {
            "character_sheet": sheet_proof,
            "gm_model": gm_proof,
            "gm_consumer": {
                **consumer_proof,
                "status": consumer_report.get("status"),
                "browser_runtime": deepcopy(browser_runtime),
            },
            "combat": combat,
        },
        "sphere_accounting": sphere_accounting,
        "event_replay_spheres": event_replay_spheres,
        "sphere_surfaces": sphere_surfaces,
        "browser_runtime": deepcopy(browser_runtime),
        "milestone_resolution": milestone_evidence,
        "fresh_live_reopen": live_reopen,
        "preview_identity": preview_evidence,
    }


def run_acceptance(*, data_dir: Path, report_path: Path, browser: str | None = None) -> dict[str, Any]:
    if browser:
        os.environ["TIANXIA_BROWSER_EXECUTABLE"] = browser
    if not PINNED_FACTORY.is_file() or sha256_file(PINNED_FACTORY) != PINNED_FACTORY_SHA256:
        raise FoundryError(
            "REC1_P1CR3_ACCEPTANCE_FACTORY_INVALID",
            "The pinned Factory archive is missing or has an unexpected SHA-256.",
            details={"path": str(PINNED_FACTORY), "expected_sha256": PINNED_FACTORY_SHA256},
            status_code=500,
        )
    settings = Settings.from_env(ROOT, data_dir.resolve())
    db = Database(settings)
    db.migrate()
    configured = FactoryAdapter(db).configure(PINNED_FACTORY)
    CatalogService(db).rebuild_core(Path(configured["factory_root"]))
    app = create_app(settings)
    builder = app.state.character_builder
    created = _build_project(builder)
    project_id = created["project"]["project_id"]
    Stage1ClipboardService(db).generate_prompt(project_id)
    execution = app.state.character_creation
    run = execution.start(
        project_id,
        execution_mode="MANUAL_CHAT",
        idempotency_key="rec1-p1cr3-real-cl20-acceptance",
    )
    before_preview = _project_snapshot(db, project_id)
    response = _semantic_response(run, ROOT)
    response_text = canonical_json(response)
    request_filename, request_payload = execution.complete_request_zip(run["run_id"])
    with zipfile.ZipFile(io.BytesIO(request_payload)) as request_archive:
        if request_archive.testzip() is not None or "RESPONSE_SCHEMA.json" not in request_archive.namelist():
            raise FoundryError(
                "REC1_P1CR3_ACCEPTANCE_REQUEST_PACKAGE_INVALID",
                "The sealed complete-character request package failed its ZIP/schema check.",
                details={"filename": request_filename},
                status_code=500,
            )
        response_schema = json.loads(request_archive.read("RESPONSE_SCHEMA.json"))["preferred_response"]
    schema_errors = list(Draft202012Validator(response_schema).iter_errors(response))
    if schema_errors:
        raise FoundryError(
            "REC1_P1CR3_ACCEPTANCE_RESPONSE_SCHEMA_INVALID",
            "The generated acceptance response does not validate against the sealed preferred schema.",
            details={"errors": [error.message for error in schema_errors[:10]]},
            status_code=500,
        )
    preview = execution.submit_manual(
        run["run_id"],
        response_text=response_text,
        request_sha256=run["request"]["request_sha256"],
    )
    after_preview = _project_snapshot(db, project_id)
    if before_preview != after_preview:
        raise FoundryError(
            "REC1_P1CR3_ACCEPTANCE_PREVIEW_MUTATED_PROJECT",
            "The semantic preview changed project mechanics before owner finalization.",
            status_code=500,
        )
    if preview.get("status") != "READY_FOR_REVIEW":
        raise FoundryError(
            "REC1_P1CR3_ACCEPTANCE_PREVIEW_NOT_CLEAN",
            "The real semantic CL20 response did not produce a clean review candidate.",
            details={"status": preview.get("status"), "blockers": preview.get("blockers")},
            status_code=409,
        )
    finalized = execution.finalize(run["run_id"])
    acceptance_evidence = _acceptance_evidence(
        settings=settings,
        db=db,
        execution=execution,
        initial_run=preview,
        finalized=finalized,
        response=response,
        browser=browser,
    )
    portable = (finalized.get("outputs") or {}).get("portable_character") or {}
    audit = portable.get("audit") or {}
    package_path = audit.get("path") or audit.get("package_path")
    package_sha256 = sha256_file(Path(package_path)) if package_path and Path(package_path).is_file() else None
    report = {
        "schema": "TianxiaFoundry.REC1P1CR3RealAcceptanceReport.v1",
        "status": "PASS",
        "project_id": project_id,
        "run_id": run["run_id"],
        "target_cl": TARGET_CL,
        "pinned_factory_sha256": PINNED_FACTORY_SHA256,
        "response_schema": RESPONSE_SCHEMA,
        "response_sha256": sha256_json(response),
        "browser_status": acceptance_evidence["semantic_equality"]["gm_consumer"].get("status"),
        "browser_runtime": deepcopy(acceptance_evidence["browser_runtime"]),
        "preferred_top_level_keys": sorted(response),
        "preferred_response_has_backend_event_fields": any(
            field in response
            for field in (
                "target_cl",
                "stage1_response",
                "stage2_proposal",
                "event_kinds",
                "acquisition_channels",
                "effective_cl_rows",
            )
        ),
        "preview": {
            "status": preview.get("status"),
            "deterministic": (preview.get("dry_run") or {}).get("deterministic"),
            "independent_compilations": (preview.get("dry_run") or {}).get("independent_compilations"),
            "project_unchanged": before_preview == after_preview,
        },
        "finalization": {
            "status": finalized.get("status"),
            "candidate_identity": (finalized.get("dry_run") or {}).get("candidate_identity"),
            "attempt_history_count": len(finalized.get("attempt_history") or []),
        },
        "acceptance_assertions": acceptance_evidence,
        "completed_package": {
            "path": package_path,
            "sha256": package_sha256,
            "audit_sha256": audit.get("sha256"),
            "audit_valid": audit.get("valid"),
            "gm_consumer_status": (portable.get("gm_export") or {}).get("status")
            or (finalized.get("outputs") or {}).get("gm_consumer", {}).get("status"),
            "clean_import": portable.get("clean_import"),
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--browser", default=os.environ.get("TIANXIA_BROWSER_EXECUTABLE"))
    args = parser.parse_args()
    try:
        report = run_acceptance(data_dir=args.data, report_path=args.report, browser=args.browser)
    except Exception as exc:
        report = {
            "schema": "TianxiaFoundry.REC1P1CR3RealAcceptanceReport.v1",
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
