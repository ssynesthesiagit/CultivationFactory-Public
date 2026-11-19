"""Shared synthetic insight selection fixtures for controller and pulse-memory tests."""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from character_creation.creative_controller import seeded_picker
from character_creation.creative_controller.linear_menus import CommittedState
from character_creation.creative_controller.linear_walk import (
    ACTION_AUTOCOMMITTED, ACTION_COMPLETE, ACTION_MENU, commit_identity, commit_option, next_step,
)

PATH_ID = "tianxia.path.qi_cultivation"

FEATURE_ID = f"{PATH_ID}.feature.ability_score_improvement_or_cultivation_insight"

SUBPATH_ID = "tianxia.subpath.qi.twin_tide_paired_saber_cultivator"

SELECTION_LEVELS = (4, 8, 12, 16, 19)

INSIGHT_ROWS = [
    ("insight.crescent-projection-student", "Crescent Projection Student", ["WIS", "CHA"], []),
    ("insight.ancestral-bloodline-awakening", "Ancestral Bloodline Awakening", ["STR", "CON"], []),
    ("insight.alchemical-constitution", "Alchemical Constitution", ["CON", "INT", "WIS"],
     [{"kind": "path", "operator": "requires", "target_id": PATH_ID}]),
    ("insight.butcher-s-mercy", "Butcher's Mercy", ["STR", "DEX"], []),
    ("insight.brutal-momentum", "Brutal Momentum", ["STR", "CON"], []),
]

def _insight_row(insight_id: str, name: str, abilities: list[str], prerequisites: list[dict]) -> dict:
    """One frozen ``insight_priorities`` row, shaped as Stage 1 freezes it.

    ``stage2_authority`` is the typed acquisition contract
    (``schemas/Cultivation_Insight_Stage2_Authority_v1.schema.json``) that
    lets a level milestone offer this Insight and name the abilities its
    printed +1 increase may go to.
    """
    return {
        "choice_id": insight_id,
        "name": name,
        "display_name": name,
        "content_type": "cultivation_insight",
        "authority": "canonical",
        "publication_state": "published",
        "acquisition_channels": ["cultivation-insight-selection"],
        "availability": {"minimum_cl": 1, "realm_rules": {}, "source_cl": {}, "suppression": {}},
        "description": f"**Ability Increase (Level Selection):** raise {' or '.join(abilities)} by 1.",
        "incompatibilities": [],
        "parent_relationships": [],
        "prerequisites": deepcopy(prerequisites),
        "stage2_authority": {
            "authority_complete": True,
            "allowed_kinds": ["cultivation_insight_acquisition"],
            "allowed_channels": ["cultivation-insight-selection"],
            "minimum_cl": 1,
            "allowed_cls": list(SELECTION_LEVELS),
            "insight_authority_type": "General",
            "insight_group": {},
            "owning_canonical_sphere_ids": [],
            "typed_prerequisites": deepcopy(prerequisites),
            "ability_change": {
                "selection_mode": "level_selection",
                "allowed_abilities": list(abilities),
                "amount": 1,
                "cap": 20,
                "allowed_cls": list(SELECTION_LEVELS),
                "source_field": "ability_options",
                "source_value": list(abilities),
            },
            "insight_ability_change": {
                "selection_mode": "level_selection",
                "allowed_abilities": list(abilities),
                "amount": 1,
                "cap": 20,
                "allowed_cls": list(SELECTION_LEVELS),
                "source_field": "ability_options",
                "source_value": list(abilities),
            },
            "repeatability": {
                "mode": "nonrepeatable", "maximum": 1, "indexing": "one_based_contiguous",
                "source_field": "repeatable", "source_value": "no",
            },
            "rule_id": f"stage2.insight.{insight_id}",
        },
    }

def _milestone_row(cl: int) -> dict:
    """The frozen ``advancement_choice_milestones`` row for one level.

    Shaped exactly as Stage 1 freezes it: typed kinds, CL, the source-bound
    ability-change budget -- and no ``resolution_options``.  The sealed provider
    projection supplies ``resolution_options``; the walk must resolve the same
    printed choice from either row shape.
    """
    return {
        "milestone_id": f"{FEATURE_ID}.cl{cl}",
        "path_id": PATH_ID,
        "cl": cl,
        "count": 1,
        "feature_kind": "advancement_choice",
        "feature_record_id": FEATURE_ID,
        "allowed_kinds": ["ability_score_change", "cultivation_insight_acquisition"],
        "ability_change": {
            "allowed_deltas": [1, 2],
            "budget": 2,
            "cap": 20,
            "allowed_cls": list(SELECTION_LEVELS),
        },
        "ability_change_source": {
            "authority": "authenticated_non_sphere_path_feature",
            "rule_id": f"ns1r.{PATH_ID}.ability_score_improvement_or_cultivation_insight.v1",
            "source": {
                "source_id": "source.686855dc1fc1e1981688b207",
                "path": "non_sphere_authority/authority/qi_cultivation.path_index.p2a.json",
                "anchor": f"path-feature:{PATH_ID}:{FEATURE_ID}",
                "source_hash": "3dd8141502d489085f9a57e45fccaa3c45fb2c1f327d5dd34cdbb811a9bc48ca",
            },
        },
        "source_path": "non_sphere_authority/authority/qi_cultivation.path_index.p2a.json",
        "source_hash": "3dd8141502d489085f9a57e45fccaa3c45fb2c1f327d5dd34cdbb811a9bc48ca",
    }

def _envelope(target_cl: int, *, insight_ids: tuple[str, ...] | None = None) -> dict:
    rows = {f"{FEATURE_ID}.cl{cl}": _milestone_row(cl) for cl in SELECTION_LEVELS}
    insight_rows = {
        insight_id: _insight_row(insight_id, name, abilities, prerequisites)
        for insight_id, name, abilities, prerequisites in INSIGHT_ROWS
        if insight_ids is None or insight_id in insight_ids
    }
    parameters = {
        insight_id: {"allowed_abilities": INSIGHT_ROWS_LOOKUP[insight_id][0], "amount": 1}
        for insight_id in insight_rows
    }
    projection_milestones = {}
    for milestone_id, row in rows.items():
        if row["cl"] > target_cl:
            continue
        projection_milestones[milestone_id] = {
            **deepcopy(row),
            "effective_cl": row["cl"],
            "resolution_cardinality": "exactly_one",
            "allowed_resolutions": ["ability_score_change", "cultivation_insight_acquisition"],
            "resolution_options": {
                "ability_score_change": {
                    "destination": f"bounded_choices.ability_score_changes_by_milestone_id.{milestone_id}",
                    "constraints": {
                        "allowed_deltas": [1, 2],
                        "budget": 2,
                        "cap": 20,
                        "allowed_cls": list(SELECTION_LEVELS),
                    },
                },
                "cultivation_insight_acquisition": {
                    "destination": "acquisition_intent.insight_occurrences[]",
                    "allowed_insight_ids": sorted(insight_rows),
                    "parameters_by_insight_id": parameters,
                },
            },
        }
    return {
        "schema": "TianxiaFoundry.DelegatedChoiceEnvelope.v1",
        "frozen_owner_target_cl": target_cl,
        "advancement_choice_milestones": list(rows.values()),
        "choices_by_slot": {"insight_priorities": insight_rows, "path_choice": {PATH_ID: {"choice_id": PATH_ID, "name": "Qi Cultivation"}}},
        "selection_limits_by_slot": {
            "path_choice": {"min_choices": 1, "max_choices": 1, "final_min": 1, "final_max": 1},
            "subpath_choice": {"min_choices": 0, "max_choices": 1, "final_min": 0, "final_max": 1},
            "insight_priorities": {"allow_none": True, "final_min": 0, "final_max": len(insight_rows), "owner_lock_min": 0, "owner_lock_max": 8},
            "ordinary_talent_ids": {"min_choices": 0, "max_choices": 0, "final_min": 0, "final_max": 0},
        },
        "owner_locks": {
            "by_slot": {
                "path_choice": [PATH_ID],
                "subpath_choice": [SUBPATH_ID],
                # A Quick Build owner locks the whole non-level surface, so the
                # walk reaches the level choices with nothing else outstanding.
                "method_choice": ["tianxia.method.qi.meridian_circulation"],
                "foundation_choice": [],
                "background_choice": ["tianxia.background.furnace_laborer"],
                "background_sphere_choice": ["tianxia.sphere.blacksmith"],
                "background_talent_choice": ["tianxia.talent.blacksmith.field_repair"],
                "origin_insight_choice": ["tianxia.origin_insight.body_is_a_shrine"],
                "insight_priorities": [],
                "sphere_priorities": [],
                "item_priorities": [],
                "advancement_skeleton": [],
            },
            "zero_owner_path_locks_are_legal": True,
        },
        "linear_provider_payload": {
            "response_contract": {
                "required_milestone_resolutions": projection_milestones,
                "expected_acquisition_counts": {"ordinary_talent_ids": 0, "sphere_free_talent_pairs": 0},
            }
        },
    }

INSIGHT_ROWS_LOOKUP = {row[0]: (row[2], row[1]) for row in INSIGHT_ROWS}

def _request(target_cl: int) -> dict:
    return {
        "schema": "TianxiaFoundry.CharacterCreationRequest.v1",
        "request_sha256": "a" * 64,
        "target_cl": target_cl,
        "autogen_seed": "OCF4-INSIGHT",
    }

def _starting_state(target_cl: int) -> CommittedState:
    """A character with everything except the level choices already committed."""
    state = CommittedState(
        by_slot={"path_choice": [PATH_ID], "subpath_choice": [SUBPATH_ID]},
        pairs=(), ordinary_by_cl={}, insight_occurrences=(),
        bounded={"ability_scores": {"STR": 15, "DEX": 13, "CON": 14, "INT": 15, "WIS": 10, "CHA": 8}},
        route_id="DETERMINISTIC_CREATIVE_CONTROLLER",
        trained_choice_skips=tuple(range(1, target_cl + 1)),
    )
    return state

def _walk_until(request: dict, envelope: dict, state: CommittedState, done, *, seed: str = "OCF4-INSIGHT", chooser=None) -> CommittedState:
    """Walk with the seeded picker until ``done(state)``, exactly as a build does.

    The picker, ``next_step`` and ``commit_option`` are the real ones the
    deterministic creative controller uses, so a step the walk never offers is
    a step this test cannot see.  ``chooser`` replaces the picker where a test
    wants a specific printed answer; it receives the menu and returns an option
    ID.  An autocommitted single-option step is already committed by the walk
    engine, so it is never committed a second time here.
    """
    choose = chooser or (lambda menu: seeded_picker.choose_option(seed, menu))
    seen_steps: list[str] = []
    for _ in range(60):
        if done(state):
            return state
        step = next_step(request, envelope, state)
        if step.action == ACTION_COMPLETE:
            return state
        assert step.action in {ACTION_MENU, ACTION_AUTOCOMMITTED}, step
        seen_steps.append(step.step_id)
        if step.action == ACTION_AUTOCOMMITTED:
            state = step.committed
            continue
        if step.step_kind == "identity":
            state = commit_identity(step.menu, seeded_picker.identity(seed, request, envelope), step.committed)
            continue
        state = commit_option(step.menu, choose(step.menu), step.committed)
    raise AssertionError(f"the walk never reached the level choices: {seen_steps}")

def _milestone_id(cl: int) -> str:
    return f"{FEATURE_ID}.cl{cl}"

def _resolution_by_milestone(state: CommittedState) -> dict[str, str]:
    """Which printed resolution each level of the finished walk carries.

    ``cultivation_insight`` for a level that took an Insight (with its printed
    +1 ability), ``ability_score_increase`` for a level that took the normal
    increase, and missing for a level the walk has not answered yet.
    """
    resolved = {
        row["milestone_id"]: "cultivation_insight"
        for row in state.insight_occurrences
        if isinstance(row, Mapping) and (row.get("parameters") or {}).get("ability")
    }
    resolved.update({
        milestone_id: "ability_score_increase"
        for milestone_id in (state.bounded.get("ability_score_changes_by_milestone_id") or {})
    })
    return resolved

def _levels_answered(state: CommittedState, target_cl: int) -> bool:
    """Every printed level at or below ``target_cl`` resolved exactly once."""
    resolved = _resolution_by_milestone(state)
    return all(
        _milestone_id(cl) in resolved
        for cl in SELECTION_LEVELS
        if cl <= target_cl
    )

def _step_for(request: dict, envelope: dict, state: CommittedState, step_id: str, *, seed: str = "OCF4-INSIGHT") -> tuple[object, CommittedState]:
    """Walk with the seeded picker until the named step is the one on offer."""
    for _ in range(40):
        step = next_step(request, envelope, state)
        if step.action == ACTION_COMPLETE:
            break
        if step.step_id == step_id:
            return step, state
        assert step.action in {ACTION_MENU, ACTION_AUTOCOMMITTED}, step
        if step.action == ACTION_AUTOCOMMITTED:
            state = step.committed
            continue
        if step.step_kind == "identity":
            state = commit_identity(step.menu, seeded_picker.identity(seed, request, envelope), step.committed)
            continue
        state = commit_option(step.menu, seeded_picker.choose_option(seed, step.menu), step.committed)
    raise AssertionError(f"the walk never offered {step_id}")
