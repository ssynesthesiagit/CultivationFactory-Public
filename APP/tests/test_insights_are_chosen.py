"""OCF4 regressions: a Cultivation Insight is chosen at every printed level.

Owner 2026-10-04: "I don't think I've seen a single character with Insights; we
need Insights to be chosen; why aren't they?"  Lead check: 0 of 58 finished
portable characters carried any Insight field.

Rule source (owner text, ``authority/typed_mechanics/rules_text.json``,
keys ``tianxia.path.<body_refining|qi_cultivation|spirit_awakening>.feature.
ability_score_improvement_or_cultivation_insight``):

    "## CL4, CL8, CL12, CL16, and CL19 - Ability Score Improvement or
     Cultivation Insight.  At each listed CL, choose one of the following:
     - Normal Ability Score Improvement ... - Cultivation Insight: Choose one
     Cultivation Insight for which you meet every prerequisite.  Gain its
     cultivation benefit and increase one ability score listed in that
     Insight's Ability Increase (Level Selection) entry by 1."

``catalog_authority/cat3/source/Tianxia_Central_Cultivation_Insights_AI_
Reference_R5_Legacy_Restored.json`` carries the same cadence as typed data
(``selection_levels: [4, 8, 12, 16, 19]``), so the printed number of
level-selected Insights is one per listed CL at or below the character's CL:
CL4->1, CL8->2, CL12->3, CL16->4, CL19->5.

Before this file the walk never offered the Insight branch:
``_asi_before_insight`` reserved ``ceil((19 - key_ability) / 2)`` of the
earliest dual milestones for a normal ability-score increase, which is >= 1 for
every 27-point buy, so CL5 and CL10 characters were offered no Insight at all
and CL20 characters at most three of five.

These tests drive the real ``creative_controller`` walk (the engine
``CharacterCreationExecutionService._run_dcc_linear_walk`` calls) over a
production-shaped frozen envelope, then the real response assembly, and finally
the real ledger -> portable-package projections.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import hashlib
import json

import pytest

from character_creation.creative_controller import seeded_picker
from character_creation.creative_controller.linear_menus import CommittedState, build_step_menu
from character_creation.creative_controller.linear_walk import (
    ACTION_AUTOCOMMITTED,
    ACTION_COMPLETE,
    ACTION_MENU,
    commit_identity,
    commit_option,
    next_step,
)
from character_creation.creative_controller.linear_assembly import build_response

PATH_ID = "tianxia.path.qi_cultivation"
FEATURE_ID = f"{PATH_ID}.feature.ability_score_improvement_or_cultivation_insight"
SUBPATH_ID = "tianxia.subpath.qi.twin_tide_paired_saber_cultivator"
SELECTION_LEVELS = (4, 8, 12, 16, 19)

# The owner catalogue's level-selection levels; see the module docstring.
PRINTED_INSIGHTS_BY_CL = {cl: sum(1 for level in SELECTION_LEVELS if level <= cl) for cl in range(1, 21)}

# Real canonical Insight rows (id, name, printed ability increase, prerequisite)
# copied from the shipped catalogue so the walk's typed legality filter, the
# repeat rule and the ability follow-up are all exercised on real data.
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
                "source_hash": "686855dc1fc1e1981688b207e1e0e29d1c17968391b67a974ad1e973d7b2cc58",
            },
        },
        "source_path": "non_sphere_authority/authority/qi_cultivation.path_index.p2a.json",
        "source_hash": "686855dc1fc1e1981688b207e1e0e29d1c17968391b67a974ad1e973d7b2cc58",
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


def _walk(target_cl: int, *, insight_ids: tuple[str, ...] | None = None, seed: str = "OCF4-INSIGHT", chooser=None) -> tuple[dict, dict, CommittedState]:
    """Walk every printed selection level of a character of ``target_cl``."""
    request = _request(target_cl)
    envelope = _envelope(target_cl, insight_ids=insight_ids)
    state = _walk_until(
        request, envelope, _starting_state(target_cl),
        lambda committed: _levels_answered(committed, target_cl),
        seed=seed,
        chooser=chooser,
    )
    return request, envelope, state


# Every Path carries the same printed feature at the same levels
# (authority/typed_mechanics/rules_text.json has the
# ability_score_improvement_or_cultivation_insight entry for all three Paths),
# so a character that selects two Paths holds two frozen milestone copies at
# each printed CL.  The owner ruling behind ``milestone_shadowed`` is that the
# level is ONE character choice, so exactly one copy may be answered.  These
# helpers build that production shape: the same frozen rows under the second
# Path's own feature ID, path ID and typed rule ID.
SECOND_PATH_ID = "tianxia.path.body_refining"
SECOND_SUBPATH_ID = "tianxia.subpath.body_refining.iron_blood_tempering"
SECOND_FEATURE_ID = f"{SECOND_PATH_ID}.feature.ability_score_improvement_or_cultivation_insight"


def _second_milestone_row(cl: int) -> dict:
    """The second Path's copy of the same frozen level-milestone row."""
    row = deepcopy(_milestone_row(cl))
    row["milestone_id"] = f"{SECOND_FEATURE_ID}.cl{cl}"
    row["path_id"] = SECOND_PATH_ID
    row["feature_record_id"] = SECOND_FEATURE_ID
    row["ability_change_source"] = {
        **row["ability_change_source"],
        "rule_id": f"ns1r.{SECOND_PATH_ID}.ability_score_improvement_or_cultivation_insight.v1",
        "anchor": f"path-feature:{SECOND_PATH_ID}:{SECOND_FEATURE_ID}",
    }
    return row


def _two_path_envelope(target_cl: int) -> dict:
    """The single-Path envelope plus a second selected Path's copies of it."""
    envelope = _envelope(target_cl)
    envelope["advancement_choice_milestones"] = list(envelope["advancement_choice_milestones"]) + [
        _second_milestone_row(cl) for cl in SELECTION_LEVELS
    ]
    projected = envelope["linear_provider_payload"]["response_contract"]["required_milestone_resolutions"]
    for cl in SELECTION_LEVELS:
        if _milestone_id(cl) not in projected:
            continue
        copied = deepcopy(projected[_milestone_id(cl)])
        copied["milestone_id"] = f"{SECOND_FEATURE_ID}.cl{cl}"
        copied["path_id"] = SECOND_PATH_ID
        copied["feature_record_id"] = SECOND_FEATURE_ID
        options = copied.get("resolution_options")
        if isinstance(options, dict) and isinstance(options.get("ability_score_change"), dict):
            options["ability_score_change"]["destination"] = (
                f"bounded_choices.ability_score_changes_by_milestone_id.{SECOND_FEATURE_ID}.cl{cl}"
            )
        projected[copied["milestone_id"]] = copied
    envelope["choices_by_slot"]["path_choice"][SECOND_PATH_ID] = {
        "choice_id": SECOND_PATH_ID, "name": "Body Refining",
    }
    envelope["selection_limits_by_slot"]["path_choice"] = {
        "min_choices": 2, "max_choices": 2, "final_min": 2, "final_max": 2,
    }
    envelope["owner_locks"]["by_slot"]["path_choice"] = [PATH_ID, SECOND_PATH_ID]
    envelope["owner_locks"]["by_slot"]["subpath_choice"] = [SUBPATH_ID, SECOND_SUBPATH_ID]
    return envelope


def _two_path_starting_state(target_cl: int) -> CommittedState:
    """The single-Path starting state with the second Path also selected."""
    return _starting_state(target_cl).with_slot(
        "path_choice", [PATH_ID, SECOND_PATH_ID]
    ).with_slot("subpath_choice", [SUBPATH_ID, SECOND_SUBPATH_ID])


def _both_copies(cl: int) -> tuple[str, str]:
    """The two frozen milestone IDs one printed level has with two Paths."""
    return _milestone_id(cl), f"{SECOND_FEATURE_ID}.cl{cl}"


def _resolutions_by_cl(state: CommittedState) -> dict[int, str]:
    """Which printed resolution each finished CL carries, with two Paths.

    Two Paths hold two frozen milestone copies per CL and the level is answered
    once, so the finished answer is keyed by the CL it belongs to rather than by
    the milestone copy it was committed under.
    """
    resolved: dict[int, str] = {}
    for milestone_id in state.bounded.get("ability_score_changes_by_milestone_id") or {}:
        resolved[int(milestone_id.rsplit(".cl", 1)[1])] = "ability_score_increase"
    for row in state.insight_occurrences:
        if isinstance(row, Mapping) and (row.get("parameters") or {}).get("ability"):
            resolved[int(str(row["milestone_id"]).rsplit(".cl", 1)[1])] = "cultivation_insight"
    return resolved


def _walk_levels(request: dict, envelope: dict, state: CommittedState, chooser) -> tuple[CommittedState, list[str]]:
    """Walk with ``chooser`` until every printed level at or below the target is answered.

    Returns the finished state and every step the walk put on offer, so a test
    can prove what it asked as well as what it committed.
    """
    target_cl = int(request["target_cl"])
    offered: list[str] = []
    for _ in range(60):
        if _resolutions_by_cl(state).keys() >= {cl for cl in SELECTION_LEVELS if cl <= target_cl}:
            return state, offered
        step = next_step(request, envelope, state)
        if step.action == ACTION_COMPLETE:
            break
        offered.append(step.step_id)
        if step.action == ACTION_AUTOCOMMITTED:
            state = step.committed
            continue
        if step.step_kind == "identity":
            state = commit_identity(step.menu, seeded_picker.identity("OCF4-TWO-PATH", request, envelope), step.committed)
            continue
        state = commit_option(step.menu, chooser(step.menu), step.committed)
    raise AssertionError(f"the two-Path walk never answered every printed level: {offered}")


def _branch_then_detail_chooser(plan: dict[int, str]):
    """A chooser that takes ``plan``'s printed resolution at each level."""

    def chooser(menu):
        if menu.step_kind == "asi_or_insight":
            return _pick_branch(menu, plan[int(menu.step_id.rsplit(".cl", 1)[1])])
        if menu.step_kind == "asi_milestone":
            return _pick_top_ability_increase(menu)
        return seeded_picker.choose_option("OCF4-TWO-PATH", menu)

    return chooser


def _pick_branch(menu, branch: str) -> str:
    """The option ID of one printed branch on a level-milestone menu."""
    options = [option for option in menu.options if list(option.choice_ids) == [branch]]
    assert len(options) == 1, [(option.option_id, option.choice_ids) for option in menu.options]
    return options[0].option_id


def _pick_top_ability_increase(menu) -> str:
    """The option ID of the first printed ability-score increase on an ASI menu.

    Which increases are legal is the menu builder's rule (the printed budget,
    the Realm cap, and the build policy that raises the Path's key ability
    first), so the test takes the menu's own first choice and reads back the
    deltas it commits.
    """
    options = [option for option in menu.options if not option.is_continuation]
    assert options, "the printed increase menu offered nothing"
    return options[0].option_id


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


@pytest.mark.parametrize("target_cl", [5, 15])
def test_a_seeded_build_answers_the_printed_choice_at_every_level(target_cl: int) -> None:
    """Quick Build / Local AI: every printed level resolves as ONE printed choice.

    Owner rule: "At CL4, CL8, CL12, CL16, and CL19, choose one of the
    following" -- a choice, not a queue and not a budget, so the regression is
    that every printed level is answered exactly once, by whichever branch the
    seeded build chose.  The seeded picker is the automatic picker and leans to
    the Insight branch (character_creation/creative_controller/seeded_picker.py),
    so this seed records one Insight per printed level, and a later test shows
    the same walk answering a level with the normal increase instead.
    """
    _request_, _envelope_, state = _walk(target_cl)
    resolved = _resolution_by_milestone(state)
    printed = [_milestone_id(cl) for cl in SELECTION_LEVELS if cl <= target_cl]
    assert sorted(resolved) == sorted(printed), (target_cl, sorted(resolved))
    # No dual milestone took both branches (the validator's "exactly one" rule).
    assert len(state.insight_occurrences) + len(state.bounded.get("ability_score_changes_by_milestone_id") or {}) == len(printed)
    assert sorted(int(mid.rsplit(".cl", 1)[1]) for mid in resolved) == sorted(
        level for level in SELECTION_LEVELS if level <= target_cl
    )
    assert all(resolved[_milestone_id(cl)] == "cultivation_insight" for cl in SELECTION_LEVELS if cl <= target_cl), resolved
    assert PRINTED_INSIGHTS_BY_CL[target_cl] == len(state.insight_occurrences)
    # No nonrepeatable Insight is taken twice (tests/test_dcc_linear_s4.py's rule).
    assert len({row["insight_id"] for row in state.insight_occurrences}) == len(state.insight_occurrences)
    # The printed +1 ability increase is recorded for every Insight.
    for row in state.insight_occurrences:
        ability = (row.get("parameters") or {}).get("ability")
        assert ability in {"STR", "DEX", "CON", "INT", "WIS", "CHA"}, row
    assert state.bounded.get("ability_score_changes_by_milestone_id") in ({}, None)


def test_a_level_offers_both_printed_resolutions_as_one_choice() -> None:
    """The printed choice is asked as one menu, with both branches on it.

    The printed feature reads "choose one of the following" and lists two
    resolutions.  Offering only the Insight branch (the state of the walk
    reviewed on 2026-10-04) silently replaced every +2 increase with an
    unrelated Insight and +1, lowering the character's intended primary
    ability; this menu is where the owner or the model picks.
    """
    target_cl = 5
    request, envelope = _request(target_cl), _envelope(target_cl)
    step, _state_ = _step_for(request, envelope, _starting_state(target_cl), f"asi_or_insight:{_milestone_id(4)}")
    assert step.action == ACTION_MENU and step.step_kind == "asi_or_insight"
    assert step.menu.title == "Ability Score Improvement or Cultivation Insight"
    assert [list(option.choice_ids) for option in step.menu.options] == [
        ["ability_score_increase"], ["cultivation_insight"],
    ]
    # Plain reading for a player who knows only basic D&D: what it does, and
    # that the numbers printed by the Path are the cap.
    cues = " ".join(option.cue for option in step.menu.options)
    assert "raise one ability score by 2, or two different ability scores by 1 each" in cues
    assert "maximum your Realm allows" in cues
    assert "one Cultivation Insight you meet every prerequisite for" in cues
    assert "one of that Insight's listed ability scores by 1" in cues
    # Two legal options, so the walk asks rather than deciding by itself.
    assert len([option for option in step.menu.options if not option.is_continuation]) == 2


def test_the_seeded_picker_states_its_own_preference_at_a_level_milestone() -> None:
    """The automatic preference lives in the automatic picker, not in the walk.

    The pre-merge review asked for exactly this split: the walk must ask the
    printed choice and never decide it, while the seeded Quick Build picker may
    state a preference.  An Insight also raises an ability score by 1, so the
    picker leans to it -- but a seed may still answer the normal increase, which
    is what keeps seeded builds varied (see the seed sweep in the lane report).
    """
    request, envelope = _request(5), _envelope(5)
    branch, _state_ = _step_for(request, envelope, _starting_state(5), f"asi_or_insight:{_milestone_id(4)}")
    chosen = {
        seed: next(option for option in branch.menu.options if option.option_id == seeded_picker.choose_option(seed, branch.menu)).choice_ids[0]
        for seed in ("OCF4-INSIGHT", "QB-7F3A91", "QB-AAA111", "QB-BBB222", "QB-CCC333", "QB-DDD444", "QB-EEE555", "QB-FFF666")
    }
    assert chosen["OCF4-INSIGHT"] == "cultivation_insight", chosen
    assert set(chosen.values()) == {"cultivation_insight", "ability_score_increase"}, chosen
    assert sum(1 for value in chosen.values() if value == "cultivation_insight") > len(chosen) // 2, chosen


def test_an_owner_locked_level_milestone_reads_as_printed_words_in_the_prompt() -> None:
    """A pre-answered level names its printed resolution, not a branch id.

    The owner may answer a level ahead of the walk, so the locked branch has to
    reach the operator in words a player understands.  Before this the line read
    "Committed choice: Committed choice" for both lock shapes.
    """
    from character_creation.creative_controller.linear_prompt import build_stable_prefix

    target_cl = 5
    milestone_id = _milestone_id(4)
    request = _request(target_cl)
    label = "Ability Score Improvement or Cultivation Insight"
    for lock, expected in (
        (f"asi_or_insight:{milestone_id}", f"{label}: a Cultivation Insight"),
        ("asi_or_insight", f"{label}: the normal Ability Score Improvement"),
    ):
        value: object = "cultivation_insight"
        if lock == "asi_or_insight":
            value = {"advancement_milestone_branch_by_milestone_id": {milestone_id: "ability_score_increase"}}
        envelope = _envelope(target_cl)
        envelope["owner_locks"]["by_slot"][lock] = value
        locked_line = next(
            line for line in build_stable_prefix(request, envelope).splitlines()
            if line.startswith("Owner-locked choices")
        )
        assert expected in locked_line, (lock, locked_line)
        for branch in ("ability_score_increase", "cultivation_insight"):
            assert branch not in locked_line, (lock, locked_line)


def test_the_owner_can_choose_the_normal_increase_while_a_legal_insight_exists() -> None:
    """The printed normal increase stays choosable at a level that has an Insight.

    This is the regression the pre-merge review raised: with a legal Insight at
    the level, the walk used to offer no way to take the +2 increase at all.
    """
    target_cl = 5
    milestone_id = _milestone_id(4)
    request, envelope = _request(target_cl), _envelope(target_cl)
    branch, state = _step_for(request, envelope, _starting_state(target_cl), f"asi_or_insight:{milestone_id}")
    state = commit_option(branch.menu, _pick_branch(branch.menu, "ability_score_increase"), state)
    # The branch commit records the printed resolution and nothing else.
    assert state.bounded["advancement_milestone_branch_by_milestone_id"] == {milestone_id: "ability_score_increase"}
    assert list(state.insight_occurrences) == []
    # The chosen branch's own menu now asks its detail question.
    detail, state = _step_for(request, envelope, state, f"asi_milestone:{milestone_id}")
    assert detail.action == ACTION_MENU and detail.step_kind == "asi_milestone"
    chosen = next(option for option in detail.menu.options if option.option_id == _pick_top_ability_increase(detail.menu))
    deltas = {token.split(":")[1]: int(token.split(":")[2]) for token in chosen.choice_ids}
    state = commit_option(detail.menu, chosen.option_id, state)
    # The printed increase: one score by 2, or two different scores by 1 each,
    # and no score past the cap its Realm allows.
    assert sum(deltas.values()) == 2 and all(delta in {1, 2} for delta in deltas.values())
    assert deltas == {"INT": 2} or sorted(deltas.values()) == [1, 1]
    assert state.bounded["ability_score_changes_by_milestone_id"] == {milestone_id: {"deltas": deltas}}
    # The Insight branch is closed for this level: no Insight was taken and
    # none may be added now, and the level is not asked again.
    assert list(state.insight_occurrences) == []
    assert build_step_menu(request, envelope, state, step_id=f"insight_occurrence:{milestone_id}") is None
    assert build_step_menu(request, envelope, state, step_id=f"asi_or_insight:{milestone_id}") is None
    assert build_step_menu(request, envelope, state, step_id=f"asi_milestone:{milestone_id}") is None
    assert _levels_answered(state, target_cl)


def test_a_mixed_build_takes_an_insight_at_some_levels_and_the_increase_at_others() -> None:
    """One character may answer different levels differently.

    Owner rule: the choice is made "at CL4, CL8, CL12, CL16, and CL19", so a
    build that takes Insights at some of them and the normal increase at others
    is legal, and both branches must survive into the validator-facing
    response.
    """
    target_cl = 15
    plan = {4: "cultivation_insight", 8: "ability_score_increase", 12: "cultivation_insight"}
    request = _request(target_cl)
    envelope = _envelope(target_cl)

    def chooser(menu):
        if menu.step_kind == "asi_or_insight":
            cl = int(menu.step_id.rsplit(".cl", 1)[1])
            return _pick_branch(menu, plan[cl])
        if menu.step_kind == "asi_milestone":
            return _pick_top_ability_increase(menu)
        return seeded_picker.choose_option("OCF4-MIXED", menu)

    state = _walk_until(
        request, envelope, _starting_state(target_cl),
        lambda committed: _levels_answered(committed, target_cl),
        chooser=chooser,
    )
    resolved = _resolution_by_milestone(state)
    assert resolved == {_milestone_id(cl): branch for cl, branch in plan.items()}, resolved
    increase = state.bounded["ability_score_changes_by_milestone_id"]
    assert list(increase) == [_milestone_id(8)], increase
    deltas = increase[_milestone_id(8)]["deltas"]
    assert sum(deltas.values()) == 2, deltas
    occurrences = {row["milestone_id"]: row for row in state.insight_occurrences}
    assert set(occurrences) == {_milestone_id(4), _milestone_id(12)}
    # No nonrepeatable Insight is taken twice, and each carries its printed +1.
    assert len({row["insight_id"] for row in occurrences.values()}) == 2
    assert all((row.get("parameters") or {}).get("ability") in {"STR", "DEX", "CON", "INT", "WIS", "CHA"} for row in occurrences.values())

    request = dict(request, delegated_choice_envelope=envelope)
    response = json.loads(build_response(request, state))
    assert {(row["insight_id"], row["milestone_id"]) for row in response["acquisition_intent"]["insight_occurrences"]} == {
        (row["insight_id"], row["milestone_id"]) for row in occurrences.values()
    }
    assert response["bounded_choices"]["ability_score_changes_by_milestone_id"] == increase


def test_an_increase_is_never_offered_before_every_insight_is_resolved() -> None:
    """Every Insight's printed +1 lands before any increase is asked.

    An Insight raises one ability score by 1, and no score may pass the cap its
    Realm allows, so a +2 increase must not be offered (and committed) while a
    later level's Insight could still spend a point of the same headroom.
    """
    target_cl = 15
    request = _request(target_cl)
    envelope = _envelope(target_cl)

    def chooser(menu):
        if menu.step_kind == "asi_or_insight":
            cl = int(menu.step_id.rsplit(".cl", 1)[1])
            return _pick_branch(menu, "ability_score_increase" if cl == 4 else "cultivation_insight")
        return seeded_picker.choose_option("OCF4-ORDER", menu)

    state = _starting_state(target_cl)
    offered: list[str] = []
    for _ in range(40):
        step = next_step(request, envelope, state)
        if step.action == ACTION_COMPLETE or _levels_answered(state, target_cl):
            break
        offered.append(step.step_id)
        if step.action == ACTION_AUTOCOMMITTED:
            state = step.committed
            continue
        if step.step_kind == "identity":
            state = commit_identity(step.menu, seeded_picker.identity("OCF4-ORDER", request, envelope), step.committed)
            continue
        state = commit_option(step.menu, chooser(step.menu), step.committed)
    assert offered.index(f"asi_milestone:{_milestone_id(4)}") > offered.index(f"insight_occurrence:{_milestone_id(12)}"), offered


@pytest.mark.parametrize("branch", ["ability_score_increase", "cultivation_insight"])
def test_a_level_with_two_paths_is_answered_once_and_the_answer_survives(branch: str) -> None:
    """Two selected Paths, one printed level: one branch question, one answer.

    Pre-merge review OCF4r1 finding 1, with two Paths selected.  Both Paths
    carry the printed *Ability Score Improvement or Cultivation Insight*
    feature at the same CL, so the walk holds two frozen milestone copies for
    that level.  The owner ruling is that the level is ONE character choice
    (owner, 2026-09-13: "the ability-score-improvement-or-Insight milestone at
    a CL is one character choice"), so exactly one copy may be asked and the
    answer given must stand: the other Path's copy must never come back as a
    second question whose other branch silently replaces the answer already
    given.

    Both directions are asserted.  Answering the normal increase and then
    finding the other Path's potential Cultivation Insight able to overwrite it
    was the reported bug, so the increase direction pins that the other copy's
    Insight menu is closed; the Insight direction pins the mirror, that the
    other copy's increase cannot displace the Insight.
    """
    target_cl = 5
    request = _request(target_cl)
    envelope = _two_path_envelope(target_cl)
    copies = _both_copies(4)
    # Before anything is answered, either copy may hold the level: shadowing is
    # a consequence of an answer, not of the second Path being selected.
    assert build_step_menu(request, envelope, _two_path_starting_state(target_cl), step_id=f"asi_or_insight:{copies[0]}") is not None
    assert build_step_menu(request, envelope, _two_path_starting_state(target_cl), step_id=f"asi_or_insight:{copies[1]}") is not None

    state, offered = _walk_levels(
        request, envelope, _two_path_starting_state(target_cl),
        _branch_then_detail_chooser({4: branch}),
    )
    branch_steps = [step_id for step_id in offered if step_id.startswith("asi_or_insight:")]
    assert len(branch_steps) == 1, branch_steps
    answered = branch_steps[0].split(":", 1)[1]
    other = next(milestone_id for milestone_id in copies if milestone_id != answered)
    # One branch question for the level, and the recorded answer is the one the
    # walk asked for, on the copy it asked it of.
    assert state.bounded["advancement_milestone_branch_by_milestone_id"] == {answered: branch}
    # The other Path's copy of the same level is closed: no second branch
    # question, and neither of its branch detail menus is offered, so its
    # potential Cultivation Insight (or its increase) cannot replace the answer.
    assert build_step_menu(request, envelope, state, step_id=f"asi_or_insight:{other}") is None
    assert build_step_menu(request, envelope, state, step_id=f"insight_occurrence:{other}") is None
    assert build_step_menu(request, envelope, state, step_id=f"asi_milestone:{other}") is None
    assert other not in (state.bounded.get("ability_score_changes_by_milestone_id") or {})
    assert all(row.get("milestone_id") != other for row in state.insight_occurrences)
    # The printed rule: exactly one resolution for the level, on the copy that
    # was asked, and its printed effect is what the walk committed.
    assert _resolutions_by_cl(state) == {4: branch}
    if branch == "ability_score_increase":
        deltas = state.bounded["ability_score_changes_by_milestone_id"][answered]["deltas"]
        assert sum(deltas.values()) == 2 and all(delta in {1, 2} for delta in deltas.values()), deltas
        assert not state.insight_occurrences
        # The answer survives into the validator-facing response.
        response = json.loads(build_response(dict(request, delegated_choice_envelope=envelope), state))
        assert response["bounded_choices"]["ability_score_changes_by_milestone_id"] == {answered: {"deltas": deltas}}
        assert response["acquisition_intent"]["insight_occurrences"] == []
    else:
        occurrence, = [row for row in state.insight_occurrences if row["milestone_id"] == answered]
        assert (occurrence.get("parameters") or {}).get("ability") in {"STR", "DEX", "CON", "INT", "WIS", "CHA"}, occurrence
        assert state.bounded.get("ability_score_changes_by_milestone_id") in ({}, None)


def test_a_two_path_walk_asks_each_printed_level_exactly_once() -> None:
    """Every printed level of a two-Path character is one question, one answer.

    The same duplicate-milestone rule at every printed level and in one walk:
    no level may be asked twice because a second selected Path holds a copy of
    the same printed milestone there, and a mixed build (an increase at one
    level, an Insight at another) still resolves each level exactly once.
    """
    target_cl = 15
    plan = {4: "ability_score_increase", 8: "cultivation_insight", 12: "ability_score_increase"}
    request = _request(target_cl)
    envelope = _two_path_envelope(target_cl)
    state, offered = _walk_levels(
        request, envelope, _two_path_starting_state(target_cl),
        _branch_then_detail_chooser(plan),
    )
    asked = [step_id.split(":", 1)[1] for step_id in offered if step_id.startswith("asi_or_insight:")]
    assert sorted(int(milestone_id.rsplit(".cl", 1)[1]) for milestone_id in asked) == sorted(plan), asked
    assert len(set(asked)) == len(asked), asked
    assert _resolutions_by_cl(state) == plan, _resolutions_by_cl(state)
    # One committed resolution per level, never both branches on one level.
    assert len(state.insight_occurrences) + len(state.bounded.get("ability_score_changes_by_milestone_id") or {}) == len(plan)
    for cl in plan:
        answered = {answered for answered in list(state.bounded.get("ability_score_changes_by_milestone_id") or {}) + [row["milestone_id"] for row in state.insight_occurrences] if answered.endswith(f".cl{cl}")}
        assert len(answered) == 1, (cl, answered)
    response = json.loads(build_response(dict(request, delegated_choice_envelope=envelope), state))
    assert len(response["bounded_choices"]["ability_score_changes_by_milestone_id"]) == 2
    assert len(response["acquisition_intent"]["insight_occurrences"]) == 1


def test_the_assembled_response_carries_every_insight_occurrence() -> None:
    """The walk's answer must reach ``acquisition_intent.insight_occurrences``."""
    target_cl = 15
    request, envelope, state = _walk(target_cl)
    request = dict(request)
    request["delegated_choice_envelope"] = envelope
    response = json.loads(build_response(request, state))
    occurrences = response["acquisition_intent"]["insight_occurrences"]
    assert len(occurrences) == PRINTED_INSIGHTS_BY_CL[target_cl]
    # The level-milestone branch record is a transient walk fact: it is not a
    # bounded choice and must not leak into the validator-facing document.
    assert "advancement_milestone_branch_by_milestone_id" not in response["bounded_choices"]
    assert {(row["insight_id"], row["milestone_id"]) for row in occurrences} == {
        (row["insight_id"], row["milestone_id"]) for row in state.insight_occurrences
    }


def test_a_level_with_no_legal_insight_still_takes_the_printed_ability_increase() -> None:
    """The printed rule is a choice, not a budget: the normal increase remains.

    When every catalogue Insight for the level needs a Talent the character does
    not have, the Insight menu is empty and the milestone resolves as the
    printed normal ability-score increase instead of dead-ending the walk.
    """
    target_cl = 5
    request = _request(target_cl)
    envelope = _envelope(target_cl, insight_ids=("insight.alchemical-constitution",))
    # Alchemical Constitution needs a Path the character does not walk.
    envelope["choices_by_slot"]["insight_priorities"]["insight.alchemical-constitution"]["prerequisites"] = [
        {"kind": "path", "operator": "requires", "target_id": "tianxia.path.body_refining"}
    ]
    envelope["owner_locks"]["by_slot"]["insight_priorities"] = ["insight.alchemical-constitution"]
    state = _walk_until(
        request, envelope, _starting_state(target_cl),
        lambda committed: bool(committed.bounded.get("ability_score_changes_by_milestone_id")),
    )
    assert list(state.insight_occurrences) == []
    changes = state.bounded.get("ability_score_changes_by_milestone_id") or {}
    assert list(changes) == [f"{FEATURE_ID}.cl4"], changes


def test_the_owner_can_choose_the_insight_a_level_takes() -> None:
    """Manual builder route: an owner lock records that exact Insight.

    ``insight_priorities`` is the owner's ranked list of Insights; naming the
    level's choice is what turns it into a recorded acquisition.
    """
    target_cl = 5
    milestone_id = f"{FEATURE_ID}.cl4"
    request = _request(target_cl)
    envelope = _envelope(target_cl)
    envelope["owner_locks"]["by_slot"]["insight_priorities"] = sorted(envelope["choices_by_slot"]["insight_priorities"])
    envelope["owner_locks"]["by_slot"][f"insight_occurrence:{milestone_id}"] = {
        "insight_id": "insight.butcher-s-mercy", "milestone_id": milestone_id,
    }
    state = _walk_until(
        request, envelope, _starting_state(target_cl),
        lambda committed: len(committed.insight_occurrences) == 1
        and bool((committed.insight_occurrences[0].get("parameters") or {}).get("ability")),
    )
    occurrences = {row["milestone_id"]: row for row in state.insight_occurrences}
    assert list(occurrences) == [milestone_id], occurrences
    assert occurrences[milestone_id]["insight_id"] == "insight.butcher-s-mercy"
    assert (occurrences[milestone_id].get("parameters") or {}).get("ability") in {"STR", "DEX"}
    assert state.bounded.get("ability_score_changes_by_milestone_id") in ({}, None)


def test_the_chosen_branch_survives_a_table_commit_and_reload(fresh_db) -> None:
    """The branch record is a walk fact the table must keep.

    Which printed resolution a level takes is a transient walk fact (like
    ``point_buy_preset``): it is what closes the branch the character did not
    take, so it has to come back from the walk snapshot's commit and reload
    with strings and integers only -- no floats, no objects -- and the reload
    must still be walking the same branch.
    """
    from app.core import canonical_json
    from character_creation.creative_controller import (
        DETERMINISTIC_CREATIVE_CONTROLLER,
        STEP_COMMITTED,
        WALK_STARTED,
        LinearWalkPersistence,
        build_route_binding,
        replay_committed_state,
    )

    target_cl = 5
    milestone_id = _milestone_id(4)
    request = dict(_request(target_cl), project_id="ocf4f1-project",
                   controller_route_binding=build_route_binding(DETERMINISTIC_CREATIVE_CONTROLLER))
    envelope = _envelope(target_cl)
    branch, state = _step_for(request, envelope, _starting_state(target_cl), f"asi_or_insight:{milestone_id}")
    state = commit_option(branch.menu, _pick_branch(branch.menu, "ability_score_increase"), state)
    assert state.bounded["advancement_milestone_branch_by_milestone_id"] == {milestone_id: "ability_score_increase"}

    _insert_project_and_run(fresh_db, request, "ocf4f1.run.branch")
    persistence = LinearWalkPersistence(fresh_db)
    bound = persistence.projection("ocf4f1.run.branch")
    head = persistence.append_event(
        "ocf4f1.run.branch",
        event_type=WALK_STARTED,
        subject_sha256=request["request_sha256"],
        state_sha256_before=bound["state_sha256"],
        state_sha256_after=state.committed_sha256,
        payload={"steps_estimate": 1, "ceilings": {"max_steps": 200}},
        expected_event_head_sha256=bound["event_head_sha256"],
        expected_ordinal=bound["event_count"] + 1,
    )["event_sha256"]
    persistence.append_event(
        "ocf4f1.run.branch",
        event_type=STEP_COMMITTED,
        subject_sha256=branch.menu.menu_sha256,
        state_sha256_before=state.committed_sha256,
        state_sha256_after=state.committed_sha256,
        payload={"step_id": branch.step_id, "choice_ids": ["ability_score_increase"]},
        expected_event_head_sha256=head,
        expected_ordinal=bound["event_count"] + 2,
    )
    saved = persistence.save_snapshot("ocf4f1.run.branch", 1, state, head)

    # The table keeps it: the stored JSON is the typed state, re-read and
    # re-verified against its own digest.
    loaded = persistence.load_snapshot("ocf4f1.run.branch")
    assert loaded["committed"].to_dict() == state.to_dict() == saved["committed"].to_dict()
    assert loaded["committed"].bounded["advancement_milestone_branch_by_milestone_id"] == {milestone_id: "ability_score_increase"}
    assert canonical_json(loaded["committed"].to_dict()) == loaded["committed_json"]

    # The reloaded walk is still on the increase branch: the Insight menu is
    # closed and the increase's own menu is the one on offer.
    reloaded = loaded["committed"]
    assert build_step_menu(request, envelope, reloaded, step_id=f"insight_occurrence:{milestone_id}") is None
    assert build_step_menu(request, envelope, reloaded, step_id=f"asi_or_insight:{milestone_id}") is None
    assert build_step_menu(request, envelope, reloaded, step_id=f"asi_milestone:{milestone_id}") is not None

    # The recorded walk event alone rebuilds the same branch.  (This walk
    # starts from an owner-locked, already-committed surface, so the full
    # from-empty controller replay that ``verified_replay`` performs is not this
    # test's subject; the branch record's own event is.)
    rebuilt = replay_committed_state(persistence.events("ocf4f1.run.branch"), request=request, envelope=envelope)
    assert rebuilt.bounded.get("advancement_milestone_branch_by_milestone_id") == {milestone_id: "ability_score_increase"}


def _insert_project_and_run(db, request: dict, run_id: str) -> None:
    """A real project + character run + controller route binding for the walk tables."""
    from app.core import canonical_json
    from character_creation.creative_controller import (
        DETERMINISTIC_CREATIVE_CONTROLLER,
        ControllerRoutePersistence,
        build_route_binding,
    )

    now = "2026-10-04T00:00:00Z"
    with db.transaction() as conn:
        conn.execute(
            """INSERT INTO projects(
               project_id,working_name,status,revision,created_at,updated_at,
               target_factory_version,target_candidate_schema_version,target_gm_screen_version,
               catalog_build_hash,quality_target,project_json,
               compatibility_projection_status,compile_status,consumer_verification_status)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("ocf4f1-project", "OCF4f1", "draft", 0, now, now, "x", "x", "x", None, "x",
             canonical_json({"project_id": "ocf4f1-project", "revision": 0}), "x", "x", "x"),
        )
        conn.execute(
            """INSERT INTO character_creation_runs(
               run_id,project_id,starting_revision,execution_mode,idempotency_key,
               request_json,status,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (run_id, "ocf4f1-project", 0, "STANDARD_API", f"ocf4f1-key-{run_id}",
             canonical_json(request), "PREPARING_REQUEST", now, now),
        )
        ControllerRoutePersistence(db).bind_new_run(
            conn,
            run_id=run_id,
            project_id="ocf4f1-project",
            request_sha256=request["request_sha256"],
            binding=build_route_binding(DETERMINISTIC_CREATIVE_CONTROLLER),
            created_at=now,
        )


def test_the_insights_tab_is_projected_from_the_ledger_occurrences() -> None:
    """The portable package's Insights tab was empty for every character.

    ``Insight_Execution_Coverage.json`` is written from
    ``command5_profile._feature_coverage_projection``, which returned an empty
    list for insights no matter what the character took, so a character who
    really had an Insight still showed no Insight coverage.
    """
    from factory_authoring.command5_profile import CharacterGMCommand5Profile

    ledger = {
        "features": [
            {"feature_id": "tianxia.path.qi_cultivation.feature.qi_sensing", "category": "path_feature",
             "source_packet_ids": ["packet.stage2.001.aa"]},
        ],
        "cultivation_insight_occurrences": [
            {"insight_id": "insight.alchemical-constitution", "name": "Alchemical Constitution",
             "gained_at_cl": 8, "source_packet_ids": ["packet.stage2.057.c5"]},
            {"insight_id": "insight.butcher-s-mercy", "name": "Butcher's Mercy",
             "gained_at_cl": 12, "source_packet_ids": []},
        ],
    }
    path_rows, subpath_rows, insight_rows, _companion = CharacterGMCommand5Profile._feature_coverage_projection(ledger)
    assert [row["feature_group_id"] for row in insight_rows] == [
        "insight.alchemical-constitution", "insight.butcher-s-mercy",
    ]
    assert [row["acquisition_cl"] for row in insight_rows] == [8, 12]
    assert [row["display_name"] for row in insight_rows] == ["Alchemical Constitution", "Butcher's Mercy"]
    assert all(row["coverage_status"] == "source_backed" for row in insight_rows)
    assert [row["feature_group_id"] for row in path_rows] == ["tianxia.path.qi_cultivation.feature.qi_sensing"]
    assert subpath_rows == []
    # A character with no Insights still projects no rows (no behaviour change).
    assert CharacterGMCommand5Profile._feature_coverage_projection({"features": []})[2] == []


def test_the_projected_insight_coverage_survives_the_sheet_projection() -> None:
    """The sheet reads ``Insight_Execution_Coverage.json``; the rows must read as text.

    ``CharacterSheetService`` drops any key its per-surface allow-list does not
    name, so a coverage row that carried only the coverage bookkeeping keys would
    reach the player as an empty object.  The ledger's own printed name and level
    must come through.
    """
    from character_sheet.service import CharacterSheetService
    from factory_authoring.command5_profile import CharacterGMCommand5Profile

    ledger = {
        "features": [],
        "insights": [
            {"insight_id": "insight.named-blade-listener", "name": "Named Blade Listener",
             "gained_at_cl": 8, "source_packet_ids": ["packet.stage2.059.cc"]},
        ],
    }
    _path, _subpath, insight_rows, _companion = CharacterGMCommand5Profile._feature_coverage_projection(ledger)
    projected = CharacterSheetService._complete_character_project_member(
        "insights",
        "Insight_Execution_Coverage.json",
        {"schema_version": "TianxiaFoundry.InsightExecutionCoverage.v1", "coverage": insight_rows,
         "source": "Character_Master_Ledger.json"},
    )
    assert [row["display_name"] for row in projected["coverage"]] == ["Named Blade Listener"]
    assert [row["acquisition_cl"] for row in projected["coverage"]] == [8]
    assert projected["coverage"][0]["source_packet_ids"] == ["packet.stage2.059.cc"]


INSIGHT_ID = "insight.crescent-projection-student"
INSIGHT_NAME = "Crescent Projection Student"


def _insight_typed_authority() -> dict:
    """A typed authority that holds exactly one Cultivation Insight.

    The printed benefit of taking an Insight is "its cultivation benefit", so an
    Insight with a typed combat effect must fight like any other owned record.
    The fixture is the smallest such record: one Action that deals 1d8 force
    damage, typed the way ``authority/Tianxia_Typed_Mechanics_Authority_R1.json``
    types one.
    """
    from tests.test_generic_reactions import _mechanic
    from factory_authoring.insight_sources import current_insight_sources, INSIGHT_KIND
    from tests.h1_support import ROOT

    selected = current_insight_sources(ROOT)[INSIGHT_ID]
    row = _mechanic(INSIGHT_ID, INSIGHT_NAME, "action", [
            {"type": "damage", "dice": {"count": 1, "sides": 8}, "damage_types": ["force"]},
        ])
    # The compiler now requires exact reviewed provenance before admitting an Insight.
    row.update(kind=INSIGHT_KIND, typing_status="reviewed_final", insight_selectable=True,
               source=deepcopy(selected["source"]),
               insight_reviewed_text_sha256=selected["source"]["text_sha256"])
    return {"mechanics": {INSIGHT_ID: row}}


def _insight_sheet(*, record_ids: tuple[str, ...] = (), occurrences: tuple[str, ...] = ()) -> dict:
    """The real ``REACTOR_SHEET`` with the character-creation Insights it owns.

    ``record_ids`` is the owner sheet's Insight record list; ``occurrences`` is
    the per-level list, which is the only surface some sheets carry.
    """
    from tests.test_generic_reactions import REACTOR_SHEET

    block: dict = {}
    if record_ids:
        block["cultivation_insight_record_ids"] = list(record_ids)
    if occurrences:
        block["cultivation_insight_occurrences"] = [
            {"insight_id": insight_id, "gained_at_cl": 8} for insight_id in occurrences
        ]
    return {**REACTOR_SHEET, "spheres_and_talents": block}


def _bundle_sha256(bundle: dict) -> str:
    return hashlib.sha256(json.dumps(bundle, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def test_a_typed_insight_compiles_into_the_characters_fight_actions() -> None:
    """``compile_character`` must read the Insights the character owns.

    Printed rule: taking a Cultivation Insight gains "its cultivation benefit", so
    an Insight with a typed combat effect fights like any other owned record.
    The id list is built from every record the sheet says the character owns; the
    Insights were missing from it, so this compiles for real instead of asserting
    on the helper that reads the sheet.
    """
    from combat.factory_compiler import compile_character

    actor = "actor:factory.ocf4f1.insight"
    authority = _insight_typed_authority()
    control = compile_character(_insight_sheet(), actor_id=actor)
    assert INSIGHT_NAME not in {row["display_name"] for row in control["action_catalog"]}

    bundle = compile_character(_insight_sheet(record_ids=(INSIGHT_ID,)), actor_id=actor, typed_authority=authority)
    action = next((row for row in bundle["action_catalog"] if row["display_name"] == INSIGHT_NAME), None)
    assert action is not None, sorted(row["display_name"] for row in bundle["action_catalog"])
    assert action["source_definition_id"].endswith(f".{INSIGHT_ID}")
    assert action["owner_id"] == actor and action["resolution_kind"] == "TYPED"
    assert action["parameters"]["typed"]["effects"] == [
        {"type": "damage", "dice": {"count": 1, "sides": 8}, "damage_types": ["force"]},
    ]
    assert action["parameters"]["typed"]["source"] == INSIGHT_ID
    assert action["parameters"]["expected_damage"] == 4
    # The character really changed: the bundle is not the one it compiles to
    # without the Insight.
    assert _bundle_sha256(bundle) != _bundle_sha256(control)
    # A sheet that carries only the per-level occurrence list compiles the same.
    occurrences_only = compile_character(_insight_sheet(occurrences=(INSIGHT_ID,)), actor_id=actor, typed_authority=authority)
    assert _bundle_sha256(occurrences_only) == _bundle_sha256(bundle)


def test_an_untyped_insight_stays_out_of_the_bundle_and_its_not_automated_lists() -> None:
    """The seam stays inert until an Insight is typed.

    P13 now types reviewed Insights and explains unreviewed ones in a manual
    boundary. An unreviewed Insight still grants no executable action and does
    not enter the skipped-action list as an internal id.
    """
    import combat.factory_compiler as factory_compiler
    from combat.factory_compiler import compile_character

    actor = "actor:factory.ocf4f1.untyped"
    control = compile_character(_insight_sheet(), actor_id=actor)
    bundle = compile_character(
        _insight_sheet(record_ids=("insight.dao-guard-veteran",), occurrences=("insight.dao-guard-veteran",)),
        actor_id=actor,
    )
    # P13 records the manual boundary in diagnostics instead of hiding an owned
    # unreviewed Insight. It still must not acquire an executable action.
    assert bundle["action_catalog"] == control["action_catalog"]
    boundary = next(row for row in bundle["diagnostics"]["insights"] if row["id"] == "insight.dao-guard-veteran")
    assert boundary["status"] == "manual" and boundary["gm_decides"]
    assert {key: value for key, value in bundle["diagnostics"]["skipped"].items() if value} == {}
    typed = json.loads(factory_compiler.TYPED_AUTHORITY.read_text(encoding="utf-8"))["mechanics"]
    assert typed["insight.dao-guard-veteran"]["typing_status"] != "reviewed_final"


def test_a_character_with_no_insights_compiles_exactly_as_before_the_seam() -> None:
    """The control bundle is unchanged, whichever surface carries no Insight.

    A character with no Insight on any surface must compile identically to one
    whose surfaces are simply absent, and neither may gain a fight row.
    """
    from combat.factory_compiler import compile_character

    actor = "actor:factory.ocf4f1.control"
    bare = compile_character(_insight_sheet(), actor_id=actor)
    empty_surfaces = compile_character(
        {**_insight_sheet(), "spheres_and_talents": {
            "cultivation_insight_record_ids": [],
            "cultivation_insight_occurrences": [],
        }},
        actor_id=actor,
    )
    assert _bundle_sha256(empty_surfaces) == _bundle_sha256(bare)
    assert not [row for row in bare["action_catalog"] if str(row["source_definition_id"]).find("insight.") >= 0]
