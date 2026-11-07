"""Forest Remembers chooses represented movement spaces at a committed table."""
from copy import deepcopy

import pytest

from combat.canonical import canonical_sha256
from combat.ext import verdant_chassis as verdant
from tests.r1i_service_support import OWNER, FOE, SECOND, candidate, fixture, force_ai_candidate
from tests.test_c16_root_feed_choices import probes
from tests.test_r1i_round3 import reload, resolve
from tests.test_riders_c16 import SOWN, SEED, VG, growth

FOREST = VG + "FOREST_REMEMBERS_THE_PATH"
CHOICE = "choice:needle.forest_remembers"


def actions(bundles):
    probes(bundles)
    for bundle in bundles:
        if bundle["actor_id"] not in (OWNER, FOE):
            continue
        base = next(a for a in bundle["action_catalog"] if a["display_name"] == "Seed-Thorn Strike")
        for name, effects in [("Path teleport", [{"type": "teleport", "applies_to": "self", "distance_ft": 90}]),
                              ("Self mark", [{"type": "mark", "mark": "Growth Mark", "applies_to": "self"}])]:
            action = deepcopy(base)
            action.update(source_definition_id="test:c16." + bundle["actor_id"] + "." + name.lower().replace(" ", "_"), display_name=name,
                          target_kind="SELF", range_ft=90 if name == "Path teleport" else None, economy="NONE")
            action["parameters"]["typed"].update(effects=effects, range_ft=action["range_ft"])
            bundle["action_catalog"].append(action)
            bundle["actor_template"]["action_ids"].append(action["source_definition_id"])
        for action in bundle["action_catalog"]:
            if action["display_name"] == "Mark probe":
                action["range_ft"] = 120
                action["parameters"]["typed"]["range_ft"] = 120
                push = deepcopy(action)
                push.update(source_definition_id="test:c16.push_probe", display_name="Push probe")
                push["parameters"]["typed"]["effects"] = [
                    {"type": "forced_movement", "direction": "away", "distance_ft": 5, "applies_to": "target"}]
        if bundle["actor_id"] == OWNER:
            bundle["action_catalog"].append(push)
            bundle["actor_template"]["action_ids"].append(push["source_definition_id"])
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)


def move_candidate(table, mid, destination, teleport=False):
    menu = table.state(mid)["menu"]
    options = (next(g["options"] for g in menu["actions"] if g["label"] == "Path teleport")
               if teleport else menu["moves"])
    return next(o["candidate_id"] for o in options if o.get("destination") == destination)


@pytest.mark.parametrize("mode", ["manual", "ai_mover", "ai_owner"])
@pytest.mark.parametrize("pick", ["cell:4,6", "cell:5,7", None])
def test_forest_space_selection_table(tmp_path, mode, pick):
    combat, table, mid, send, commit = fixture(
        tmp_path, [SOWN, SEED, FOREST], foe_talents=[SEED], bundle_transform=actions,
        positions={OWNER: {"x": 1, "y": 6}, FOE: {"x": 4, "y": 6}, SECOND: {"x": 7, "y": 6}})
    commit(candidate(table, mid, "Mark probe", FOE))
    commit(candidate(table, mid, "Mark probe", FOE))
    commit(table.state(mid)["menu"]["end_turn"])
    assert table.state(mid)["menu"]["actor_id"] == FOE
    cid = move_candidate(table, mid, {"x": 5, "y": 7})
    if mode == "ai_mover":
        force_ai_candidate(combat, mid, FOE, cid)
    elif mode == "ai_owner":
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    before, prompts = resolve(combat, mid, send, cid, {CHOICE: pick}, auto=mode == "ai_mover")
    choices = [p for p in prompts if p["context"]["reaction_source_id"] == CHOICE]
    assert bool(choices) == (mode != "ai_owner")
    if choices:
        prompt = choices[0]
        assert {"cell:4,6", "cell:5,7"} <= {o["id"] for o in prompt["choice"]["options"]}
        assert prompt["context"]["reactor_id"] == OWNER
        assert "Forest Remembers the Path" in prompt["moment"] and "Foe" in prompt["moment"]
        assert "movement" in prompt["moment"].lower() and "1 Growth Mark" in prompt["moment"]
        assert all("1 minute" in o["label"] for o in prompt["choice"]["options"])
    engine = reload(tmp_path, mid)
    expected = "cell:5,7" if mode == "ai_owner" else pick
    assert engine.state.actors[FOE].position.model_dump(mode="json") == {"x": 5, "y": 7}
    assert growth(engine, FOE, OWNER) == 2 - int(expected is not None)
    made = verdant.claims(engine, engine.state.actors[OWNER])
    assert len(made) == int(expected is not None)
    if made:
        assert expected == f"cell:{made[0].position.x},{made[0].position.y}"
        assert made[0].component["on"] == ""
        assert made[0].component["until_round"] == engine.state.round_number + 10
        assert any(e.event_type == "OBJECT_UPDATED" and e.source_definition_id == FOREST for e in engine.events)
    assert before["actors"][FOE]["position"] == {"x": 4, "y": 6}


@pytest.mark.parametrize("pick", ["cell:11,0", "cell:18,0"])
def test_teleport_departure_in_range_arrival_outside_table(tmp_path, pick):
    combat, table, mid, send, commit = fixture(
        tmp_path, [SOWN, SEED, FOREST], foe_talents=[SEED], bundle_transform=actions,
        positions={OWNER: {"x": 0, "y": 0}, FOE: {"x": 11, "y": 0}, SECOND: {"x": 0, "y": 6}})
    commit(candidate(table, mid, "Mark probe", FOE))
    commit(table.state(mid)["menu"]["end_turn"])
    cid = move_candidate(table, mid, {"x": 18, "y": 0}, teleport=True)
    _, prompts = resolve(combat, mid, send, cid, {
        "choice:needle.teleport_destination": "cell:18,0", CHOICE: pick})
    prompt = next(p for p in prompts if p["context"]["reaction_source_id"] == CHOICE)
    assert {o["id"] for o in prompt["choice"]["options"]} == {"cell:11,0", "cell:18,0"}
    assert "Path teleport" in prompt["moment"]
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].position.model_dump(mode="json") == {"x": 18, "y": 0}
    assert growth(engine, FOE, OWNER) == 0
    obj, = verdant.claims(engine, engine.state.actors[OWNER])
    assert pick == f"cell:{obj.position.x},{obj.position.y}"


def test_self_marked_owner_can_choose_departure_table(tmp_path):
    combat, table, mid, send, commit = fixture(tmp_path, [SOWN, SEED, FOREST], foe_talents=[SEED], bundle_transform=actions,
        positions={OWNER: {"x": 1, "y": 6}, FOE: {"x": 4, "y": 6}, SECOND: {"x": 7, "y": 6}})
    commit(candidate(table, mid, "Self mark"))
    cid = move_candidate(table, mid, {"x": 1, "y": 7})
    _, prompts = resolve(combat, mid, send, cid, {CHOICE: "cell:1,6"})
    assert any(p["context"]["reaction_source_id"] == CHOICE for p in prompts)
    engine = reload(tmp_path, mid)
    assert growth(engine, OWNER, OWNER) == 0
    obj, = verdant.claims(engine, engine.state.actors[OWNER])
    assert obj.position.model_dump(mode="json") == {"x": 1, "y": 6}
    assert obj.component["on"] == ""  # leaving your square creates a ground claim, not body growth


@pytest.mark.parametrize("case", ["intermediate", "without_row", "unmarked", "outside", "ai_one_mark", "claim_limit"])
def test_forest_intermediate_and_inert_controls_table(tmp_path, case):
    talents = [SOWN, SEED] + ([] if case == "without_row" else [FOREST])
    start = {"x": 15 if case == "outside" else 4, "y": 0}
    end = {"x": 17 if case == "outside" else 7, "y": 0}
    combat, table, mid, send, commit = fixture(tmp_path, talents, foe_talents=[SEED], bundle_transform=actions,
        owner_pb=1 if case == "claim_limit" else 4,
        positions={OWNER: {"x": 0, "y": 0}, FOE: start, SECOND: {"x": 0, "y": 6}})
    old_claim = None
    if case == "claim_limit":
        from tests.test_c16_root_feed_choices import sow
        sow(table, mid, commit, 2, 0)
        engine = reload(tmp_path, mid)
        old_claim, = verdant.claims(engine, engine.state.actors[OWNER])
    if case != "unmarked":
        commit(candidate(table, mid, "Mark probe", FOE))
    commit(table.state(mid)["menu"]["end_turn"])
    if case == "ai_one_mark":
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    cid = move_candidate(table, mid, end)
    _, prompts = resolve(combat, mid, send, cid, {
        CHOICE: "cell:5,0", "choice:needle.wither_claim": old_claim.object_id if old_claim else None})
    applies = case in ("intermediate", "claim_limit")
    choices = [p for p in prompts if p["context"]["reaction_source_id"] == CHOICE]
    assert bool(choices) == applies
    if choices:
        assert {o["id"] for o in choices[0]["choice"]["options"]} == {f"cell:{x},0" for x in range(4, 8)}
    engine = reload(tmp_path, mid)
    assert growth(engine, FOE, OWNER) == int(case != "unmarked") - int(applies)
    made = verdant.claims(engine, engine.state.actors[OWNER])
    assert len(made) == int(applies)
    if made:
        assert made[0].position.model_dump(mode="json") == {"x": 5, "y": 0}
    if old_claim:
        assert engine.state.objects[old_claim.object_id].destroyed
        assert any(p["context"]["reaction_source_id"] == "choice:needle.wither_claim" for p in prompts)


@pytest.mark.parametrize("case", ["missing_path", "unchanged", "interrupted", "teleport", "blocked", "large"])
def test_forest_uses_only_changed_supported_committed_footprints(tmp_path, monkeypatch, case):
    """Supplementary payload contract checks; table/reload coverage is above."""
    from combat.footprints import ActorFootprintDefinition

    _, table, mid, _, commit = fixture(tmp_path, [SOWN, SEED, FOREST], foe_talents=[SEED], bundle_transform=actions,
        positions={OWNER: {"x": 0, "y": 0}, FOE: {"x": 4, "y": 0}, SECOND: {"x": 0, "y": 6}})
    commit(candidate(table, mid, "Mark probe", FOE))
    engine = reload(tmp_path, mid)
    payload = {"path": [{"x": 4, "y": 0}, {"x": 5, "y": 0}], "destination": {"x": 5, "y": 0}}
    expected = {"cell:4,0", "cell:5,0"}
    if case == "missing_path":
        payload.pop("path")
        expected = set()
    elif case == "unchanged":
        payload["path"] = [{"x": 4, "y": 0}, {"x": 4, "y": 0}]
        expected = set()
    elif case == "interrupted":
        payload.update(interrupted=True, planned_path=[{"x": x, "y": 0} for x in range(4, 8)])
    elif case == "teleport":
        payload.update(teleport=True, path=[{"x": x, "y": 0} for x in range(4, 8)])
        expected = {"cell:4,0", "cell:7,0"}
    elif case == "blocked":
        engine.grid.blocked.add((5, 0))
        expected = {"cell:4,0"}
    elif case == "large":
        engine.actor_footprints[FOE] = ActorFootprintDefinition.rectangle(
            2, 2, footprint_id="test:c16.large", source_definition_id="test:c16.large")
        expected = {"cell:4,0", "cell:4,1", "cell:6,0", "cell:6,1"}
    calls = []

    def decline(*args, **kwargs):
        calls.append(set(args[5]))
        return []

    monkeypatch.setattr(verdant, "ask", decline)
    verdant._forest_remembers(engine, engine.state.actors[OWNER], engine.state.actors[FOE], payload)
    assert calls == ([expected] if expected else [])
    assert growth(engine, FOE, OWNER) == 1
    assert not verdant.claims(engine, engine.state.actors[OWNER])


def test_forced_movement_prompt_names_action_actor_and_affected_creature_table(tmp_path):
    combat, table, mid, send, commit = fixture(tmp_path, [SOWN, SEED, FOREST], foe_talents=[SEED], bundle_transform=actions,
        positions={OWNER: {"x": 0, "y": 0}, FOE: {"x": 4, "y": 0}, SECOND: {"x": 0, "y": 6}})
    commit(candidate(table, mid, "Mark probe", FOE))
    _, prompts = resolve(combat, mid, send, candidate(table, mid, "Push probe", FOE), {CHOICE: "cell:4,0"})
    prompt = next(p for p in prompts if p["context"]["reaction_source_id"] == CHOICE)
    assert "Owner's Push probe" in prompt["moment"] and "Foe moved" in prompt["moment"]
    assert prompt["action"] == "Push probe"
    assert prompt["affected"] == "Foe"
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].position.model_dump(mode="json") == {"x": 5, "y": 0}
    assert growth(engine, FOE, OWNER) == 0
    obj, = verdant.claims(engine, engine.state.actors[OWNER])
    assert obj.position.model_dump(mode="json") == {"x": 4, "y": 0}
