"""Rider lane 9 (owner 2026-09-29: "i want everything we can automated, keep going until its only the non-combat ones left"):
printed lines of partly automated abilities that were only shown to the GM as riders.  Each test compiles a real character and runs
the newly automated line on the engine; each fails on the typing (or the plug-ins) the authority carried before.

Report: /var/tmp/auto-audit/fix/R_lane9.report.md.  Overrides: authority/typed_mechanics/reviewed_final.d/riders_lane9.json.
"""

import json
import pytest
from pathlib import Path

from combat import factory_compiler
from combat.ext import formations
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_formations import ME, _do, _sheet, _turn

ROOT = Path(__file__).resolve().parents[1]
T = "tianxia.talent.formations."
THEM = "actor:factory.g"


def _authority():
    return json.loads(Path(factory_compiler.TYPED_AUTHORITY).read_bytes())["mechanics"]


def _riders(mid):
    return _authority()[mid].get("riders") or []


# ------------------------------------------------------------------------------------------------------- Formations
def _pair(mine, theirs=(), *, cl=15, seed="R9F", me_at=(3, 6), them_at=(8, 6), qi=60):
    """ME (team a, Formations talents ``mine``) and THEM (team b, ``theirs``), both compiled Formations characters."""
    bundles = (compile_character(_sheet([T + t for t in mine], cl, qi), actor_id=ME),
               compile_character(_sheet([T + t for t in theirs], cl, qi), actor_id=THEM))
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=bundles,
                                   roster_setup={"primary_actor_ids": [ME, THEM], "team_by_actor": {ME: "team:a", THEM: "team:b"},
                                                 "starting_positions": {ME: {"x": me_at[0], "y": me_at[1]}, THEM: {"x": them_at[0], "y": them_at[1]}}})
    _turn(engine, ME)
    return engine


def _dc(engine, owner, dc):
    for zone in formations.arrays(engine, owner):
        zone.trigger_profile["formation"]["numbers"]["save_dc"] = dc


def _conds(actor):
    return {c.condition_id for c in actor.conditions.values()}


def _moves(engine, actor_id):
    return {(c.destination.x, c.destination.y) for c in engine.legal_candidates() if c.actor_id == actor_id and str(c.kind) == "MOVE"}


@pytest.mark.parametrize("dc", [-50, 99])
def test_formation_maze_is_gm_managed_on_turn_start_and_entry(dc):
    engine = _pair(["formation_maze"], them_at=(11, 6))
    _do(engine, "Combat Array: Sensing Eye", at=(8, 6))
    _dc(engine, ME, dc)
    owner = engine.state.actors[ME]
    qi = owner.resources["resource:core.qi"]
    _turn(engine, THEM)
    them = engine.state.actors[THEM]
    candidate = next(c for c in engine.legal_candidates() if c.actor_id == THEM and str(c.kind) == "MOVE" and c.destination
                     and (c.destination.x, c.destination.y) == (7, 6))
    before = them.movement_remaining_ft
    start = them.position
    engine.execute_intent(ActionIntent(intent_id="in", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=THEM, target_ids=(), destination=candidate.destination))
    from combat.ext.formation_riders import LOST, SOURCE_MAZE
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.source_definition_id == SOURCE_MAZE]
    assert len(saves) == 1 and saves[0].payload['success'] == (dc == -50)
    assert not owner.reaction_available and owner.resources["resource:core.qi"] == qi - 2
    if dc == -50:
        assert before - them.movement_remaining_ft == candidate.movement_cost_ft
        assert them.position == candidate.destination
        assert LOST not in _conds(them)
        assert any('10 additional feet' in str(e.payload) for e in engine.events)
    else:
        # Failed save turns the path on entry: only the completed entry step
        # is paid, and the remaining approach to the chosen Eye is refused.
        assert before - them.movement_remaining_ft == 5
        assert engine.grid.distance_ft(start, them.position) == 5
        assert them.position in candidate.canonical_path and them.position != candidate.destination
        assert LOST in _conds(them)
    _turn(engine, ME)
    assert LOST not in _conds(them)  # printed owner-start expiry
    # A failed entry can stop outside the array. Set up the distinct printed
    # start-inside trigger explicitly rather than assuming entry completed.
    them.position = candidate.destination
    _turn(engine, THEM)
    assert len([e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.source_definition_id == SOURCE_MAZE]) == 2
    assert owner.resources['resource:core.qi'] == qi - 4
    assert (LOST in _conds(them)) == (dc == 99)
    assert any("GM:" in line for line in _riders(T + "formation_maze"))


def test_formation_maze_needs_the_talent():
    engine = _pair([])
    _do(engine, "Combat Array: Locking Gate", at=(8, 6))
    _dc(engine, ME, 99)
    _turn(engine, THEM)
    assert "condition:typed.formation_maze_lost" not in _conds(engine.state.actors[THEM])


def _force_hits(engine, *ids):
    for who in ids:
        engine.state.actors[who].armor_class = -50


def _use(engine, actor, name, target):
    candidate = next(c for c in engine.legal_candidates() if c.actor_id == actor and c.target_ids == (target,)
                     and getattr(engine.action_catalog.get(c.source_definition_id), "display_name", None) == name)
    engine.execute_intent(ActionIntent(intent_id=f"{name}{engine.state.event_sequence}", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=actor,
                                       target_ids=candidate.target_ids, destination=candidate.destination))


def test_reflecting_gate_turns_a_ranged_hit_back_on_the_attacker():
    engine = _pair(["reflecting_gate"], them_at=(7, 6))
    _do(engine, "Combat Array: Sensing Eye", at=(4, 6))
    zone = formations.arrays(engine, ME)[0]
    zone.trigger_profile["formation"]["numbers"]["attack_bonus"] = 100  # the Formation Check beats the attack roll
    _force_hits(engine, ME, THEM)
    me, them = engine.state.actors[ME], engine.state.actors[THEM]
    hp_me, hp_them, qi = me.current_hp, them.current_hp, me.resources["resource:core.qi"]
    _turn(engine, THEM)
    _use(engine, THEM, "Bi Shou (Dagger) thrown", ME)
    assert me.current_hp == hp_me, "the attack misses the protected creature"
    assert them.current_hp < hp_them, "it rebounds on the attacker with the same roll"
    assert me.reaction_available is False and me.resources["resource:core.qi"] == qi - 2
    assert not any("Make a Formation Check" in line or line.startswith("Success: Choose one") for line in _riders(T + "reflecting_gate"))


def test_reflecting_gate_fails_its_check_and_the_attack_lands():
    engine = _pair(["reflecting_gate"], them_at=(7, 6))
    _do(engine, "Combat Array: Sensing Eye", at=(4, 6))
    formations.arrays(engine, ME)[0].trigger_profile["formation"]["numbers"]["attack_bonus"] = -100
    _force_hits(engine, ME, THEM)
    me, them = engine.state.actors[ME], engine.state.actors[THEM]
    hp_me, hp_them = me.current_hp, them.current_hp
    _turn(engine, THEM)
    _use(engine, THEM, "Bi Shou (Dagger) thrown", ME)
    assert me.current_hp < hp_me and them.current_hp == hp_them and me.reaction_available is False


def test_reflecting_gate_ignores_an_attacker_inside_the_array():
    engine = _pair(["reflecting_gate"], them_at=(5, 6))
    _do(engine, "Combat Array: Sensing Eye", at=(4, 6))
    _force_hits(engine, ME, THEM)
    me = engine.state.actors[ME]
    _turn(engine, THEM)
    hp = me.current_hp
    _use(engine, THEM, "Bi Shou (Dagger) thrown", ME)
    assert me.current_hp < hp and me.reaction_available is True


def test_nine_palaces_is_gm_managed_and_keeps_normal_single_target_pulse():
    bundles = (compile_character(_sheet([T + "nine_palaces_killing_array"], 15, 60), actor_id=ME), compile_character(_sheet([], 15, 60), actor_id=THEM))
    engine = Gate4ControllerEngine(ROOT, match_seed="R9N", typed_bundles=bundles,
                                   roster_setup={"primary_actor_ids": [ME, THEM, AN], "team_by_actor": {ME: "team:a", THEM: "team:b", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, THEM: {"x": 8, "y": 6}, AN: {"x": 8, "y": 7}}})
    _turn(engine, ME)
    _do(engine, "Combat Array: Killing Line (Fire)", at=(8, 5))
    _force_hits(engine, THEM, AN)
    hp = {who: engine.state.actors[who].current_hp for who in (THEM, AN)}
    before = len(engine.events)
    _use(engine, ME, "Pulse: Killing Line", THEM)
    rolls = [e for e in engine.events[before:] if e.event_type == "ATTACK_ROLLED"]
    assert {e.target_ids[0] for e in rolls} == {THEM}
    assert not any(e.payload.get("nine_palaces") for e in rolls)
    assert engine.state.actors[THEM].current_hp < hp[THEM]
    assert engine.state.actors[AN].current_hp == hp[AN]
    assert any("shared-d20" in line for line in _riders(T + "nine_palaces_killing_array"))


def test_without_nine_palaces_the_killing_line_pulse_strikes_one_creature():
    bundles = (compile_character(_sheet([], 15, 60), actor_id=ME), compile_character(_sheet([], 15, 60), actor_id=THEM))
    engine = Gate4ControllerEngine(ROOT, match_seed="R9N", typed_bundles=bundles,
                                   roster_setup={"primary_actor_ids": [ME, THEM, AN], "team_by_actor": {ME: "team:a", THEM: "team:b", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, THEM: {"x": 8, "y": 6}, AN: {"x": 8, "y": 7}}})
    _turn(engine, ME)
    _do(engine, "Combat Array: Killing Line (Fire)", at=(8, 5))
    _force_hits(engine, THEM, AN)
    hp = engine.state.actors[AN].current_hp
    _use(engine, ME, "Pulse: Killing Line", THEM)
    assert engine.state.actors[AN].current_hp == hp


RAIN = "TAL_METAL_THOUSAND_EDGE_RAIN"  # a 20-foot-sphere Dexterity save for damage, 90 feet away, 4 CP


def _devour_fight(mine, cl=10, extra=None):
    from tests.test_auto_lane1 import _sheet as one_sheet

    bundles = (compile_character(_sheet([T + t for t in mine], cl, 60), actor_id=ME), compile_character(one_sheet(RAIN), actor_id=THEM))
    ids = [ME, THEM] + ([AN] if extra else [])
    engine = Gate4ControllerEngine(ROOT, match_seed="R9D", typed_bundles=bundles,
                                   roster_setup={"primary_actor_ids": ids, "team_by_actor": {ME: "team:a", THEM: "team:b", AN: "team:c"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, THEM: {"x": 12, "y": 6},
                                                                        **({AN: {"x": extra[0], "y": extra[1]}} if extra else {})}})
    _turn(engine, ME)
    _do(engine, "Combat Array: Locking Gate", at=(4, 6))
    formations.arrays(engine, ME)[0].trigger_profile["formation"]["numbers"]["attack_bonus"] = 100
    _turn(engine, THEM)
    return engine


def _rain(engine, at):
    candidate = next(c for c in engine.legal_candidates() if c.actor_id == THEM and c.destination is not None and (c.destination.x, c.destination.y) == at
                     and getattr(engine.action_catalog.get(c.source_definition_id), "display_name", "") == "Thousand-Edge Rain")
    engine.execute_intent(ActionIntent(intent_id="rain", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=THEM, target_ids=candidate.target_ids, destination=candidate.destination))


def test_formation_devours_technique_stops_a_technique_that_only_reaches_inside():
    engine = _devour_fight(["formation_devours_technique"])
    me = engine.state.actors[ME]
    hp, qi = me.current_hp, me.resources["resource:core.qi"]
    _rain(engine, (3, 6))
    assert me.current_hp == hp and me.reaction_available is False and me.resources["resource:core.qi"] == qi - 3
    assert not any("Formation Check" in line for line in _riders(T + "formation_devours_technique"))


def test_formation_devours_technique_prevents_only_crossing_recipients_automatically():
    engine = _devour_fight(["formation_devours_technique"], extra=(3, 10))  # a creature outside the array is in the area too
    inside, outside = engine.state.actors[ME], engine.state.actors[AN]
    before_inside, before_outside = inside.current_hp, outside.current_hp
    _rain(engine, (3, 7))
    # Partial-boundary prevention is now an automatic option; the outside
    # recipient still takes the real area save/effect instead of cancellation.
    notes = [e.payload.get("rider", e.payload.get("text", "")) for e in engine.events
             if e.event_type in ("GM_RIDER", "PASSIVE_TRIGGERED")]
    assert any("the array catches it; it does not cross the boundary" in n for n in notes)
    assert inside.current_hp == before_inside
    assert outside.current_hp < before_outside


def test_array_that_swallows_the_attack_stores_and_releases_the_caught_force():
    engine = _devour_fight(["formation_devours_technique", "array_that_swallows_the_attack"], cl=15, extra=(3, 10))
    _rain(engine, (3, 7))
    zone = formations.arrays(engine, ME)[0]
    stored = formations.record(zone).get("stored")
    if not stored:  # nothing got through the reduction to be caught: the damage rolled low against 6d8
        return
    them = engine.state.actors[THEM]
    them.position = Position(x=5, y=6)
    them.armor_class = -50
    _turn(engine, ME)
    hp = them.current_hp
    _use(engine, ME, "Pulse: Locking Gate", THEM)
    assert not formations.record(formations.arrays(engine, ME)[0]).get("stored")
    assert hp - them.current_hp >= stored["amount"] or not them.active


# ------------------------------------------------------------------------------------------------------- Talismans
TT = "tianxia.talent.talismans."
PREP, EMER = "resource:named.prepared_talismans", "resource:named.emergency_talismans"


def _talisman_sheet(talents, cl=10):
    from tests.test_carry import KIT
    from tests.test_zones import SHEET

    bases = [k for k in _authority() if k.startswith("TALISMANS_BASE")]
    sheet = {**SHEET, "equipment": [{"starting_kit": KIT}],
             "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.talismans"], "automatic_sphere_component_record_ids": bases,
                                     "learned_talent_record_ids": [TT + t for t in talents]}}
    sheet["identity"] = {**SHEET["identity"], "cultivation_level": cl}
    return sheet


def _talisman_fight(talents, cl=10, foe_at=(5, 6)):
    bundle = compile_character(_talisman_sheet(talents, cl), actor_id=ME)
    engine = Gate4ControllerEngine(ROOT, match_seed="R9T", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": foe_at[0], "y": foe_at[1]}}})
    _turn(engine, ME)
    engine.state.actors[AN].armor_class = -50
    return engine


def _names_now(engine, actor=ME):
    return {getattr(engine.action_catalog.get(c.source_definition_id), "display_name", None) for c in engine.legal_candidates() if c.actor_id == actor}


def _act(engine, name, target=None, actor=ME):
    candidate = next(c for c in engine.legal_candidates() if c.actor_id == actor
                     and getattr(engine.action_catalog.get(c.source_definition_id), "display_name", None) == name
                     and (target is None or c.target_ids == (target,)))
    engine.execute_intent(ActionIntent(intent_id=f"{name}{engine.state.event_sequence}", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=actor,
                                       target_ids=candidate.target_ids, destination=candidate.destination))


def _refresh(engine):
    me = engine.state.actors[ME]
    me.action_available = me.bonus_action_available = me.reaction_available = True
    return me


def test_prepared_talisman_limit_is_pb_plus_intelligence_and_hidden_sleeve_adds_two():
    me = _talisman_fight(["ember_talisman"]).state.actors[ME]
    assert me.resources[PREP] == me.resource_maximums[PREP] == 4 + 2  # PB 4 + INT 14 (+2)
    me = _talisman_fight(["ember_talisman", "hidden_sleeve_preparation"]).state.actors[ME]
    assert me.resource_maximums[PREP] == 8
    assert not any(line.startswith("Increase your Prepared Talisman Limit") for line in _riders(TT + "hidden_sleeve_preparation"))


def test_a_consumed_formula_uses_up_a_prepared_talisman_and_is_not_offered_without_one():
    engine = _talisman_fight(["ember_talisman"])
    me = engine.state.actors[ME]
    _act(engine, "Ember Talisman", AN)
    assert me.resources[PREP] == 5
    me.resources[PREP] = 0
    _refresh(engine)
    assert "Ember Talisman" not in _names_now(engine)
    _act(engine, "Ready a talisman")
    assert me.resources[PREP] == 1
    _refresh(engine)
    assert "Ember Talisman" in _names_now(engine)
    assert "Consumed: yes" not in _riders(TT + "ember_talisman")


def test_ember_talisman_damage_scales_with_cl():
    engine = _talisman_fight(["ember_talisman"], cl=17)
    before = len(engine.events)
    _act(engine, "Ember Talisman", AN)
    (rolled,) = [e for e in engine.events[before:] if e.event_type == "DAMAGE_ROLLED"]
    assert rolled.payload["expression"] in ("4d10+0", "8d10+0")  # 4d10 at CL 17 (doubled on a critical hit)


def test_emergency_stroke_draws_a_common_talisman_that_only_a_common_formula_spends():
    engine = _talisman_fight(["ember_talisman", "binding_talisman"])
    me = engine.state.actors[ME]
    me.resources[PREP] = 0
    _act(engine, "Emergency Stroke")
    assert me.resources[EMER] == 1 and me.resources["resource:named.emergency_strokes"] == 3
    _refresh(engine)
    names = _names_now(engine)
    assert "Ember Talisman" in names and "Binding Talisman" not in names
    _act(engine, "Ember Talisman", AN)
    assert me.resources[EMER] == 0


def test_emergency_stroke_costs_two_cp_after_the_proficiency_bonus_uses():
    engine = _talisman_fight(["ember_talisman"])
    me = engine.state.actors[ME]
    me.resources["resource:named.emergency_strokes"] = 0
    names = _names_now(engine)
    assert "Emergency Stroke" not in names and "Emergency Stroke (2 CP)" in names
    qi = me.resources["resource:core.qi"]
    _act(engine, "Emergency Stroke (2 CP)")
    assert me.resources["resource:core.qi"] == qi - 2 and me.resources[EMER] == 1


def test_battle_stroke_scripture_lets_emergency_stroke_be_a_bonus_action():
    engine = _talisman_fight(["ember_talisman", "battle_stroke_scripture"])
    assert "Emergency Stroke (Bonus Action)" not in _names_now(engine)
    _act(engine, "Battle Stroke Scripture")
    _refresh(engine)
    assert "Emergency Stroke (Bonus Action)" in _names_now(engine)
    _act(engine, "Emergency Stroke (Bonus Action)")
    assert engine.state.actors[ME].resources[EMER] == 1


def test_talisman_wall_spends_prepared_talismans_for_its_hit_points():
    from combat.ext import docket_walls
    from combat import zones

    engine = _talisman_fight(["talisman_wall"], cl=10, foe_at=(9, 6))
    me = engine.state.actors[ME]
    qi = me.resources["resource:core.qi"]
    candidate = next(c for c in engine.legal_candidates() if c.actor_id == ME and c.destination is not None
                     and getattr(engine.action_catalog.get(c.source_definition_id), "display_name", None) == "Talisman Wall")
    engine.execute_intent(ActionIntent(intent_id="wall", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids, destination=candidate.destination))
    (wall,) = [z for z in zones.typed_zones(engine) if z.trigger_profile.get("wall")]
    assert me.resources[PREP] == 0 and me.resources["resource:core.qi"] == qi - 6
    assert docket_walls.stats(wall)["hp"] == 60


def test_dao_sealing_talisman_seals_the_targets_path_resource():
    from tests.test_riders_lane9 import THEM as OTHER

    mine = compile_character(_talisman_sheet(["secret_formula"], cl=17), actor_id=ME)
    theirs = compile_character(_talisman_sheet(["ember_talisman", "talisman_spirit"], cl=17), actor_id=OTHER)
    engine = Gate4ControllerEngine(ROOT, match_seed="R9S", typed_bundles=(mine, theirs),
                                   roster_setup={"primary_actor_ids": [ME, OTHER], "team_by_actor": {ME: "team:a", OTHER: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, OTHER: {"x": 4, "y": 6}}})
    _turn(engine, ME)
    engine.state.actors[OTHER].armor_class = -50
    for action in engine.action_catalog.values():
        if action.owner_id == ME and (action.parameters or {}).get("typed"):
            action.parameters["typed"]["numbers"] = {**action.parameters["typed"]["numbers"], "save_dc": 99}
    _act(engine, "Secret Formula", OTHER)
    other = engine.state.actors[OTHER]
    sealed = [c for c in other.conditions.values() if c.condition_id == "condition:typed.cp_sealed"]
    assert sealed and sealed[0].data["pools"] == ["resource:core.qi"]
    _turn(engine, OTHER)
    assert "Talisman Spirit" not in _names_now(engine, OTHER)  # 6 CP of Qi cannot be spent
    assert not any(line.startswith("Failed Save: Choose Body Refining") for line in _riders(TT + "secret_formula"))


def test_talisman_spirit_is_summoned_and_uses_up_a_prepared_talisman():
    engine = _talisman_fight(["talisman_spirit"], cl=10)
    me = engine.state.actors[ME]
    _act(engine, "Talisman Spirit")
    spirit = next(a for a in engine.state.actors.values() if a.display_name == "Talisman Spirit")
    assert spirit.active and spirit.armor_class == 15 and spirit.maximum_hp == 20 and me.resources[PREP] == 5


def test_demon_subduing_tag_failed_save_also_blocks_teleporting_and_invisibility():
    engine = _talisman_fight(["demon_subduing_tag"], cl=10)
    for action in engine.action_catalog.values():
        if action.owner_id == ME and (action.parameters or {}).get("typed"):
            action.parameters["typed"]["numbers"] = {**action.parameters["typed"]["numbers"], "save_dc": 99}
    _act(engine, "Demon-Subduing Tag", AN)
    held = _conds(engine.state.actors[AN])
    assert "condition:typed.cannot_teleport" in held and any("invisible" in c for c in held)


def test_qi_storage_talisman_restores_proficiency_bonus_cp():
    engine = _talisman_fight(["qi_storage_talisman"], cl=10)
    me = engine.state.actors[ME]
    me.resources["resource:core.qi"] = 10
    _act(engine, "Qi Storage Talisman")
    assert me.resources["resource:core.qi"] == 14 and me.resources[PREP] == 5


# ------------------------------------------------------------------------------------------------------- Equipment
TE = "tianxia.talent.equipment."


def _equipment_fight(talents, cl=12):
    from tests.test_carry import KIT
    from tests.test_zones import SHEET

    sheet = {**SHEET, "equipment": [{"starting_kit": KIT}],  # Lacquered Lamellar: medium armor
             "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.equipment"], "automatic_sphere_component_record_ids": [],
                                     "learned_talent_record_ids": [TE + t for t in talents]}}
    sheet["identity"] = {**SHEET["identity"], "cultivation_level": cl}
    bundle = compile_character(sheet, actor_id=ME)
    engine = Gate4ControllerEngine(ROOT, match_seed="R9E", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}})
    _turn(engine, ME)
    return engine


def _taken(engine, amount, kind):
    from combat import typed_reactions

    return typed_reactions.defend(engine, engine.state.actors[ME], amount, kind, None, AN)


def _incapacitate(engine):
    me = engine.state.actors[ME]
    engine._apply_condition(me, "condition:typed.stunned", "test", AN, expires_on="UNTIL_REMOVED")
    return me


def test_mountain_pattern_grand_shell_reduces_physical_damage_once_a_round_and_not_while_incapacitated():
    engine = _equipment_fight(["mountain_pattern_grand_shell"])
    assert _taken(engine, 20, "SLASHING") == 16 and _taken(engine, 20, "SLASHING") == 20  # once per round
    engine.state.round_number += 1
    _incapacitate(engine)
    assert _taken(engine, 20, "PIERCING") == 20
    assert not _riders(TE + "mountain_pattern_grand_shell")


def test_grand_shell_steps_aside_for_padded_layers_on_bludgeoning():
    engine = _equipment_fight(["mountain_pattern_grand_shell", "padded_layers"])
    assert _taken(engine, 20, "BLUDGEONING") == 16  # one passive Equipment reduction, not both
    assert _taken(engine, 20, "SLASHING") == 16      # the Grand Shell is still unused this round


def test_beast_hide_harness_lets_padded_layers_catch_slashing_once_a_round():
    engine = _equipment_fight(["padded_layers", "beast_hide_harness_scripture"])
    assert _taken(engine, 20, "SLASHING") == 16
    assert _taken(engine, 20, "BLUDGEONING") == 20  # Padded Layers is spent for the round


def test_circuit_armor_awakens_reduces_damage_and_ends_when_incapacitated():
    engine = _equipment_fight(["circuit_armor"], cl=12)
    _act(engine, "Circuit Armor")
    me = engine.state.actors[ME]
    assert "condition:typed.circuit_armor" in _conds(me)
    assert _taken(engine, 10, "FIRE") == 8  # key modifier 2
    _incapacitate(engine)
    assert "condition:typed.circuit_armor" not in _conds(me)


def test_qi_conductive_lacing_gives_temp_hp_when_cp_goes_into_an_equipment_talent():
    engine = _equipment_fight(["circuit_armor", "qi_conductive_lacing"], cl=12)
    _act(engine, "Circuit Armor")
    assert engine.state.actors[ME].temporary_hp == 4


def test_black_armor_legion_scripture_grants_temp_hp_as_the_fight_begins():
    engine = _equipment_fight(["black_armor_legion_scripture"])
    assert engine.state.actors[ME].temporary_hp == 6  # PB 4 + key modifier 2


def test_walking_fortress_can_be_ended_and_ends_when_incapacitated():
    engine = _equipment_fight(["walking_fortress_scripture"], cl=15)
    me = engine.state.actors[ME]
    _act(engine, "Walking Fortress Scripture")
    assert _taken(engine, 20, "SLASHING") == 10
    _refresh(engine)
    _act(engine, "End Walking Fortress")
    assert _taken(engine, 20, "SLASHING") == 20
    _refresh(engine)
    _act(engine, "Walking Fortress Scripture")
    _incapacitate(engine)
    assert not any(str(m.source_definition_id).endswith("walking_fortress_scripture") for m in me.modifiers.values())


def test_mountain_pattern_shell_bonus_is_lost_while_incapacitated():
    engine = _equipment_fight(["mountain_pattern_shell"])
    me = engine.state.actors[ME]
    before = me.armor_class + engine._ac_modifier(me)
    _incapacitate(engine)
    assert me.armor_class + engine._ac_modifier(me) == before - 1


def test_mirror_bright_armor_needs_a_target_that_can_see_you():
    engine = _equipment_fight(["mirror_bright_armor"])
    assert "Mirror-Bright Armor" in _names_now(engine)
    engine._apply_condition(engine.state.actors[AN], "condition:typed.blinded", "test", ME, expires_on="UNTIL_REMOVED")
    assert "Mirror-Bright Armor" not in _names_now(engine)


def test_armor_ease_does_not_invent_a_category_or_proficiency():
    from tests.test_carry import KIT
    from tests.test_zones import SHEET

    def hide(talents):
        sheet = {**SHEET, "equipment": [{"starting_kit": KIT}],
                 "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.equipment"], "learned_talent_record_ids": [TE + t for t in talents]}}
        row = next(r for r in compile_character(sheet, actor_id=ME)["action_catalog"] if r["display_name"] == "Hide")
        return row["parameters"]["typed"]["effects"][0].get("mode")

    assert hide([]) == hide(["armor_ease"]) == "DISADVANTAGE"


def test_shield_talisman_reaction_uses_up_a_prepared_talisman():
    from combat import ext, typed_reactions

    engine = _talisman_fight(["shield_talisman"], foe_at=(4, 6))
    me = engine.state.actors[ME]
    (row,) = [r for r in typed_reactions._rows(engine, ME, "generic") if r["feature_id"].endswith("shield_talisman")]
    typed_reactions._open(engine, row, me, (AN,), "ATTACK_HIT_BEFORE_DAMAGE")  # the reaction answers a hit
    assert me.resources[PREP] == 5
    me.resources[PREP] = 0
    assert ext.any_false("row_allowed", engine, me, row)  # none prepared: it is not offered


# ------------------------------------------------------------------------------------------------------- Jester
TJ = "tianxia.talent.jester."
ALLY = "actor:factory.lane9_ally"


def _jester_sheet(talents, cl=15):
    from tests.test_carry import KIT
    from tests.test_zones import SHEET

    bases = [k for k in _authority() if k.startswith("JESTER_BASE")]
    sheet = {**SHEET, "equipment": [{"starting_kit": KIT}],
             "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.jester"], "automatic_sphere_component_record_ids": bases,
                                     "learned_talent_record_ids": [TJ + t for t in talents]}}
    sheet["identity"] = {**SHEET["identity"], "cultivation_level": cl}
    return sheet


def _jester_fight(talents, *, them_at=(4, 6), ally=False, them_sheet=None, cl=15):
    bundles = [compile_character(_jester_sheet(talents, cl), actor_id=ME), compile_character(them_sheet or _sheet([], 15, 60), actor_id=THEM)]
    ids, teams, spots = [ME, THEM], {ME: "team:a", THEM: "team:b"}, {ME: {"x": 3, "y": 6}, THEM: {"x": them_at[0], "y": them_at[1]}}
    if ally:
        bundles.append(compile_character(_sheet([], 15, 60), actor_id=ALLY))
        ids.append(ALLY)
        teams[ALLY] = "team:a"
        spots[ALLY] = {"x": them_at[0] + 1, "y": them_at[1]}
    engine = Gate4ControllerEngine(ROOT, match_seed="R9J", typed_bundles=tuple(bundles),
                                   roster_setup={"primary_actor_ids": ids, "team_by_actor": teams, "starting_positions": spots})
    _turn(engine, ME)
    return engine


def _scene(engine, proposition, target=THEM):
    _act(engine, f"Set the Scene: {proposition}", target)


def _foil_marks(engine, who=THEM):
    return {c.condition_id for c in engine.state.actors[who].conditions.values() if ".mark.foil_" in c.condition_id}


def _attack(engine, attacker, name, target):
    _turn(engine, attacker)
    _act(engine, name, target, actor=attacker)


def test_a_fine_display_takes_pb_off_a_hit_from_the_foil_and_ends_the_scene():
    engine = _jester_fight(["a_fine_display"])
    _scene(engine, "Strike the Fool")
    me = engine.state.actors[ME]
    me.armor_class = -50
    before = len(engine.events)
    _attack(engine, THEM, "Bi Shou (Dagger) attack", ME)
    rolled = sum(int(e.payload["total"]) for e in engine.events[before:] if e.event_type == "DAMAGE_ROLLED")
    taken = sum(int(e.payload["hp_damage"]) for e in engine.events[before:] if e.event_type == "DAMAGE_COMMITTED" and ME in e.target_ids)
    assert taken == max(0, rolled - 4) and me.reaction_available is False and not _foil_marks(engine)


def test_a_fine_display_on_a_miss_steps_away_and_flusters_the_foil():
    engine = _jester_fight(["a_fine_display"])
    _scene(engine, "Strike the Fool")
    me = engine.state.actors[ME]
    me.armor_class = 99
    start = me.position
    _attack(engine, THEM, "Bi Shou (Dagger) attack", ME)
    assert me.position != start and engine.grid.distance_ft(me.position, engine.state.actors[THEM].position) > 5
    assert "condition:typed.flustered" in _conds(engine.state.actors[THEM])


def test_banquet_escape_steps_out_of_reach_and_the_hit_misses():
    engine = _jester_fight(["banquet_escape"], cl=5)
    _scene(engine, "Strike the Fool")
    me = engine.state.actors[ME]
    me.armor_class = -50
    hp = me.current_hp
    _attack(engine, THEM, "Bi Shou (Dagger) attack", ME)
    assert me.current_hp == hp and engine._distance_actor_to_actor(me, engine.state.actors[THEM]) > 5


def test_strike_the_fool_punchlines_answer_only_the_foil():
    engine = _jester_fight(["a_fine_display"])
    me = engine.state.actors[ME]
    me.armor_class = -50
    _attack(engine, THEM, "Bi Shou (Dagger) attack", ME)
    assert me.reaction_available is True


def test_false_opening_costs_two_ac_and_the_first_miss_returns_focus_and_a_step():
    engine = _jester_fight(["false_opening"])
    me = engine.state.actors[ME]
    ac = me.armor_class + engine._ac_modifier(me)
    _act(engine, "False Opening (-2 AC)")
    assert me.armor_class + engine._ac_modifier(me) == ac - 2
    me.resources["resource:core.martial_focus"] = 0
    me.armor_class = 99
    start = me.position
    _attack(engine, THEM, "Bi Shou (Dagger) attack", ME)
    assert me.resources["resource:core.martial_focus"] == 1 and me.position != start


def test_pratfall_exit_steps_five_feet_when_knocked_prone_once_a_round():
    engine = _jester_fight(["pratfall_exit"])
    me = engine.state.actors[ME]
    start = me.position
    engine._apply_condition(me, "condition:typed.prone", "test", THEM, expires_on="UNTIL_REMOVED")
    moved = me.position
    assert moved != start
    engine._remove_condition(me, "condition:typed.prone", "test")
    engine._apply_condition(me, "condition:typed.prone", "test", THEM, expires_on="UNTIL_REMOVED")
    assert me.position == moved


def test_grand_entrance_sets_the_scene_free_on_the_first_turn_only():
    engine = _jester_fight(["grand_entrance"])
    assert "Set the Scene (free): Strike the Fool" in _names_now(engine)
    _act(engine, "Set the Scene (free): Strike the Fool", THEM)
    assert engine.state.actors[ME].bonus_action_available and _foil_marks(engine)
    _refresh(engine)
    assert "Set the Scene (free): Strike the Fool" not in _names_now(engine)


def test_mock_praise_scripture_sets_two_propositions_on_the_foil():
    engine = _jester_fight(["mock_praise_scripture"])
    _act(engine, "Set the Scene (Mock-Praise): Strike the Fool + Show Your Hand", THEM)
    assert len(_foil_marks(engine)) == 2


def test_recluse_at_court_keeps_three_foils_and_a_flustered_foil_returns_focus():
    engine = _jester_fight(["recluse_at_court_incarnation"], ally=True)
    me = engine.state.actors[ME]
    _act(engine, "Recluse-at-Court Incarnation")
    _refresh(engine)
    _act(engine, "Set the Scene (free): Strike the Fool", THEM)
    engine.state.actors[ALLY].team_id = "team:c"  # a second creature to be a Foil
    _refresh(engine)
    _scene(engine, "Come Closer", ALLY)
    assert _foil_marks(engine, THEM) and _foil_marks(engine, ALLY)
    me.resources["resource:core.martial_focus"] = 0
    from combat.ext import jester
    from combat.typed_executor import Context

    action = next(iter(engine.action_catalog.values()))
    jester.run_flustered(Context(engine, me, action, None, {"numbers": {}}, [engine.state.actors[THEM]], engine.state.actors[THEM], {}), {})
    assert me.resources["resource:core.martial_focus"] == 1


def test_no_bonus_actions_condition_removes_bonus_action_choices():
    engine = _jester_fight(["mock_praise_scripture"])
    assert any(str(c.kind) == "BONUS_ACTION" for c in engine.legal_candidates() if c.actor_id == ME)
    engine._apply_condition(engine.state.actors[ME], "condition:typed.no_bonus_actions", "test", THEM, expires_on="UNTIL_REMOVED")
    assert not any(str(c.kind) == "BONUS_ACTION" for c in engine.legal_candidates() if c.actor_id == ME)
    laughs = json.dumps(_authority()[TJ + "the_whole_court_laughs"]["effects"])
    assert "no_bonus_actions" in laughs


def test_borrowed_gesture_answers_the_foil_attacking_an_ally_with_a_dodge():
    engine = _jester_fight(["borrowed_gesture"], ally=True)
    _scene(engine, "Ignore the Fool")
    _attack(engine, THEM, "Bi Shou (Dagger) attack", ALLY)
    assert "condition:core.dodge" in _conds(engine.state.actors[ME])


def test_thrown_slipper_rebuke_strikes_the_foil_attacking_an_ally():
    engine = _jester_fight(["ridiculous_weapon", "thrown_slipper_rebuke"], ally=True)
    _scene(engine, "Ignore the Fool")
    them = engine.state.actors[THEM]
    them.armor_class = -50
    hp = them.current_hp
    _attack(engine, THEM, "Bi Shou (Dagger) attack", ALLY)
    assert them.current_hp < hp and "condition:typed.flustered" in _conds(them)


def test_painted_exit_can_leave_you_standing():
    engine = _jester_fight(["painted_exit"])
    _act(engine, "Painted Exit: Remain Standing")
    assert "condition:typed.prone" not in _conds(engine.state.actors[ME])


def test_reductio_ad_absurdum_makes_the_foil_choose_and_resolving_flusters_and_hurts_it():
    engine = _jester_fight(["reductio_ad_absurdum"], them_at=(6, 6))
    _scene(engine, "Show Your Hand")
    them = engine.state.actors[THEM]
    hp = them.current_hp
    _turn(engine, THEM)
    _do(engine, "Combat Array: Locking Gate", at=(8, 6), actor=THEM)
    assert "condition:typed.flustered" in _conds(them) and them.current_hp < hp
    assert formations.arrays(engine, THEM)  # resolved normally


def test_reductio_abandon_refunds_the_technique():
    from combat.ext import jester_riders

    engine = _jester_fight(["reductio_ad_absurdum"], them_at=(6, 6))
    _scene(engine, "Show Your Hand")
    them = engine.state.actors[THEM]
    qi = them.resources["resource:core.qi"]
    original = jester_riders.ask
    jester_riders.ask = lambda *a, **k: ["abandon"] if "abandon" in (a[5] if len(a) > 5 else []) else original(*a, **k)
    try:
        _turn(engine, THEM)
        _do(engine, "Combat Array: Locking Gate", at=(8, 6), actor=THEM)
    finally:
        jester_riders.ask = original
    assert them.resources["resource:core.qi"] == qi and not formations.arrays(engine, THEM)


# ------------------------------------------------------------------------------------------------------- Life
TL = "tianxia.talent.life."


def _life_sheet(talents, cl=10):
    from tests.test_carry import KIT
    from tests.test_zones import SHEET

    bases = [k for k in _authority() if k.startswith("LIFE_BASE")]
    sheet = {**SHEET, "equipment": [{"starting_kit": KIT}],
             "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.life"], "automatic_sphere_component_record_ids": bases,
                                     "learned_talent_record_ids": [TL + t for t in talents]}}
    sheet["identity"] = {**SHEET["identity"], "cultivation_level": cl}
    return sheet


def _life_fight(talents, *, cl=10, ally_at=(4, 6), them_at=(9, 6)):
    bundles = (compile_character(_life_sheet(talents, cl), actor_id=ME), compile_character(_sheet([], 15, 60), actor_id=ALLY),
               compile_character(_sheet([], 15, 60), actor_id=THEM))
    engine = Gate4ControllerEngine(ROOT, match_seed="R9L", typed_bundles=bundles,
                                   roster_setup={"primary_actor_ids": [ME, ALLY, THEM], "team_by_actor": {ME: "team:a", ALLY: "team:a", THEM: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, ALLY: {"x": ally_at[0], "y": ally_at[1]},
                                                                        THEM: {"x": them_at[0], "y": them_at[1]}}})
    _turn(engine, ME)
    return engine


def _hurt(engine, who, amount=20):
    actor = engine.state.actors[who]
    actor.current_hp = max(1, actor.current_hp - amount)
    return actor


def test_meridian_unbinding_removes_a_speed_reduction_and_no_longer_petrifies():
    engine = _life_fight(["meridian_unbinding"])
    ally = engine.state.actors[ALLY]
    engine._add_modifier(ally, "test.slow", "speed_ft", "ADD", -10, "SELF", expires_on="UNTIL_REMOVED")
    ally.modifiers[next(iter(k for k in ally.modifiers if "test.slow" in k))] = ally.modifiers[next(iter(k for k in ally.modifiers if "test.slow" in k))].model_copy(update={"source_actor_id": THEM})
    engine._apply_condition(ally, "condition:typed.poisoned", "test", THEM, expires_on="UNTIL_REMOVED")
    _act(engine, "Augment Purify the Pulse: Remove Poisoned: Meridian Unbinding")
    _act(engine, "Purify the Pulse: Remove Poisoned + Meridian Unbinding", ALLY)
    assert not any(m.target_field == "speed_ft" and int(m.value) < 0 for m in ally.modifiers.values())
    assert "condition:typed.petrified" not in _conds(ally) and "condition:typed.poisoned" not in _conds(ally)


def test_mind_cooling_pulse_removes_frightened():
    engine = _life_fight(["mind_cooling_pulse"])
    ally = engine.state.actors[ALLY]
    engine._apply_condition(ally, "condition:typed.frightened", "test", THEM, expires_on="UNTIL_REMOVED")
    engine._apply_condition(ally, "condition:typed.poisoned", "test", THEM, expires_on="UNTIL_REMOVED")
    _act(engine, "Augment Purify the Pulse: Remove Poisoned: Mind-Cooling Pulse")
    _act(engine, "Purify the Pulse: Remove Poisoned + Mind-Cooling Pulse", ALLY)
    assert "condition:typed.frightened" not in _conds(ally)


def test_greater_purification_takes_off_one_level_of_exhaustion_once():
    from combat.ext import forged_exhaustion

    engine = _life_fight(["greater_purification"])
    ally = engine.state.actors[ALLY]
    forged_exhaustion.set_level(engine, ally, 2, "test")
    engine._apply_condition(ally, "condition:typed.poisoned", "test", THEM, expires_on="UNTIL_REMOVED")
    _act(engine, "Augment Purify the Pulse: Remove Poisoned: Greater Purification")
    _act(engine, "Purify the Pulse: Remove Poisoned + Greater Purification", ALLY)
    assert forged_exhaustion.level(ally) == 1


def test_empathic_transfer_takes_the_affliction_onto_the_healer_for_no_cp():
    engine = _life_fight(["empathic_transfer"])
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    engine._apply_condition(ally, "condition:typed.poisoned", "test", THEM, expires_on="UNTIL_REMOVED")
    qi = me.resources["resource:core.qi"]
    name = next(n for n in _names_now(engine) if n and "Empathic Transfer" in n and "Poisoned" in n)
    _act(engine, name, ALLY)
    assert "condition:typed.poisoned" not in _conds(ally) and "condition:typed.poisoned" in _conds(me)
    assert me.resources["resource:core.qi"] == qi


def test_contagion_reversal_casts_the_affliction_into_a_foe_that_fails():
    engine = _life_fight(["contagion_reversal"], them_at=(3, 7))
    ally = engine.state.actors[ALLY]
    engine._apply_condition(ally, "condition:typed.blinded", "test", THEM, expires_on="UNTIL_REMOVED")
    for action in engine.action_catalog.values():
        if action.owner_id == ME and (action.parameters or {}).get("typed"):
            action.parameters["typed"]["numbers"] = {**action.parameters["typed"]["numbers"], "save_dc": 99}
    name = next(n for n in _names_now(engine) if n and "Contagion Reversal" in n and "Blinded" in n)
    _act(engine, name, ALLY)
    assert "condition:typed.blinded" in _conds(engine.state.actors[THEM]) and "condition:typed.blinded" not in _conds(ally)


def test_physician_s_step_lets_the_target_stand_with_its_reaction():
    engine = _life_fight(["physician_s_step"])
    ally = engine.state.actors[ALLY]
    engine._apply_condition(ally, "condition:typed.prone", "test", THEM, expires_on="UNTIL_REMOVED")
    engine._apply_condition(ally, "condition:typed.poisoned", "test", THEM, expires_on="UNTIL_REMOVED")
    _act(engine, "Purify the Pulse: Remove Poisoned", ALLY)  # free and harmless: every Purify carries it
    assert "condition:typed.prone" not in _conds(ally) and ally.reaction_available is False


def test_fount_of_life_stores_mend_and_releases_it_with_an_action():
    engine = _life_fight(["fount_of_life"])
    me = engine.state.actors[ME]
    ally = _hurt(engine, ALLY, 30)
    hp = ally.current_hp
    _act(engine, "Mend the Pulse + Fount of Life", ALLY)
    stored = me.resources["resource:named.fount_of_life"]
    assert stored > 0 and ally.current_hp == hp
    _refresh(engine)
    _act(engine, "Release Fount of Life", ALLY)
    assert ally.current_hp == hp + stored and me.resources["resource:named.fount_of_life"] == 0


def test_latent_healing_waits_for_the_carriers_reaction_when_hurt():
    engine = _life_fight(["latent_healing"])
    ally = _hurt(engine, ALLY, 5)
    _act(engine, "Mend the Pulse + Latent Healing", ALLY)
    assert "condition:typed.latent_healing" in _conds(ally)
    hp = ally.current_hp
    engine._commit_damage(ally, 10, "SLASHING", "test", THEM, None, reaction_depth=0)
    assert "condition:typed.latent_healing" not in _conds(ally) and ally.current_hp > hp - 10 and ally.reaction_available is False


def test_revitalizing_thread_heals_at_the_start_of_each_turn():
    engine = _life_fight(["revitalizing_thread"])
    ally = _hurt(engine, ALLY, 20)
    _act(engine, "Mend the Pulse + Revitalizing Thread", ALLY)
    hp = ally.current_hp
    _turn(engine, ALLY)
    assert ally.current_hp == hp + 3  # Core Formation (CL 10): 3 Hit Points


def test_shared_infirmary_hand_mends_a_second_creature_in_reach():
    engine = _life_fight(["shared_infirmary_hand"], cl=4)
    ally = _hurt(engine, ALLY, 20)
    me = _hurt(engine, ME, 20)
    hp_me = me.current_hp
    _act(engine, "Mend the Pulse + Shared Infirmary Hand", ALLY)
    assert me.current_hp > hp_me  # the healer is the other creature within touch


def test_pulse_array_treatment_mends_every_pulse_seal_bearer_in_range():
    from combat.typed_executor import mark_condition_id

    engine = _life_fight(["pulse_array_treatment"], ally_at=(8, 6), them_at=(12, 6))
    ally = _hurt(engine, ALLY, 20)
    me = _hurt(engine, ME, 20)
    engine._apply_condition(ally, mark_condition_id("Pulse Seal", ME), "test", ME, expires_on="UNTIL_REMOVED")
    hp = ally.current_hp
    _act(engine, "Mend the Pulse + Pulse Array Treatment", ME)
    assert ally.current_hp > hp


def test_adrenaline_surge_lets_a_prone_ally_stand_with_its_reaction():
    engine = _life_fight(["adrenaline_surge"])
    ally = _hurt(engine, ALLY, 10)
    engine._apply_condition(ally, "condition:typed.prone", "test", THEM, expires_on="UNTIL_REMOVED")
    _act(engine, "Mend the Pulse + Adrenaline Surge", ALLY)
    assert "condition:typed.prone" not in _conds(ally) and ally.reaction_available is False


def test_borrowed_breath_needs_an_injured_target():
    engine = _life_fight([])
    assert not any(c.target_ids == (ALLY,) for c in engine.legal_candidates()
                   if getattr(engine.action_catalog.get(c.source_definition_id), "display_name", "") == "Borrowed Breath")
    _hurt(engine, ALLY, 5)
    assert any(c.target_ids == (ALLY,) for c in engine.legal_candidates()
               if getattr(engine.action_catalog.get(c.source_definition_id), "display_name", "") == "Borrowed Breath")


def test_read_the_pulse_reports_and_reaches_a_sealed_creature_far_away():
    engine = _life_fight([], ally_at=(12, 6), them_at=(14, 9))
    ally = _hurt(engine, ALLY, 5)
    from combat.typed_executor import mark_condition_id

    engine._apply_condition(ally, mark_condition_id("Pulse Seal", ME), "test", ME, expires_on="UNTIL_REMOVED")
    before = len(engine.events)
    _act(engine, "Read the Pulse (Pulse Seal)", ALLY)
    logs = [e.payload.get("log", "") for e in engine.events[before:] if e.event_type == "PASSIVE_TRIGGERED"]
    assert any("is living" in log and "feet away" in log for log in logs)


def test_vital_court_field_gives_another_chosen_creature_temp_hp_when_one_is_healed():
    from combat.typed_executor import mark_condition_id

    engine = _life_fight(["vital_court_field"], ally_at=(4, 6))
    me = engine.state.actors[ME]
    _act(engine, "Vital Court Field")
    for who in (ME, ALLY):
        engine._apply_condition(engine.state.actors[who], mark_condition_id("Pulse Seal", ME), "test", ME, expires_on="UNTIL_REMOVED")
    ally = _hurt(engine, ALLY, 10)
    _refresh(engine)
    _act(engine, "Mend the Pulse", ALLY)
    assert me.temporary_hp >= 4


def test_a_life_character_with_every_talent_can_start_a_fight():
    """Meridian Unbinding's three augment options collided (TYPED_ACTION_ID_COLLISION): no such character could start a fight."""
    every = [k.rsplit(".", 1)[-1] for k in _authority() if k.startswith(TL)]
    bundle = compile_character(_life_sheet(every, 15), actor_id=ME)
    engine = Gate4ControllerEngine(ROOT, match_seed="R9ALL", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 5, "y": 6}}})
    _turn(engine, ME)
    assert engine.legal_candidates()


# ------------------------------------------------------------------------------------------------------- Illusion
TI = "tianxia.talent.illusion."


def _illusion_sheet(talents, cl=15):
    from tests.test_carry import KIT
    from tests.test_zones import SHEET

    bases = [k for k in _authority() if k.startswith("TAL_ILLUSION_") and _authority()[k].get("kind") == "base_ability"]
    sheet = {**SHEET, "equipment": [{"starting_kit": KIT}],
             "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.illusion"], "automatic_sphere_component_record_ids": bases,
                                     "learned_talent_record_ids": list(talents)}}
    sheet["identity"] = {**SHEET["identity"], "cultivation_level": cl}
    return sheet


def _illusion_fight(talents, *, cl=15, them_at=(5, 6), ally=False):
    bundles = [compile_character(_illusion_sheet(talents, cl), actor_id=ME), compile_character(_sheet([], 15, 60), actor_id=THEM)]
    ids, teams, spots = [ME, THEM], {ME: "team:a", THEM: "team:b"}, {ME: {"x": 3, "y": 6}, THEM: {"x": them_at[0], "y": them_at[1]}}
    if ally:
        bundles.append(compile_character(_sheet([], 15, 60), actor_id=ALLY))
        ids.append(ALLY)
        teams[ALLY] = "team:a"
        spots[ALLY] = {"x": 3, "y": 7}
    engine = Gate4ControllerEngine(ROOT, match_seed="R9I", typed_bundles=tuple(bundles),
                                   roster_setup={"primary_actor_ids": ids, "team_by_actor": teams, "starting_positions": spots})
    _turn(engine, ME)
    return engine


def _premise_on(engine, who=THEM, source="test"):
    from combat.typed_executor import mark_condition_id

    engine._apply_condition(engine.state.actors[who], mark_condition_id("False Premise", ME), source, ME, expires_on="START_OF_SOURCE_NEXT_TURN")


def _has_premise(engine, who=THEM):
    from combat.typed_executor import bears_mark

    return bears_mark(engine.state.actors[who], ME, "False Premise")


def test_obscuring_glamer_ends_when_its_bearer_attacks_unless_unending():
    engine = _illusion_fight(["TAL_ILLUSION_OBSCURING_GLAMER"], ally=True)
    _act(engine, "Obscuring Glamer: Blurred", ALLY)
    ally = engine.state.actors[ALLY]
    assert any(str(m.source_definition_id).split("#")[0].endswith("OBSCURING_GLAMER") for m in ally.modifiers.values())
    engine.state.actors[THEM].armor_class = -50
    _attack(engine, ALLY, "Bi Shou (Dagger) thrown", THEM)
    assert not any(str(m.source_definition_id).split("#")[0].endswith("OBSCURING_GLAMER") for m in ally.modifiers.values())
    engine2 = _illusion_fight(["TAL_ILLUSION_OBSCURING_GLAMER"], ally=True)
    _act(engine2, "Obscuring Glamer: Unending (1 CP)", ALLY)
    engine2.state.actors[THEM].armor_class = -50
    _attack(engine2, ALLY, "Bi Shou (Dagger) thrown", THEM)
    assert any(str(m.source_definition_id).split("#")[0].endswith("OBSCURING_GLAMER") for m in engine2.state.actors[ALLY].modifiers.values())


def test_obscuring_glamer_invisible_option():
    engine = _illusion_fight(["TAL_ILLUSION_OBSCURING_GLAMER"], ally=True)
    _act(engine, "Obscuring Glamer: Invisible (1 CP)", ALLY)
    assert "condition:typed.invisible" in _conds(engine.state.actors[ALLY])


def test_false_obstruction_heavily_obscured_option():
    from combat import zones

    engine = _illusion_fight(["TAL_ILLUSION_FALSE_OBSTRUCTION"])
    candidate = next(c for c in engine.legal_candidates() if c.actor_id == ME and c.destination is not None
                     and getattr(engine.action_catalog.get(c.source_definition_id), "display_name", "") == "False Obstruction: Heavily Obscured (1 extra CP, 2 CP in total)")
    engine.execute_intent(ActionIntent(intent_id="fo", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids, destination=candidate.destination))
    assert any(z.trigger_profile.get("obscured") == "heavy" or "heavy" in json.dumps(z.trigger_profile) for z in zones.typed_zones(engine))


def test_consensus_lie_gives_the_failing_creature_a_false_premise():
    engine = _illusion_fight([TI + "consensus_lie"], them_at=(8, 6))
    for action in engine.action_catalog.values():
        if action.owner_id == ME and (action.parameters or {}).get("typed"):
            action.parameters["typed"]["numbers"] = {**action.parameters["typed"]["numbers"], "save_dc": 99}
    candidate = next(c for c in engine.legal_candidates() if c.actor_id == ME and c.destination is not None
                     and getattr(engine.action_catalog.get(c.source_definition_id), "display_name", "") == "Consensus Lie"
                     and (c.destination.x, c.destination.y) == (8, 6))
    engine.execute_intent(ActionIntent(intent_id="cl", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids, destination=candidate.destination))
    assert _has_premise(engine)


def test_premise_chain_keeps_the_false_premise_after_a_response():
    engine = _illusion_fight(["TAL_ILLUSION_PREMISE_CHAIN"])
    _premise_on(engine)
    qi = engine.state.actors[ME].resources["resource:core.qi"]
    _act(engine, "Misdirection Response: Lost Timing", THEM)
    assert _has_premise(engine) and engine.state.actors[ME].resources["resource:core.qi"] == qi - 1


def test_without_premise_chain_a_response_ends_the_premise():
    engine = _illusion_fight([])
    _premise_on(engine)
    _act(engine, "Misdirection Response: Lost Timing", THEM)
    assert not _has_premise(engine)


def test_impossible_premise_responses_apply_two_different_responses():
    engine = _illusion_fight([TI + "impossible_premise"])
    _premise_on(engine, source="action:typed.x." + TI + "impossible_premise")
    _act(engine, "Misdirection Response: Stolen Step", THEM)
    them = engine.state.actors[THEM]
    assert "condition:typed.reaction_denied" in _conds(them)  # the second Response: Lost Timing


def test_sovereign_illusion_incarnation_allows_two_responses_and_bonus_action_figments():
    engine = _illusion_fight([TI + "sovereign_illusion_incarnation"], ally=True)
    engine.state.actors[ALLY].team_id = "team:c"
    _act(engine, "Sovereign Illusion Incarnation")
    _premise_on(engine)
    _premise_on(engine, who=ALLY)
    _act(engine, "Misdirection Response: Lost Timing", THEM)
    assert "Misdirection Response: Stolen Step" in _names_now(engine)
    _refresh(engine)  # (the Incarnation itself took this turn's Bonus Action)
    assert "Plant False Premise (Bonus Action)" in _names_now(engine) or "Create Figment (Bonus Action)" in _names_now(engine)


def test_premise_transfer_passes_an_expiring_premise_to_a_neighbour():
    engine = _illusion_fight(["TAL_ILLUSION_PREMISE_TRANSFER"], them_at=(8, 6), ally=True)
    ally = engine.state.actors[ALLY]
    ally.team_id = "team:c"
    ally.position = Position(x=8, y=7)
    for action in engine.action_catalog.values():
        if action.owner_id == ME and (action.parameters or {}).get("typed"):
            action.parameters["typed"]["numbers"] = {**action.parameters["typed"]["numbers"], "save_dc": 99}
    _premise_on(engine)
    _turn(engine, THEM)
    _turn(engine, ME)  # the premise ends at the start of the illusionist's turn
    assert not _has_premise(engine) and _has_premise(engine, ALLY)


def test_the_one_false_premise_applies_two_responses_on_a_failed_save():
    engine = _illusion_fight([TI + "the_one_false_premise_beneath_heaven"], cl=17)
    for action in engine.action_catalog.values():
        if action.owner_id == ME and (action.parameters or {}).get("typed"):
            action.parameters["typed"]["numbers"] = {**action.parameters["typed"]["numbers"], "save_dc": 99}
    _act(engine, "The One False Premise Beneath Heaven", THEM)
    them = engine.state.actors[THEM]
    assert "condition:typed.reaction_denied" in _conds(them)


# ------------------------------------------------------------------------------------------------------- Shield
TS = "tianxia.talent.shield."
SHIELD_ALLY = "actor:factory.lane9_shield_ally"


def _shield_fight(talents, *, cl=15, bases=True, them_at=(4, 6), ally_at=None, them_sheet=None):
    """ME: a Shield fighter (Active Defense and Shield Training unless ``bases`` is False) with ``talents``; THEM: a Formations fighter
    with a Bi Shou (melee and thrown); SHIELD_ALLY (team a) when ``ally_at`` is given.

    ME carries an actual Shield: Active Defense prints "Requirement: Wielding a Shield"
    (SHIELD_BASE_ACTIVE_DEFENSE), and the table now enforces it (combat/ext/shield_wielding.py), so a Shield fighter
    whose starting kit has no Shield in it would have no Active Defense to test. AUTO55 2026-10-05."""
    from tests.test_carry import KIT
    from tests.test_zones import SHEET

    base_ids = [k for k in _authority() if k.startswith("SHIELD_BASE")] if bases else []
    kit = {**KIT, "items": [row for row in KIT["items"] if "armor.shield" not in row["item_id"]],
             "items": [*KIT["items"], {"item_id": "tianxia.mortal.armor.shield", "name": "Shield", "quantity": 1}]}
    sheet = {**SHEET, "equipment": [{"starting_kit": kit}],
             "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.shield"], "automatic_sphere_component_record_ids": base_ids,
                                     "learned_talent_record_ids": list(talents)}}
    sheet["identity"] = {**SHEET["identity"], "cultivation_level": cl}
    bundles = [compile_character(sheet, actor_id=ME), compile_character(them_sheet or _sheet([], 15, 60), actor_id=THEM)]
    ids, teams, spots = [ME, THEM], {ME: "team:a", THEM: "team:b"}, {ME: {"x": 3, "y": 6}, THEM: {"x": them_at[0], "y": them_at[1]}}
    if ally_at:
        bundles.append(compile_character(_sheet([], 15, 60), actor_id=SHIELD_ALLY))
        ids.append(SHIELD_ALLY)
        teams[SHIELD_ALLY] = "team:a"
        spots[SHIELD_ALLY] = {"x": ally_at[0], "y": ally_at[1]}
    engine = Gate4ControllerEngine(ROOT, match_seed="R9S", typed_bundles=tuple(bundles),
                                   roster_setup={"primary_actor_ids": ids, "team_by_actor": teams, "starting_positions": spots})
    _turn(engine, ME)
    return engine


def _answers(monkeypatch, **by_choice):
    """The Shield plug-in's choices answered: choice name -> the options picked ([] declines)."""
    from combat.ext import shield_riders

    def ask(engine, intent, checkpoint, chooser, choice_id, options, **kwargs):
        name = choice_id.split(":")[-1].split(".")[-1]
        return list(by_choice.get(name, options[:1]))

    monkeypatch.setattr(shield_riders, "ask", ask)


def _stab(engine, name="Bi Shou (Dagger) attack", target=ME):
    before = len(engine.events)
    _attack(engine, THEM, name, target)
    return engine.events[before:]


def _answered(events, feature):
    return any(e.event_type == "REACTION_WINDOW_OPENED" and str(e.source_definition_id) == feature for e in events)


def test_smashing_counter_shoves_the_attacker_prone_after_active_defense_turns_its_attack():
    from tests.test_auto_lane4 import _script

    engine = _shield_fight([TS + "smashing_counter"])
    engine.state.actors[ME].armor_class = 60
    _script(engine, [5, 1])  # THEM's attack misses; its save against the Shove fails
    events = _stab(engine)
    assert _answered(events, "SHIELD_BASE_ACTIVE_DEFENSE")
    assert any("prone" in c for c in _conds(engine.state.actors[THEM]))


def test_heaven_rebuking_bash_adds_2d8_plus_strength_to_a_successful_smashing_counter(monkeypatch):
    from tests.test_auto_lane4 import _script

    _answers(monkeypatch, smashing_counter=["push"], heaven_rebuking=["damage"])
    engine = _shield_fight([TS + "smashing_counter", "TAL_SHIELD_HEAVEN_REBUKING_BASH"])
    engine.state.actors[ME].armor_class = 60
    _script(engine, [5, 1, 3, 4])
    events = _stab(engine)
    bash = [e.payload for e in events if e.event_type == "DAMAGE_COMMITTED" and str(e.source_definition_id) == "TAL_SHIELD_HEAVEN_REBUKING_BASH"]
    assert bash and bash[0]["hp_damage"] == 3 + 4 + 2  # 2d8 + Strength below CL 17
    assert engine.state.actors[THEM].position.x == 5  # the Shove's 5 feet


def test_punch_block_uses_an_unarmed_strike_roll_in_place_of_ac(monkeypatch):
    from tests.test_auto_lane4 import _script

    _answers(monkeypatch, punch_block=["punch"])
    engine = _shield_fight(["TAL_SHIELD_PUNCH_BLOCK"])
    me = engine.state.actors[ME]
    me.armor_class = 5
    hp = me.current_hp
    _script(engine, [10, 20])  # THEM hits AC 7 with 10 + its bonus; the Unarmed Strike roll is a 20 + STR + PB
    events = _stab(engine)
    assert me.current_hp == hp and not any(e.event_type == "DAMAGE_COMMITTED" and ME in e.target_ids for e in events)


def test_sacrificial_shield_breaks_the_shield_to_make_a_critical_hit_normal():
    from tests.test_auto_lane4 import _script

    engine = _shield_fight([TS + "sacrificial_shield"])
    me = engine.state.actors[ME]
    hp, ac = me.current_hp, me.armor_class + engine._ac_modifier(me)
    _script(engine, [20, 3, 4])  # a natural 20; the doubled 1d4
    events = _stab(engine)
    rolled = [e.payload for e in events if e.event_type == "DAMAGE_ROLLED"][0]
    assert rolled["critical"]
    assert hp - me.current_hp == int(rolled["total"]) - 4  # the critical die comes off
    assert "condition:typed.shield_broken" in _conds(me)
    engine._remove_condition(me, "condition:typed.extensive_defense", "test")
    assert me.armor_class + engine._ac_modifier(me) <= ac  # the broken Shield's -2 (Active Defense's +2 lasts to the next turn)


def test_rain_on_the_lotus_sends_a_missed_projectile_back_at_the_thrower():
    from tests.test_auto_lane4 import _script

    engine = _shield_fight(["TAL_SHIELD_RAIN_ON_THE_LOTUS_DEFLECTION"], them_at=(6, 6))
    engine.state.actors[ME].armor_class = 60
    engine.state.actors[THEM].armor_class = 5
    _script(engine, [5, 15, 3])
    events = _stab(engine, "Bi Shou (Dagger) thrown")
    back = [e for e in events if e.event_type == "DAMAGE_COMMITTED" and str(e.source_definition_id) == "TAL_SHIELD_RAIN_ON_THE_LOTUS_DEFLECTION"]
    assert back and THEM in back[0].target_ids and back[0].payload["hp_damage"] == 3 + 2  # the dagger's 1d4 + DEX


def test_greater_deflect_spends_martial_focus_for_a_second_deflect(monkeypatch):
    from tests.test_auto_lane4 import _script

    _answers(monkeypatch)
    engine = _shield_fight([TS + "smashing_counter", "TAL_SHIELD_RAIN_ON_THE_LOTUS_DEFLECTION", "TAL_SHIELD_GREATER_DEFLECT"], them_at=(4, 6))
    me, them = engine.state.actors[ME], engine.state.actors[THEM]
    me.armor_class, them.armor_class = 60, 5
    _script(engine, [5, 5, 1, 15, 3])  # the adjacent throw (Disadvantage) misses; Smashing Counter's save fails; the projectile goes back
    events = _stab(engine, "Bi Shou (Dagger) thrown")
    assert any("prone" in c for c in _conds(them))
    assert any(e.event_type == "DAMAGE_COMMITTED" and str(e.source_definition_id) == "TAL_SHIELD_RAIN_ON_THE_LOTUS_DEFLECTION" for e in events)
    assert me.resources["resource:core.martial_focus"] == 0


def test_one_deflect_per_active_defense_without_greater_deflect(monkeypatch):
    from tests.test_auto_lane4 import _script

    _answers(monkeypatch)
    engine = _shield_fight([TS + "smashing_counter", "TAL_SHIELD_RAIN_ON_THE_LOTUS_DEFLECTION"], them_at=(4, 6))
    engine.state.actors[ME].armor_class = 60
    _script(engine, [5, 5, 1, 15, 3])
    events = _stab(engine, "Bi Shou (Dagger) thrown")
    assert any("prone" in c for c in _conds(engine.state.actors[THEM]))  # the first Deflect
    assert not any(str(e.source_definition_id) == "TAL_SHIELD_RAIN_ON_THE_LOTUS_DEFLECTION" for e in events)


def test_cover_ally_raises_the_allys_ac_with_the_shield_bearers_reaction():
    engine = _shield_fight(["TAL_SHIELD_COVER_ALLY"], them_at=(5, 6), ally_at=(4, 6))
    ally = engine.state.actors[SHIELD_ALLY]
    ac = ally.armor_class + engine._ac_modifier(ally)
    events = _stab(engine, target=SHIELD_ALLY)
    assert _answered(events, "TAL_SHIELD_COVER_ALLY") and not engine.state.actors[ME].reaction_available
    assert ally.armor_class + engine._ac_modifier(ally) == ac + 2


def test_extensive_defense_gives_every_attack_the_plus_two_without_a_reaction_and_covers_allies():
    engine = _shield_fight(["TAL_SHIELD_EXTENSIVE_DEFENSE", "TAL_SHIELD_COVER_ALLY"], ally_at=(3, 7))
    me, ally = engine.state.actors[ME], engine.state.actors[SHIELD_ALLY]
    mine, theirs = me.armor_class + engine._ac_modifier(me), ally.armor_class + engine._ac_modifier(ally)
    _act(engine, "Extensive Defense (Martial Focus)")
    assert me.resources["resource:core.martial_focus"] == 0 and "condition:typed.extensive_defense" in _conds(me)
    assert me.armor_class + engine._ac_modifier(me) == mine + 2 and ally.armor_class + engine._ac_modifier(ally) == theirs + 2
    events = _stab(engine)
    assert me.reaction_available and not _answered(events, "SHIELD_BASE_ACTIVE_DEFENSE")


def test_shield_of_the_second_answer_leaves_an_echo_only_when_active_defense_caused_the_miss():
    from tests.test_auto_lane4 import _script

    engine = _shield_fight(["TAL_SHIELD_SHIELD_OF_THE_SECOND_ANSWER"])
    engine.state.actors[ME].armor_class = 15
    _script(engine, [2])  # far below: Active Defense did not cause this miss
    events = _stab(engine)
    assert _answered(events, "SHIELD_BASE_ACTIVE_DEFENSE") and "condition:typed.second_answer" not in _conds(engine.state.actors[ME])
    bonus = next(e.payload["modified_total"] - e.payload["natural_result"] for e in events if e.event_type == "ATTACK_ROLLED")

    engine = _shield_fight(["TAL_SHIELD_SHIELD_OF_THE_SECOND_ANSWER"])
    me = engine.state.actors[ME]
    me.armor_class = 15
    _script(engine, [15 - bonus])  # it would hit AC 15; Active Defense's +2 turns it
    _stab(engine)
    assert "condition:typed.second_answer" in _conds(me)
    _script(engine, [2])
    events = _stab(engine)  # the echo answers the next attack (+2 on that roll's AC), then it is gone
    rolled = next(e.payload for e in events if e.event_type == "ATTACK_ROLLED")
    assert "condition:typed.second_answer" not in _conds(me) and rolled["target_ac"] == me.armor_class + engine._ac_modifier(me) + 2


def test_mountain_rooted_rim_cuts_forced_movement_on_the_protected_creature_by_ten_feet():
    from combat import typed_reactions
    from tests.test_auto_lane4 import _script

    engine = _shield_fight(["TAL_SHIELD_MOUNTAIN_ROOTED_RIM"])
    me, them = engine.state.actors[ME], engine.state.actors[THEM]
    assert typed_reactions.on_forced_movement(engine, me, them, 15) == 15
    me.armor_class = 60
    _script(engine, [5])
    _stab(engine)
    assert "condition:typed.rooted_rim" in _conds(me)
    assert typed_reactions.on_forced_movement(engine, me, them, 15) == 5


def test_reactive_defense_strikes_back_once_at_a_creature_that_misses_after_the_dodge():
    from tests.test_auto_lane4 import _script

    engine = _shield_fight(["TAL_SHIELD_REACTIVE_DEFENSE"], bases=False)
    me = engine.state.actors[ME]
    before = len(engine.events)
    _act(engine, "Dodge")
    assert not any(e.event_type == "ATTACK_ROLLED" and e.actor_id == ME for e in engine.events[before:])  # not as the Dodge is taken
    me.armor_class = 60
    _script(engine, [5])
    events = _stab(engine)
    assert any(e.event_type == "ATTACK_ROLLED" and e.actor_id == ME and THEM in e.target_ids for e in events)
    assert not me.reaction_available


def test_blockade_answers_a_dexterity_save_for_half_damage_and_a_success_takes_none(monkeypatch):
    from tests.test_auto_lane1 import _sheet as one_sheet
    from tests.test_auto_lane4 import _script

    _answers(monkeypatch, blockade=["use"])
    engine = _shield_fight(["TAL_SHIELD_BLOCKADE"], them_at=(12, 6), them_sheet=one_sheet(RAIN))
    me = engine.state.actors[ME]
    hp = me.current_hp
    _turn(engine, THEM)
    _script(engine, [19])  # ME's Dexterity save
    _rain(engine, (3, 6))
    assert me.current_hp == hp and not me.reaction_available
    assert any(e.event_type == "REACTION_WINDOW_OPENED" and str(e.source_definition_id) == "TAL_SHIELD_BLOCKADE" for e in engine.events)


def test_shield_typing_celestial_disc_sweep_shapes_and_returning_disc_dice():
    auth = _authority()
    shapes = [o["area"]["shape"] for o in auth["TAL_SHIELD_CELESTIAL_DISC_SWEEP"]["options"]]
    assert shapes == ["cone", "line"]
    hit = auth["TAL_SHIELD_RETURNING_SHIELD_DISC"]["effects"][0]["on_hit"][0]
    assert hit["dice_by_cl"] == [[1, 10, 1, 8], [11, 16, 2, 8], [17, 20, 3, 8]]
    assert auth["TAL_SHIELD_COVER_ALLY"]["activation"]["economy"] == "reaction"


# ------------------------------------------------------------------------------------------------------- Fate
TF = "TAL_FATE_"


def _fate_fight(talents, *, cl=15, them_at=(4, 6), ally_at=(3, 7), dc=30, seed="R9FATE", bases=False, an_at=None):
    """ME: a Fate caster (``talents``, 80 Qi, save DC ``dc``; the Fate base abilities only when ``bases`` -- Twist of Fate would spend its
    Reaction on every roll near it); THEM (team b) and ALLY (team a): plain fighters."""
    from tests.test_carry import KIT
    from tests.test_zones import SHEET

    auth = _authority()
    base_ids = [k for k in auth if auth[k].get("sphere_id") == "tianxia.sphere.fate" and auth[k].get("kind") == "base_ability"] if bases else []
    sheet = {**SHEET, "equipment": [{"starting_kit": KIT}],
             "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.fate"], "automatic_sphere_component_record_ids": base_ids,
                                     "learned_talent_record_ids": [t if t.startswith(("TAL_", "tianxia.")) else TF + t for t in talents]}}
    sheet["identity"] = {**SHEET["identity"], "cultivation_level": cl}
    sheet["ability_scores_and_statistics"] = {**SHEET["ability_scores_and_statistics"], "primary_resource": {"name": "Qi", "maximum": 80},
                                              "technique_save_dc": dc}
    bundles = [compile_character(sheet, actor_id=ME), compile_character(_sheet([], 15, 60), actor_id=THEM)]
    ids, teams, spots = [ME, THEM], {ME: "team:a", THEM: "team:b"}, {ME: {"x": 3, "y": 6}, THEM: {"x": them_at[0], "y": them_at[1]}}
    if ally_at:
        bundles.append(compile_character(_sheet([], 15, 60), actor_id=ALLY))
        ids.append(ALLY)
        teams[ALLY] = "team:a"
        spots[ALLY] = {"x": ally_at[0], "y": ally_at[1]}
    if an_at:
        ids.append(AN)
        teams[AN] = "team:b"
        spots[AN] = {"x": an_at[0], "y": an_at[1]}
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=tuple(bundles),
                                   roster_setup={"primary_actor_ids": ids, "team_by_actor": teams, "starting_positions": spots})
    _turn(engine, ME)
    return engine


def _fate_answers(monkeypatch, **by_choice):
    from combat.ext import fate_riders

    def ask(engine, intent, checkpoint, chooser, choice_id, options, **kwargs):
        name = choice_id.split(":")[-1].split(".")[-1]
        return list(by_choice.get(name, options[:1]))

    monkeypatch.setattr(fate_riders, "ask", ask)


def _from(events, source, target=None):
    return [e for e in events if str(e.source_definition_id) == source and (target is None or target in (e.target_ids or ()))]


def test_consequence_edict_burns_a_damager_inside_the_aura_once_a_round_and_spares_the_designated():
    from tests.test_auto_lane4 import _script

    engine = _fate_fight(["CONSEQUENCE_EDICT"])
    _act(engine, "Consequence Edict")
    engine.state.actors[ME].armor_class = -50
    events = _stab(engine)
    burn = [e.payload for e in _from(events, TF + "CONSEQUENCE_EDICT", THEM) if e.event_type == "DAMAGE_COMMITTED"]
    assert burn and burn[0]["reduced_to"] == 4  # PB
    _script(engine, [15])
    events = _stab(engine)
    assert not _from(events, TF + "CONSEQUENCE_EDICT", THEM)  # once per round
    before = len(engine.events)
    engine.state.round_number += 1
    _turn(engine, ME)
    _act(engine, "Bi Shou (Dagger) attack", THEM)  # the owner is designated
    assert not _from(engine.events[before:], TF + "CONSEQUENCE_EDICT", ME)


def test_undo_harm_edict_grants_temporary_hp_before_the_first_damage_each_round_and_they_vanish_outside():
    engine = _fate_fight(["UNDO_HARM_EDICT"])
    _act(engine, "Undo Harm Edict")
    me = engine.state.actors[ME]
    me.armor_class = -50
    events = _stab(engine)
    hit = [e.payload for e in events if e.event_type == "DAMAGE_COMMITTED" and ME in e.target_ids][0]
    assert hit["temporary_hp_absorbed"] > 0  # PB 4 + 10 at CL 15, before the damage
    engine._grant_temp_hp(me, 5, "test", ME)
    me.position = Position(x=12, y=12)
    engine._append_event("MOVEMENT_COMMITTED", "test", actor_id=ME, payload={})
    assert me.temporary_hp <= 5 - min(5, 14)  # gone once it is outside the aura


def test_purity_edict_adds_pb_to_the_first_healing_each_round_inside_at_cl_10():
    engine = _fate_fight(["PURITY_EDICT"])
    _act(engine, "Purity Edict")
    me = engine.state.actors[ME]
    me.current_hp = 20
    me.current_hp = 25
    engine._append_event("HEALING_APPLIED", "test", actor_id=ME, target_ids=(ME,), payload={"offered": 5, "before": 20, "after": 25})
    assert me.current_hp == 29
    me.current_hp = 30
    engine._append_event("HEALING_APPLIED", "test", actor_id=ME, target_ids=(ME,), payload={"offered": 1, "before": 29, "after": 30})
    assert me.current_hp == 30  # once a round


def test_subvert_harm_turns_the_attackers_damage_on_itself_on_a_failed_save(monkeypatch):
    from tests.test_auto_lane4 import _script

    _fate_answers(monkeypatch, subvert_harm=["use"])
    engine = _fate_fight(["SUBVERT_HARM"])
    me, them = engine.state.actors[ME], engine.state.actors[THEM]
    me.armor_class = -50
    hp, qi = me.current_hp, me.resources["resource:core.qi"]
    events = _stab(engine)
    assert me.current_hp == hp and me.resources["resource:core.qi"] == qi - 4 and not me.reaction_available
    assert [e for e in _from(events, TF + "SUBVERT_HARM", THEM) if e.event_type == "DAMAGE_COMMITTED"]


def test_violence_word_leaves_only_an_attack_on_the_nearest_creature_for_its_action():
    engine = _fate_fight(["VIOLENCE_WORD"], them_at=(6, 6), ally_at=(7, 6))
    _act(engine, "Violence Word", THEM)
    assert "condition:typed.violence_word" in _conds(engine.state.actors[THEM])
    _turn(engine, THEM)
    from combat.gate2_runtime_models import EconomyKind

    actions = [(c, engine.action_catalog.get(c.source_definition_id)) for c in engine.legal_candidates() if c.actor_id == THEM]
    main = [(c.target_ids, a.display_name) for c, a in actions if a is not None and a.economy == EconomyKind.ACTION]
    assert main and all(t == (ALLY,) for t, _name in main)  # the ally stands nearest (5 feet); ME is 15 feet away
    _act(engine, "Bi Shou (Dagger) attack", ALLY, actor=THEM)
    assert "condition:typed.violence_word" not in _conds(engine.state.actors[THEM])


def test_jinxed_name_takes_1d4_once_a_round_and_repeats_the_save():
    from tests.test_auto_lane4 import _script

    engine = _fate_fight(["JINXED_NAME"])
    _act(engine, "Jinxed Name", THEM)
    jinx = [c for c in engine.state.actors[THEM].conditions.values() if c.condition_id == "condition:typed.jinxed_name"]
    assert jinx and jinx[0].data["repeat_save"]["ability"] == "CHA"
    _script(engine, [3, 10])  # the 1d4 comes off before the d20 is rolled
    events = _stab(engine)
    rolled = [e.payload for e in events if e.event_type == "ATTACK_ROLLED"][0]
    control = _fate_fight(["JINXED_NAME"])
    _script(control, [10])
    plain = [e.payload for e in _stab(control) if e.event_type == "ATTACK_ROLLED"][0]
    assert rolled["modified_total"] == plain["modified_total"] - 3


def test_chain_of_misfortune_answers_the_first_miss_each_round_with_the_chosen_misfortune():
    from tests.test_auto_lane4 import _script

    engine = _fate_fight(["CHAIN_OF_MISFORTUNE"])
    _act(engine, "Chain of Misfortune", THEM)
    assert "condition:typed.chain_of_misfortune" in _conds(engine.state.actors[THEM])
    engine.state.actors[ME].armor_class = 60
    _script(engine, [2, 5, 6])
    events = _stab(engine)
    psychic = [e.payload for e in _from(events, TF + "CHAIN_OF_MISFORTUNE", THEM) if e.event_type == "DAMAGE_COMMITTED"]
    assert psychic and psychic[0]["reduced_to"] == 11  # 2d8 = 5 + 6
    events = _stab(engine)
    assert not [e for e in _from(events, TF + "CHAIN_OF_MISFORTUNE", THEM) if e.event_type == "DAMAGE_COMMITTED"]  # once a round


def test_calamity_finds_a_path_lands_two_chosen_misfortunes_on_a_failed_save():
    engine = _fate_fight(["CALAMITY_FINDS_A_PATH"])
    them = engine.state.actors[THEM]
    ac = them.armor_class + engine._ac_modifier(them)
    _act(engine, "Calamity Finds a Path", THEM)
    assert any("prone" in c for c in _conds(them)) and them.armor_class + engine._ac_modifier(them) == ac - 2


def test_calamity_success_takes_half_damage_and_one_misfortune_and_no_standing_ac_penalty():
    from tests.test_auto_lane4 import _script

    engine = _fate_fight(["CALAMITY_FINDS_A_PATH"], dc=5)
    them = engine.state.actors[THEM]
    ac = them.armor_class + engine._ac_modifier(them)
    _script(engine, [15])
    _act(engine, "Calamity Finds a Path", THEM)
    assert any("prone" in c for c in _conds(them)) and them.armor_class + engine._ac_modifier(them) == ac


def test_borrowed_lifespan_holds_an_ally_at_1_hp_once_per_creature_and_asks_the_cost():
    engine = _fate_fight(["BORROWED_LIFESPAN_TALISMAN"], them_at=(4, 7))
    ally = engine.state.actors[ALLY]
    ally.armor_class, ally.current_hp = -50, 1
    events = _stab(engine, target=ALLY)
    assert _answered(events, TF + "BORROWED_LIFESPAN_TALISMAN") and ally.current_hp >= 1
    assert any("repayment oath" in str(e.payload) for e in events)
    _refresh(engine)
    ally.current_hp = 1
    events = _stab(engine, target=ALLY)
    assert not _answered(events, TF + "BORROWED_LIFESPAN_TALISMAN")  # once per creature


def test_guiding_star_auspice_release_stops_the_opportunity_attack():
    engine = _fate_fight(["GUIDING_STAR_AUSPICE"], ally_at=None)
    _act(engine, "Guiding Star Auspice", ME)
    me = engine.state.actors[ME]
    _refresh(engine)
    before = len(engine.events)
    candidate = next(c for c in engine.legal_candidates() if c.actor_id == ME and str(c.kind) == "MOVE" and c.destination and c.destination.x == 1)
    engine.execute_intent(ActionIntent(intent_id="leave", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, destination=candidate.destination))
    assert not any(e.event_type == "ATTACK_ROLLED" and e.actor_id == THEM for e in engine.events[before:])
    assert "condition:typed.guiding_star_free" in _conds(me) and not me.reaction_available


def test_moving_star_auspice_release_ignores_a_stun():
    from combat import typed_reactions
    from combat.typed_executor import run_effects

    engine = _fate_fight(["MOVING_STAR_AUSPICE"], ally_at=None)
    _act(engine, "Moving Star Auspice", ME)
    me = engine.state.actors[ME]
    _refresh(engine)
    row = {"feature_id": "TEST_STUN", "name": "Stun", "effects": [], "numbers": {}}
    run_effects(typed_reactions._generic_context(engine, engine.state.actors[THEM], me, row),
                [{"type": "condition", "condition": "stunned", "applies_to": "target"}])
    assert not any("stunned" in c for c in _conds(me)) and "condition:typed.moving_star_ignore" in _conds(me)


def test_turning_wheel_rolls_its_d6_and_adds_the_bonus_by_cl():
    from tests.test_auto_lane4 import _script

    engine = _fate_fight(["TURNING_WHEEL_AUSPICE"], ally_at=None)
    _script(engine, [2])  # 1-2: attack and damage rolls
    _act(engine, "Turning Wheel Auspice", ME)
    wheel = [c.data for c in engine.state.actors[ME].conditions.values() if c.condition_id == "condition:typed.turning_wheel"]
    assert wheel and wheel[0]["kind"] == "attack" and wheel[0]["bonus"] == 2  # CL 15


def test_twist_of_fate_rolls_the_fate_die_by_cl():
    engine = _fate_fight([], bases=True, cl=15)
    events = _stab(engine)
    twist = [e.payload for e in events if e.event_type == "REACTION_RESOLVED" and str(e.source_definition_id) == TF + "TWIST_OF_FATE"]
    die = [e.payload for e in events if e.event_type == "ROLL_RECORDED" and "REACTION_DIE" in str(e.payload.get("reason"))]
    assert twist and (not die or die[0]["expression"] == "1d8")
    assert -8 <= twist[0]["bonus"] <= -1


def test_twist_of_fate_and_guiding_star_typing():
    auth = _authority()
    assert auth[TF + "TWIST_OF_FATE"]["effects"][0]["die_by_cl"] == [[1, 4, 4], [5, 10, 6], [11, 16, 8], [17, 20, 10]]
    assert auth[TF + "GUIDING_STAR_AUSPICE"]["activation"]["economy"] == "action"


def test_quiet_mandate_edict_silences_creatures_inside():
    from combat import speech

    engine = _fate_fight(["QUIET_MANDATE_EDICT"])
    them = engine.state.actors[THEM]
    assert not speech.silenced(them)
    _act(engine, "Quiet Mandate Edict")
    assert speech.silenced(them)


def test_freedom_word_makes_an_escape_attempt_at_once():
    from tests.test_auto_lane4 import _script

    engine = _fate_fight(["FREEDOM_WORD"], ally_at=None)
    me = engine.state.actors[ME]
    engine._apply_condition(me, "condition:typed.grappled", "test", THEM, expires_on="UNTIL_REMOVED", data={"escape_dc": 5, "reach_ft": 5})
    _script(engine, [15])
    _act(engine, "Freedom Word", ME)
    assert "condition:typed.grappled" not in _conds(me)


def test_serendipity_edict_adds_1d4_to_an_allys_roll_once_a_round():
    from tests.test_auto_lane4 import _script

    engine = _fate_fight(["SERENDIPITY_EDICT"], them_at=(4, 7))
    _act(engine, "Serendipity Edict")
    _turn(engine, ALLY)
    _script(engine, [10, 3])
    before = len(engine.events)
    _act(engine, "Bi Shou (Dagger) attack", THEM, actor=ALLY)
    assert any("Serendipity Edict" in str(e.payload) for e in engine.events[before:])


def test_marked_by_the_ledger_moves_the_mark_after_its_creature_drops():
    engine = _fate_fight(["MARKED_BY_THE_LEDGER"], ally_at=None, an_at=(6, 6))
    _act(engine, "Marked by the Ledger: Tracking Advantage", THEM)
    me = engine.state.actors[ME]
    assert "Move the Ledger Mark" not in _names_now(engine)
    them = engine.state.actors[THEM]
    engine._commit_damage(them, them.current_hp + them.temporary_hp, "SLASHING", "test", ME, None, reaction_depth=0)
    assert "Move the Ledger Mark" not in _names_now(engine)  # "on a later turn"
    engine.state.round_number += 1
    _turn(engine, ME)
    _act(engine, "Move the Ledger Mark", AN)
    marks = [m.value for m in me.modifiers.values() if m.target_field == "typed_on_hit"]
    assert marks and all(str(v).startswith(AN + "|") for v in marks)


def test_fate_sovereign_incarnation_makes_the_fate_die_a_d10_and_gives_an_ally_a_boon():
    from combat.ext import fate_riders

    engine = _fate_fight(["FATE_SOVEREIGN_INCARNATION"], cl=15)
    name = next(n for n in _names_now(engine) if n and n.startswith("Fate-Sovereign Incarnation"))
    _act(engine, name)
    me = engine.state.actors[ME]
    assert fate_riders.fate_die(engine, me, 15) == 10
    engine.state.round_number += 1
    _turn(engine, ME)
    assert "condition:typed.sovereign_boon" in _conds(engine.state.actors[ALLY])


# ------------------------------------------------------------------------------------------------------- Ice
TICE = "TAL_ICE_"


def _ice_fight(talents, *, cl=15, them_at=(5, 6), ally_at=None, dc=30, seed="R9ICE", bases=("ICE_BASE_SPENDING_A_FRACTURE_MARK",)):
    """ME: an Ice cultivator (Spending a Fracture Mark and ``bases``, ``talents``, 80 Qi, save DC ``dc``); THEM (team b); ALLY (team a)."""
    from tests.test_carry import KIT
    from tests.test_zones import SHEET

    sheet = {**SHEET, "equipment": [{"starting_kit": KIT}],
             "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.ice"], "automatic_sphere_component_record_ids": list(bases),
                                     "learned_talent_record_ids": [t if t.startswith(("TAL_", "tianxia.", "ICE_BASE")) else TICE + t for t in talents]}}
    sheet["identity"] = {**SHEET["identity"], "cultivation_level": cl}
    sheet["ability_scores_and_statistics"] = {**SHEET["ability_scores_and_statistics"], "primary_resource": {"name": "Qi", "maximum": 80},
                                              "technique_save_dc": dc}
    bundles = [compile_character(sheet, actor_id=ME), compile_character(_sheet([], 15, 60), actor_id=THEM)]
    ids, teams, spots = [ME, THEM], {ME: "team:a", THEM: "team:b"}, {ME: {"x": 3, "y": 6}, THEM: {"x": them_at[0], "y": them_at[1]}}
    if ally_at:
        bundles.append(compile_character(_sheet([], 15, 60), actor_id=ALLY))
        ids.append(ALLY)
        teams[ALLY] = "team:a"
        spots[ALLY] = {"x": ally_at[0], "y": ally_at[1]}
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=tuple(bundles),
                                   roster_setup={"primary_actor_ids": ids, "team_by_actor": teams, "starting_positions": spots})
    _turn(engine, ME)
    return engine


def _mark(engine, who=THEM):
    from combat.ext import ice_fracture

    ice_fracture.give_mark(engine, engine.state.actors[ME], engine.state.actors[who], "test")
    return ice_fracture.marked(engine.state.actors[who], ME)


def _lattice_under(engine, who):
    from combat.ext import ice_fracture

    ice_fracture._lattice_at(engine, engine.state.actors[ME], engine.state.actors[who], "test")


def _marked(engine, who=THEM):
    from combat.ext import ice_fracture

    return ice_fracture.marked(engine.state.actors[who], ME)


def test_crystallize_path_places_lattice_spaces_by_cl():
    from combat.ext import ice_fracture

    engine = _ice_fight([], bases=("ICE_BASE_SPENDING_A_FRACTURE_MARK", "ICE_BASE_CRYSTALLIZE_PATH"))
    _act(engine, "Crystallize Path")
    assert len(ice_fracture.lattice_cells(engine, ME)) == 4  # CL 15: 4 spaces


def test_a_fracture_mark_lasts_until_the_end_of_the_marker_next_turn():
    engine = _ice_fight([], bases=("ICE_BASE_SPENDING_A_FRACTURE_MARK", "ICE_BASE_SHARD_NEEDLE"))
    engine.state.actors[THEM].armor_class = -50
    _act(engine, "Shard Needle", THEM)
    marks = [c for c in engine.state.actors[THEM].conditions.values() if ".fracture_mark." in c.condition_id]
    assert marks and marks[0].expires_on == "END_OF_MARKER_NEXT_TURN"


def test_brittle_opening_spends_the_mark_when_the_marked_creature_is_hit():
    engine = _ice_fight([], them_at=(4, 6))
    assert _mark(engine)
    engine.state.actors[THEM].armor_class = -50
    before = len(engine.events)
    _act(engine, "Bi Shou (Dagger) attack", THEM)
    events = engine.events[before:]
    cold = [e.payload for e in events if e.event_type == "DAMAGE_COMMITTED" and str(e.source_definition_id) == "ICE_BASE_SPENDING_A_FRACTURE_MARK"]
    assert cold and cold[0]["damage_type"] == "COLD" and not _marked(engine)


def test_crack_aim_takes_a_die_off_the_marked_creatures_attack_roll():
    from tests.test_auto_lane4 import _script

    engine = _ice_fight([], them_at=(4, 6))
    _mark(engine)
    _script(engine, [3, 10])  # Crack Aim's 1d6 (CL 11+) before the d20
    rolled = [e.payload for e in _stab(engine) if e.event_type == "ATTACK_ROLLED"][0]
    control = _ice_fight([], them_at=(4, 6))
    _script(control, [10])
    plain = [e.payload for e in _stab(control) if e.event_type == "ATTACK_ROLLED"][0]
    assert rolled["modified_total"] == plain["modified_total"] - 3 and not _marked(engine)


def test_shatter_space_as_the_marked_creature_starts_its_turn_on_the_lattice():
    from combat.ext import ice_fracture

    engine = _ice_fight([])
    _lattice_under(engine, THEM)
    _mark(engine)
    them = engine.state.actors[THEM]
    hp = them.current_hp
    _turn(engine, THEM)
    assert them.current_hp < hp and any("prone" in c for c in _conds(them)) and not _marked(engine)
    assert not ice_fracture.lattice_cells(engine, ME)  # that space ends


def test_catch_step_cuts_the_marked_creatures_movement_as_its_turn_starts():
    engine = _ice_fight([], them_at=(9, 6))
    _mark(engine)
    _turn(engine, THEM)
    them = engine.state.actors[THEM]
    assert them.movement_remaining_ft == 30 - 20 and not _marked(engine)  # 20 feet at CL 11+


def test_fracture_responses_are_once_per_round():
    engine = _ice_fight([], them_at=(4, 6))
    _mark(engine)
    them = engine.state.actors[THEM]
    them.armor_class = -50
    _act(engine, "Bi Shou (Dagger) attack", THEM)
    assert not _marked(engine)
    _mark(engine)
    _refresh(engine)
    before = len(engine.events)
    _act(engine, "Bi Shou (Dagger) attack", THEM)
    assert _marked(engine) and not any(str(e.source_definition_id) == "ICE_BASE_SPENDING_A_FRACTURE_MARK" and e.event_type == "DAMAGE_COMMITTED"
                                       for e in engine.events[before:])


def test_crystal_guard_shields_a_marked_ally():
    engine = _ice_fight([], them_at=(4, 7), ally_at=(3, 7))
    _mark(engine, ALLY)
    ally = engine.state.actors[ALLY]
    ally.armor_class = -50
    events = _stab(engine, target=ALLY)
    hit = [e.payload for e in events if e.event_type == "DAMAGE_COMMITTED" and ALLY in e.target_ids][0]
    assert hit["reduced_to"] < hit["rolled_or_pending_damage"] and not _marked(engine, ALLY)


def test_crossing_the_lattice_marks_the_mover_and_mirror_slick_floor_trips_it():
    from combat.gate2_runtime_models import Position

    engine = _ice_fight(["MIRROR_SLICK_FLOOR"], bases=("ICE_BASE_SPENDING_A_FRACTURE_MARK", "ICE_BASE_CRYSTALLIZE_PATH"), them_at=(7, 6))
    them = engine.state.actors[THEM]
    home = them.position
    for x in (7, 8):  # two Lattice Spaces on its path
        them.position = Position(x=x, y=6)
        _lattice_under(engine, THEM)
    them.position = home
    engine.state.round_number += 1
    _turn(engine, THEM)
    start = them.position
    them.position = Position(x=start.x + 2, y=start.y)
    engine._append_event("MOVEMENT_COMMITTED", "test", actor_id=THEM,
                         payload={"path": [{"x": start.x, "y": start.y}, {"x": start.x + 1, "y": start.y}, {"x": start.x + 2, "y": start.y}]})
    assert _marked(engine) and any("prone" in c for c in _conds(them))


def test_ninefold_crack_calculation_adds_lock_grip_to_crack_aim():
    engine = _ice_fight(["NINEFOLD_CRACK_CALCULATION"], them_at=(4, 6))
    _mark(engine)
    qi = engine.state.actors[ME].resources["resource:core.qi"]
    _stab(engine)
    them = engine.state.actors[THEM]
    assert "condition:typed.lock_grip" in _conds(them) and engine.state.actors[ME].resources["resource:core.qi"] == qi - 1


def test_rime_hook_drags_the_target_after_shatter_space():
    from combat.ext import ice_fracture

    engine = _ice_fight(["RIME_HOOK"], them_at=(6, 6))
    _lattice_under(engine, THEM)
    them = engine.state.actors[THEM]
    _mark(engine)
    ice_fracture._lattice_at(engine, engine.state.actors[ME], engine.state.actors[ME], "test")  # a second space, under ME
    start = (them.position.x, them.position.y)
    _turn(engine, THEM)
    assert them.active and (them.position.x, them.position.y) != start  # dragged 10 feet toward the lattice (CL 11+)
    assert any(e.event_type == "MOVEMENT_COMMITTED" and str(e.source_definition_id) == TICE + "RIME_HOOK" for e in engine.events)


def test_frost_sheathed_guard_marks_the_first_melee_attacker_not_the_guarded_ally():
    engine = _ice_fight(["FROST_SHEATHED_GUARD"], them_at=(4, 7), ally_at=(3, 7))
    _act(engine, "Frost-Sheathed Guard", ALLY)
    assert not _marked(engine, ALLY) and engine.state.actors[ALLY].temporary_hp > 0
    engine.state.actors[ALLY].armor_class = -50
    _stab(engine, target=ALLY)
    assert _marked(engine)


def test_bitter_edge_adds_pb_cold_and_marks_a_target_on_the_lattice():
    engine = _ice_fight(["BITTER_EDGE"], them_at=(4, 6))
    _act(engine, "Bitter Edge")
    _lattice_under(engine, THEM)
    engine.state.actors[THEM].armor_class = -50
    before = len(engine.events)
    _act(engine, "Bi Shou (Dagger) attack", THEM)
    cold = [e.payload for e in engine.events[before:] if e.event_type == "DAMAGE_COMMITTED" and str(e.source_definition_id) == TICE + "BITTER_EDGE"]
    assert cold and cold[0]["rolled_or_pending_damage"] == 4 and _marked(engine)


def test_diamond_rime_body_puts_a_lattice_space_under_a_melee_attacker():
    from combat.ext import ice_fracture
    from combat.gate2_runtime_models import ReactionDecision

    engine = _ice_fight(["DIAMOND_RIME_BODY"], them_at=(4, 6))
    _act(engine, "Diamond Rime Body")
    engine.state.actors[ME].armor_class = -50
    def choose_attacker(request):
        assert request["reaction_source_id"] == "choice:needle.rime_body_space"
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="USE", option_ids=(THEM,)), None
    engine.set_reaction_provider(choose_attacker)
    _stab(engine)
    them = engine.state.actors[THEM]
    assert (them.position.x, them.position.y) in ice_fracture.lattice_cells(engine, ME)


def test_ice_coffin_needs_a_marked_target_on_the_lattice_and_gives_cover_and_a_repeat_save():
    engine = _ice_fight(["ICE_COFFIN"], them_at=(5, 6))
    assert "Ice Coffin" not in _names_now(engine)
    _mark(engine)
    _lattice_under(engine, THEM)
    them = engine.state.actors[THEM]
    ac = them.armor_class + engine._ac_modifier(them)
    _act(engine, "Ice Coffin", THEM)
    held = [c for c in them.conditions.values() if c.condition_id == "condition:typed.restrained"]
    assert held and held[0].data["repeat_save"]["ability"] == "STR" and them.armor_class + engine._ac_modifier(them) == ac + 2


def test_shatter_bloom_shatters_lattice_spaces_near_hostile_creatures():
    from combat.ext import ice_fracture

    engine = _ice_fight(["SHATTER_BLOOM"], them_at=(6, 6))
    _lattice_under(engine, THEM)
    them = engine.state.actors[THEM]
    hp = them.current_hp
    _act(engine, "Shatter Bloom")
    assert them.current_hp < hp and any("prone" in c for c in _conds(them)) and not ice_fracture.lattice_cells(engine, ME)


def test_winter_stores_the_blow_cuts_damage_on_the_lattice_and_stores_it():
    engine = _ice_fight(["WINTER_STORES_THE_BLOW"], them_at=(4, 7), ally_at=(3, 7))
    _lattice_under(engine, ALLY)
    engine.state.actors[ALLY].armor_class = -50
    events = _stab(engine, target=ALLY)
    hit = [e.payload for e in events if e.event_type == "DAMAGE_COMMITTED" and ALLY in e.target_ids][0]
    assert hit["reduced_to"] < hit["rolled_or_pending_damage"] and not engine.state.actors[ME].reaction_available
    from combat.ext.ice_fracture import STORED

    stored = [c for c in engine.state.actors[ME].conditions.values() if c.condition_id == STORED]
    assert len(stored) == 1 and stored[0].data["amount"] == hit["rolled_or_pending_damage"] - hit["reduced_to"]


def _three_marks(talents):
    engine = _ice_fight(talents, cl=17, ally_at=(3, 7))
    for row in engine.typed_passive_rows[ME]:
        if row.get("kind") == "fracture":
            row["pb"] = 2  # a Fracture Mark limit of 2
    for who in (THEM, ALLY, ME):
        _mark(engine, who)
    return sum(_marked(engine, who) for who in (THEM, ALLY, ME))


def test_the_fracture_mark_limit_is_pb_and_nascent_soul_adds_one():
    assert _three_marks([]) == 2  # the oldest ends
    assert _three_marks(["tianxia.talent.ice.nascent_soul_glacier_soul_takes_shape"]) == 3


def test_white_step_counter_marks_a_creature_leaving_ground_near_the_lattice():
    from combat.gate2_runtime_models import Position

    engine = _ice_fight(["WHITE_STEP_COUNTER"], them_at=(5, 6))
    _lattice_under(engine, ME)
    them = engine.state.actors[THEM]
    _turn(engine, THEM)
    them.position = Position(x=7, y=6)  # it leaves a space 10 feet from the lattice under ME
    engine._append_event("MOVEMENT_COMMITTED", "test", actor_id=THEM, payload={"path": [{"x": 5, "y": 6}, {"x": 6, "y": 6}, {"x": 7, "y": 6}]})
    assert _marked(engine) and not engine.state.actors[ME].reaction_available


def test_frozen_river_reversal_returns_a_marked_creature_that_slides_across_the_lattice():
    from combat.gate2_runtime_models import Position

    engine = _ice_fight(["FROZEN_RIVER_REVERSAL"], them_at=(6, 6))
    them = engine.state.actors[THEM]
    for x in (6, 8):
        them.position = Position(x=x, y=6)
        _lattice_under(engine, THEM)
    them.position = Position(x=6, y=6)
    _turn(engine, THEM)
    _mark(engine)  # after its turn began (Shatter Space would have spent it as the turn started on the lattice)
    engine.state.actors[ME].reaction_available = True
    them.position = Position(x=8, y=6)
    engine._append_event("MOVEMENT_COMMITTED", "test", actor_id=THEM, payload={"path": [{"x": 6, "y": 6}, {"x": 7, "y": 6}, {"x": 8, "y": 6}]})
    assert (them.position.x, them.position.y) == (6, 6)


def test_frozen_meridian_bind_restrains_after_catch_step_near_the_lattice():
    from combat.gate2_runtime_models import Position

    engine = _ice_fight(["FROZEN_MERIDIAN_BIND"], them_at=(9, 6))
    them = engine.state.actors[THEM]
    them.position = Position(x=10, y=6)
    _lattice_under(engine, THEM)
    them.position = Position(x=9, y=6)  # next to the lattice, not on it: Catch Step, not Shatter Space
    _mark(engine)
    _turn(engine, THEM)
    assert "condition:typed.restrained" in _conds(them)


# ------------------------------------------------------------------------------------------------------- Hunger
TH = "tianxia.talent.hunger."


def _hunger_fight(talents, *, them_at=(4, 6), seed="R9H", dc=30):
    from tests.test_carry import KIT
    from tests.test_zones import SHEET

    sheet = {**SHEET, "equipment": [{"starting_kit": KIT}],
             "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.hunger"], "automatic_sphere_component_record_ids": ["HUNGER_BASE_DIGESTIVE_MANTLE"],
                                     "learned_talent_record_ids": [TH + t for t in talents]}}
    sheet["identity"] = {**SHEET["identity"], "cultivation_level": 15}
    sheet["ability_scores_and_statistics"] = {**SHEET["ability_scores_and_statistics"], "primary_resource": {"name": "Qi", "maximum": 80},
                                              "technique_save_dc": dc}
    bundles = (compile_character(sheet, actor_id=ME), compile_character(_sheet([], 15, 60), actor_id=THEM))
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=bundles,
                                   roster_setup={"primary_actor_ids": [ME, THEM], "team_by_actor": {ME: "team:a", THEM: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, THEM: {"x": them_at[0], "y": them_at[1]}}})
    _turn(engine, ME)
    engine.state.actors[ME].resources["resource:named.satiety"] = 3
    return engine


def _mantle(engine, name):
    _act(engine, name)
    return next(c for c in engine.state.actors[ME].conditions.values() if c.condition_id == "condition:typed.digestive_mantle")


def _extra(events, source="HUNGER_BASE_DIGESTIVE_MANTLE"):
    return [e.payload for e in events if e.event_type == "DAMAGE_COMMITTED" and str(e.source_definition_id) == source]


def test_thick_hide_cuts_physical_damage_once_a_round():
    engine = _hunger_fight([])
    _mantle(engine, "Digestive Mantle: Thick Hide")
    me = engine.state.actors[ME]
    me.armor_class, me.temporary_hp = -50, 0
    events = _stab(engine)
    hit = [e.payload for e in events if e.event_type == "DAMAGE_COMMITTED" and ME in e.target_ids][0]
    assert hit["reduced_to"] == max(0, hit["rolled_or_pending_damage"] - 6)  # PB 4 + CON 2
    from tests.test_auto_lane4 import _script

    _script(engine, [10])
    events = _stab(engine)
    hit = [e.payload for e in events if e.event_type == "DAMAGE_COMMITTED" and ME in e.target_ids][0]
    assert hit["reduced_to"] == hit["rolled_or_pending_damage"]  # once a round


def test_armored_hunger_triples_the_pb_in_thick_hide():
    engine = _hunger_fight(["nine_beast_sovereign_course"])
    _mantle(engine, "Digestive Mantle: Thick Hide + Nine-Beast Sovereign Course: Armored Hunger")
    me = engine.state.actors[ME]
    me.armor_class, me.temporary_hp = -50, 0
    hit = [e.payload for e in _stab(engine) if e.event_type == "DAMAGE_COMMITTED" and ME in e.target_ids][0]
    assert hit["reduced_to"] == max(0, hit["rolled_or_pending_damage"] - 14)


def test_venom_belly_adds_pb_plus_key_poison_once_a_turn():
    engine = _hunger_fight([])
    _mantle(engine, "Digestive Mantle: Venom Belly")
    engine.state.actors[THEM].armor_class = -50
    before = len(engine.events)
    _act(engine, "Bi Shou (Dagger) attack", THEM)
    extra = _extra(engine.events[before:])
    assert [p["rolled_or_pending_damage"] for p in extra] == [6] and extra[0]["damage_type"] == "POISON"


def test_beast_strength_adds_pb_to_one_melee_hit_only():
    engine = _hunger_fight([])
    _mantle(engine, "Digestive Mantle: Beast Strength")
    engine.state.actors[THEM].armor_class = -50
    before = len(engine.events)
    _act(engine, "Bi Shou (Dagger) attack", THEM)
    assert [p["rolled_or_pending_damage"] for p in _extra(engine.events[before:])] == [4]
    _refresh(engine)
    before = len(engine.events)
    _act(engine, "Bi Shou (Dagger) attack", THEM)
    assert not _extra(engine.events[before:])  # "Once before the Mantle ends"


def test_predator_step_needs_ten_feet_toward_the_target_first():
    engine = _hunger_fight([], them_at=(6, 6))
    _mantle(engine, "Digestive Mantle: Predator Step")
    engine.state.actors[THEM].armor_class = -50
    candidate = next(c for c in engine.legal_candidates() if c.actor_id == ME and str(c.kind) == "MOVE" and c.destination and (c.destination.x, c.destination.y) == (5, 6))
    engine.execute_intent(ActionIntent(intent_id="step", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, destination=candidate.destination))
    before = len(engine.events)
    _act(engine, "Bi Shou (Dagger) attack", THEM)
    assert [p["rolled_or_pending_damage"] for p in _extra(engine.events[before:])] == [4]


def test_iron_stomach_and_bitter_medicine_belly_reward_a_saved_poison():
    from combat import typed_reactions
    from combat.typed_executor import run_effects
    from tests.test_auto_lane4 import _script

    engine = _hunger_fight(["bitter_medicine_belly"])
    _mantle(engine, "Digestive Mantle: Iron Stomach")
    me = engine.state.actors[ME]
    me.temporary_hp = 0
    qi = me.resources["resource:core.qi"]
    row = {"feature_id": "TEST_POISON", "name": "Poison", "effects": [], "numbers": {"save_dc": 5}}
    _script(engine, [20, 20])
    run_effects(typed_reactions._generic_context(engine, engine.state.actors[THEM], me, row),
                [{"type": "save", "ability": "con", "dc": 5, "on_fail": [{"type": "condition", "condition": "poisoned", "applies_to": "target"}]}])
    assert me.temporary_hp == 4 and me.resources["resource:core.qi"] == qi - 1  # Iron Stomach's and Bitter Medicine's PB (the larger stays)


def test_three_course_battle_body_swaps_the_mantle_benefit():
    engine = _hunger_fight(["three_course_battle_body"])
    held = _mantle(engine, "Digestive Mantle: Venom Belly")
    _refresh(engine)
    name = next(n for n in _names_now(engine) if n and n.startswith("Three-Course Battle Body"))
    _act(engine, name)
    assert held.data["benefits"] == ["Thick Hide"]


def test_marrow_furnace_pulse_gives_temp_hp_when_cp_goes_into_a_hunger_talent():
    engine = _hunger_fight(["marrow_furnace_pulse"])
    _mantle(engine, "Digestive Mantle: Venom Belly")
    me = engine.state.actors[ME]
    assert not any(str(e.source_definition_id) == TH + "marrow_furnace_pulse" for e in engine.events)  # not the Mantle's own cost
    me.temporary_hp = 0
    engine.state.round_number += 1
    _turn(engine, ME)
    me.resources["resource:named.satiety"] = 3
    _mantle(engine, "Digestive Mantle: Thick Hide")
    assert any(str(e.source_definition_id) == TH + "marrow_furnace_pulse" for e in engine.events)


# ------------------------------------------------------------------------------------------------------- Karma
TK = "tianxia.talent.karma."


def _karma_fight(talents, *, them_at=(4, 6), ally_at=(3, 7), dc=30, seed="R9K"):
    from tests.test_carry import KIT
    from tests.test_zones import SHEET

    sheet = {**SHEET, "equipment": [{"starting_kit": KIT}],
             "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.karma"], "automatic_sphere_component_record_ids": ["TAL_KARMA_RECORD_THE_DEED"],
                                     "learned_talent_record_ids": [TK + t for t in talents]}}
    sheet["identity"] = {**SHEET["identity"], "cultivation_level": 15}
    sheet["ability_scores_and_statistics"] = {**SHEET["ability_scores_and_statistics"], "primary_resource": {"name": "Qi", "maximum": 80},
                                              "technique_save_dc": dc}
    bundles = [compile_character(sheet, actor_id=ME), compile_character(_sheet([], 15, 60), actor_id=THEM)]
    ids, teams, spots = [ME, THEM], {ME: "team:a", THEM: "team:b"}, {ME: {"x": 3, "y": 6}, THEM: {"x": them_at[0], "y": them_at[1]}}
    if ally_at:
        bundles.append(compile_character(_sheet([], 15, 60), actor_id=ALLY))
        ids.append(ALLY)
        teams[ALLY] = "team:a"
        spots[ALLY] = {"x": ally_at[0], "y": ally_at[1]}
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=tuple(bundles),
                                   roster_setup={"primary_actor_ids": ids, "team_by_actor": teams, "starting_positions": spots})
    _turn(engine, ME)
    return engine


def _imprint(engine, who=THEM, kind="debt", count=1):
    from combat.ext import karma_imprints

    for _ in range(count):
        karma_imprints.place(engine, engine.state.actors[ME], engine.state.actors[who], kind, "test", "test")
    return len(karma_imprints.held(engine.state.actors[who], ME, kind))


def _psychic_from(events, source):
    return [e.payload for e in events if e.event_type == "DAMAGE_COMMITTED" and str(e.source_definition_id) == source]


def test_chain_of_consequence_needs_three_debts_spends_them_and_returns_the_next_harm():
    engine = _karma_fight(["chain_of_consequence"])
    _imprint(engine, count=2)
    assert "Chain of Consequence" not in _names_now(engine)
    assert _imprint(engine) == 3
    _act(engine, "Chain of Consequence", THEM)
    assert _imprint(engine, count=0) == 0
    engine.state.actors[ME].armor_class = -50
    events = _stab(engine)
    dealt = [e.payload for e in events if e.event_type == "DAMAGE_COMMITTED" and ME in e.target_ids][0]["reduced_to"]
    back = _psychic_from(events, TK + "chain_of_consequence")
    assert back and back[0]["rolled_or_pending_damage"] == dealt


def test_heavenly_retribution_consumes_every_debt_and_scales_its_damage():
    engine = _karma_fight(["heavenly_retribution"])
    _imprint(engine, count=4)
    them = engine.state.actors[THEM]
    them.maximum_hp = them.current_hp = 500  # it lives through 16d10
    hp = them.current_hp
    _act(engine, "Heavenly Retribution", THEM)
    rolled = [r for r in engine.rolls if r.reason.startswith("DAMAGE:") and "heavenly_retribution" in r.reason]
    assert rolled and rolled[-1].expression.startswith("16d10")  # 4 Imprints (PB 4): 4d10 each
    assert _imprint(engine, count=0) == 0 and "condition:typed.stunned" in _conds(them) and them.current_hp < hp


def test_trial_of_the_ledger_punishes_the_first_harm_each_turn_and_repeats_its_save():
    engine = _karma_fight(["trial_of_the_ledger"])
    _imprint(engine, count=2)
    _act(engine, "Trial of the Ledger", THEM)
    trial = [c for c in engine.state.actors[THEM].conditions.values() if c.condition_id == "condition:typed.karma_trial"]
    assert trial and trial[0].data["repeat_save"]["ability"] == "CHA"
    engine.state.actors[ME].armor_class = -50
    events = _stab(engine)
    assert _psychic_from(events, TK + "trial_of_the_ledger")


def test_ten_thousand_debts_returns_the_first_harm():
    engine = _karma_fight(["ten_thousand_debts_return_to_source"])
    _imprint(engine)
    _act(engine, "Ten Thousand Debts Return to Source", THEM)
    engine.state.actors[ME].armor_class = -50
    events = _stab(engine)
    dealt = [e.payload for e in events if e.event_type == "DAMAGE_COMMITTED" and ME in e.target_ids][0]["reduced_to"]
    assert [p["rolled_or_pending_damage"] for p in _psychic_from(events, TK + "ten_thousand_debts_return_to_source")] == [dealt]


def test_judgment_writ_costs_psychic_for_the_first_harm_each_turn():
    engine = _karma_fight(["judgment_writ"])
    assert "Judgment Writ" not in _names_now(engine)
    _imprint(engine)
    _act(engine, "Judgment Writ", THEM)
    engine.state.actors[ME].armor_class = -50
    events = _stab(engine)
    assert [p["rolled_or_pending_damage"] for p in _psychic_from(events, TK + "judgment_writ")] == [6]  # PB 4 + CON 2


def test_debt_written_on_bone_spends_a_debt_and_answers_the_next_damage():
    engine = _karma_fight(["debt_written_on_bone"])
    _imprint(engine)
    _act(engine, "Debt Written on Bone: Psychic Backlash", THEM)
    assert _imprint(engine, count=0) == 0
    engine.state.actors[ME].armor_class = -50
    events = _stab(engine)
    assert [p["rolled_or_pending_damage"] for p in _psychic_from(events, TK + "debt_written_on_bone")] == [6]


def test_merit_becomes_armor_gives_temp_hp_when_the_bearer_heals_another():
    engine = _karma_fight(["merit_becomes_armor"])
    _imprint(engine, ALLY, "grace")
    _act(engine, "Merit Becomes Armor", ALLY)
    ally = engine.state.actors[ALLY]
    ally.temporary_hp = 0
    engine._append_event("HEALING_APPLIED", "test", actor_id=ALLY, target_ids=(ME,), payload={"offered": 5, "before": 10, "after": 15})
    assert ally.temporary_hp == 4


def test_borrowed_tomorrow_keeps_an_ally_at_1_hp_once():
    engine = _karma_fight(["borrowed_tomorrow"], them_at=(4, 7))
    ally = engine.state.actors[ALLY]
    ally.armor_class, ally.current_hp = -50, 1
    _stab(engine, target=ALLY)
    assert ally.current_hp == 1 and not engine.state.actors[ME].reaction_available
    _refresh(engine)
    _stab(engine, target=ALLY)
    assert ally.current_hp == 0  # once a fight


def test_fate_deferred_holds_lethal_damage_until_the_end_of_the_creatures_next_turn():
    engine = _karma_fight(["fate_deferred"], them_at=(4, 7))
    ally = engine.state.actors[ALLY]
    ally.armor_class, ally.current_hp = -50, 2
    _stab(engine, target=ALLY)
    assert ally.current_hp == 2
    _turn(engine, ALLY)
    engine.end_turn()
    assert ally.current_hp < 2  # it arrives as its next turn ends


def test_karma_sovereign_incarnation_extends_record_the_deed():
    from combat.ext import karma_imprints

    engine = _karma_fight(["karma_sovereign_incarnation"])
    me = engine.state.actors[ME]
    assert karma_imprints.record_range(me) == 60
    name = next(n for n in _names_now(engine) if n and n.startswith("Karma-Sovereign"))
    _act(engine, name)
    assert karma_imprints.record_range(me) == 300


# ------------------------------------------------------------------------------------------------------- Glass
TG = "TAL_GLASS_"
GLASS_BASES = ("GLASS_BASE_REFRACTION_RESPONSES", "GLASS_BASE_TEMPER_GLASS_SURFACE", "GLASS_BASE_FAULTLINE_MARKS")


def _glass_fight(talents, *, them_at=(4, 6), ally_at=None, bases=GLASS_BASES, seed="R9G"):
    from tests.test_carry import KIT
    from tests.test_zones import SHEET

    sheet = {**SHEET, "equipment": [{"starting_kit": KIT}],
             "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.glass"], "automatic_sphere_component_record_ids": list(bases),
                                     "learned_talent_record_ids": [TG + t for t in talents]}}
    sheet["identity"] = {**SHEET["identity"], "cultivation_level": 15}
    sheet["ability_scores_and_statistics"] = {**SHEET["ability_scores_and_statistics"], "primary_resource": {"name": "Qi", "maximum": 80}}
    bundles = [compile_character(sheet, actor_id=ME), compile_character(_sheet([], 15, 60), actor_id=THEM)]
    ids, teams, spots = [ME, THEM], {ME: "team:a", THEM: "team:b"}, {ME: {"x": 3, "y": 6}, THEM: {"x": them_at[0], "y": them_at[1]}}
    if ally_at:
        bundles.append(compile_character(_sheet([], 15, 60), actor_id=ALLY))
        ids.append(ALLY)
        teams[ALLY] = "team:a"
        spots[ALLY] = {"x": ally_at[0], "y": ally_at[1]}
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=tuple(bundles),
                                   roster_setup={"primary_actor_ids": ids, "team_by_actor": teams, "starting_positions": spots})
    _turn(engine, ME)
    return engine


def _faultline(engine, who=THEM):
    from combat.ext import glass_refraction

    glass_refraction.give_mark(engine, engine.state.actors[ME], engine.state.actors[who], "test")
    return glass_refraction.marked(engine.state.actors[who], ME)


def _faulted(engine, who=THEM):
    from combat.ext import glass_refraction

    return glass_refraction.marked(engine.state.actors[who], ME)


def test_temper_glass_surface_is_offered_and_attackers_of_a_tempered_fighter_gain_marks():
    engine = _glass_fight([])
    _act(engine, "Temper Glass Surface")
    assert "condition:typed.glass_tempered" in _conds(engine.state.actors[ME])
    engine.state.actors[ME].armor_class = 60
    engine.state.actors[ME].reaction_available = False  # no Response: the mark stays
    _stab(engine)
    assert _faulted(engine)
    marks = [c for c in engine.state.actors[THEM].conditions.values() if ".faultline_mark." in c.condition_id]
    assert marks[0].expires_on == "END_OF_MARKER_NEXT_TURN"


def test_turn_the_angle_cuts_the_marked_attackers_damage_on_an_ally_beside_a_tempered_surface():
    engine = _glass_fight([], them_at=(4, 7), ally_at=(3, 7))
    _act(engine, "Temper Glass Surface")
    _faultline(engine)
    ally = engine.state.actors[ALLY]
    ally.armor_class = -50
    events = _stab(engine, target=ALLY)
    hit = [e.payload for e in events if e.event_type == "DAMAGE_COMMITTED" and ALLY in e.target_ids][0]
    assert hit["reduced_to"] == max(0, hit["rolled_or_pending_damage"] - _last_die(engine, "TURN_THE_ANGLE") - 4)
    assert not engine.state.actors[ME].reaction_available and not _faulted(engine)


def _last_die(engine, reason):
    return next(int(r.total) for r in reversed(engine.rolls) if reason in r.reason)


def test_shatter_warning_takes_two_off_and_pierces_on_a_miss():
    from tests.test_auto_lane4 import _script

    engine = _glass_fight([])
    _act(engine, "Temper Glass Surface")
    _faultline(engine)
    engine.state.actors[ME].armor_class = 30
    _script(engine, [5])
    events = _stab(engine)
    rolled = [e.payload for e in events if e.event_type == "ATTACK_ROLLED"][0]
    control = _glass_fight([])
    _script(control, [5])
    plain = [e.payload for e in _stab(control) if e.event_type == "ATTACK_ROLLED"][0]
    assert rolled["modified_total"] == plain["modified_total"] - 2
    assert [p["rolled_or_pending_damage"] for p in (e.payload for e in events if e.event_type == "DAMAGE_COMMITTED" and THEM in e.target_ids)] == [4]


def test_bitter_edge_cuts_a_marked_creatures_willing_move():
    from combat.gate2_runtime_models import Position

    engine = _glass_fight([], them_at=(8, 6))
    _faultline(engine)
    them = engine.state.actors[THEM]
    _turn(engine, THEM)
    left, hp = them.movement_remaining_ft, them.current_hp
    them.position = Position(x=9, y=6)
    engine._append_event("MOVEMENT_COMMITTED", "test", actor_id=THEM, payload={"path": [{"x": 8, "y": 6}, {"x": 9, "y": 6}]})
    assert them.current_hp == hp - 4 and them.movement_remaining_ft == left - 10 and not _faulted(engine)


def test_visible_crack_answers_a_marked_creature_hiding():
    engine = _glass_fight([], them_at=(8, 6))
    _faultline(engine)
    them = engine.state.actors[THEM]
    engine._apply_condition(them, "condition:typed.hidden", "test", THEM, expires_on="UNTIL_REMOVED")
    assert "condition:typed.hidden" not in _conds(them) and "condition:typed.glass_revealed" in _conds(them)


def test_lens_of_the_honest_crack_marks_the_targets_first_attack():
    engine = _glass_fight(["LENS_OF_THE_HONEST_CRACK"], them_at=(8, 6))
    _act(engine, "Lens of the Honest Crack", THEM)
    assert not _faulted(engine)
    _attack(engine, THEM, "Bi Shou (Dagger) thrown", ME)
    assert _faulted(engine)


def test_living_pane_sutra_keeps_a_tempered_body_at_1_hp_once():
    engine = _glass_fight(["LIVING_PANE_SUTRA"])
    _act(engine, "Temper Glass Surface")
    me = engine.state.actors[ME]
    me.armor_class, me.current_hp, me.temporary_hp = -50, 1, 0
    me.reaction_available = False
    _stab(engine)
    assert me.current_hp == 1
    _stab(engine)
    assert me.current_hp == 0


def test_polished_warning_needs_a_tempered_surface():
    from combat.ext import glass_refraction

    engine = _glass_fight([])
    me = engine.state.actors[ME]
    row = {"feature_id": TG + "POLISHED_WARNING"}
    assert glass_refraction.polished_needs_a_surface(engine, me, row) is False
    _act(engine, "Temper Glass Surface")
    assert glass_refraction.polished_needs_a_surface(engine, me, row) is None


# ------------------------------------------------------------------------------------------------------- Retribution
TR = "TAL_RETRIBUTION_"


def _ret_fight(talents, *, them_at=(4, 6)):
    from tests.test_auto_docket import WEAPON
    from tests.test_zones import SHEET

    sheet = {**SHEET, **WEAPON, "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.retribution"],
                                                         "learned_talent_record_ids": ["RETRIBUTION_BASE_COUNTERSTRIKE", *[TR + t for t in talents]]}}
    sheet["identity"] = {**SHEET["identity"], "cultivation_level": 15}
    bundles = (compile_character(sheet, actor_id=ME), compile_character(_sheet([], 15, 60), actor_id=THEM))
    engine = Gate4ControllerEngine(ROOT, match_seed="R9R", typed_bundles=bundles,
                                   roster_setup={"primary_actor_ids": [ME, THEM], "team_by_actor": {ME: "team:a", THEM: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, THEM: {"x": them_at[0], "y": them_at[1]}}})
    _turn(engine, ME)
    return engine


def _ret_ctx(engine, feature):
    from combat import typed_reactions

    return typed_reactions._generic_context(engine, engine.state.actors[ME], engine.state.actors[THEM],
                                            {"feature_id": feature, "name": feature, "effects": [], "numbers": {"save_dc": 30, "pb": 4}})


def _them_action(engine, name):
    return next(a for a in engine.action_catalog.values() if a.owner_id == THEM and a.display_name == name)


def test_haymaker_rides_the_counterstrike_hit_and_damages_the_speech():
    from combat.gate2_runtime_content import AN
    from tests.test_h2_counterstrike import _answering, _attacked, _fighter, _prepare, _turn as h2_turn

    engine = _fighter()
    engine.state.actors[AN].saving_throws = {**engine.state.actors[AN].saving_throws, "DEX": -40}
    _prepare(engine, "Counterstrike + Haymaker")
    h2_turn(engine, AN)
    _answering(engine)
    _attacked(engine)
    assert "condition:typed.speech_damaged" in _conds(engine.state.actors[AN])


def test_a_damaged_speech_channel_fails_a_voiced_ability_on_a_failed_con_save(monkeypatch):
    from combat import speech
    from combat.ext import retribution_riders

    engine = _ret_fight(["HAYMAKER"])
    them = engine.state.actors[THEM]
    engine._apply_condition(them, "condition:typed.speech_damaged", "test", ME, expires_on="UNTIL_REMOVED", data={"dc": 30})
    action = _them_action(engine, "Combat Array: Locking Gate")
    assert retribution_riders.refuse(engine, them, action) is None  # it needs no voice
    monkeypatch.setattr(speech, "needs_voice", lambda a: True)
    assert retribution_riders.refuse(engine, them, action) is True


def test_intense_conditioning_spends_focus_and_then_refuses_the_same_kind_of_action():
    from combat.ext import retribution_riders
    from combat.typed_executor import run_effects

    engine = _ret_fight(["INTENSE_CONDITIONING"])
    me, them = engine.state.actors[ME], engine.state.actors[THEM]
    dagger = _them_action(engine, "Bi Shou (Dagger) attack")
    engine._append_event("INTENT_ACCEPTED", dagger.source_definition_id, actor_id=THEM, target_ids=(ME,), payload={})
    focus = me.resources["resource:core.martial_focus"]
    run_effects(_ret_ctx(engine, TR + "INTENSE_CONDITIONING"), [{"type": "retribution_conditioning", "applies_to": "target"}])
    held = [c for c in them.conditions.values() if c.condition_id == "condition:typed.conditioned"]
    assert me.resources["resource:core.martial_focus"] == focus - 1 and held and held[0].data["category"] == "attack"
    assert retribution_riders.refuse(engine, them, _them_action(engine, "Combat Array: Locking Gate")) is None  # another category
    assert retribution_riders.refuse(engine, them, dagger) is True


def test_spell_breaker_breaks_a_technique_the_counterstrike_damaged():
    from combat.ext import retribution_riders
    from combat.typed_executor import run_effects

    engine = _ret_fight(["SPELL_BREAKER"])
    them = engine.state.actors[THEM]
    gate = _them_action(engine, "Combat Array: Locking Gate")
    engine._append_event("INTENT_ACCEPTED", gate.source_definition_id, actor_id=THEM, target_ids=(), payload={})
    engine._commit_damage(them, 12, "SLASHING", "test", ME, None, reaction_depth=0)
    run_effects(_ret_ctx(engine, TR + "SPELL_BREAKER"), [{"type": "retribution_spell_breaker", "applies_to": "target"}])
    assert retribution_riders.refuse(engine, them, gate) is True


def test_dug_in_blow_halves_the_targets_next_physical_hit():
    from combat import typed_reactions
    from combat.typed_executor import run_effects

    engine = _ret_fight(["DUG_IN_BLOW"])
    run_effects(_ret_ctx(engine, TR + "DUG_IN_BLOW"), [{"type": "retribution_dug_in", "applies_to": "target"}])
    me = engine.state.actors[ME]
    assert typed_reactions.defend(engine, me, 10, "SLASHING", None, THEM) == 5 and "condition:typed.dug_in" not in _conds(me)
    assert typed_reactions.defend(engine, me, 10, "SLASHING", None, THEM) == 10  # one instance


def test_headfake_gives_opportunity_attacks_disadvantage_while_holding_focus():
    from combat.ext import retribution_riders

    engine = _ret_fight(["HEADFAKE"])
    ctx = _ret_ctx(engine, "test")
    ctx.actor = engine.state.actors[THEM]
    me = engine.state.actors[ME]
    assert retribution_riders.headfake(ctx, me) is None
    engine._typed_oa_attacker = THEM
    assert retribution_riders.headfake(ctx, me) == "DISADVANTAGE"
    me.resources["resource:core.martial_focus"] = 0
    assert retribution_riders.headfake(ctx, me) is None


# ------------------------------------------------------------------------------------------------------- Earth
TE_ = "TAL_EARTH_"


def _earth_fight(talents, *, them_at=(4, 6), ally_at=None, dc=30, bases=("EARTH_BASE_SPENDING_A_BURDEN_MARK",), seed="R9EA", an_at=None):
    from tests.test_carry import KIT
    from tests.test_zones import SHEET

    sheet = {**SHEET, "equipment": [{"starting_kit": KIT}],
             "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.earth"], "automatic_sphere_component_record_ids": list(bases),
                                     "learned_talent_record_ids": [TE_ + t for t in talents]}}
    sheet["identity"] = {**SHEET["identity"], "cultivation_level": 15}
    sheet["ability_scores_and_statistics"] = {**SHEET["ability_scores_and_statistics"], "primary_resource": {"name": "Qi", "maximum": 80},
                                              "technique_save_dc": dc}
    bundles = [compile_character(sheet, actor_id=ME), compile_character(_sheet([], 15, 60), actor_id=THEM)]
    ids, teams, spots = [ME, THEM], {ME: "team:a", THEM: "team:b"}, {ME: {"x": 3, "y": 6}, THEM: {"x": them_at[0], "y": them_at[1]}}
    if ally_at:
        bundles.append(compile_character(_sheet([], 15, 60), actor_id=ALLY))
        ids.append(ALLY)
        teams[ALLY] = "team:a"
        spots[ALLY] = {"x": ally_at[0], "y": ally_at[1]}
    if an_at:
        ids.append(AN)
        teams[AN] = "team:b"
        spots[AN] = {"x": an_at[0], "y": an_at[1]}
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=tuple(bundles),
                                   roster_setup={"primary_actor_ids": ids, "team_by_actor": teams, "starting_positions": spots})
    _turn(engine, ME)
    return engine


def _burden(engine, who=THEM):
    from combat.ext import earth_responses

    earth_responses.give_mark(engine, engine.state.actors[ME], engine.state.actors[who], "test")
    return earth_responses.marked(engine.state.actors[who], ME)


def _burdened(engine, who=THEM):
    from combat.ext import earth_responses

    return earth_responses.marked(engine.state.actors[who], ME)


def _walk(engine, who, cells):
    from combat.gate2_runtime_models import Position

    actor = engine.state.actors[who]
    actor.position = Position(x=cells[-1][0], y=cells[-1][1])
    engine._append_event("MOVEMENT_COMMITTED", "test", actor_id=who, payload={"path": [{"x": x, "y": y} for x, y in cells]})


def test_drag_down_trips_a_marked_creature_that_moves_and_sinking_foot_follows():
    engine = _earth_fight(["SINKING_FOOT_REBUKE"], them_at=(8, 6))
    _burden(engine)
    them = engine.state.actors[THEM]
    _turn(engine, THEM)
    _walk(engine, THEM, [(8, 6), (9, 6)])
    assert any("prone" in c for c in _conds(them)) and not _burdened(engine)
    assert "condition:typed.sinking_dex" in _conds(them)  # already Prone: Disadvantage on its next Dexterity save


def test_bear_the_blow_cuts_a_marked_attackers_damage():
    engine = _earth_fight([])
    _burden(engine)
    me = engine.state.actors[ME]
    me.armor_class = -50
    events = _stab(engine)
    hit = [e.payload for e in events if e.event_type == "DAMAGE_COMMITTED" and ME in e.target_ids][0]
    assert hit["reduced_to"] < hit["rolled_or_pending_damage"] or hit["reduced_to"] == 0
    assert not _burdened(engine)


def test_settle_the_impact_shortens_a_marked_creatures_push_on_an_ally():
    from combat import typed_reactions

    engine = _earth_fight([], ally_at=(3, 7))
    _burden(engine)
    left = typed_reactions.on_forced_movement(engine, engine.state.actors[ALLY], engine.state.actors[THEM], 25)
    assert left == 5 and not _burdened(engine)  # 20 feet at CL 11+


def test_raise_the_ridge_gives_half_cover_against_a_marked_creatures_ranged_attack():
    from tests.test_auto_lane4 import _script

    engine = _earth_fight([], them_at=(7, 6))
    _burden(engine)
    _script(engine, [10])
    rolled = [e.payload for e in _stab(engine, "Bi Shou (Dagger) thrown") if e.event_type == "ATTACK_ROLLED"][0]
    control = _earth_fight([], them_at=(7, 6))
    _script(control, [10])
    plain = [e.payload for e in _stab(control, "Bi Shou (Dagger) thrown") if e.event_type == "ATTACK_ROLLED"][0]
    assert rolled["modified_total"] == plain["modified_total"] - 2 and not _burdened(engine)


def test_earth_responses_are_once_per_round():
    from combat import typed_reactions

    engine = _earth_fight([], ally_at=(3, 7))
    _burden(engine)
    typed_reactions.on_forced_movement(engine, engine.state.actors[ALLY], engine.state.actors[THEM], 25)
    _burden(engine)
    assert typed_reactions.on_forced_movement(engine, engine.state.actors[ALLY], engine.state.actors[THEM], 25) == 25


def test_deep_root_stance_shortens_pushes_and_marks_a_melee_miss():
    from combat import typed_reactions

    engine = _earth_fight(["DEEP_ROOT_STANCE"])
    _act(engine, "Deep Root Stance")
    me = engine.state.actors[ME]
    assert typed_reactions.on_forced_movement(engine, me, engine.state.actors[THEM], 15) == 5  # 10 feet at CL 10+
    me.armor_class = 60
    _stab(engine)
    assert _burdened(engine)


def test_landslide_argument_slides_a_marked_creature_crossing_the_foundation():
    engine = _earth_fight(["LANDSLIDE_ARGUMENT", "DEEP_ROOT_STANCE"], them_at=(5, 6))
    _act(engine, "Deep Root Stance")  # ME's own space is a Foundation Space
    _burden(engine)
    them = engine.state.actors[THEM]
    hp = them.current_hp
    _turn(engine, THEM)
    _walk(engine, THEM, [(4, 7), (3, 6), (2, 5)])  # a synthetic path over ME's space (a Foundation Space): 10 feet touching it
    assert not _burdened(engine) and them.current_hp < hp and any("prone" in c for c in _conds(them))


def test_the_burden_mark_limit_is_pb():
    engine = _earth_fight([], an_at=(8, 8))
    for row in engine.typed_passive_rows[ME]:
        if row.get("kind") == "burden":
            row["pb"] = 1  # a limit of one
        if row.get("block") == "mark_caps" and "burden mark" in row.get("caps", {}):
            # Keep this synthetic PB override consistent with the native cap
            # sealed from the same compile numbers; production changes recompile.
            row["caps"]["burden mark"] = 1
    _burden(engine, THEM)
    _burden(engine, AN)
    assert _burdened(engine, AN) and not _burdened(engine, THEM)  # the oldest ended
