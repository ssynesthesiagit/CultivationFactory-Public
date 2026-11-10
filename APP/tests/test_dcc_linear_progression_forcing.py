"""The walk's Path progression forcing mirrors Stage 2's initial-creation rules.

Stage 2 (NS1R) requires every selected Path to advance, a Path with a selected
Subpath or Tradition to reach that Subpath's minimum attainment, and the
governing Method's allocation rule to hold over the final split (secondary
minimum, equal split, milestone lock). The walk keeps only progression
candidates from which a legal completion still exists.
"""
from __future__ import annotations

from character_creation.creative_controller.linear_menus import (
    CommittedState,
    _completion_feasible,
    _governing_method_id,
    _method_progression_constraints,
    _required_path_attainment,
)

BODY = "tianxia.path.body_refining"
SPIRIT = "tianxia.path.spirit_awakening"
SECONDARY = [{"kind": "secondary_minimum", "primary": BODY, "primary_ratio": 2, "secondary": SPIRIT, "secondary_ratio": 1}]


def _envelope() -> dict:
    return {
        "choices_by_slot": {
            "subpath_choice": {
                "tianxia.subpath.body.bone_monarch": {"owning_path_id": BODY},
                "tianxia.tradition.spirit.soul_warden_necromancer": {"owning_path_id": SPIRIT},
            },
        },
        "typed_choice_authority_by_slot": {
            "subpath_choice": {"minimum_attainment_by_choice": {"tianxia.subpath.body.bone_monarch": 3, "tianxia.tradition.spirit.soul_warden_necromancer": 4}},
        },
        "path_method_authority": {
            "method_allocation_by_id": {
                "METHOD-083": {
                    "allocation_rule": "PRIMARY_WITH_SECONDARY_MINIMUM",
                    "granted_path_ids": [BODY, SPIRIT],
                    "minimum_commitments": ["For every 2 AP to Body Refining, at least 1 AP to Spirit Awakening."],
                },
                "METHOD-EQ": {"allocation_rule": "EQUAL_SPLIT", "granted_path_ids": [BODY, SPIRIT], "minimum_commitments": []},
            }
        },
    }


def _request(method_plan: bool = True) -> dict:
    locks = [{"field": "character_sheet.method_access_plan", "value": {"method_id": "METHOD-083"}}] if method_plan else []
    return {"stage1_prompt": {"envelope": {"user_locks": locks}}}


def test_secondary_minimum_feasibility_matches_ns1r_inequality() -> None:
    required = {BODY: 1, SPIRIT: 3}
    # 7:3 at the end violates 2*3 >= 7; 6:3 with one advance left can reach 6:4.
    assert _completion_feasible({BODY: 7, SPIRIT: 3}, 0, required, SECONDARY) is False
    assert _completion_feasible({BODY: 6, SPIRIT: 3}, 1, required, SECONDARY) is True
    # From 5:2 with three left, only splits that end at least 2:1 survive.
    assert _completion_feasible({BODY: 6, SPIRIT: 2}, 2, required, SECONDARY) is True
    assert _completion_feasible({BODY: 7, SPIRIT: 2}, 1, required, SECONDARY) is False


def test_required_attainment_uses_published_subpath_minimum() -> None:
    committed = CommittedState()
    committed = committed.with_slot("path_choice", [BODY, SPIRIT]) if hasattr(committed, "with_slot") else committed
    state = {"by_slot": {"path_choice": [BODY, SPIRIT], "subpath_choice": ["tianxia.tradition.spirit.soul_warden_necromancer"]}}
    required = _required_path_attainment(_request(), _envelope(), state, {BODY, SPIRIT})
    assert required == {BODY: 1, SPIRIT: 4}


def test_governing_method_and_constraints_are_read_from_sealed_authority() -> None:
    state = {"by_slot": {"path_choice": [BODY, SPIRIT]}}
    assert _governing_method_id(_request(), _envelope(), state) == "METHOD-083"
    assert _governing_method_id(_request(method_plan=False), _envelope(), state) is None
    constraints = _method_progression_constraints(_request(), _envelope(), state)
    assert constraints == SECONDARY
    committed = {"by_slot": {"path_choice": [BODY, SPIRIT], "method_choice": ["METHOD-EQ"]}}
    assert _method_progression_constraints(_request(), _envelope(), committed) == [{"kind": "equal_split", "paths": [BODY, SPIRIT]}]
    assert _completion_feasible({BODY: 5, SPIRIT: 4}, 1, {BODY: 1, SPIRIT: 1}, [{"kind": "equal_split", "paths": [BODY, SPIRIT]}]) is True
    assert _completion_feasible({BODY: 6, SPIRIT: 4}, 0, {BODY: 1, SPIRIT: 1}, [{"kind": "equal_split", "paths": [BODY, SPIRIT]}]) is False


# --- Regressions from the 2026-09-05 audit (F1-F4) -------------------------

import pytest

from character_creation.creative_controller.linear_menus import (
    LinearMenuError,
    _foundation_candidates,
    build_path_progression_menu,
)


def _progression_envelope(target_cl: int, minimum: int = 3) -> dict:
    return {
        "frozen_owner_target_cl": target_cl,
        "path_progression_choices": [{"cl": cl, "path_ids": [BODY, SPIRIT]} for cl in range(1, target_cl + 1)],
        "choices_by_slot": {"subpath_choice": {"sub-b": {"owning_path_id": BODY}, "sub-s": {"owning_path_id": SPIRIT}}},
        "typed_choice_authority_by_slot": {"subpath_choice": {"minimum_attainment_by_choice": {"sub-b": minimum, "sub-s": minimum}}},
    }


def _progression_state(advances: dict) -> dict:
    return {"by_slot": {"path_choice": [BODY, SPIRIT], "subpath_choice": ["sub-b", "sub-s"]}, "bounded": {"path_progression_by_cl": advances}}


def _rule_envelope(rule: str) -> dict:
    return {"path_method_authority": {"method_allocation_by_id": {"audit": {
        "allocation_rule": rule, "granted_path_ids": [BODY, SPIRIT], "minimum_commitments": ["At least 1 AP to each"],
    }}}}


@pytest.mark.parametrize("rule", ["MILESTONE_LOCKED", "OWNER_DISTRIBUTED"])
def test_f1_realm_boundary_straddle_is_infeasible_like_ns1r(rule: str) -> None:
    constraints = _method_progression_constraints({}, _rule_envelope(rule), {"by_slot": {"method_choice": ["audit"]}})
    # Body 5 / Spirit 4 straddles the CL 5 Realm boundary: NS1R rejects it.
    assert _completion_feasible({BODY: 5, SPIRIT: 4}, 0, {BODY: 1, SPIRIT: 1}, constraints) is False
    # Body 5 / Spirit 5 does not, and Body 4 / Spirit 4 does not.
    assert _completion_feasible({BODY: 5, SPIRIT: 5}, 0, {BODY: 1, SPIRIT: 1}, constraints) is True
    assert _completion_feasible({BODY: 4, SPIRIT: 4}, 0, {BODY: 1, SPIRIT: 1}, constraints) is True
    # At CL 10 with one advance left from 5:4 the only legal pick is Spirit.
    assert _completion_feasible({BODY: 6, SPIRIT: 4}, 0, {BODY: 1, SPIRIT: 1}, constraints) is False
    assert _completion_feasible({BODY: 5, SPIRIT: 5}, 0, {BODY: 1, SPIRIT: 1}, constraints) is True


def test_f2_future_owner_locked_advances_are_not_free_budget() -> None:
    # Target CL 6, both Subpaths need 3. Body holds CL 1, CL 2 and a locked CL 6.
    # Only CL 3, 4, 5 are unassigned and Spirit needs all three.
    menu = build_path_progression_menu({}, _progression_envelope(6), _progression_state({"1": BODY, "2": BODY, "6": BODY}), cl=3)
    assert menu is None or [option.choice_ids for option in menu.options if not option.is_continuation] == [(SPIRIT,)]


def test_f3_unsatisfiable_progression_raises_instead_of_offering() -> None:
    # Target CL 5, both Subpaths need 3, Body 3 / Spirit 1 before CL 5: no pick works.
    with pytest.raises(LinearMenuError) as raised:
        build_path_progression_menu({}, _progression_envelope(5), _progression_state({"1": BODY, "2": BODY, "3": BODY, "4": SPIRIT}), cl=5)
    assert raised.value.code == "DCC_LINEAR_PROGRESSION_UNSATISFIABLE"
    assert raised.value.details["required_minimum_attainment"] == {BODY: 3, SPIRIT: 3}


def test_f4_foundation_filter_uses_the_governing_method_when_slot_is_deferred() -> None:
    request = {"stage1_prompt": {"envelope": {"user_locks": [
        {"field": "character_sheet.method_planning_mode", "value": "EXACT"},
        {"field": "character_sheet.method_access_plan", "value": {"method_id": "METHOD-A"}},
    ]}}}
    envelope = {"frozen_owner_target_cl": 10, "choices_by_slot": {"foundation_choice": {
        "FOUNDATION-B": {"choice_id": "FOUNDATION-B", "compatible_method_ids": ["METHOD-B"]},
        "FOUNDATION-A": {"choice_id": "FOUNDATION-A", "compatible_method_ids": ["METHOD-A"]},
        "FOUNDATION-ANY": {"choice_id": "FOUNDATION-ANY", "compatible_method_ids": []},
    }}}
    assert _governing_method_id(request, envelope, {}) == "METHOD-A"
    offered = sorted(candidate.choice_ids[0] for candidate in _foundation_candidates(request, envelope, {}) if candidate.choice_ids)
    assert offered == ["FOUNDATION-A", "FOUNDATION-ANY"]



def test_review_sheet_lists_only_parentless_cards_as_spheres() -> None:
    from app.api import _bounded_owner_scratch_sheet

    compiled = {"owner_character_sheet": {
        "identity": {"display_name": "Probe"},
        "selected_record_sections": {
            "spheres": [
                {"record_id": "s1", "display_name": "Death", "one_line_description": "Sphere of Death"},
                {"record_id": "c1", "display_name": "Grave Sense", "parent_sphere_name": "Death", "one_line_description": "Sense graves"},
            ],
            "sphere_components": [
                {"record_id": "c2", "display_name": "Rouse Lesser Dead", "parent_sphere_name": "Death", "one_line_description": "Rouse"},
            ],
        },
        "spheres_and_talents": {"automatic_sphere_components": [
            {"display_name": "Grave Sense", "parent_sphere_name": "Death"},
            {"display_name": "Rouse Lesser Dead", "parent_sphere_name": "Death"},
        ]},
    }}
    sheet = _bounded_owner_scratch_sheet(compiled)
    assert [row["name"] for row in sheet["spheres"]] == ["Death"]
    assert sorted(row["name"] for row in sheet["automatic_components"]) == ["Grave Sense", "Rouse Lesser Dead"]
