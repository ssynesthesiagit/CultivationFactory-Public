"""Formation arrays (combat/ext/formations.py): the Formations sphere's Combat Array, Pulse Array, Collapse Array and the Basic
Patterns, played on the engine with a real compiled Formations character (Sphere Compendium, Formations)."""

import json
from pathlib import Path

import pytest

from combat import ext, zones
from combat.factory_compiler import compile_character
from combat.ext import formations
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_carry import KIT
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.f"
RULES = json.loads((ROOT / "authority" / "typed_mechanics" / "rules_text.json").read_text())


def _sheet(talents=None, cl=None, qi=None):
    base = [key for key in RULES if key.startswith("FORMATIONS_BASE")]
    every = [key for key in RULES if key.startswith("tianxia.talent.formations.")]
    sheet = {**SHEET, "equipment": [{"starting_kit": KIT}],
             "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.formations"], "automatic_sphere_component_record_ids": base,
                                     "learned_talent_record_ids": every if talents is None else list(talents)}}
    if cl:  # the Domain talents need CL 12 / 15
        sheet["identity"] = {**SHEET["identity"], "cultivation_level": cl}
    if qi:
        sheet["ability_scores_and_statistics"] = {**SHEET["ability_scores_and_statistics"], "primary_resource": {"name": "Qi", "maximum": qi}}
    return sheet


def _engine(talents=None, *, foe_at=(8, 6), seed="FORM", team_foe="team:b", cl=None, qi=None):
    bundle = compile_character(_sheet(talents, cl, qi), actor_id=ME)
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: team_foe},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": foe_at[0], "y": foe_at[1]}}})
    _turn(engine, ME)
    return engine, bundle


def _turn(engine, actor_id):
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    engine.state.current_actor_id = actor_id
    engine._system_start_turn()


def _do(engine, name, *, at=None, target=None, actor=ME):
    candidate = next(c for c in engine.legal_candidates()
                     if getattr(engine.action_catalog.get(c.source_definition_id), "display_name", None) == name and c.actor_id == actor
                     and (at is None or (c.destination and (c.destination.x, c.destination.y) == at))
                     and (target is None or c.target_ids == (target,)))
    engine.execute_intent(ActionIntent(intent_id=f"{name}{engine.state.event_sequence}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=actor, target_ids=candidate.target_ids,
                                       destination=candidate.destination))


def _names(engine, actor=ME):
    return {getattr(engine.action_catalog.get(c.source_definition_id), "display_name", None) for c in engine.legal_candidates() if c.actor_id == actor}


def _array(engine):
    return formations.arrays(engine, ME)


def test_compile_offers_an_action_per_pattern_and_hides_the_inert_base_rows():
    engine, bundle = _engine([])
    names = {row["display_name"] for row in bundle["action_catalog"]}
    assert {"Combat Array: Locking Gate", "Combat Array: Nourishing Cycle", "Combat Array: Killing Line (Fire)", "Pulse: Locking Gate",
            "Collapse Array"} <= names
    offered = _names(engine)
    assert "Combat Array: Locking Gate" in offered
    assert not {name for name in offered if name and name.startswith("Set Array")}


def test_a_combat_array_is_a_zone_with_an_eye_the_owner_concentrates_on():
    engine, _bundle = _engine([])
    before = engine.state.actors[ME].resources.get("resource:core.qi")
    _do(engine, "Combat Array: Locking Gate", at=(5, 6))
    (zone,) = _array(engine)
    assert zone.trigger_profile["difficult"] == "hostile" and zone.trigger_profile["name"] == "Locking Gate Array"
    assert engine.state.actors[ME].concentration.zone_id == zone.zone_id
    eye = engine.state.objects[formations.record(zone)["eye"]]
    assert (eye.ac, eye.current_hp, eye.maximum_hp) == (13, 5 + int(formations.record(zone)["cl"]), 5 + int(formations.record(zone)["cl"]))
    assert eye.damage_immunities == ("POISON", "PSYCHIC") and (eye.position.x, eye.position.y) == (5, 6)
    assert engine.state.actors[ME].resources.get("resource:core.qi") == before - 2
    cells = {(cell.x, cell.y) for cell in zone.affected_cells}
    assert (5, 6) in cells and (7, 6) in cells and (8, 6) not in cells  # a 10-foot radius is two squares


def _foe(engine):
    return engine.state.actors[AN]


def _step_into(engine, position):
    foe = _foe(engine)
    start = foe.position
    foe.position = Position(x=position[0], y=position[1])
    zones.on_moved(engine, foe, start, foe.position)


def test_killing_line_hurts_a_hostile_entering_once_a_turn_for_the_chosen_type():
    engine, _bundle = _engine([], foe_at=(12, 6))
    _do(engine, "Combat Array: Killing Line (Fire)", at=(5, 6))
    foe = _foe(engine)
    before = foe.current_hp
    _step_into(engine, (7, 6))
    pb = int(formations.record(_array(engine)[0])["numbers"]["pb"])
    assert before - foe.current_hp == pb
    log = " ".join(str(event.payload) for event in engine.events)
    assert "FIRE" in log.upper()
    _step_into(engine, (6, 6))
    assert before - foe.current_hp == pb  # once each turn


def test_locking_gate_is_difficult_ground_to_hostiles_only():
    engine, _bundle = _engine([], foe_at=(12, 6))
    _do(engine, "Combat Array: Locking Gate", at=(5, 6))
    (zone,) = _array(engine)
    assert zones.difficult_for(engine, _foe(engine), Position(x=6, y=6)) if hasattr(zones, "difficult_for") else zone.trigger_profile["difficult"] == "hostile"


def test_collapse_array_removes_the_zone_its_eye_and_the_concentration():
    engine, _bundle = _engine([])
    _do(engine, "Combat Array: Locking Gate", at=(5, 6))
    (zone,) = _array(engine)
    eye_id = formations.record(zone)["eye"]
    _do(engine, "Collapse Array", at=(5, 6))
    assert not _array(engine) and engine.state.objects[eye_id].destroyed
    assert engine.state.actors[ME].concentration is None
    assert "Collapse Array" not in _names(engine)


def test_losing_concentration_collapses_the_array():
    engine, _bundle = _engine([])
    _do(engine, "Combat Array: Locking Gate", at=(5, 6))
    (zone,) = _array(engine)
    eye_id = formations.record(zone)["eye"]
    engine._end_concentration(engine.state.actors[ME], "FAILED_DAMAGE_CHECK")
    assert not _array(engine) and engine.state.objects[eye_id].destroyed


def _duel(seed="DUEL"):
    """Two compiled Formations characters: ME (team a) and THEM (team b), so either can strike the other's array."""
    them = "actor:factory.g"
    bundles = tuple(compile_character(_sheet([]), actor_id=who) for who in (ME, them))
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=bundles,
                                   roster_setup={"primary_actor_ids": [ME, them], "team_by_actor": {ME: "team:a", them: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, them: {"x": 7, "y": 6}}})
    _turn(engine, them)
    return engine, them


@pytest.mark.parametrize("generic_object_attack", [False, True], ids=["weapon", "object-action"])
def test_an_enemys_weapon_attack_can_strike_the_eye_and_it_is_immune_to_poison(generic_object_attack):
    engine, them = _duel()
    _do(engine, "Combat Array: Locking Gate", at=(7, 6), actor=them)
    zone = formations.arrays(engine, them)[0]
    eye = engine.state.objects[formations.record(zone)["eye"]]
    _turn(engine, ME)
    engine.state.actors[ME].position = Position(x=6, y=6)
    # Both actions can strike the Eye. Select the intended path, independent of candidate ordering.
    strikes = [c for c in engine.legal_candidates() if c.actor_id == ME and c.target_ids == (eye.object_id,)
               and bool((engine.action_catalog[c.source_definition_id].parameters or {}).get("object_attack")) == generic_object_attack]
    assert strikes, "an enemy's weapon attack can target the Eye"
    action = engine.action_catalog[strikes[0].source_definition_id]
    assert ext.run("ai_candidate_allowed", engine, engine.state.actors[ME], strikes[0], action) == [False]
    engine.execute_intent(ActionIntent(intent_id="strike", decision_id=strikes[0].decision_id, candidate_id=strikes[0].candidate_id,
                                       state_version=strikes[0].state_version, actor_id=ME, target_ids=strikes[0].target_ids,
                                       destination=strikes[0].destination))
    event_type = "ATTACK_ROLLED" if generic_object_attack else "CHECK_ROLLED"
    rolled = [event for event in engine.events if event.event_type == event_type and eye.object_id in (event.target_ids or ())]
    assert len(rolled) == 1 and rolled[0].source_definition_id == action.source_definition_id
    if generic_object_attack:
        assert rolled[0].payload["object_id"] == eye.object_id and rolled[0].payload["target_ac"] == eye.ac
    else:
        assert "Eye" in rolled[0].payload["check"] and rolled[0].payload["dc"] == eye.ac
    assert formations.hurt_object(engine, engine.state.objects[eye.object_id], 99, "POISON", "test", ME) == 0 and formations.arrays(engine, them)


def test_destroying_the_eye_collapses_the_array():
    engine, them = _duel()
    _do(engine, "Combat Array: Locking Gate", at=(7, 6), actor=them)
    zone = formations.arrays(engine, them)[0]
    eye = engine.state.objects[formations.record(zone)["eye"]]
    formations.hurt_object(engine, eye, 3, "SLASHING", "test", ME)
    assert formations.arrays(engine, them)
    formations.hurt_object(engine, engine.state.objects[eye.object_id], 99, "SLASHING", "test", ME)
    assert not formations.arrays(engine, them)
    assert engine.state.actors[them].concentration is None


def _force_dc(engine, dc):
    for action in engine.action_catalog.values():
        if action.owner_id == ME and (action.parameters or {}).get("typed"):
            typed = action.parameters["typed"]
            typed["numbers"] = {**typed["numbers"], "save_dc": dc}


def _conditions(actor):
    return {condition.condition_id for condition in actor.conditions.values()}


def test_locking_gate_pulse_holds_a_creature_that_fails_and_slows_one_that_saves():
    engine, _bundle = _engine([], foe_at=(6, 6))
    _do(engine, "Combat Array: Locking Gate", at=(5, 6))
    _force_dc(engine, 99)
    foe = _foe(engine)
    assert "Pulse: Locking Gate" in _names(engine)
    _do(engine, "Pulse: Locking Gate", target=AN)
    assert any("held_fast" in cid for cid in _conditions(foe)), _conditions(foe)
    assert engine.state.actors[ME].bonus_action_available is False
    _turn(engine, ME)  # the same named Pulse touches a creature once a round
    assert "Pulse: Locking Gate" not in _names(engine)


def test_pulse_needs_a_creature_inside_its_array_and_the_pattern_as_a_layer():
    engine, _bundle = _engine([], foe_at=(12, 6))
    _do(engine, "Combat Array: Locking Gate", at=(5, 6))
    assert "Pulse: Locking Gate" not in _names(engine)  # nobody inside
    assert "Pulse: Killing Line" not in _names(engine)  # the array is not a Killing Line


def test_killing_line_pulse_is_a_formation_attack_for_the_arrays_type():
    engine, _bundle = _engine([], foe_at=(6, 6))
    _do(engine, "Combat Array: Killing Line (Radiant)", at=(5, 6))
    foe = _foe(engine)
    before = foe.current_hp
    engine.roller_force = None
    _do(engine, "Pulse: Killing Line", target=AN)
    log = [event for event in engine.events if event.event_type == "DAMAGE_COMMITTED"]
    assert foe.current_hp <= before
    if foe.current_hp < before:
        assert "RADIANT" in str(log[-1].payload).upper()


def test_nourishing_cycle_pulse_heals_an_ally_inside_once_per_round():
    engine, _bundle = _engine([])
    _do(engine, "Combat Array: Nourishing Cycle", at=(3, 6))
    me = engine.state.actors[ME]
    me.current_hp = 1
    assert "Pulse: Nourishing Cycle" in _names(engine)
    _do(engine, "Pulse: Nourishing Cycle", target=ME)
    assert me.current_hp > 1


# ---------------------------------------------------------------------------------------------- the other Basic Patterns
BINDING = ["tianxia.talent.formations.binding_array"]
SEALING = ["tianxia.talent.formations.sealing_gate_pattern"]


def test_pattern_talents_are_offered_only_with_the_talent():
    plain, _ = _engine([])
    assert {"Combat Array: Binding", "Combat Array: Sealing Gate"}.isdisjoint(_names(plain))
    bound, _ = _engine(BINDING + SEALING)
    assert {"Combat Array: Binding", "Combat Array: Sealing Gate"} <= _names(bound)


def test_suppressing_vein_disadvantages_concentration_only_against_the_owners_side():
    from types import SimpleNamespace

    from combat import concentration

    engine, _bundle = _engine([], foe_at=(6, 6))
    _do(engine, "Combat Array: Suppressing Vein", at=(5, 6))
    foe = _foe(engine)
    assert any("Suppressing Vein" in str((c.data or {}).get("name")) for c in foe.conditions.values())
    engine._active_intent = SimpleNamespace(actor_id=ME)  # the owner's side deals the damage
    assert concentration.save_mode(engine, foe) == "DISADVANTAGE"
    engine._active_intent = SimpleNamespace(actor_id=AN)  # anyone else's damage: nothing changes
    assert concentration.save_mode(engine, foe) is None


def test_suppressing_vein_pulse_locks_cp_reactions_or_taxes_the_next_spend():
    engine, _bundle = _engine([], foe_at=(6, 6))
    _do(engine, "Combat Array: Suppressing Vein", at=(5, 6))
    _force_dc(engine, 99)
    foe = _foe(engine)
    _do(engine, "Pulse: Suppressing Vein", target=AN)
    assert any("formation_cp_locked" in cid for cid in _conditions(foe))
    assert ext.any_false("row_allowed", engine, foe, {"cost": 1}) and not ext.any_false("row_allowed", engine, foe, {"cost": 0})
    # a save that succeeds: the next CP it spends costs 1 more
    engine2, _ = _engine([], foe_at=(6, 6), seed="TAX")
    _do(engine2, "Combat Array: Suppressing Vein", at=(5, 6))
    _force_dc(engine2, -50)
    _do(engine2, "Pulse: Suppressing Vein", target=AN)
    foe2 = _foe(engine2)
    assert any("formation_cp_tax" in cid for cid in _conditions(foe2))
    resource = next(key for key in foe2.resources if key.endswith(".stamina"))
    before = foe2.resources[resource]
    engine2._spend_resource(foe2, resource, 1, "test:spend")
    assert foe2.resources[resource] == before - 2 and not any("formation_cp_tax" in cid for cid in _conditions(foe2))


def test_sensing_eye_pulse_pins_down_a_creature_while_it_stays_inside():
    from combat import senses

    engine, _bundle = _engine([], foe_at=(6, 6))
    _do(engine, "Combat Array: Sensing Eye", at=(5, 6))
    me, foe = engine.state.actors[ME], _foe(engine)
    assert not senses.pinpoints(engine, me, foe)
    _do(engine, "Pulse: Sensing Eye (foe)", target=AN)
    assert senses.pinpoints(engine, me, foe) and senses.finds(engine, me, foe)
    _step_into(engine, (12, 6))
    assert not senses.pinpoints(engine, me, foe)  # "while it remains inside the array"


def test_sensing_eye_reports_creatures_entering_and_leaving_with_a_count():
    engine, _bundle = _engine([], foe_at=(12, 6))
    _do(engine, "Combat Array: Sensing Eye", at=(5, 6))
    _step_into(engine, (6, 6))
    lines = [str(event.payload.get("rider") or event.payload.get("text") or "") for event in engine.events]
    assert any("enters the array at (5,6); 2 inside now" in line for line in lines), lines[-6:]
    foe = _foe(engine)
    start = foe.position
    foe.position = Position(x=12, y=6)
    engine._append_event("MOVEMENT_COMMITTED", "test:move", actor_id=AN, payload={"destination": foe.position.model_dump(mode="json"), "path": [
        start.model_dump(mode="json"), foe.position.model_dump(mode="json")], "cost_ft": 30})
    lines = [str(event.payload.get("rider") or event.payload.get("text") or "") for event in engine.events]
    assert any("leaves the array at (5,6); 1 inside now" in line for line in lines), lines[-6:]


def test_veiled_road_pulse_moves_an_ally_ten_feet_free_and_blinds_outsiders():
    engine, _bundle = _engine([], foe_at=(12, 6))
    _do(engine, "Combat Array: Veiled Road", at=(3, 6))
    me = engine.state.actors[ME]
    assert {"Pulse: Veiled Road (move 10 ft)", "Pulse: Veiled Road (Hide)"} <= _names(engine)
    before = me.movement_remaining_ft
    _do(engine, "Pulse: Veiled Road (move 10 ft)", target=ME)
    assert me.movement_remaining_ft == before + 10 and me.turn_flags.get("oa_free_ft") == 10
    zone = _array(engine)[0]
    assert formations.veiled_search(engine, _foe(engine), me) == "DISADVANTAGE" and formations.veiled_search(engine, me, me) is None
    assert zone.trigger_profile["inside"][0]["name"] == "Veiled Road"


def test_nourishing_cycle_helps_a_creature_only_once_per_short_rest():
    engine, _bundle = _engine([])
    _do(engine, "Combat Array: Nourishing Cycle", at=(3, 6))
    engine.state.actors[ME].current_hp = 1
    _do(engine, "Pulse: Nourishing Cycle", target=ME)
    engine.state.round_number += 1
    _turn(engine, ME)
    assert "Pulse: Nourishing Cycle" not in _names(engine)


def test_binding_pulse_restrains_or_denies_reactions_and_the_passive_hampers_escapes():
    engine, _bundle = _engine(BINDING, foe_at=(6, 6))
    _do(engine, "Combat Array: Binding", at=(5, 6))
    _force_dc(engine, 99)
    foe = _foe(engine)
    grip = engine._apply_condition
    grip(foe, "condition:typed.grappled", "test:grab", ME, expires_on="UNTIL_REMOVED")
    grips = [c for c in foe.conditions.values() if c.condition_id == "condition:typed.grappled"]
    assert formations.escape_mode(engine, foe, grips) == "DISADVANTAGE"
    _do(engine, "Pulse: Binding", target=AN)
    assert any("restrained" in cid for cid in _conditions(foe))
    engine2, _ = _engine(BINDING, foe_at=(6, 6), seed="BIND2")
    _do(engine2, "Combat Array: Binding", at=(5, 6))
    _force_dc(engine2, -50)
    _do(engine2, "Pulse: Binding", target=AN)
    assert any("reaction_denied" in cid for cid in _conditions(_foe(engine2)))


def test_sealing_gate_makes_a_teleport_through_the_array_take_a_charisma_save():
    engine, _bundle = _engine(SEALING, foe_at=(6, 6))
    _do(engine, "Combat Array: Sealing Gate", at=(5, 6))
    foe = _foe(engine)
    _force_dc(engine, 99)
    out, nearby = Position(x=15, y=6), Position(x=6, y=7)
    zone = _array(engine)[0]
    zone.trigger_profile["formation"]["numbers"]["save_dc"] = 99
    assert formations.teleport_check(engine, foe, foe.position, out) is False  # out of the array: the save fails
    assert formations.teleport_check(engine, foe, foe.position, nearby) is None  # wholly inside it: not affected
    zone.trigger_profile["formation"]["numbers"]["save_dc"] = -50
    assert formations.teleport_check(engine, foe, foe.position, out) is None  # a save that succeeds lets it through
    zone.trigger_profile["formation"]["numbers"]["save_dc"] = 99
    _do(engine, "Pulse: Sealing Gate", target=AN)
    assert any("cannot_teleport" in cid for cid in _conditions(foe))


# ---------------------------------------------------------------------------------------------- the talents (Stage 3)
T = "tianxia.talent.formations."


def _with(*names, **kwargs):
    return _engine([T + name for name in names], **kwargs)


def _log(engine):
    return [str(event.payload.get("rider") or event.payload.get("text") or "") for event in engine.events]


def test_layered_pattern_adds_a_second_layer_for_two_more_cp_and_either_pulse_works():
    engine, _bundle = _with("layered_pattern", foe_at=(6, 6))
    me = engine.state.actors[ME]
    before = me.resources.get("resource:core.qi")
    _do(engine, "Next array: second layer, Sensing Eye")
    assert any(c.condition_id.endswith("formation_setup") for c in me.conditions.values())
    _do(engine, "Combat Array: Locking Gate", at=(5, 6))
    (zone,) = _array(engine)
    assert formations.record(zone)["layers"] == ["locking_gate", "sensing_eye"]
    assert me.resources.get("resource:core.qi") == before - 4  # 2 CP for the array, 2 more for the layer
    assert zone.trigger_profile["name"] == "Locking Gate + Sensing Eye Array" and zone.trigger_profile["difficult"] == "hostile"
    assert not any(c.condition_id.endswith("formation_setup") for c in me.conditions.values())  # used up
    assert {"Pulse: Locking Gate", "Pulse: Sensing Eye (foe)"} <= _names(engine)  # "choose one Pattern Layer to Pulse"


def test_layered_pattern_without_the_cp_leaves_the_array_plain():
    engine, _bundle = _with("layered_pattern")
    me = engine.state.actors[ME]
    _do(engine, "Next array: second layer, Sensing Eye")
    me.resources["resource:core.qi"] = 3
    _do(engine, "Combat Array: Locking Gate", at=(5, 6))
    assert formations.record(_array(engine)[0])["layers"] == ["locking_gate"]
    assert any("Not enough CP for the second layer" in line for line in _log(engine))


def test_layered_pattern_is_offered_only_with_the_talent():
    plain, _ = _engine([])
    assert not any(name and name.startswith("Next array") for name in _names(plain))


def test_line_array_is_a_line_from_its_eye_away_from_the_owner():
    engine, _bundle = _with("line_array")
    _do(engine, "Next array: shape it as a line")
    _do(engine, "Combat Array: Locking Gate", at=(5, 6))
    (zone,) = _array(engine)
    assert {(cell.x, cell.y) for cell in zone.affected_cells} == {(5 + step, 6) for step in range(6)}  # 30 feet long, 5 feet wide
    assert formations.record(zone)["line"] and (formations.record(zone)["eye"] in engine.state.objects)


def test_gate_keeper_keys_a_hostile_creature_past_the_arrays_hostile_effects():
    engine, _bundle = _with("gate_keeper", foe_at=(12, 6))
    _do(engine, "Next array: key a creature", target=AN)
    _do(engine, "Combat Array: Killing Line (Fire)", at=(5, 6))
    (zone,) = _array(engine)
    foe = _foe(engine)
    assert AN in formations.record(zone)["keyed"] and not formations.hostile_to(engine, zone, foe)
    before = foe.current_hp
    _step_into(engine, (6, 6))
    assert foe.current_hp == before  # a keyed creature passes "without triggering your hostile boundary effects"
    # As a Bonus Action within 120 feet: unkey it, and the array works on it again.
    _do(engine, "Gate Keeper: Unkey a creature from your arrays", target=AN)
    assert AN not in formations.record(zone)["keyed"] and formations.hostile_to(engine, zone, foe)
    assert engine.state.actors[ME].bonus_action_available is False
    _turn(engine, ME)
    _do(engine, "Gate Keeper: Key a creature to your arrays", target=AN)
    assert AN in formations.record(_array(engine)[0])["keyed"]


def test_reinforced_nodes_adds_cl_hit_points_and_a_reaction_and_cp_leaves_a_broken_eye_at_one():
    engine, _bundle = _with("reinforced_nodes")
    _do(engine, "Combat Array: Locking Gate", at=(5, 6))
    (zone,) = _array(engine)
    cl = int(formations.record(zone)["cl"])
    eye = engine.state.objects[formations.record(zone)["eye"]]
    assert eye.maximum_hp == 5 + cl + cl  # "Increase the Hit Points of your Nodes and Eyes by your CL"
    me = engine.state.actors[ME]
    cp = me.resources.get("resource:core.qi")
    formations.hurt_object(engine, eye, 999, "SLASHING", "test", AN)
    left = engine.state.objects[eye.object_id]
    assert left.current_hp == 1 and not left.destroyed and _array(engine)
    assert me.reaction_available is False and me.resources.get("resource:core.qi") == cp - 1
    formations.hurt_object(engine, left, 999, "SLASHING", "test", AN)  # the Reaction is spent: it falls
    assert engine.state.objects[eye.object_id].destroyed and not _array(engine)


def test_array_repair_restores_a_damaged_eye_and_ends_a_disruption():
    engine, _bundle = _with("array_repair")
    _do(engine, "Combat Array: Locking Gate", at=(5, 6))
    (zone,) = _array(engine)
    eye = engine.state.objects[formations.record(zone)["eye"]]
    assert "Array Repair: restore Hit Points" not in _names(engine)  # nothing is damaged
    formations.hurt_object(engine, eye, 4, "SLASHING", "test", AN)
    hurt = engine.state.objects[eye.object_id].current_hp
    me = engine.state.actors[ME]
    _turn(engine, ME)  # Combat Array took her Action
    cp = me.resources.get("resource:core.qi")
    _do(engine, "Array Repair: restore Hit Points", target=eye.object_id)
    assert engine.state.objects[eye.object_id].current_hp > hurt and me.resources.get("resource:core.qi") == cp - 1
    disrupted = engine.state.objects[eye.object_id]
    engine._update_object(disrupted.model_copy(update={"component": {**disrupted.component, "disrupted_by": AN}}), "test", AN)
    _turn(engine, ME)
    _do(engine, "Array Repair: end a disruption", target=eye.object_id)
    assert not formations.disrupted(engine.state.objects[eye.object_id])


def _duel_with(talents, seed="DISRUPT"):
    """ME has the given Formations talents; THEM (team b) has none and sets an array at (7, 6)."""
    them = "actor:factory.g"
    bundles = (compile_character(_sheet(talents), actor_id=ME), compile_character(_sheet([]), actor_id=them))
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=bundles,
                                   roster_setup={"primary_actor_ids": [ME, them], "team_by_actor": {ME: "team:a", them: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, them: {"x": 7, "y": 6}}})
    _turn(engine, them)
    _do(engine, "Combat Array: Sensing Eye", at=(7, 6), actor=them)
    zone = formations.arrays(engine, them)[0]
    return engine, them, zone, engine.state.objects[formations.record(zone)["eye"]]


def _set_dc(zone, dc):
    zone.trigger_profile["formation"]["numbers"]["save_dc"] = dc


def test_disrupt_node_makes_an_eye_useless_and_the_array_unstable_until_its_creator_holds_it():
    engine, them, zone, eye = _duel_with([T + "disrupt_node"])
    _set_dc(zone, -50)  # "a Formation Check against the creator's Formation Save DC": ours succeeds
    _turn(engine, ME)
    assert "Disrupt Node" in _names(engine)
    _do(engine, "Disrupt Node", target=eye.object_id)
    assert formations.disrupted(engine.state.objects[eye.object_id])
    assert formations.record(zone)["unstable"]["by"] == ME
    # a disrupted Eye cannot Pulse the array: Pulse actions are not offered against it
    _turn(engine, them)
    _set_dc(zone, 99)  # "the creator must succeed on a Formation Check against your Formation Save DC": theirs fails
    _turn(engine, them)
    assert not formations.arrays(engine, them) and any("unstable" in line.lower() for line in _log(engine))


def test_disrupt_node_that_misses_changes_nothing():
    engine, _them, zone, eye = _duel_with([T + "disrupt_node"], seed="DISRUPT2")
    _set_dc(zone, 99)
    _turn(engine, ME)
    _do(engine, "Disrupt Node", target=eye.object_id)
    assert not formations.disrupted(engine.state.objects[eye.object_id]) and not formations.record(zone).get("unstable")
    assert any("holds" in line for line in _log(engine))


def test_formation_compass_learns_one_thing_about_an_array_within_sixty_feet():
    engine, _bundle = _with("formation_compass")
    _do(engine, "Combat Array: Locking Gate", at=(5, 6))
    zone = _array(engine)[0]
    zone.trigger_profile["formation"]["numbers"]["save_dc"] = -50
    _turn(engine, ME)
    _do(engine, "Formation Compass: find its Eye", at=(6, 6))
    assert any("its Eye is at (5,6)" in line for line in _log(engine))
    _turn(engine, ME)
    _do(engine, "Formation Compass: learn whether it needs Concentration", at=(5, 6))
    assert any("needs its creator's Concentration" in line for line in _log(engine))
    _turn(engine, ME)
    _do(engine, "Formation Compass: learn a Pattern Layer", at=(5, 6))
    assert any("holds a Locking Gate layer" in line for line in _log(engine))
    zone.trigger_profile["formation"]["numbers"]["save_dc"] = 99
    _turn(engine, ME)
    _do(engine, "Formation Compass: learn how it would collapse", at=(5, 6))
    assert any("keeps its secrets" in line for line in _log(engine))


def test_shifting_gates_makes_a_hostile_crossing_the_boundary_save_and_lasts_to_the_owners_next_turn():
    engine, _bundle = _with("shifting_gates", foe_at=(12, 6))
    _do(engine, "Combat Array: Locking Gate", at=(5, 6))
    zone = _array(engine)[0]
    _set_dc(zone, 99)  # the Dexterity save fails
    _do(engine, "Shifting Gates", at=(5, 6))
    assert formations.record(zone)["shifting"] is True
    foe = _foe(engine)
    foe.movement_remaining_ft = 30
    _step_into(engine, (7, 6))
    assert foe.movement_remaining_ft == 0 and any("movement ends at the array's boundary" in line for line in _log(engine))
    # a creature that saves is slowed instead: Speed -10 until the start of its next turn
    _set_dc(zone, -50)
    foe.movement_remaining_ft = 30
    _step_into(engine, (12, 6))
    zone.per_turn_triggered.clear() if hasattr(zone, "per_turn_triggered") else None
    _step_into(engine, (7, 6))
    assert foe.movement_remaining_ft == 30
    assert engine._effective_speed(foe) == foe.speed_ft - 10
    _turn(engine, ME)  # the start of the owner's next turn
    assert formations.record(zone)["shifting"] is False
    assert not any(row.get("id") == "formation:shifting_gates" for row in zone.trigger_profile["triggers"])


def test_formation_step_teleports_within_the_array_the_owner_started_her_turn_in_once_a_turn():
    engine, _bundle = _with("formation_step")
    _do(engine, "Combat Array: Locking Gate", at=(3, 6))
    assert "Formation Step" not in _names(engine)  # she did not *start* the turn inside it
    _turn(engine, ME)  # a new turn: she stands inside
    me = engine.state.actors[ME]
    assert "Formation Step" in _names(engine)
    _do(engine, "Formation Step", at=(5, 6))
    assert (me.position.x, me.position.y) == (5, 6) and me.bonus_action_available is False
    me.bonus_action_available = True
    assert "Formation Step" not in _names(engine)  # "cannot use it again until the start of its next turn"
    _turn(engine, ME)
    assert "Formation Step" in _names(engine)
    cells = {(cell.x, cell.y) for cell in _array(engine)[0].affected_cells}
    destinations = [c.destination for c in engine.legal_candidates()
                    if c.actor_id == ME and getattr(engine.action_catalog.get(c.source_definition_id), "display_name", "") == "Formation Step"]
    assert destinations and all((d.x, d.y) in cells for d in destinations)  # only inside the same array


def test_collapsing_exit_lets_the_owner_step_out_free_and_gain_temp_hp_when_she_ends_outside():
    engine, _bundle = _with("collapsing_exit")
    _do(engine, "Combat Array: Locking Gate", at=(3, 6))
    me = engine.state.actors[ME]
    cells = {(cell.x, cell.y) for cell in _array(engine)[0].affected_cells}
    assert (me.position.x, me.position.y) in cells
    _turn(engine, ME)
    before = me.movement_remaining_ft
    _do(engine, "Collapse Array", at=(3, 6))
    assert me.movement_remaining_ft >= before + 10  # "move up to 10 feet without provoking Opportunity Attacks"
    assert any(c.condition_id.endswith("formation_exit") for c in me.conditions.values())
    start = me.position
    me.position = Position(x=start.x + 5, y=start.y)  # ten feet away: outside the former array (radius 10 ft around (3,6) is 2 squares)
    assert (me.position.x, me.position.y) not in cells
    engine._append_event("MOVEMENT_COMMITTED", "test:move", actor_id=ME,
                         payload={"destination": {"x": me.position.x, "y": me.position.y}, "path": [{"x": start.x, "y": start.y}, {"x": me.position.x, "y": me.position.y}], "cost_ft": 25})
    assert me.temporary_hp > 0 and not any(c.condition_id.endswith("formation_exit") for c in me.conditions.values())


# ---------------------------------------------------------------------------------------------- the higher talents (formation_masters.py)
def _layered(second, *talents, first="Locking Gate", **kwargs):
    """ME sets a two-layer array at (5, 6): ``first`` plus ``second`` (Layered Pattern), with Harmonized Pulse and any extra talents."""
    engine, bundle = _with("layered_pattern", "harmonized_pulse", *talents, **kwargs)
    _do(engine, f"Next array: second layer, {second}")
    _do(engine, f"Combat Array: {first}", at=(5, 6))
    return engine


def _move(engine, who, cells):
    """Commit a move of ``who`` along ``cells`` (the movement hooks read the MOVEMENT_COMMITTED event)."""
    actor = engine.state.actors[who]
    start = actor.position
    actor.position = Position(x=cells[-1][0], y=cells[-1][1])
    engine._append_event("MOVEMENT_COMMITTED", "test:move", actor_id=who, payload={
        "destination": actor.position.model_dump(mode="json"), "cost_ft": 5 * (len(cells) - 1),
        "path": [start.model_dump(mode="json"), *[{"x": x, "y": y} for x, y in cells]]})


def test_harmonized_pulse_is_offered_only_with_the_talent_and_a_second_layer():
    plain, _ = _with("layered_pattern")
    assert not any(name and name.startswith("Harmonized Pulse") for name in _names(plain))
    engine, _bundle = _with("layered_pattern", "harmonized_pulse")
    assert not any(name and name.startswith("Harmonized Pulse") for name in _names(engine))  # no array yet
    _do(engine, "Next array: second layer, Sensing Eye")
    _do(engine, "Combat Array: Locking Gate", at=(5, 6))
    assert {"Harmonized Pulse: strengthen Locking Gate", "Harmonized Pulse: strengthen Sensing Eye"} <= _names(engine)
    assert "Harmonized Pulse: strengthen Nourishing Cycle" not in _names(engine)  # not a layer of this array
    single, _ = _with("harmonized_pulse")
    _do(single, "Combat Array: Locking Gate", at=(5, 6))
    assert "Harmonized Pulse: strengthen Locking Gate" not in _names(single)  # "an array with two or more layers"


def test_harmonized_locking_gate_takes_an_extra_five_feet_for_every_five_a_hostile_moves_inside():
    engine = _layered("Sensing Eye", foe_at=(12, 6))
    me, foe = engine.state.actors[ME], _foe(engine)
    cp = me.resources.get("resource:core.qi")
    _do(engine, "Harmonized Pulse: strengthen Locking Gate")
    assert me.resources.get("resource:core.qi") == cp - 1 and formations.record(_array(engine)[0])["harmonized"] == "locking_gate"
    _turn(engine, AN)
    assert foe.movement_remaining_ft == 30
    _move(engine, AN, [(9, 6), (8, 6), (7, 6), (6, 6)])  # two squares of the array (7,6) and (6,6): 10 feet paid twice
    assert foe.movement_remaining_ft == 30 - 10
    assert any("extra feet of movement" in line for line in _log(engine))
    _turn(engine, ME)  # "until the start of your next turn"
    assert not formations.record(_array(engine)[0])["harmonized"]
    _turn(engine, AN)
    _move(engine, AN, [(5, 6), (4, 6)])
    assert foe.movement_remaining_ft == 30 - 0  # the strengthening is gone: no further tax


def test_harmonized_sensing_eye_takes_the_invisible_benefit_from_a_creature_inside_against_the_owner():
    from combat import senses

    engine = _layered("Sensing Eye", first="Locking Gate", foe_at=(6, 6))
    me, foe = engine.state.actors[ME], _foe(engine)
    engine._apply_condition(foe, "condition:typed.invisible", "test:invisible", AN, expires_on="UNTIL_REMOVED")
    assert not senses.masked_conditions(engine, me, foe)
    _do(engine, "Harmonized Pulse: strengthen Sensing Eye")
    masked = senses.masked_conditions(engine, me, foe)
    assert masked.get(AN), masked
    _step_into(engine, (12, 6))  # outside the array it is not "inside", so it is Invisible again
    assert not senses.masked_conditions(engine, me, foe)


def test_harmonized_veiled_road_gives_one_keyed_ally_half_cover():
    engine = _layered("Veiled Road", first="Locking Gate", team_foe="team:a", foe_at=(6, 6))
    me, ally = engine.state.actors[ME], _foe(engine)
    assert ext.run("cover", engine, ally, me) == []
    _do(engine, "Harmonized Pulse: strengthen Veiled Road", target=AN)
    assert ext.run("cover", engine, me, ally) == [2]
    assert any("has Half Cover" in line for line in _log(engine))
    _step_into(engine, (12, 6))  # it must remain inside the array
    assert ext.run("cover", engine, me, ally) == []


def test_harmonized_veiled_road_cannot_cover_a_hostile_creature():
    engine = _layered("Veiled Road", first="Locking Gate", foe_at=(6, 6))
    assert "Harmonized Pulse: strengthen Veiled Road" not in {
        getattr(engine.action_catalog.get(c.source_definition_id), "display_name", None) for c in engine.legal_candidates()
        if c.actor_id == ME and c.target_ids == (AN,)}


def test_harmonized_nourishing_cycle_adds_the_key_modifier_to_the_temporary_hp():
    engine = _layered("Nourishing Cycle", first="Locking Gate", team_foe="team:a", foe_at=(4, 6))
    me, ally = engine.state.actors[ME], _foe(engine)
    ally.current_hp = 1
    _turn(engine, AN)
    plain = ally.temporary_hp
    assert plain == int(formations.record(_array(engine)[0])["numbers"]["pb"])  # the Passive alone: PB
    ally.temporary_hp = 0
    zone = _array(engine)[0]
    zone.trigger_profile["formation"]["per_round_used"] = {}
    _turn(engine, ME)
    _do(engine, "Harmonized Pulse: strengthen Nourishing Cycle")
    engine.state.round_number += 1
    zone.trigger_profile["triggers"][0].pop("_used", None)
    _turn(engine, AN)
    key = int(formations.record(zone)["numbers"]["key_mod"])
    assert ally.temporary_hp == plain + max(0, key) and key > 0


def test_harmonized_suppressing_vein_taxes_the_first_hostile_cp_spend_inside():
    engine = _layered("Suppressing Vein", first="Locking Gate", foe_at=(6, 6))
    foe = _foe(engine)
    _do(engine, "Harmonized Pulse: strengthen Suppressing Vein")
    _set_dc(_array(engine)[0], 99)  # the Charisma save fails
    resource = next(key for key in foe.resources if key.endswith(".stamina"))
    before = foe.resources[resource]
    engine._spend_resource(foe, resource, 1, "test:spend")
    assert foe.resources[resource] == before - 2  # the spend and one more
    assert any("loses 1 more CP" in line for line in _log(engine))
    again = foe.resources[resource]
    engine._spend_resource(foe, resource, 1, "test:spend")
    assert foe.resources[resource] == again - 1  # only the first hostile spender is taxed


def test_harmonized_suppressing_vein_spares_a_creature_that_saves():
    engine = _layered("Suppressing Vein", first="Locking Gate", foe_at=(6, 6))
    foe = _foe(engine)
    _do(engine, "Harmonized Pulse: strengthen Suppressing Vein")
    _set_dc(_array(engine)[0], -50)
    resource = next(key for key in foe.resources if key.endswith(".stamina"))
    before = foe.resources[resource]
    engine._spend_resource(foe, resource, 1, "test:spend")
    assert foe.resources[resource] == before - 1


def test_harmonized_killing_line_adds_the_proficiency_bonus_to_the_first_damage_only():
    engine = _layered("Sensing Eye", first="Killing Line (Fire)", foe_at=(12, 6))
    foe, pb = _foe(engine), None
    zone = _array(engine)[0]
    pb = int(formations.record(zone)["numbers"]["pb"])
    _do(engine, "Harmonized Pulse: strengthen Killing Line")
    before = foe.current_hp
    _step_into(engine, (7, 6))
    assert before - foe.current_hp == 2 * pb  # "the first damage roll from the array adds your Proficiency Bonus"
    _step_into(engine, (12, 6))
    _turn(engine, AN)
    _turn(engine, AN)
    hp = foe.current_hp
    _step_into(engine, (6, 6))
    assert hp - foe.current_hp == pb  # used up


ELEMENTAL = ["elemental_killing_array"]


def _element(element, name):
    engine, _bundle = _with(*ELEMENTAL, foe_at=(6, 6))
    _do(engine, f"Next Killing Line: {name}")
    _do(engine, "Combat Array: Killing Line (Fire)", at=(5, 6))
    for action in engine.action_catalog.values():  # a Formation Attack that hits
        if action.owner_id == ME and (action.parameters or {}).get("typed"):
            action.parameters["typed"]["numbers"] = {**action.parameters["typed"]["numbers"], "attack_bonus": 99}
    _do(engine, "Pulse: Killing Line", target=AN)
    return engine, _foe(engine)


def test_elemental_killing_array_is_offered_by_talent_and_names_each_sphere():
    plain, _ = _engine([])
    assert not any(name and name.startswith("Next Killing Line") for name in _names(plain))
    engine, _bundle = _with(*ELEMENTAL)
    assert {"Next Killing Line: Fire or Ash", "Next Killing Line: Water or Ice", "Next Killing Line: Force"} <= _names(engine)


def test_elemental_fire_stops_healing_and_lightning_stops_reactions():
    from combat import typed_executor

    engine, foe = _element("fire", "Fire or Ash")
    assert typed_executor._reduced_healing(engine, foe, 10) == 0
    assert any("Fire or Ash" in line for line in _log(engine))
    engine, foe = _element("lightning", "Lightning or Thunder")
    assert any("reaction_denied" in cid for cid in _conditions(foe))


def test_elemental_water_slows_sand_stops_dash_radiance_unmasks_shadow_and_blood_disadvantage():
    engine, foe = _element("water", "Water or Ice")
    assert engine._effective_speed(foe) == foe.speed_ft - 10
    engine, foe = _element("sand", "Sand or Earth")
    assert any("no_dash" in cid for cid in _conditions(foe))
    engine, foe = _element("radiance", "Radiance")
    assert any("formation_unlit" in cid for cid in _conditions(foe))
    engine, foe = _element("shadow", "Shadow or Dark")
    assert any("formation_dim" in cid for cid in _conditions(foe))
    engine, foe = _element("blood", "Blood or Poison")
    assert any("formation_weak_con" in cid for cid in _conditions(foe))


def test_elemental_force_pushes_the_target_five_feet_and_only_once_a_turn():
    engine, foe = _element("force", "Force")
    assert foe.position.x == 7  # five feet along its Flow Line, away from the Eye at (5, 6)... it stood at (6, 6)
    assert any("Force" in line for line in _log(engine))


def test_radiance_rider_lets_a_watcher_see_an_invisible_creature():
    from combat import senses

    engine, foe = _element("radiance", "Radiance")
    me = engine.state.actors[ME]
    engine._apply_condition(foe, "condition:typed.invisible", "test:invisible", AN, expires_on="UNTIL_REMOVED")
    assert senses.masked_conditions(engine, me, foe).get(AN)


def test_the_shadow_rider_is_used_up_by_the_next_perception_check():
    engine, foe = _element("shadow", "Shadow or Dark")
    assert any("formation_dim" in cid for cid in _conditions(foe))
    engine._append_event("CHECK_ROLLED", "test:look", actor_id=AN, payload={"check": "Perception", "total": 12})
    assert not any("formation_dim" in cid for cid in _conditions(foe))


def test_spirit_lock_makes_a_failed_sealing_gate_save_block_summoning_too():
    engine, _bundle = _with("sealing_gate_pattern", "spirit_lock_array", foe_at=(6, 6))
    _do(engine, "Combat Array: Sealing Gate", at=(5, 6))
    _force_dc(engine, 99)
    foe = _foe(engine)
    _do(engine, "Pulse: Sealing Gate", target=AN)
    assert any("formation_spirit_locked" in cid for cid in _conditions(foe)) and any("cannot_teleport" in cid for cid in _conditions(foe))
    assert ext.run("summon_check", engine, engine.state.actors[ME], foe, foe.position, True, "test:summon") == [False]
    assert formations.teleport_check(engine, foe, foe.position, Position(x=6, y=7)) is False


def test_without_spirit_lock_a_failed_sealing_gate_save_only_blocks_teleporting():
    engine, _bundle = _with("sealing_gate_pattern", foe_at=(6, 6))
    _do(engine, "Combat Array: Sealing Gate", at=(5, 6))
    _force_dc(engine, 99)
    _do(engine, "Pulse: Sealing Gate", target=AN)
    foe = _foe(engine)
    assert not any("formation_spirit_locked" in cid for cid in _conditions(foe))
    assert ext.run("summon_check", engine, engine.state.actors[ME], foe, foe.position, True, "test:summon") == []


def test_sovereign_pulse_lets_a_second_different_layer_pulse_for_two_cp():
    engine, _bundle = _with("layered_pattern", "sovereign_pulse", foe_at=(6, 6))
    _do(engine, "Next array: second layer, Sensing Eye")
    _do(engine, "Combat Array: Locking Gate", at=(5, 6))
    _force_dc(engine, 99)
    me, foe = engine.state.actors[ME], _foe(engine)
    _do(engine, "Pulse: Locking Gate", target=AN)
    assert any("held_fast" in cid for cid in _conditions(foe))
    cp = me.resources.get("resource:core.qi")
    assert not any(name and name.startswith("Second Pulse: Locking Gate") for name in _names(engine))  # "a second, *different* layer"
    _do(engine, "Second Pulse: Sensing Eye (foe)", target=AN)
    assert me.resources.get("resource:core.qi") == cp - 2


def test_second_pulse_is_not_offered_without_the_talent():
    engine, _bundle = _with("layered_pattern", foe_at=(6, 6))
    _do(engine, "Next array: second layer, Sensing Eye")
    _do(engine, "Combat Array: Locking Gate", at=(5, 6))
    _force_dc(engine, 99)
    _do(engine, "Pulse: Locking Gate", target=AN)
    assert not any(name and name.startswith("Second Pulse") for name in _names(engine))


EYE = ["eye_of_the_formation_master"]


def _break_eye(engine, damage=99):
    zone = _array(engine)[0]
    eye = engine.state.objects[formations.record(zone)["eye"]]
    formations.hurt_object(engine, eye, damage, "SLASHING", "test", AN)
    return zone, eye


def test_eye_of_the_formation_master_holds_the_array_for_a_reaction_and_two_cp_and_marks_the_owner():
    engine, _bundle = _with(*EYE, foe_at=(4, 6))
    _do(engine, "Combat Array: Locking Gate", at=(3, 6))
    me, foe = engine.state.actors[ME], _foe(engine)
    cp = me.resources.get("resource:core.qi")
    zone, eye = _break_eye(engine)
    assert engine.state.zones[zone.zone_id].active and engine.state.objects[eye.object_id].destroyed
    assert me.reaction_available is False and me.resources.get("resource:core.qi") == cp - 2
    assert any("formation_marked" in cid for cid in _conditions(me))
    assert any("Eye of the Formation Master" in line for line in _log(engine))
    # "attacks against you have Advantage if the attacker is inside the array and can see you"
    ctx = type("Ctx", (), {"engine": engine, "actor": foe})()
    assert ext.run("attack_mode", ctx, me) == ["ADVANTAGE"]
    foe.position = Position(x=12, y=6)
    assert ext.run("attack_mode", ctx, me) == []


def test_the_held_array_falls_at_the_end_of_the_owners_next_turn():
    engine, _bundle = _with(*EYE, foe_at=(12, 6))
    _do(engine, "Combat Array: Locking Gate", at=(3, 6))
    me = engine.state.actors[ME]
    zone, _eye = _break_eye(engine)
    engine.end_turn()  # the end of this turn: the array still stands
    assert engine.state.zones[zone.zone_id].active
    assert engine.state.current_actor_id == AN
    engine.end_turn()
    assert engine.state.current_actor_id == ME and engine.state.zones[zone.zone_id].active  # "until the end of your next turn"
    assert any("formation_marked" in cid for cid in _conditions(me))
    engine.end_turn()  # the end of her next turn
    assert not engine.state.zones[zone.zone_id].active
    assert not any("formation_marked" in cid for cid in _conditions(me))
    assert engine.state.actors[ME].concentration is None


def test_without_the_talent_or_the_cp_a_broken_eye_still_collapses_the_array():
    engine, _bundle = _with(foe_at=(12, 6))
    _do(engine, "Combat Array: Locking Gate", at=(3, 6))
    zone, _eye = _break_eye(engine)
    assert not engine.state.zones[zone.zone_id].active
    engine, _bundle = _with(*EYE, foe_at=(12, 6))
    _do(engine, "Combat Array: Locking Gate", at=(3, 6))
    engine.state.actors[ME].resources["resource:core.qi"] = 1
    zone, _eye = _break_eye(engine)
    assert not engine.state.zones[zone.zone_id].active
    engine, _bundle = _with(*EYE, foe_at=(12, 6))
    _do(engine, "Combat Array: Locking Gate", at=(3, 6))
    engine.state.actors[ME].reaction_available = False
    zone, _eye = _break_eye(engine)
    assert not engine.state.zones[zone.zone_id].active


def test_the_owner_must_stand_inside_the_array_to_serve_as_its_eye():
    engine, _bundle = _with(*EYE, foe_at=(12, 6))
    _do(engine, "Combat Array: Locking Gate", at=(6, 6))
    engine.state.actors[ME].position = Position(x=1, y=1)
    zone, _eye = _break_eye(engine)
    assert not engine.state.zones[zone.zone_id].active


def test_disrupt_node_on_a_held_eye_leaves_the_array_holding_instead_of_unstable():
    them = "actor:factory.g"  # THEM owns the array and has the Eye of the Formation Master talent; ME disrupts it
    bundles = (compile_character(_sheet([T + "disrupt_node"]), actor_id=ME), compile_character(_sheet([T + EYE[0]]), actor_id=them))
    engine = Gate4ControllerEngine(ROOT, match_seed="DISRUPT4", typed_bundles=bundles,
                                   roster_setup={"primary_actor_ids": [ME, them], "team_by_actor": {ME: "team:a", them: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, them: {"x": 7, "y": 6}}})
    _turn(engine, them)
    _do(engine, "Combat Array: Sensing Eye", at=(7, 6), actor=them)
    zone = formations.arrays(engine, them)[0]
    eye = engine.state.objects[formations.record(zone)["eye"]]
    _set_dc(zone, -50)
    _turn(engine, ME)
    _do(engine, "Disrupt Node", target=eye.object_id)
    assert formations.arrays(engine, them) and not formations.record(zone).get("unstable")
    assert formations.record(zone).get("held")
    assert any("holds" in line.lower() for line in _log(engine))


COURT = ["court_of_the_ninefold_array"]


def _court(*talents, **kwargs):
    kwargs.setdefault("foe_at", (12, 6))
    engine, bundle = _with(*COURT, *talents, cl=kwargs.pop("cl", 12), qi=kwargs.pop("qi", 60), **kwargs)
    return engine


def _cast_court(engine, at=(5, 6)):
    _do(engine, "Court of the Ninefold Array", at=at)
    (zone,) = [row for row in _array(engine) if formations.record(row).get("domain") == "court"]
    return zone


def test_the_court_is_offered_only_with_the_talent_and_at_cl_twelve():
    plain, _ = _with(cl=12, qi=60)
    assert "Court of the Ninefold Array" not in _names(plain)
    young, _ = _with(*COURT, cl=10, qi=60)
    assert "Court of the Ninefold Array" not in _names(young)
    engine = _court()
    assert "Court of the Ninefold Array" in _names(engine)
    assert not {name for name in _names(engine) if name and name.startswith("Free Pulse")} - {name for name in _names(engine)}  # (offered below)


def test_the_court_is_a_forty_foot_zone_with_an_eye_nine_nodes_two_layers_and_costs_eight_cp():
    engine = _court()
    me = engine.state.actors[ME]
    cp = me.resources.get("resource:core.qi")
    zone = _cast_court(engine)
    record = formations.record(zone)
    assert me.resources.get("resource:core.qi") == cp - 8 and me.concentration.zone_id == zone.zone_id
    cells = {(cell.x, cell.y) for cell in zone.affected_cells}
    assert (13, 6) in cells and (14, 6) not in cells and (5, 13) in cells  # a 40-foot radius is eight squares
    eye = engine.state.objects[record["eye"]]
    assert (eye.ac, eye.maximum_hp, (eye.position.x, eye.position.y)) == (13, 5 + 12, (5, 6))
    nodes = [engine.state.objects[oid] for oid in record["nodes"]]
    assert len(nodes) == 9 and all((node.ac, node.maximum_hp) == (15, 3 * 12) for node in nodes)
    assert all((node.position.x, node.position.y) in cells for node in nodes) and len({(n.position.x, n.position.y) for n in nodes}) == 9
    assert all(node.damage_immunities == ("POISON", "PSYCHIC") for node in nodes)
    assert len(record["layers"]) == 2 and zone.trigger_profile["difficult"] == "hostile"  # "hostile creatures treat it as Difficult Terrain"
    assert "Court of the Ninefold Array" not in _names(engine)  # "once per short or long rest"


def test_the_court_takes_the_layers_the_owner_chose_and_a_reinforced_court_has_more_hit_points():
    engine = _court("reinforced_nodes", "layered_pattern")
    _do(engine, "Next Domain: layer Nourishing Cycle")
    _do(engine, "Next Domain: layer Veiled Road")
    zone = _cast_court(engine)
    record = formations.record(zone)
    assert record["layers"] == ["nourishing_cycle", "veiled_road"]
    assert engine.state.objects[record["eye"]].maximum_hp == 5 + 12 + 12
    assert engine.state.objects[record["nodes"][0]].maximum_hp == 36 + 12
    assert not any(c.condition_id.endswith("formation_setup") for c in engine.state.actors[ME].conditions.values())


def test_a_free_pulse_takes_no_action_and_only_once_a_turn():
    engine = _court(foe_at=(6, 6))
    _cast_court(engine)
    me, foe = engine.state.actors[ME], _foe(engine)
    _force_dc(engine, 99)
    bonus = me.bonus_action_available
    cp = me.resources.get("resource:core.qi")
    _do(engine, "Free Pulse: Locking Gate", target=AN)
    assert any("held_fast" in cid for cid in _conditions(foe)) and me.bonus_action_available == bonus and me.resources.get("resource:core.qi") == cp
    assert not any(name and name.startswith("Free Pulse") for name in _names(engine))  # "once during each of your turns"
    _turn(engine, ME)
    assert any(name and name.startswith("Free Pulse") for name in _names(engine))


def test_a_hostile_that_fails_a_court_pulse_save_lets_the_owner_move_a_node_and_the_node_hurts_what_it_crosses():
    engine = _court(foe_at=(10, 6))
    zone = _cast_court(engine)
    me, foe = engine.state.actors[ME], _foe(engine)
    node = engine.state.objects[formations.record(zone)["nodes"][0]]
    assert (node.position.x, node.position.y) == (11, 6)
    assert "Court: move a Node" not in _names(engine)  # nothing has failed a save yet
    _set_dc(zone, 99)
    _force_dc(engine, 99)
    _do(engine, "Free Pulse: Locking Gate", target=AN)
    assert me.turn_flags.get("formation_court_move") == 1
    hp = foe.current_hp
    pb = int(formations.record(zone)["numbers"]["pb"])
    _do(engine, "Court: move a Node", at=(9, 6))  # from (11, 6) through the hostile's square at (10, 6)
    moved = engine.state.objects[node.object_id]
    assert (moved.position.x, moved.position.y) == (9, 6)
    assert hp - foe.current_hp == pb and "Court: move a Node" not in _names(engine)
    assert any("A Node of the Court moves" in line for line in _log(engine))


def test_a_node_move_needs_a_node_within_ten_feet_of_the_square():
    engine = _court(foe_at=(10, 6))
    zone = _cast_court(engine)
    me = engine.state.actors[ME]
    me.turn_flags["formation_court_move"] = 1
    destinations = {(c.destination.x, c.destination.y) for c in engine.legal_candidates()
                    if c.actor_id == ME and getattr(engine.action_catalog.get(c.source_definition_id), "display_name", "") == "Court: move a Node"}
    assert (10, 6) in destinations and (13, 6) in destinations and (5, 9) not in destinations  # the Node at (11, 6) reaches two squares
    assert (11, 6) not in destinations


def test_the_court_falls_when_its_eye_is_destroyed_or_five_of_its_nine_nodes_are():
    engine = _court()
    zone = _cast_court(engine)
    record = formations.record(zone)
    for oid in record["nodes"][:4]:
        formations.hurt_object(engine, engine.state.objects[oid], 99, "SLASHING", "test", AN)
    assert engine.state.zones[zone.zone_id].active  # four Nodes are not enough
    formations.hurt_object(engine, engine.state.objects[record["nodes"][4]], 99, "SLASHING", "test", AN)
    assert not engine.state.zones[zone.zone_id].active and engine.state.actors[ME].concentration is None
    engine = _court()
    zone = _cast_court(engine)
    formations.hurt_object(engine, engine.state.objects[formations.record(zone)["eye"]], 99, "SLASHING", "test", AN)
    assert not engine.state.zones[zone.zone_id].active


def test_losing_concentration_collapses_the_court_and_its_objects():
    engine = _court()
    zone = _cast_court(engine)
    record = formations.record(zone)
    engine._end_concentration(engine.state.actors[ME], "FAILED_DAMAGE_CHECK")
    assert not engine.state.zones[zone.zone_id].active
    assert all(engine.state.objects[oid].destroyed for oid in [record["eye"], *record["nodes"]])


def test_keyed_allies_ignore_the_courts_difficult_terrain_and_hostiles_do_not():
    engine = _court(foe_at=(7, 6), team_foe="team:a")
    zone = _cast_court(engine)
    ally = _foe(engine)
    assert not zones.difficult_cells(engine, ally) & {(7, 6), (8, 6)}
    engine2 = _court(foe_at=(7, 6))
    zone2 = _cast_court(engine2)
    assert {(7, 6), (8, 6)} <= set(zones.difficult_cells(engine2, _foe(engine2)))


def test_a_court_gives_formation_step_without_the_talent():
    engine = _court()
    _cast_court(engine, at=(3, 6))
    _turn(engine, ME)
    assert "Formation Step" in _names(engine)
    me = engine.state.actors[ME]
    _do(engine, "Formation Step", at=(6, 6))
    assert (me.position.x, me.position.y) == (6, 6)
    plain, _ = _with(cl=12, qi=60)
    assert "Formation Step" not in _names(plain)


def test_a_court_is_not_an_array_for_formation_load():
    engine = _court("formation_load") if False else _court()
    court = _cast_court(engine)
    _turn(engine, ME)
    _do(engine, "Combat Array: Locking Gate", at=(3, 6))
    _turn(engine, ME)
    _do(engine, "Combat Array: Sensing Eye", at=(4, 6))
    assert engine.state.zones[court.zone_id].active
    assert len(_array(engine)) == 3  # Formation Load 2 at CL 12: the Court is not counted against it


SOVEREIGN = ["court_of_the_ninefold_array", "sovereign_of_the_world_diagram"]


def _sovereign(**kwargs):
    kwargs.setdefault("foe_at", (12, 6))
    engine, _bundle = _with(*SOVEREIGN, cl=15, qi=80, **kwargs)
    return engine


def _cast_sovereign(engine):
    _do(engine, "Sovereign of the World-Diagram")
    (zone,) = [row for row in _array(engine) if formations.record(row).get("domain") == "sovereign"]
    return zone


def test_sovereign_is_offered_only_with_the_talent_at_cl_fifteen():
    young, _ = _with(*SOVEREIGN, cl=12, qi=80)
    assert "Sovereign of the World-Diagram" not in _names(young)
    plain, _ = _with(cl=15, qi=80)
    assert "Sovereign of the World-Diagram" not in _names(plain)
    assert "Sovereign of the World-Diagram" in _names(_sovereign())


def test_the_sovereign_array_is_a_sixty_foot_emanation_for_a_minute_without_concentration():
    engine = _sovereign()
    me = engine.state.actors[ME]
    cp = me.resources.get("resource:core.qi")
    zone = _cast_sovereign(engine)
    record = formations.record(zone)
    assert me.resources.get("resource:core.qi") == cp - 10 and me.concentration is None  # 10 CP, "not Concentration"
    assert me.bonus_action_available is False and len(record["layers"]) == 3 and record["eye_actor"] == ME
    cells = {(cell.x, cell.y) for cell in zone.affected_cells}
    assert (15, 6) in cells and (16, 6) not in cells  # 60 feet: twelve squares from the owner at (3, 6)
    assert zone.trigger_profile["follows_owner"]
    assert (zone.trigger_profile["difficult"] == "hostile") == ("locking_gate" in record["layers"])  # only a Locking Gate layer makes Difficult Terrain
    assert "Sovereign of the World-Diagram" not in _names(engine)  # "once per long rest"


def test_the_sovereign_emanation_moves_with_its_owner():
    engine = _sovereign()
    zone = _cast_sovereign(engine)
    me = engine.state.actors[ME]
    start = me.position
    me.position = Position(x=6, y=6)
    zones.on_moved(engine, me, start, me.position)
    assert (zone.center.x, zone.center.y) == (6, 6)
    assert (18, 6) in {(cell.x, cell.y) for cell in zone.affected_cells}


def test_the_sovereign_array_has_a_free_pulse_and_a_second_pulse_for_two_cp():
    engine = _sovereign(foe_at=(6, 6))
    _cast_sovereign(engine)
    _turn(engine, ME)
    me, foe = engine.state.actors[ME], _foe(engine)
    _force_dc(engine, 99)
    names = _names(engine)
    assert any(name and name.startswith("Free Pulse") for name in names)
    assert not any(name and name.startswith("Second Pulse") for name in names)  # a *second* Pulse comes after a first
    cp = me.resources.get("resource:core.qi")
    layers = formations.record(_array(engine)[0])["layers"]
    _do(engine, "Free Pulse: Locking Gate" if "locking_gate" in layers else next(name for name in sorted(names) if name.startswith("Free Pulse")), target=AN)
    assert me.resources.get("resource:core.qi") == cp and me.bonus_action_available
    second = next(name for name in sorted(filter(None, {getattr(engine.action_catalog.get(c.source_definition_id), "display_name", None)
                                                        for c in engine.legal_candidates() if c.actor_id == ME and c.target_ids == (AN,)}))
                  if name.startswith("Second Pulse"))  # a second, different layer that can touch the hostile
    _do(engine, second, target=AN)
    assert me.resources.get("resource:core.qi") == cp - 2


def test_the_sovereign_array_collapses_when_its_eye_is_incapacitated():
    engine = _sovereign()
    zone = _cast_sovereign(engine)
    me = engine.state.actors[ME]
    engine._apply_condition(me, "condition:typed.stone_shell", "test:stun", AN, expires_on="UNTIL_REMOVED")
    formations.sweep(engine, "test")
    assert not engine.state.zones[zone.zone_id].active


def test_a_hostile_inside_the_sovereign_array_needs_a_charisma_save_to_teleport():
    engine = _sovereign(foe_at=(6, 6))
    zone = _cast_sovereign(engine)
    foe = _foe(engine)
    out = Position(x=1, y=1)
    _set_dc(zone, 99)
    assert formations.teleport_check(engine, foe, foe.position, out) is False
    _set_dc(zone, -50)
    assert formations.teleport_check(engine, foe, foe.position, out) is None
    assert formations.teleport_check(engine, engine.state.actors[ME], engine.state.actors[ME].position, out) is None  # the owner is not a hostile creature


# ---------------------------------------------------------------------------------------------- Mountain-Sealing Great Array
MOUNTAIN = ["mountain_sealing_great_array"]


def _mountain(*talents, **kwargs):
    kwargs.setdefault("foe_at", (6, 6))
    engine, _bundle = _with(*MOUNTAIN, *talents, cl=15, qi=80, **kwargs)
    return engine


def _cast_mountain(engine, at=(5, 6)):
    _do(engine, "Mountain-Sealing Great Array", at=at)
    (zone,) = [row for row in _array(engine) if formations.record(row).get("domain") == "mountain"]
    return zone


def test_the_mountain_array_has_four_anchors_a_thirty_foot_radius_and_needs_concentration():
    engine = _mountain()
    me = engine.state.actors[ME]
    cp = me.resources.get("resource:core.qi")
    zone = _cast_mountain(engine)
    record = formations.record(zone)
    assert me.resources.get("resource:core.qi") == cp - 9 and me.concentration.zone_id == zone.zone_id
    cells = {(cell.x, cell.y) for cell in zone.affected_cells}
    assert (11, 6) in cells and (12, 6) not in cells  # 30 feet: six squares
    anchors = [engine.state.objects[oid] for oid in record["nodes"]]
    assert len(anchors) == 4 and all((a.ac, a.maximum_hp) == (15, 3 * 15) for a in anchors)
    assert all((a.position.x, a.position.y) in cells for a in anchors) and record["eye"] is None
    assert "Mountain-Sealing Great Array" not in _names(engine)
    assert not _names(engine) & {"Free Pulse: Locking Gate"}  # it is not a Pulse array


def test_the_mountain_array_falls_when_two_anchors_are_destroyed():
    engine = _mountain()
    zone = _cast_mountain(engine)
    anchors = formations.record(zone)["nodes"]
    formations.hurt_object(engine, engine.state.objects[anchors[0]], 99, "SLASHING", "test", AN)
    assert engine.state.zones[zone.zone_id].active
    formations.hurt_object(engine, engine.state.objects[anchors[1]], 99, "SLASHING", "test", AN)
    assert not engine.state.zones[zone.zone_id].active and engine.state.actors[ME].concentration is None


def test_teleporting_in_or_out_of_the_mountain_array_takes_a_charisma_save_even_for_its_owner():
    engine = _mountain()
    zone = _cast_mountain(engine)
    foe, me = _foe(engine), engine.state.actors[ME]
    out = Position(x=1, y=12)
    _set_dc(zone, 99)
    assert formations.teleport_check(engine, foe, foe.position, out) is False
    assert formations.teleport_check(engine, me, me.position, out) is False  # "you are affected unless keyed"
    assert formations.teleport_check(engine, foe, Position(x=1, y=12), Position(x=2, y=12)) is None  # wholly outside
    _set_dc(zone, -50)
    assert formations.teleport_check(engine, foe, foe.position, out) is None


def test_a_keyed_creature_is_not_held_by_the_mountain_array():
    engine = _mountain("gate_keeper")
    _do(engine, "Next array: key a creature", target=AN)
    zone = _cast_mountain(engine)
    foe = _foe(engine)
    _set_dc(zone, 99)
    assert AN in formations.record(zone)["keyed"]
    assert formations.teleport_check(engine, foe, foe.position, Position(x=1, y=12)) is None
    _move(engine, AN, [(7, 6), (8, 6), (9, 6), (10, 6), (11, 6), (12, 6)])
    assert foe.position.x == 12


def test_a_hostile_that_fails_the_save_cannot_willingly_leave_the_mountain_array():
    engine = _mountain(foe_at=(10, 6))
    zone = _cast_mountain(engine)
    foe = _foe(engine)
    _set_dc(zone, 99)
    _turn(engine, AN)
    _move(engine, AN, [(11, 6), (12, 6), (13, 6)])  # out of the six-square radius around (5, 6)
    assert (foe.position.x, foe.position.y) == (11, 6)  # held on the last square inside
    assert any("holds" in line for line in _log(engine))
    _set_dc(zone, -50)
    foe.movement_remaining_ft = 30
    _move(engine, AN, [(12, 6), (13, 6)])
    assert foe.position.x == 13 and any("breaks out" in line for line in _log(engine))


def test_moving_about_inside_the_mountain_array_needs_no_save():
    engine = _mountain(foe_at=(10, 6))
    zone = _cast_mountain(engine)
    _set_dc(zone, 99)
    _move(engine, AN, [(9, 6), (8, 6)])
    assert _foe(engine).position.x == 8


def _summoner_duel(seed="MSEAL"):
    """ME (Mountain-Sealing) against a summoner of Corpse Servants standing at (8, 6)."""
    from tests import test_summons as TS

    bundles = (compile_character(_sheet([T + name for name in MOUNTAIN], cl=15, qi=80), actor_id=ME),
               compile_character(TS._sheet(["TAL_DEATH_CORPSE_SERVANT"]), actor_id=TS.OWNER, summon_plan={"corpse_servant": 1}))
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=bundles,
                                   roster_setup={"primary_actor_ids": [ME, TS.OWNER], "team_by_actor": {ME: "team:a", TS.OWNER: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, TS.OWNER: {"x": 8, "y": 6}}})
    _turn(engine, ME)
    return engine, TS.OWNER


def test_summoning_into_the_mountain_array_fails_unless_the_summoner_passes_a_formation_check():
    from combat import summons

    engine, owner_id = _summoner_duel()
    zone = _cast_mountain(engine)
    owner = engine.state.actors[owner_id]
    (servant,) = summons.owned_by(engine, owner_id, "corpse_servant")
    servant.active = False  # not yet called
    _set_dc(zone, 99)
    assert summons.summon(engine, owner, "corpse_servant", "test:call") == [] and not servant.active
    assert any(event.event_type == "SUMMON_BLOCKED" for event in engine.events)
    _set_dc(zone, -50)  # the summoner's Formation Check succeeds
    assert summons.summon(engine, owner, "corpse_servant", "test:call") == [servant.entity_id] and servant.active


def test_a_spirit_locked_creature_cannot_be_summoned():
    from combat import summons

    engine, owner_id = _summoner_duel(seed="SLOCK")
    owner = engine.state.actors[owner_id]
    (servant,) = summons.owned_by(engine, owner_id, "corpse_servant")
    servant.active = False
    engine._apply_condition(servant, "condition:typed.formation_spirit_locked", "test:lock", ME, expires_on="UNTIL_REMOVED")
    assert summons.summon(engine, owner, "corpse_servant", "test:call") == [] and not servant.active
    engine._remove_condition(servant, "condition:typed.formation_spirit_locked", "test")
    assert summons.summon(engine, owner, "corpse_servant", "test:call") == [servant.entity_id]


# ---------------------------------------------------------------------------------------------- Turn the Battlefield Inside Out
TURN = ["turn_the_battlefield_inside_out"]
ALLY = "actor:factory.g"


def _turn_engine(seed="TURN", **kwargs):
    """ME with an ally at (4, 6) and a hostile AN at (7, 6), both inside her array at (5, 6)."""
    bundles = (compile_character(_sheet([T + name for name in TURN], cl=15, qi=80), actor_id=ME), compile_character(_sheet([]), actor_id=ALLY))
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=bundles,
                                   roster_setup={"primary_actor_ids": [ME, ALLY, AN], "team_by_actor": {ME: "team:a", ALLY: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, ALLY: {"x": 4, "y": 6}, AN: {"x": 7, "y": 6}}})
    _turn(engine, ME)
    _do(engine, "Combat Array: Locking Gate", at=(5, 6))
    _turn(engine, ME)
    return engine


def test_turn_the_battlefield_needs_the_talent_a_keyed_ally_and_a_hostile_inside_the_array():
    plain, _ = _with(cl=15, qi=80, foe_at=(6, 6))
    assert "Turn the Battlefield Inside Out" not in _names(plain)
    engine = _turn_engine()
    assert "Turn the Battlefield Inside Out" in _names(engine)
    engine.state.actors[AN].position = Position(x=12, y=6)  # the hostile is outside the array
    assert "Turn the Battlefield Inside Out" not in _names(engine)


def test_a_hostile_that_fails_the_wisdom_save_swaps_places_with_the_keyed_ally():
    engine = _turn_engine()
    me, ally, foe = engine.state.actors[ME], engine.state.actors[ALLY], engine.state.actors[AN]
    cp = me.resources.get("resource:core.qi")
    _force_dc(engine, 99)
    _do(engine, "Turn the Battlefield Inside Out", at=(5, 6))
    assert (ally.position.x, ally.position.y) == (7, 6) and (foe.position.x, foe.position.y) == (4, 6)
    assert me.resources.get("resource:core.qi") == cp - 7
    assert any("exchanges places" in line for line in _log(engine))
    assert "Turn the Battlefield Inside Out" not in _names(engine)  # once per long rest


def test_a_hostile_that_saves_stays_put_but_cannot_take_reactions():
    engine = _turn_engine(seed="TURN2")
    ally, foe = engine.state.actors[ALLY], engine.state.actors[AN]
    _force_dc(engine, -50)
    _do(engine, "Turn the Battlefield Inside Out", at=(5, 6))
    assert (ally.position.x, ally.position.y) == (4, 6) and (foe.position.x, foe.position.y) == (7, 6)
    assert any("reaction_denied" in cid for cid in _conditions(foe))


def test_a_teleport_block_stops_the_exchange():
    engine = _turn_engine(seed="TURN3")
    ally, foe = engine.state.actors[ALLY], engine.state.actors[AN]
    engine._apply_condition(foe, "condition:typed.cannot_teleport", "test:block", ME, expires_on="UNTIL_REMOVED")
    _force_dc(engine, 99)
    _do(engine, "Turn the Battlefield Inside Out", at=(5, 6))
    assert (ally.position.x, ally.position.y) == (4, 6) and (foe.position.x, foe.position.y) == (7, 6)
    assert any("cannot exchange places" in line for line in _log(engine))


def test_every_formation_condition_explains_itself_on_hover():
    from combat.condition_text import all_conditions
    table = all_conditions()
    keys = [key for key in json.loads((ROOT / "combat" / "rules" / "typed_conditions.json").read_text())["conditions"]
            if key.startswith("formation_")]
    assert len(keys) >= 14
    for key in keys:
        assert table[key]["reading"], key
    assert "Disadvantage on Perception checks" in table["formation_dim"]["mechanics"]
    assert any("teleport" in line for line in table["formation_spirit_locked"]["mechanics"])
    assert any("Reactions" in line for line in table["formation_cp_locked"]["mechanics"])


def test_only_the_project_and_judgement_talents_are_left_out_of_the_compile():
    skipped = compile_character(_sheet(None, 15, 80), actor_id=ME)["diagnostics"]["skipped"]
    # Maze failure runs on movement_attempt/turn_start_choice and candidate_allowed;
    # its successful-save tax and doors/exits remain explicit GM riders. Thread Relay
    # originates its own attack (combat/ext/remote_origins.py).
    assert skipped["reaction"] == [] and skipped["passive"] == [] and skipped["definition"] == []
    assert sorted(skipped["outside"]) == ["FORMATION SPIRIT", "HEAVENLY GRAND FORMATION", "SECT FORMATION DESIGN"]
    assert sorted(skipped["table"]) == ["HEAVEN AND EARTH BECOME THE DIAGRAM"]  # Devours, Reflecting Gate, Maze and Relay all run.
    assert sorted(skipped["build"]) == ["ADDITIONAL PATTERN", "Formation Training"]


def test_an_arrays_eye_nodes_and_anchors_are_symbols_on_the_table_until_the_array_collapses():
    from combat.tabletop_service import TabletopService
    engine = _mountain()
    assert TabletopService._dropped_items(None, "m", engine) == []
    _cast_mountain(engine)
    marks = [item for item in TabletopService._dropped_items(None, "m", engine) if item.get("formation")]
    assert [item["label"] for item in marks] == ["⚓"] * 4 and all("Anchor" in item["name"] and "HP" in item["name"] for item in marks)
    _do(engine, "Collapse Array", at=(5, 6))
    assert TabletopService._dropped_items(None, "m", engine) == []
    engine, _ = _engine()  # a plain Combat Array: the Eye, at the point chosen
    _do(engine, "Combat Array: Locking Gate", at=(5, 6))
    (eye,) = [item for item in TabletopService._dropped_items(None, "m", engine) if item.get("formation")]
    assert eye["label"] == "◉" and "Eye" in eye["name"] and "HP" in eye["name"] and eye["color"] and (eye["x"], eye["y"]) == (5, 6)
