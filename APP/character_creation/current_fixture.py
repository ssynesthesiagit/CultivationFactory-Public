from __future__ import annotations

import json
import uuid
from copy import deepcopy
from typing import Any

from app.core import Database, FoundryError
from character_builder import CharacterBuilderService
from stage1.service import Stage1ClipboardService

QI_PATH = "tianxia.path.qi_cultivation"
CINDER_HEART = "tianxia.subpath.qi.cinder_heart_cultivator"
ABANDONED_ORPHAN = "tianxia.background.abandoned_orphan"
SCOUNDREL = "tianxia.sphere.scoundrel"
HIDDEN_TOOL_CACHE = "tianxia.background_talent.scoundrel.hidden_tool_cache"
HIDDEN_TOOL_CACHE_STAGE2 = "TAL_SCOUNDREL_HIDDEN_TOOL_CACHE"
STREET_HARDENED = "tianxia.origin_insight.street_hardened"
FIRE = "tianxia.sphere.fire"
FIRE_TALENTS = (
    "FIRE_TAL_FLAME_LASH",
    "FIRE_TAL_BURNING_WEAPON",
    "FIRE_TAL_FIRE_WARD",
    "FIRE_TAL_COMBUSTIVE_STEP",
    "FIRE_TAL_HEAT_HAZE",
    "FIRE_TAL_FIREBALL_ART",
)
STARTING_SCORES = {"STR": 8, "DEX": 14, "CON": 14, "INT": 15, "WIS": 12, "CHA": 8}
W5_PROJECT_ID = "40ea751e-7913-557f-b403-a3ec3cd7c004"
W5_PROJECT_NAME = "W5 Current Fire-Qi Owner-Test Fixture"

SELECTIONS = {
    "path_choice": [QI_PATH],
    "subpath_choice": [CINDER_HEART],
    "background_choice": [ABANDONED_ORPHAN],
    "background_talent_choice": [HIDDEN_TOOL_CACHE],
    "origin_insight_choice": [STREET_HARDENED],
    "sphere_priorities": [FIRE],
    # Only the current creator-selectable subset is locked as blueprint intent.
    # The remaining accepted Fire progression is resolved by Stage 2 authority.
    "advancement_skeleton": [FIRE_TALENTS[0], FIRE_TALENTS[1], FIRE_TALENTS[5]],
}


def _assert_current_choices(builder: CharacterBuilderService) -> None:
    options = builder.options()
    by_slot = {
        category["slot_id"]: {choice["choice_id"] for choice in category.get("choices", [])}
        for category in options["categories"]
    }
    missing = sorted(
        f"{slot}:{value}"
        for slot, values in SELECTIONS.items()
        for value in values
        if value not in by_slot.get(slot, set())
    )
    if missing:
        raise FoundryError(
            "CG1_CURRENT_FIXTURE_CHOICE_UNAVAILABLE",
            f"The bounded Fire/Qi fixture no longer resolves against the current catalog: {missing}",
            details={"missing_choice_ids": missing},
        )


def create_fresh_project(db: Database, *, project_id: str | None = None) -> dict[str, Any]:
    """Create the bounded acceptance project through the current Character Builder."""
    builder = CharacterBuilderService(db)
    _assert_current_choices(builder)
    created = builder.create_project(
        working_name=W5_PROJECT_NAME,
        concept="Cinder Heart Cultivator; Abandoned Orphan; Street-Hardened.",
        target_cl=5,
        power_band="bounded-production-acceptance",
        source_reference="Accepted C1A owner intent; current catalog authority only",
        creation_mode="detailed",
        ability_scores=deepcopy(STARTING_SCORES),
        selections=deepcopy(SELECTIONS),
        canonical_sphere_ids=[FIRE],
        sphere_free_talent_grants={FIRE: FIRE_TALENTS[0]},
        ordinary_talent_ids=[FIRE_TALENTS[1], FIRE_TALENTS[5]],
        background_route_ids={
            "background_route_record_id": "tianxia.background_talent.scoundrel.hidden_tool_cache",
            "background_talent_choice_id": HIDDEN_TOOL_CACHE,
            "background_sphere_choice_id": SCOUNDREL,
            "origin_insight_choice_id": STREET_HARDENED,
        },
        generation_route="ai_bootstrap",
        project_id_override=project_id,
    )
    project_id = created["project"]["project_id"]
    # These accepted C1A selections are stable owner-intent references, appended
    # through the current immutable project-lock service before Stage 1. No old
    # project identity, revision, event, hash, or artifact is reused.
    return builder.projects.append_user_locks(project_id, [
        {"field": "character.identity.display_name", "value": W5_PROJECT_NAME, "source": "w5-p1-current-fixture"},
        {"field": "character.choices.qi_cultivation_skills", "value": ["tianxia.fixture.skill.arcana", "tianxia.fixture.skill.history"], "source": "w5-p1-current-fixture"},
        {"field": "character.choices.street_hardened", "value": "tianxia.fixture.street_hardened.deception", "source": "w5-p1-current-fixture"},
        {"field": "character.choices.language", "value": "tianxia.language.classical", "source": "w5-p1-current-fixture"},
    ])


def exact_stage1_response(prompt: dict[str, Any]) -> dict[str, Any]:
    envelope = prompt["envelope"]
    decisions = []
    for slot in envelope["decision_slots"]:
        required = list(slot.get("required_choice_ids") or [])
        if required:
            decision = {"slot_id": slot["slot_id"], "state": "selected", "choice_ids": required}
        elif slot["coverage_state"] == "blocked_missing_authority":
            decision = {
                "slot_id": slot["slot_id"],
                "state": "blocked_missing_authority",
                "choice_ids": [],
                "reason_code": slot["blocked_reason_code"],
                "reason": slot["blocked_reason"],
            }
        else:
            decision = {
                "slot_id": slot["slot_id"],
                "state": "deferred_with_reason",
                "choice_ids": [],
                "reason_code": "deferred_future_decision",
                "reason": "The bounded Fire/Qi acceptance fixture does not select another choice in this slot.",
            }
        decisions.append(decision)
    return {
        "protocol_version": "TianxiaFoundry.AIClipboard.Stage1.v2",
        "response_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"w5-current-fixture:{prompt['prompt_sha256']}")),
        "prompt_id": prompt["prompt_id"],
        "prompt_sha256": prompt["prompt_sha256"],
        "project_id": envelope["project_id"],
        "expected_project_revision": envelope["project_revision"],
        "catalog_build_id": envelope["catalog_build_id"],
        "content_lock_hash": envelope["content_lock_hash"],
        "stage_id": envelope["stage_id"],
        "response_payload": {
            "decisions": decisions,
            "authored_notes": [],
            "planner_rationale": "Exact bounded Fire/Qi owner intent; all mechanics remain locally compiled.",
        },
    }


def _choice(kind: str, cl: int, record_id: str, channel: str, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "kind": kind,
        "effective_cl": cl,
        "record_id": record_id,
        "acquisition_channel": channel,
        "parameters": deepcopy(parameters or {}),
    }


def stage2_choices() -> list[dict[str, Any]]:
    return [
        _choice("starting_state", 0, "tianxia.source.canon.authority.manifest.p2a.json", "source-document", {"ability_scores": deepcopy(STARTING_SCORES)}),
        _choice("background_acquisition", 1, ABANDONED_ORPHAN, "background-selection", {"ability": "DEX", "amount": 2}),
        _choice("background_sphere_acquisition", 1, SCOUNDREL, "background-grant"),
        _choice("background_talent_acquisition", 1, HIDDEN_TOOL_CACHE_STAGE2, "background-grant"),
        _choice("origin_insight_acquisition", 1, STREET_HARDENED, "origin-selection"),
        _choice("path_acquisition", 1, QI_PATH, "path-selection"),
        _choice("ai_bootstrap_sphere_acquisition", 1, FIRE, "ai-bootstrap-free-cl1-sphere"),
        _choice("ai_bootstrap_talent_acquisition", 1, FIRE_TALENTS[0], "ai-bootstrap-free-cl1-talent"),
        _choice("level_advance", 1, "tianxia.path.qi_cultivation.feature.qi_sensing", "level-advance"),
        _choice("level_talent_acquisition", 1, FIRE_TALENTS[1], "level-choice"),
        _choice("level_advance", 2, "tianxia.path.qi_cultivation.feature.meridian_regulation", "level-advance"),
        _choice("level_talent_acquisition", 2, FIRE_TALENTS[2], "level-choice"),
        _choice("level_advance", 3, "tianxia.path.qi_cultivation.feature.qi_cultivation_subpath", "level-advance"),
        _choice("subpath_acquisition", 3, CINDER_HEART, "subpath-selection"),
        _choice("level_talent_acquisition", 3, FIRE_TALENTS[3], "level-choice"),
        _choice("level_advance", 4, "tianxia.path.qi_cultivation.feature.ability_score_improvement_or_cultivation_insight", "level-advance"),
        _choice("ability_score_change", 4, "tianxia.path.qi_cultivation.feature.ability_score_improvement_or_cultivation_insight", "level-choice", {"deltas": {"INT": 2}}),
        _choice("level_talent_acquisition", 4, FIRE_TALENTS[4], "level-choice"),
        _choice("level_advance", 5, "tianxia.path.qi_cultivation.feature.qi_armor", "level-advance"),
        _choice("level_talent_acquisition", 5, FIRE_TALENTS[5], "level-choice"),
        *[
            _choice(
                "typed_none",
                5,
                f"tianxia.c1a.none.{target}",
                "typed-none",
                {
                    "target": target,
                    "reason_code": "not_selected_for_c1a_proof",
                    "reason": "The bounded current acceptance identity does not select this optional subsystem.",
                },
            )
            for target in ("method", "foundation", "manuals", "equipment", "forged_techniques")
        ],
    ]


def complete_plan(db: Database, project_id: str) -> dict[str, Any]:
    prompt = Stage1ClipboardService(db).generate_prompt(project_id)
    project = CharacterBuilderService(db).projects.get_project(project_id)["project"]
    return {
        "schema": "TianxiaFoundry.CharacterCreationPlan.v2",
        "stage1_response": exact_stage1_response(prompt),
        "target_cl": 5,
        "stage2_proposal": {
            "schema_version": "TianxiaFoundry.Stage2AdvancementProposal.v2",
            "project_id": project_id,
            "expected_project_revision": int(project["revision"]) + 1,
            "expected_content_lock_hash": project["content_lock"]["lock_hash"],
            "target_cl": 5,
            "idempotency_key": "w5.current.fixture.stage2",
            "choices": stage2_choices(),
        },
        "owner_descriptive_fields": {
            "identity": {"name": W5_PROJECT_NAME},
            "concept": "Qi Cultivation / Cinder Heart / Abandoned Orphan / Street-Hardened",
        },
        "uncertainties": [],
        "fallbacks": [],
        "output_profile": {"combat_ready": False, "profile": "CHARACTER_GM_MODEL"},
    }

def exact_plan_text(db: Database, project_id: str) -> str:
    return json.dumps(complete_plan(db, project_id), sort_keys=True, separators=(",", ":"))
