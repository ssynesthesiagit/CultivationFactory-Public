"""Heaven-Devouring Black Cauldron, slice 1: the CL18 Cauldron field.

The field is compiled from an authenticated native Subpath selection, is a
legal table candidate, and places the engine's own zone (tagged profile), one
ordinary Cultivation Asset anchor, the hostile entry/start save, the point
drain and the once-per-scene ledger -- all read back from a cold reload.
"""
import json

import pytest

from combat.factory_compiler import compile_character
from combat.ext import black_cauldron as C
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate2_runtime_models import Position
from combat.history_feed import concealed_condition_instances
from tests.h1_support import sheet, script
from tests.worker2_support import OWNER, FOE, candidate, fixture, reload, settle, turn

QI = "tianxia.path.qi_cultivation"
SOUND = "tianxia.subpath.qi.sound_cultivator"
FIELD_NAME = "Heaven-Devouring Cauldron"


def fixed_dice(monkeypatch, values):
    """Targeted intents use the first die; turn transitions use the rest (public copy)."""
    current = Gate4ControllerEngine.execute_intent
    original = getattr(current, "_pt_original", current)
    def execute(engine, intent, *args, **kwargs):
        script(engine, values if intent.target_ids else values[1:])
        return original(engine, intent, *args, **kwargs)
    execute._pt_original = original
    monkeypatch.setattr(Gate4ControllerEngine, "execute_intent", execute)


@pytest.fixture(autouse=True)
def isolated_transports(monkeypatch):
    """Deterministic embeddings, and a table whose dice fail the field's save."""
    from combat import embedding_rank, menu_rank
    def transport(url, body, timeout):
        count = len(json.loads(body)["input"])
        return json.dumps({"data": [{"index": i, "embedding": [1] + [0] * (embedding_rank.DIMENSION - 1)}
                                    for i in range(count)]}).encode()
    monkeypatch.setattr(menu_rank, "_CLIENT", embedding_rank.EmbeddingClient(transport=transport))
    fixed_dice(monkeypatch, [19] + [4] * 150)


def acquired_sheet(cl, parent=C.PARENT, name=None):
    """A sheet whose Path row carries the recorded native Subpath selection the compiler consumes."""
    doc = sheet([], cl=cl, name=name or "Cauldron keeper")
    doc["path_and_subpath"] = {"paths": [{"path_id": QI, "attainment": cl, "effective_cl": cl,
        "subpath_or_tradition_id": parent,
        "subpath_or_tradition_acquisition_provenance": {
            "schema": "TianxiaFactory.AcquisitionProvenance.v1", "canonical_content_id": parent,
            "content_type": "Qi Cultivation Subpath", "access_category": "Open",
            "source": "post-creation-authority-selection", "recorded": True}}]}
    return doc


def scenario(tmp_path, cl=18, *, parent=C.PARENT):
    doc = acquired_sheet(cl, parent)
    bundle = compile_character(doc, actor_id=OWNER, reaction_plan={"ask": True})
    foe = acquired_sheet(3, SOUND, name="Hostile musician")
    return fixture(tmp_path, [], owner_bundle=bundle, foe_sheet=foe, cl=cl, ask=True, seed="CAULDRON-FIELD")


def field_action(engine):
    return next((action for action in engine.action_catalog.values()
                 if action.owner_id == OWNER and action.display_name == FIELD_NAME), None)


def field_candidates(engine, action):
    return [row for row in engine.legal_candidates() if row.source_definition_id == action.source_definition_id]


def aim_on_foe(engine, action):
    """The legal 2x2 anchor square nearest the hostile creature."""
    foe = engine.state.actors[FOE]
    return min(field_candidates(engine, action),
               key=lambda row: abs(row.destination.x - foe.position.x) + abs(row.destination.y - foe.position.y)).destination


def cast_field(combat, table, mid, aim, kind="FORCE"):
    return settle(table, mid, candidate(combat, mid, FIELD_NAME, at=(aim.x, aim.y)).candidate_id,
                  choices={"choice:needle.black_cauldron_field_type": [kind]})


def test_cauldron_field_compiles_only_at_its_printed_tier(tmp_path):
    low_combat, low_table, low_mid = scenario(tmp_path / "cl14", 14)
    low = reload(tmp_path / "cl14", low_mid)
    assert C.owned(low, low.state.actors[OWNER]) is None
    assert field_action(low) is None
    combat, table, mid = scenario(tmp_path / "cl18", 18)
    engine = reload(tmp_path / "cl18", mid)
    actor = engine.state.actors[OWNER]
    assert C.owned(engine, actor)["feature_id"] == C.FIELD
    assert C.numbers(engine, actor) == {"cl": 18, "pb": 6, "key_mod": 2, "con_mod": 2, "attack_bonus": 8, "save_dc": 16}
    action = field_action(engine)
    assert action.costs == (("resource:core.qi", 8),)
    assert not any(pool.startswith("resource:uses.") for pool, _ in action.costs)


def test_a_selection_of_another_subpath_compiles_no_cauldron_field(tmp_path):
    combat, table, mid = scenario(tmp_path, 18, parent=SOUND)
    engine = reload(tmp_path, mid)
    assert C.owned(engine, engine.state.actors[OWNER]) is None
    assert field_action(engine) is None


def test_field_candidates_are_free_two_by_two_squares_in_range(tmp_path):
    combat, table, mid = scenario(tmp_path)
    engine = reload(tmp_path, mid)
    action = field_action(engine)
    assert (action.target_kind, action.range_ft) == ("CELL", 90)
    assert action.parameters["cell_placement"] == {"width_cells": 2, "height_cells": 2}
    spec = action.parameters["typed"]["zone_spec"]
    assert spec["profile"] == {"black_cauldron": 1}
    assert (spec["shape"], spec["size_ft"], spec["height_ft"], spec["difficult"]) == ("cylinder", 30, 40, "hostile")
    assert spec["duration"] == {"kind": "minutes", "amount": 1, "concentration": True}
    assert [row["on"] for row in spec["triggers"]] == [["enter", "start"]]
    owner = engine.state.actors[OWNER]
    candidates = field_candidates(engine, action)
    assert candidates
    for row in candidates:
        cells = [Position(x=row.destination.x + dx, y=row.destination.y + dy, z=row.destination.z)
                 for dx in range(2) for dy in range(2)]
        assert all(engine.grid.volume_legal(cell) for cell in cells)
        assert engine._effect_distance_to_cell(owner, row.destination) <= 90


def test_cast_places_the_tagged_field_its_anchor_and_the_scene_ledger(tmp_path):
    combat, table, mid = scenario(tmp_path)
    before = reload(tmp_path, mid)
    qi, aim = before.state.actors[OWNER].resources[C.QI], aim_on_foe(before, field_action(before))
    cast_field(combat, table, mid, aim)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.resources[C.QI] == qi - 8
    [field] = C.fields(engine, owner)
    profile = field.trigger_profile["profile"]
    assert (profile["black_cauldron"], profile["kind"]) == (1, "FORCE")
    assert (field.trigger_profile["height_ft"], field.trigger_profile["difficult"]) == (40, "hostile")
    assert field.center == Position(x=aim.x, y=aim.y, z=0)
    assert field.trigger_profile["triggers"][0]["effects"] == [{"type": "black_cauldron_pulse", "kind": "FORCE"}]
    assert owner.concentration is not None and owner.concentration.zone_id == field.zone_id
    anchor = engine.state.objects[profile["anchor"]]
    numbers = C.numbers(engine, owner)
    assert (anchor.ac, anchor.maximum_hp, anchor.current_hp) == (numbers["save_dc"], 5 * numbers["cl"], 5 * numbers["cl"])
    assert (anchor.ac, anchor.maximum_hp) == (16, 90)
    assert anchor.owner_id == OWNER and anchor.position == field.center
    assert (anchor.component["width_cells"], anchor.component["length_cells"]) == (2, 2)
    ledger = C.condition(owner, C.USED)
    assert (ledger.data["field_used"], ledger.data["ends_with_scene"], ledger.data["hidden"]) == (1, 1, True)
    assert C.used(owner) is True
    assert C.admission(engine, owner, None, field_action(engine)) is False
    assert not field_candidates(engine, field_action(engine))


def test_internal_scene_ledger_stays_out_of_player_surfaces(tmp_path):
    combat, table, mid = scenario(tmp_path)
    engine = reload(tmp_path, mid)
    cast_field(combat, table, mid, aim_on_foe(engine, field_action(engine)))
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    instance = C.condition(owner, C.USED).instance_id
    assert instance in concealed_condition_instances(engine.state.model_dump(mode="json"))
    from combat.condition_names import NAMES
    from combat.condition_text import READING
    names = {C.USED, C.USED.removeprefix("condition:typed.")}
    assert not names & set(NAMES)
    assert not names & set(READING)


def test_field_start_save_drains_a_point_and_blocks_regain_until_its_next_turn(tmp_path):
    combat, table, mid = scenario(tmp_path)
    engine = reload(tmp_path, mid)
    cast_field(combat, table, mid, aim_on_foe(engine, field_action(engine)), kind="NECROTIC")
    engine = reload(tmp_path, mid)
    foe = engine.state.actors[FOE]
    hp, qi = foe.current_hp, foe.resources[C.QI]
    turn(table, mid, FOE)
    engine = reload(tmp_path, mid)
    foe = engine.state.actors[FOE]
    save = [event for event in engine.events if event.event_type == "SAVE_ROLLED"][-1].payload
    rolled = [event for event in engine.events if event.event_type == "DAMAGE_ROLLED"][-1].payload
    committed = [event for event in engine.events if event.event_type == "DAMAGE_COMMITTED"][-1].payload
    assert (save["reason"].split(":")[0], save["reason"].split(":")[-1], save["dc"], save["success"]) == ("SAVE", "CON", 16, False)
    assert rolled["expression"] == "5d8+0"
    assert committed["damage_type"] == "NECROTIC" and committed["hp_before"] == hp
    assert foe.current_hp == hp - rolled["total"] == committed["remaining_hp"]
    assert foe.resources[C.QI] == qi - 1
    condition = C.condition(foe, "condition:typed.no_cp_regain")
    assert condition is not None
    assert condition.expires_on == f"START_OF_TURN_AT:{FOE}:2"
    assert condition.data["origin_save"] == {"ability": "CON", "dc": 16}
    before = foe.resources[C.QI]
    engine._gain_resource(foe, C.QI, 5, "system:test")
    assert foe.resources[C.QI] == before
    assert [event.payload for event in engine.events if event.event_type == "GM_RIDER"][-1]["automated"] is True


def test_field_passed_save_takes_half_and_costs_no_cultivation_point(tmp_path, monkeypatch):
    fixed_dice(monkeypatch, [20] + [20] * 150)
    combat, table, mid = scenario(tmp_path)
    engine = reload(tmp_path, mid)
    cast_field(combat, table, mid, aim_on_foe(engine, field_action(engine)))
    engine = reload(tmp_path, mid)
    foe = engine.state.actors[FOE]
    hp, qi = foe.current_hp, foe.resources[C.QI]
    turn(table, mid, FOE)
    engine = reload(tmp_path, mid)
    foe = engine.state.actors[FOE]
    save = [event for event in engine.events if event.event_type == "SAVE_ROLLED"][-1].payload
    rolled = [event for event in engine.events if event.event_type == "DAMAGE_ROLLED"][-1].payload
    assert (save["natural_result"], save["total"], save["success"]) == (20, 22, True)
    assert rolled["expression"] == "5d8+0" and rolled["total"] == 40
    assert foe.current_hp == hp - 20
    assert foe.resources[C.QI] == qi
    assert C.condition(foe, "condition:typed.no_cp_regain") is None


def test_a_creature_with_no_cultivation_point_takes_the_extra_two_d8(tmp_path):
    from combat.typed_executor import CP_POOLS, Context, run_effects
    combat, table, mid = scenario(tmp_path)
    engine = reload(tmp_path, mid)
    cast_field(combat, table, mid, aim_on_foe(engine, field_action(engine)))
    engine = reload(tmp_path, mid)
    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    for pool in CP_POOLS:
        if foe.resources.get(pool):
            engine._spend_resource(foe, pool, foe.resources[pool], C.FIELD)
    assert not [pool for pool in CP_POOLS if foe.resources.get(pool)]
    hp, action = foe.current_hp, field_action(engine)
    run_effects(Context(engine, owner, action, engine._active_intent, action.parameters["typed"], [foe], foe, {}),
                [{"type": "black_cauldron_drain", "kind": "FORCE"}])
    rolled = [event for event in engine.events if event.event_type == "DAMAGE_ROLLED"][-1].payload
    committed = [event for event in engine.events if event.event_type == "DAMAGE_COMMITTED"][-1].payload
    assert rolled["expression"] == "2d8+0"
    assert committed["damage_type"] == "FORCE" and foe.current_hp == hp - rolled["total"] == committed["remaining_hp"]
    assert C.condition(foe, "condition:typed.no_cp_regain") is not None


def test_anchor_moves_twenty_feet_once_and_the_field_follows(tmp_path):
    combat, table, mid = scenario(tmp_path)
    engine = reload(tmp_path, mid)
    cast_field(combat, table, mid, aim_on_foe(engine, field_action(engine)))
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    [field] = C.fields(engine, owner)
    anchor_id = field.trigger_profile["profile"]["anchor"]
    start = engine.state.objects[anchor_id].position
    prompts = settle(table, mid, candidate(combat, mid, "Move Cauldron Anchor").candidate_id)
    [prompt] = [row for row in prompts if (row.get("context") or {}).get("reaction_source_id") == "choice:needle.black_cauldron_move_anchor"]
    chosen = prompt["choice"]["options"][0]["id"]
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    [field] = C.fields(engine, owner)
    anchor = engine.state.objects[anchor_id]
    x, y, z = (int(part) for part in chosen.split(","))
    assert (anchor.position.x, anchor.position.y, anchor.position.z) == (x, y, z)
    assert engine.grid.distance_ft(start, anchor.position) <= 20
    assert field.center == anchor.position and anchor.current_hp == anchor.maximum_hp
    assert not [row for row in engine.legal_candidates() if row.display_name == "Move Cauldron Anchor"]


def test_field_end_retires_the_anchor_and_a_later_scene_frees_the_field(tmp_path):
    combat, table, mid = scenario(tmp_path)
    engine = reload(tmp_path, mid)
    cast_field(combat, table, mid, aim_on_foe(engine, field_action(engine)))
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    [field] = C.fields(engine, owner)
    anchor_id = field.trigger_profile["profile"]["anchor"]
    from combat import ext as ext_hooks, zones
    ext_hooks.run_strict("scene_end", engine)
    assert C.used(owner) is False and C.condition(owner, C.USED) is None
    zones.remove(engine, field, "TEST_FIELD_END")
    anchor = engine.state.objects[anchor_id]
    assert anchor.destroyed and anchor.current_hp == 0 and C.fields(engine, owner) == []
    assert [event.source_definition_id for event in engine.events if event.event_type == "CONDITION_REMOVED"][-1] == "system:scene_end"
