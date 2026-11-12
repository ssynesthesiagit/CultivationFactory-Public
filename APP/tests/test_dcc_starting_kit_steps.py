"""Controller starting-kit steps and the resulting equipment display."""

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


@pytest.mark.parametrize("printed_ammunition", [False, True])
def test_generated_ranged_character_gets_usable_weapon_and_printed_ammunition(monkeypatch, printed_ammunition) -> None:
    import json
    from character_creation.constructed_arts.records import validate_starting_kit_record
    from character_creation.service import CharacterCreationExecutionService
    from combat.factory_compiler import compile_character
    from factory_authoring import starting_kits

    bow = "tianxia.mortal.weapon.duan_gong"
    arrows = "tianxia.mortal.gear.arrows_20"
    if printed_ammunition:
        original = starting_kits.background_kit

        def background(background_id):
            kit = original(background_id)
            # Synthetic printed choice, not an edit to the shipped kit authority.
            kit["entries"].append({"kind": "choice", "printed": "arrows or bolts", "options": [
                {"kind": "item", "item_id": "tianxia.mortal.gear.bolts_20", "quantity": 1},
                {"kind": "item", "item_id": arrows, "quantity": 1},
            ]})
            return kit

        monkeypatch.setattr(starting_kits, "background_kit", background)
    pairs = [
        {"sphere_id": "tianxia.sphere.sniper", "talent_id": "TAL_SNIPER_DEADLY_SHOT"},
        {"sphere_id": "tianxia.sphere.barrage", "talent_id": "TAL_BARRAGE_HAMMERING_SHOTS"},
    ]
    state = CommittedState(by_slot=_state().by_slot, pairs=pairs)
    request = {"owner_gear_preferences": [bow]}
    menu = build_step_menu(request, {}, state, step_id="starting_kit_option")
    state = commit_option(menu, menu.options[0].option_id, state)
    raw_menus = starting_kits.choice_menus(BRAT, QI)
    for raw in raw_menus:
        step = "starting_kit_choice:" + raw["choice_id"]
        menu = build_step_menu(request, {}, state, step_id=step)
        if raw["choice_id"] == "path:1":
            # Qi's first option is a staff; only the thrown daggers fit.
            assert [option.choice_ids for option in menu.options] == [("path:1=1",)]
        if raw["choice_id"] == "background:1":
            assert len(menu.options) == 1 and "Shortbow" in menu.options[0].cue
        state = commit_option(menu, menu.options[0].option_id, state)
    intent = {"selected_by_slot": dict(state.by_slot), "acquisition_intent": {
        "starting_kit": state.bounded["starting_kit"], "sphere_free_talent_pairs": pairs,
    }}
    kit, record = CharacterCreationExecutionService._starting_kit_construction(
        intent, "generated-ranged-kit", 1, owner_gear_preferences=[bow],
    )
    from factory_authoring.weapon_requirements import item_fits_requirement, owned_weapon_requirements

    needs = owned_weapon_requirements([row["talent_id"] for row in pairs], [row["sphere_id"] for row in pairs])
    items = kit["resolved"]["items"]
    assert bow in {row["item_id"] for row in items}
    assert all(any(item_fits_requirement(starting_kits.item_definition(row["item_id"]), need)
                   for row in items) for need in needs)
    assert (arrows in {row["item_id"] for row in items}) is printed_ammunition
    assert any("ammunition" in warning for warning in kit["resolved"].get("warnings", [])) is not printed_ammunition
    assert validate_starting_kit_record(json.loads(json.dumps(record))) == kit
    # The resulting generated sheet uses the real combat compiler too.
    sheet = {
        "identity": {"cultivation_level": 1, "proficiency_bonus": 2, "path": "Qi Cultivation", "key_ability": "CON"},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": ability, "score": 14, "modifier": 2}
                          for ability in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
            "primary_resource": {"name": "Qi", "maximum": 10},
            "hit_points": {"maximum": 20}, "speed": {"walking_ft": 30},
        },
        "spheres_and_talents": {"sphere_record_ids": [row["sphere_id"] for row in pairs],
                               "learned_talent_record_ids": [row["talent_id"] for row in pairs]},
        "equipment": [{"starting_kit": {"items": items}}],
    }
    actions = compile_character(sheet, actor_id="actor:generated.ranged")["action_catalog"]
    assert any(row["display_name"].startswith("Snipe Shot: Duan Gong") for row in actions)
    assert any(row["display_name"].startswith("Barrage: Duan Gong") for row in actions)
    # A stale/manual response cannot omit a weapon decision and acquire item 0.
    intent["acquisition_intent"]["starting_kit"]["picks"].pop("path:1")
    with pytest.raises(FoundryError):
        CharacterCreationExecutionService._starting_kit_construction(intent, "missing-weapon", 1)


def test_items_renderer_omits_absent_notes_instead_of_native_dom_null_text() -> None:
    import subprocess
    from pathlib import Path

    subprocess.run(["node", str(Path(__file__).with_name("starting_kit_items.mjs"))], check=True)


def test_creation_weapon_query_does_not_load_combat_runtime() -> None:
    import subprocess
    import sys

    subprocess.run([sys.executable, "-c",
        "import sys; from factory_authoring.weapon_requirements import owned_weapon_requirements; "
        "assert owned_weapon_requirements(spheres=['tianxia.sphere.barrage']); "
        "assert not any(name == 'combat' or name.startswith('combat.') for name in sys.modules)"],
        check=True)


def test_starting_kit_decision_accepts_option_b_purchases_only() -> None:
    kit = {"path_option": "option_b", "picks": {}, "purchases": ["tianxia.mortal.weapon.jian"]}
    assert canonical_starting_kit(kit) == kit
    with pytest.raises(FoundryError):
        canonical_starting_kit({"path_option": "option_a", "picks": {}, "purchases": ["tianxia.mortal.weapon.jian"]})
