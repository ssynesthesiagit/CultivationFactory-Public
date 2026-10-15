"""Controller starting-kit steps: A/B option, closed kit menus, response field."""

from __future__ import annotations

import pytest

from app.core import FoundryError
from character_creation.creative_controller.linear_menus import CommittedState, build_step_menu
from character_creation.creative_controller.linear_walk import commit_option, replay_committed_state
from character_creation.response_materialization import canonical_starting_kit

BRAT = "tianxia.background.military_brat"
QI = "tianxia.path.qi_cultivation"


def _state() -> CommittedState:
    return CommittedState(by_slot={"background_choice": [BRAT], "path_choice": [QI]})


def _pick(state: CommittedState, step_id: str, cue_fragment: str) -> CommittedState:
    menu = build_step_menu({}, {}, state, step_id=step_id)
    assert menu is not None
    option = next(option for option in menu.options if cue_fragment in option.cue)
    return commit_option(menu, option.option_id, state)


def test_kit_steps_offer_a_or_b_then_each_closed_choice() -> None:
    state = _state()
    menu = build_step_menu({}, {}, state, step_id="starting_kit_option")
    assert [option.cue.split(":")[0] for option in menu.options] == ["A", "B"]
    assert "Lacquered Leather" in menu.options[0].cue and menu.options[1].cue == "B: 55 ST to buy your own gear"
    state = _pick(state, "starting_kit_option", "A:")
    state = _pick(state, "starting_kit_choice:background:1", "Gu Duo (Mace)")
    state = _pick(state, "starting_kit_choice:path:1", "2 × Bi Shou (Dagger)")
    kit = state.bounded["starting_kit"]
    assert kit["path_option"] == "option_a" and set(kit["picks"]) == {"background:1", "path:1"}
    assert build_step_menu({}, {}, state, step_id="starting_kit_choice:background:1") is None
    assert canonical_starting_kit(kit) == kit


def test_replay_rebuilds_the_kit_decision() -> None:
    events = [
        {"event_type": "STEP_COMMITTED", "step_id": "starting_kit_option", "choice_ids": ["option_b"]},
        {"event_type": "STEP_COMMITTED", "step_id": "starting_kit_choice:background:1", "choice_ids": ["background:1=3"]},
    ]
    state = replay_committed_state(events, _state())
    assert state.bounded["starting_kit"] == {"path_option": "option_b", "picks": {"background:1": 3}}


def test_kit_steps_are_absent_without_a_published_kit_and_bad_shapes_are_rejected() -> None:
    fixture = CommittedState(by_slot={"background_choice": ["background.wanderer"], "path_choice": ["path.wood"]})
    assert build_step_menu({}, {}, fixture, step_id="starting_kit_option") is None
    with pytest.raises(FoundryError):
        canonical_starting_kit({"path_option": "option_c", "picks": {}})


def test_service_accepts_the_starting_kit_acquisition_field() -> None:
    # The service's strict preferred-response shape check must allow the
    # controller's starting-kit decision (regression: first real walk, 2026-09-23).
    from character_creation.service import OPTIONAL_PREFERRED_ACQUISITION_KEYS

    assert "starting_kit" in OPTIONAL_PREFERRED_ACQUISITION_KEYS


def test_delegated_item_checks_skip_the_constructed_starting_kit() -> None:
    # The kit is a constructed item record, not a pick from the item menu
    # (regression: CG1_DELEGATED_CHOICE_OUT_OF_ENVELOPE, 2026-09-23).
    from character_creation.delegated_choice_authority import _is_constructed_starting_kit_row

    assert _is_constructed_starting_kit_row({"kind": "equipment_acquisition", "record_id": "tianxia.constructed.starting_kit.abc"})
    assert not _is_constructed_starting_kit_row({"kind": "equipment_acquisition", "record_id": "tianxia.item.ch4.001.cultivators_storage_ring"})


def test_owner_preferred_gear_pins_the_kit_steps() -> None:
    # A preferred weapon the kit offers pins Option A and its menu; the
    # model still answers the other open menus.
    request = {"owner_gear_preferences": ["tianxia.mortal.weapon.bi_shou"]}
    state = _state()
    menu = build_step_menu(request, {}, state, step_id="starting_kit_option")
    assert [option.choice_ids for option in menu.options] == [("option_a",)]
    state = commit_option(menu, menu.options[0].option_id, state)
    # The first menu offering the dagger (the Background weapon) is pinned.
    pinned = build_step_menu(request, {}, state, step_id="starting_kit_choice:background:1")
    assert len(pinned.options) == 1 and "Bi Shou" in pinned.options[0].cue
    assert len(build_step_menu(request, {}, state, step_id="starting_kit_choice:path:1").options) > 1


def test_starting_kit_decision_accepts_option_b_purchases_only() -> None:
    kit = {"path_option": "option_b", "picks": {}, "purchases": ["tianxia.mortal.weapon.jian"]}
    assert canonical_starting_kit(kit) == kit
    with pytest.raises(FoundryError):
        canonical_starting_kit({"path_option": "option_a", "picks": {}, "purchases": ["tianxia.mortal.weapon.jian"]})
