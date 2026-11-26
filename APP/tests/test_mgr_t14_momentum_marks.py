"""Momentum acquisition/expiry through compiled sources and native table commits.

No synthetic actions, receipts, resource funding or model calls are used.
"""
import json
import zipfile

import pytest

from combat.ext.warleader import MOMENTUM
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.worker2_support import OWNER, ALLY, FOE, candidate, reload, settle, turn

ROW = "WARLEADER_BASE_MOMENTUM_MARKS"


def make(tmp_path, *, acquisition="explicit", foe_hp=60, owner_pb=2):
    owner = sheet([ROW], cl=1)
    if acquisition == "sphere_only":
        owner["spheres_and_talents"]["learned_talent_record_ids"] = []
        owner["spheres_and_talents"]["automatic_sphere_component_record_ids"] = []
    elif acquisition == "unowned":
        owner = sheet([], cl=1)
    owner["identity"]["proficiency_bonus"] = owner_pb
    foe = sheet([], cl=1)
    foe["ability_scores_and_statistics"]["hit_points"]["maximum"] = foe_hp
    # A weak foe can be defeated with real Unarmed Strike attacks; no damage
    # packet is injected to manufacture the native MATCH_ENDED event.
    foe["ability_scores_and_statistics"]["armor_class"]["base_value"] = 1
    docs = [owner, sheet([], cl=1), foe]
    ids = [OWNER, ALLY, FOE]
    for aid, doc in zip(ids, docs):
        directory = tmp_path / "portable_characters" / aid.removeprefix("actor:factory.")
        directory.mkdir(parents=True)
        with zipfile.ZipFile(directory / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    bundles = [compile_character(doc, actor_id=aid, reaction_plan={"ask": True}) for aid, doc in zip(ids, docs)]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        bundles, ids, {OWNER: "team:a", ALLY: "team:a", FOE: "team:b"},
        {OWNER: {"x": 3, "y": 6}, ALLY: {"x": 4, "y": 6}, FOE: {"x": 4, "y": 7}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"],
        [OWNER, ALLY], [FOE], control_modes={aid: "MANUAL" for aid in ids},
        match_seed="WORKER2", display_name="Momentum Marks", maximum_rounds=15)["match_id"]
    turn(table, mid, OWNER)
    return combat, table, mid


def use(combat, table, mid, name, target=None):
    return settle(table, mid, candidate(combat, mid, name, target=target).candidate_id)


@pytest.mark.parametrize("acquisition", ["explicit", "sphere_only", "unowned"])
@pytest.mark.parametrize("pb", [2, 4])
def test_source_acquisition_empty_pb_pool_and_wrong_owners(tmp_path, acquisition, pb):
    _, table, mid = make(tmp_path, acquisition=acquisition, owner_pb=pb)
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    engine = reload(tmp_path, mid)
    leader = engine.state.actors[OWNER]
    if acquisition == "unowned":
        assert MOMENTUM not in leader.resources
    else:
        assert leader.resources[MOMENTUM] == 0
        assert leader.resource_maximums[MOMENTUM] == pb
    for aid in [ALLY, FOE]:
        assert MOMENTUM not in engine.state.actors[aid].resources


def test_real_standard_gains_persist_between_turns_and_cap_at_pb(tmp_path):
    combat, table, mid = make(tmp_path)
    for expected in [1, 2, 2]:
        turn(table, mid, OWNER)
        use(combat, table, mid, "Set the Standard")
        use(combat, table, mid, "Unarmed Strike", FOE)
        engine = reload(tmp_path, mid)
        assert engine.state.actors[OWNER].resources[MOMENTUM] == expected
        settle(table, mid, table.state(mid)["menu"]["end_turn"])
        assert reload(tmp_path, mid).state.actors[OWNER].resources[MOMENTUM] == expected


def test_real_combat_end_clears_marks_and_survives_cold_replay(tmp_path):
    combat, table, mid = make(tmp_path, foe_hp=1)
    use(combat, table, mid, "Set the Standard")
    # Native attacks may roll a natural 1. Repeat on subsequent turns only if
    # the real foe survived; never override the dice or the saved HP/resource.
    for _ in range(8):
        use(combat, table, mid, "Unarmed Strike", FOE)
        engine = reload(tmp_path, mid)
        if engine.state.terminal_result is not None:
            break
        settle(table, mid, table.state(mid)["menu"]["end_turn"])
        turn(table, mid, OWNER)
        use(combat, table, mid, "Set the Standard")
    assert engine.state.terminal_result is not None
    events = engine.events
    gained = [event for event in events if event.event_type == "RESOURCE_GAINED"
              and event.actor_id == OWNER and event.payload.get("resource_id") == MOMENTUM]
    ended = next(event for event in events if event.event_type == "MATCH_ENDED")
    spent = [event for event in events if event.event_type == "RESOURCE_SPENT"
             and event.source_definition_id == ROW and event.actor_id == OWNER]
    assert gained and spent
    assert gained[0].sequence < ended.sequence < spent[-1].sequence
    assert engine.state.actors[OWNER].resources[MOMENTUM] == 0
