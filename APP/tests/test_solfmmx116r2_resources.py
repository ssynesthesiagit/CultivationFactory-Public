"""Persisted MANUAL/Ask-me tables with real typed attacks and Foundation payments.

The fixture extends a compiled attack with deterministic damage packets and a
nested attack, to exercise the same composition as the reported combat bug.
No event, reaction callback, die result or engine function is fabricated.
"""
from copy import deepcopy

import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_lock2_persistence import act
from tests.test_pressure import FOUNDATION

ATTACKER = "actor:factory.11111111"
DEFENDER = "actor:factory.22222222"
PULSE = "resource:foundation.golden_sea_pulse"
GUARD = "foundation.ancient_desolate_sacred_body_v0_2C.golden_sea_guard"


def fight(tmp_path, *, nested=False, owns=True, crane=False, native=False):
    attacker = compile_character(sheet(["tianxia.path.body_refining.feature.iron_fist"]), actor_id=ATTACKER)
    defender_doc = sheet([])
    defender_doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = 1000
    if owns:
        defender_doc["foundation"] = deepcopy(FOUNDATION)
        if crane:
            defender_doc["foundation"] = {
                "foundation_id": "white_crane_cloud_step_v0_2B", "stage": "Awakened",
                "resource": {"name": "Crane Breath", "resource_id": "foundation.resource.white_crane_cloud_step_v0_2B",
                             "maximum": 1, "current": 0, "initial_current": 0}}
    defender = compile_character(defender_doc, actor_id=DEFENDER, reaction_plan={"ask": True})
    action = next(a for a in attacker["action_catalog"] if a["display_name"] == "Iron Fist attack")
    action["display_name"] = "Two-packet strike"
    typed = action["parameters"]["typed"]
    typed["numbers"]["attack_bonus"] = 1000
    if crane:
        typed["numbers"]["attack_bonus"] = -1000
    typed["weapon"]["damage_types"] = ["BLUDGEONING"]
    packet = {"type": "damage", "flat": 10, "damage_types": ["bludgeoning"]}
    hit = [deepcopy(packet)]
    if nested:
        hit.append({"type": "attack", "attack_kind": "unarmed", "count": 1,
                    "on_hit": [deepcopy(packet)]})
    if native:
        hit.append({"type": "test_native_return_step"})
    hit.append(deepcopy(packet))
    typed["effects"] = [{"type": "attack", "attack_kind": "unarmed", "count": 2, "on_hit": hit}]
    source = action["source_definition_id"]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    if native:
        from combat.gate2_runtime_content import AN
        mid = combat.persistence.create_match(
            match_seed="SOLFMMX116r3", typed_bundles=(attacker, defender),
            roster_setup={"primary_actor_ids": [ATTACKER, DEFENDER, AN],
                          "team_by_actor": {ATTACKER: "team:a", DEFENDER: "team:b", AN: "team:a"},
                          "starting_positions": {ATTACKER: {"x": 3, "y": 6},
                                                 DEFENDER: {"x": 4, "y": 6}, AN: {"x": 5, "y": 7}}}).match_id
        for aid in (ATTACKER, DEFENDER, AN):
            combat.set_controller_mode(mid, actor_id=aid, controller_mode="MANUAL")
    else:
        mid = combat._finish_factory_match(
            [attacker, defender], [ATTACKER, DEFENDER],
            {ATTACKER: "team:a", DEFENDER: "team:b"},
            {ATTACKER: {"x": 3, "y": 6}, DEFENDER: {"x": 4, "y": 6}},
            combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [ATTACKER], [DEFENDER],
            control_modes={ATTACKER: "MANUAL", DEFENDER: "MANUAL"}, match_seed="SOLFMMX116r2",
            display_name="Resource scope regression", maximum_rounds=10)["match_id"]
    while table.state(mid)["menu"]["actor_id"] != ATTACKER:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    return combat, table, mid, source


@pytest.mark.parametrize("nested", [False, True])
def test_manual_pulse_packets_nested_return_later_attack_and_reload(tmp_path, nested):
    check_pulse_return(tmp_path, nested=nested)


def test_native_opportunity_return_persisted_table(tmp_path, monkeypatch):
    from combat import ext, movement_paths
    from combat.gate2_runtime_models import Position
    # A fixture-only effect composes a real willing step between A's packets.
    # Production movement finds, asks and resolves the native OA; no engine or
    # reaction functions, journal events or dice are replaced.
    def step(ctx, effect):
        target = ctx.targets[0]
        if target.position == Position(x=4, y=6):
            movement_paths.resolve(ctx.engine, target,
                (target.position, Position(x=4, y=5)), ctx.source,
                kind="granted", feet=5, intent=ctx.intent)
    monkeypatch.setitem(ext.effects(), "test_native_return_step", step)
    check_pulse_return(tmp_path, native=True)


def check_pulse_return(tmp_path, *, nested=False, native=False):
    combat, table, mid, source = fight(tmp_path, nested=nested, native=native)
    initial = combat._load_session(mid).engine.state.model_dump(mode="json")
    initial_events = [e.model_dump(mode="json") for e in combat._load_session(mid).engine.events]
    state = table.state(mid)
    menu = state["menu"]
    cid = next(g["options"][0]["candidate_id"] for g in menu["actions"] if g["source_definition_id"] == source)
    args = (mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"])
    first = table.act(*args, [])
    assert first["status"] == "REACTION_REQUIRED", first
    answers = []
    if native:
        from combat.gate2_runtime_content import AN
        assert first["reaction"]["context"]["reactor_id"] == AN
        assert first["reaction"]["context"]["reaction_source_id"] == "system:combat.opportunity_attack"
        answers.append({**first["reaction"]["context"], "selection": "USE"})
        first = table.act(*args, answers)
        assert first["status"] == "REACTION_REQUIRED", first
    prompt = first["reaction"]
    assert prompt["reaction"] == "Golden Sea Guard"
    assert prompt["context"]["reactor_id"] == DEFENDER
    assert ("An Eui" if native else "Two-packet strike") in prompt["moment"]
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == initial
    assert [e.model_dump(mode="json") for e in combat._load_session(mid).engine.events] == initial_events
    # A new service must reproduce the paused question from disk, not retain an engine's hold.
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    assert table.act(*args, answers)["reaction"] == prompt
    if nested or native:
        # B may use A's Pulse. Declining B must restore A's restriction for A's second packet.
        answers.append({**prompt["context"], "selection": "DECLINE"})
        second = table.act(*args, answers)
        assert second["status"] == "REACTION_REQUIRED", second
        assert second["reaction"]["reaction"] == "Golden Sea Guard"
        assert second["reaction"]["context"] != prompt["context"]
        prompt = second["reaction"]
    answers.append({**prompt["context"], "selection": "USE"})
    done = table.act(*args, answers)
    assert done["status"] == "COMMITTED", done
    committed = combat._load_session(mid)
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    assert fresh.engine.state.model_dump(mode="json") == committed.engine.state.model_dump(mode="json")
    assert [e.model_dump(mode="json") for e in fresh.engine.events] == [e.model_dump(mode="json") for e in committed.engine.events]
    events = fresh.engine.events[len(initial_events):]
    gains = [e for e in events if e.event_type == "RESOURCE_GAINED" and e.payload.get("resource_id") == PULSE and e.payload.get("gained")]
    spends = [e for e in events if e.event_type == "RESOURCE_SPENT" and e.payload.get("resource_id") == PULSE]
    guards = [e for e in events if e.event_type == "REACTION_RESOLVED" and e.source_definition_id == GUARD]
    assert len(gains) == len(spends) == len(guards) == 1
    rolls = [i for i, e in enumerate(events) if e.event_type == "ATTACK_ROLLED"]
    damage = [i for i, e in enumerate(events) if e.event_type == "DAMAGE_COMMITTED"]
    assert len(rolls) == (3 if native else 4 if nested else 2)
    if native:
        assert events[rolls[1]].source_definition_id == "system:combat.opportunity_attack"
        assert events[rolls[1]].actor_id == AN
    # No spending in A, including its packet after returning from B. The accepted defense belongs to C.
    assert events.index(spends[0]) > rolls[2 if nested or native else 1]
    assert len([i for i in damage if i < rolls[2 if nested or native else 1]]) == (3 if nested or native else 2)
    assert fresh.engine.state.actors[DEFENDER].resources[PULSE] == 0
    assert not fresh.engine.state.actors[DEFENDER].reaction_available
    assert fresh.mechanical.replay()["status"] == "PASS"


def test_real_crane_miss_generator_runs_inside_established_window(tmp_path):
    from combat import ext, typed_reactions
    breath = "resource:foundation.crane_breath"
    combat, table, mid, source = fight(tmp_path, crane=True)
    assert act(table, mid, "end")["status"] == "COMMITTED"
    state = table.state(mid)
    assert state["menu"]["actor_id"] == DEFENDER
    move = next(m for m in state["menu"]["moves"] if m["destination"] == {"x": 4, "y": 5})
    assert table.act(mid, move["candidate_id"], state["menu"]["decision_id"],
                     state["menu"]["state_version"], state["last_sequence"], [])["status"] == "COMMITTED"
    assert act(table, mid, "end")["status"] == "COMMITTED"
    checks = []

    def observe(engine, event_type, kwargs):
        if event_type == "ATTACK_ROLLED" and kwargs.get("actor_id") == ATTACKER:
            actor = engine.state.actors[DEFENDER]
            if actor.resources.get(breath):
                checks.append(typed_reactions._holds(engine, actor, breath))

    ext.hook("event", priority=1000)(observe)
    try:
        assert act(table, mid, source)["status"] == "COMMITTED"
    finally:
        ext._HOOKS["event"].remove(observe)
        ext._HOOK_PRIORITIES.pop(("event", observe), None)
    assert checks and not checks[0], "the real Crane generator's grant must still be held in its miss window"
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    gains = [e for e in fresh.engine.events if e.event_type == "RESOURCE_GAINED" and e.payload.get("resource_id") == breath]
    assert len(gains) == 1 and gains[0].payload["gained"] == 1
    assert fresh.engine.state.actors[DEFENDER].resources[breath] == 1
    assert typed_reactions._holds(fresh.engine, fresh.engine.state.actors[DEFENDER], breath)
    assert fresh.mechanical.replay()["status"] == "PASS"


def test_non_owner_table_is_inert_and_reloadable(tmp_path):
    combat, table, mid, source = fight(tmp_path, nested=True, owns=False)
    assert act(table, mid, source)["status"] == "COMMITTED"
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = fresh.engine.state.actors[DEFENDER]
    assert PULSE not in actor.resources
    assert actor.reaction_available
    assert not any(e.event_type == "RESOURCE_GAINED" and e.payload.get("resource_id") == PULSE for e in fresh.engine.events)
    assert not any(k.startswith("_prior_event_") for k in fresh.engine.__dict__)
    assert fresh.mechanical.replay()["status"] == "PASS"
