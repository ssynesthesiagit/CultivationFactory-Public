"""Service regressions for painted map hazards and movement text (hunt 51 findings 5 and 6)."""
from pathlib import Path

import pytest

from combat import zones
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import LEE
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import sheet


IDS = ["actor:factory.l39-a", "actor:factory.l39-b", "actor:factory.l39-c", "actor:factory.l39-d"]
NAMES = {IDS[0]: "First Grappler", IDS[1]: "Second Fighter", IDS[2]: "Held Fighter", IDS[3]: "Other Fighter"}


def _fight(tmp_path, name, materials=(), high_dex=False, reader=False):
    user = tmp_path / name
    user.mkdir()
    service = CombatService(Path(__file__).resolve().parents[1], user)
    table = TabletopService(service, user)
    bundles = []
    for index, actor_id in enumerate(IDS):
        doc = sheet([], cl=18, dc=30, primary="Stamina", score=30 if index < 2 else 10)
        doc["identity"]["display_name"] = NAMES[actor_id]
        if high_dex and index == 2:
            dex = next(row for row in doc["ability_scores_and_statistics"]["abilities"] if row["ability"] == "DEX")
            dex.update(score=30, modifier=10)
        doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = 1000
        bundles.append(compile_character(doc, actor_id=actor_id, reaction_plan={"ask": True}))
    arena = service.tabletop_maps.save({"display_name": name, "width_squares": 12, "height_squares": 10,
        "walls": [], "materials": list(materials),
        "starts": {"team1": [[3, 3], [3, 5]], "team2": [[4, 3], [9, 8]]}})
    positions = dict(zip(IDS, [{"x": 3, "y": 3}, {"x": 1, "y": 8}, {"x": 4, "y": 3}, {"x": 9, "y": 8}]))
    primary = IDS + ([LEE] if reader else [])
    teams = dict(zip(IDS, ["team:factory", "team:factory", "team:opponents", "team:opponents"]))
    if reader:
        positions[LEE] = {"x": 1, "y": 1}
        teams[LEE] = "team:factory"
    match = service._finish_factory_match(
        bundles, primary, teams,
        positions, service.factory_arenas()["battlefield:map." + arena["map_id"]], IDS[:2], IDS[2:],
        control_modes={actor_id: "MANUAL" for actor_id in primary}, match_seed="L39-" + name,
        display_name=name, maximum_rounds=10)["match_id"]
    return user, service, table, match


def _act(table, match, choose, trace):
    state = table.state(match)
    menu = state["menu"]
    options = [option for group in menu.get("actions", []) for option in group["options"]] + menu.get("moves", [])
    chosen = next((option for option in options if choose(option)), None) if choose else None
    if choose and chosen is None:
        raise AssertionError("requested table action was unavailable")
    candidate_id = chosen["candidate_id"] if chosen else menu["end_turn"]
    answers = []
    for _ in range(40):
        response = table.act(match, candidate_id, menu["decision_id"], menu["state_version"], state["last_sequence"], answers)
        trace.append((chosen, response))
        if response["status"] != "REACTION_REQUIRED":
            break
        prompt = response["reaction"]
        answer = {**prompt["context"], "selection": "DECLINE"}
        if prompt.get("choice") and not prompt["choice"].get("allow_decline"):
            answer.update(selection="USE", option_ids=[prompt["choice"]["options"][0]["id"]])
        answers.append(answer)
    assert response["status"] == "COMMITTED"
    return response


def _on_turn(table, match, actor_id, trace):
    for _ in range(30):
        if table.state(match)["menu"]["actor_id"] == actor_id:
            return
        _act(table, match, None, trace)
    raise AssertionError("desired fighter did not receive a turn")


def _finish(user, service, table, match):
    live = service._load_session(match)
    fresh = CombatService(Path(__file__).resolve().parents[1], user)._load_session(match)
    history = table.events(match, 0)
    assert fresh.engine.state.model_dump(mode="json") == live.engine.state.model_dump(mode="json")
    assert fresh.verify()["status"] == fresh.mechanical.replay()["status"] == "PASS"
    return live.engine, history


def test_painted_fire_triggers_on_real_shove_and_survives_reload(tmp_path):
    user, service, table, match = _fight(tmp_path, "painted-fire", [
        {"material": "terrain:fire terrain", "cells": [[5, 3]]}])
    trace = []
    _on_turn(table, match, IDS[0], trace)
    _act(table, match, lambda option: "Shove: Push 5 ft" in str(option.get("label")) and option.get("target_ids") == [IDS[2]], trace)
    engine, _ = _finish(user, service, table, match)
    assert engine.state.actors[IDS[2]].position.model_dump(mode="json") == {"x": 5, "y": 3}
    painted = next(zone for zone in table.state(match)["presentation"]["zones"]
                   if zone["trigger_profile"].get("map"))
    assert painted["trigger_profile"]["triggers"][0]["on"] == ["enter", "start"]
    assert any(event.event_type == "SAVE_ROLLED" and event.actor_id == IDS[2]
               and event.payload.get("dc") == 13 for event in engine.events)


def test_painted_fire_usage_survives_each_table_commit_and_resets_next_turn(tmp_path):
    user, service, table, match = _fight(tmp_path, "painted-fire-once", [
        {"material": "terrain:fire terrain", "cells": [[5, 3]]}])
    trace = []
    _on_turn(table, match, IDS[2], trace)

    def move_to(destination):
        _act(table, match, lambda option: option.get("destination") == destination, trace)

    move_to({"x": 5, "y": 3})  # enter: save and commit
    saves_after_entry = sum(event.event_type == "SAVE_ROLLED" and event.actor_id == IDS[2]
                            for event in service._load_session(match).engine.events)
    assert saves_after_entry == 1
    _finish(user, service, table, match)  # force an independent reload after the commit
    move_to({"x": 4, "y": 3})
    move_to({"x": 5, "y": 3})  # same slot/turn: the persisted guard suppresses another save
    loaded = service._load_session(match).engine
    assert sum(event.event_type == "SAVE_ROLLED" and event.actor_id == IDS[2] for event in loaded.events) == 1

    _act(table, match, None, trace)
    _on_turn(table, match, IDS[2], trace)
    loaded_session = service._load_session(match)
    loaded = loaded_session.engine
    assert sum(event.event_type == "SAVE_ROLLED" and event.actor_id == IDS[2] for event in loaded.events) == 2
    assert loaded_session.verify()["status"] == loaded_session.mechanical.replay()["status"] == "PASS"


def test_painted_fire_triggers_at_turn_start_and_resolves_both_save_outcomes(tmp_path):
    outcomes = []
    for name, high_dex in (("painted-fire-start-fail", False), ("painted-fire-start-success", True)):
        user, service, table, match = _fight(tmp_path, name, [
            {"material": "terrain:fire terrain", "cells": [[4, 3]]}], high_dex=high_dex)
        trace = []
        _on_turn(table, match, IDS[2], trace)
        engine, _ = _finish(user, service, table, match)
        event = next(event for event in engine.events if event.event_type == "SAVE_ROLLED" and event.actor_id == IDS[2])
        outcomes.append((event.payload["success"], event.payload, engine.state.actors[IDS[2]]))
    assert {success for success, _, _ in outcomes} == {False, True}
    failed = next((payload, actor) for success, payload, actor in outcomes if not success)
    succeeded = next((payload, actor) for success, payload, actor in outcomes if success)
    assert failed[1].current_hp == 998  # map Fire Terrain deals its listed 2-point Proficiency Bonus damage
    assert any(condition.condition_id.endswith(".burning") for condition in failed[1].conditions.values())
    assert succeeded[1].current_hp == 1000
    assert any(condition.condition_id.endswith(".kindled") for condition in succeeded[1].conditions.values())


def test_map_usage_is_not_a_countercurrent_pattern_after_commit_and_reload(tmp_path):
    user, service, table, match = _fight(tmp_path, "terrain-pattern-isolation", [
        {"material": "terrain:fire terrain", "cells": [[5, 3]]}], reader=True)
    trace = []

    def patterns():
        return [option for group in table.state(match)["menu"].get("actions", [])
                for option in group["options"] if "Countercurrent" in option["label"]]

    _on_turn(table, match, LEE, trace)
    assert patterns() == []  # no enemy-created pattern exists
    _on_turn(table, match, IDS[2], trace)
    _act(table, match, lambda option: option.get("destination") == {"x": 5, "y": 3}, trace)
    engine, _ = _finish(user, service, table, match)
    [usage] = list(engine.state.zones.values())
    assert usage.trigger_profile["kind"] == "MAP_TERRAIN_USAGE"
    assert not usage.active
    assert usage.per_turn_triggered
    assert all(isinstance(key, str) and isinstance(value, int)
               for key, value in usage.per_turn_triggered.items())
    [ground] = zones.typed_zones(engine)
    assert ground.active and ground.trigger_profile["kind"] == "TYPED"
    from combat.ext import placed
    assert placed.of(engine) == []
    _on_turn(table, match, LEE, trace)
    assert patterns() == []
    _finish(user, service, table, match)


@pytest.mark.parametrize("terrain", ["ash terrain", "obsidian terrain", "shattered glass terrain"])
def test_existing_movement_hazards_do_not_persist_new_zone_snapshots(tmp_path, terrain):
    user, service, table, match = _fight(tmp_path, "existing-" + terrain.replace(" ", "-"), [
        # Ash and Obsidian require more than 10 feet actually traveled through
        # their terrain. A single endpoint square supplies only 5 feet.
        {"material": "terrain:" + terrain, "cells": [[x, y] for x in range(5, 8) for y in range(10)]}])
    trace = []
    _on_turn(table, match, IDS[2], trace)
    _act(table, match, lambda option: option.get("destination") == {"x": 7, "y": 3}, trace)
    engine, _ = _finish(user, service, table, match)
    [trigger] = [event for event in engine.events if event.event_type == "PASSIVE_TRIGGERED"
                 and event.payload.get("zone_id") == "zone:map:1"]
    assert trigger.payload == {"zone_id": "zone:map:1", "trigger": "moving through the terrain",
                               "moment": "move_through"}
    assert engine.state.zones == {}
