"""A2R09 (automation pass, non-sphere abilities): the Ninpo Adept residual.

Shadow Clone Array (creation, Clone Interposition, the array benefits, Replace a
Clone, Clone Assault Misdirection), Vanishing Technique's Harmful Action lifecycle
and its 30-foot forms, Shadow Step's next-Stealth Advantage, and Smoke Veil's
PB-chosen Lightly Obscured roster (combat/ext/tabik_ninpo.py)."""

from pathlib import Path

import pytest

from combat import zones
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_carry import KIT
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.tabik"
FOE = "actor:factory.foe"

NINPO = ["tianxia.subpath.qi.ninpo_adept.feature.shadow_step",
         "tianxia.subpath.qi.ninpo_adept.feature.smoke_veil",
         "tianxia.subpath.qi.ninpo_adept.feature.hidden_strike",
         "tianxia.subpath.qi.ninpo_adept.feature.shadow_clone_array",
         "tianxia.subpath.qi.ninpo_adept.feature.vanishing_technique",
         "tianxia.subpath.body.shinobi.feature.shadow_afterimage",
         "tianxia.subpath.body.shinobi.feature.pressure_point_strike"]


def _ninja(*, with_array=True, with_vanishing=True, seed="A2R09"):
    features = [feature for feature in NINPO
                if (with_array or "shadow_clone_array" not in feature)
                and (with_vanishing or "vanishing_technique" not in feature)]
    me_sheet = {**SHEET, "equipment": [{"starting_kit": KIT}],
                "path_and_subpath": {"path_feature_record_ids": features},
                "spheres_and_talents": {"sphere_record_ids": [], "learned_talent_record_ids": []}}
    foe_sheet = {**SHEET, "equipment": [{"starting_kit": KIT}],
                 "spheres_and_talents": {"sphere_record_ids": [], "learned_talent_record_ids": []}}
    mine, theirs = compile_character(me_sheet, actor_id=ME), compile_character(foe_sheet, actor_id=FOE)
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=(mine, theirs),
                                       roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                                                     "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}}})
    _turn(engine, ME)
    return engine


def _turn(engine, actor_id):
    """Jump the initiative to ``actor_id``, wrapping rounds like ``end_turn``.

    Setting the slot directly keeps end-of-turn expiry out of the scenario
    (the 1-minute states outlive a jump), but a wrap to slot 0 must still
    start a new round: once-per-round limits compare the round number.
    """
    index = engine.state.initiative_order.index(actor_id)
    if index <= engine.state.current_slot_index:
        engine.state.round_number += 1
        engine._append_event("ROUND_STARTED", "system:turn", payload={"round": engine.state.round_number})
    engine.state.current_slot_index = index
    engine.state.current_actor_id = actor_id
    engine._system_start_turn()


def _act(engine, name, *, actor=ME, bonus=None, at=None):
    candidate = next(c for c in engine.legal_candidates() if c.actor_id == actor
                     and c.source_definition_id in engine.action_catalog
                     and engine.action_catalog[c.source_definition_id].display_name == name
                     and (at is None or (c.destination is not None
                                          and (c.destination.x, c.destination.y) == at)))
    if bonus is not None:
        typed = engine.action_catalog[candidate.source_definition_id].parameters["typed"]
        typed["numbers"] = {**typed["numbers"], "attack_bonus": bonus}
    engine.execute_intent(ActionIntent(intent_id=f"{name}{engine.state.event_sequence}",
                                         decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                         state_version=candidate.state_version, actor_id=actor,
                                         target_ids=candidate.target_ids, destination=candidate.destination))


def _foe_attack(engine, bonus=40):
    attack = next(c for c in engine.legal_candidates() if c.actor_id == FOE
                  and c.source_definition_id in engine.action_catalog
                  and ".weapon." in c.source_definition_id
                  and (engine.action_catalog[c.source_definition_id].range_ft or 5) <= 5
                  and ME in (c.target_ids or ()))
    typed = engine.action_catalog[attack.source_definition_id].parameters["typed"]
    typed["numbers"] = {**typed["numbers"], "attack_bonus": bonus}
    engine.execute_intent(ActionIntent(intent_id=f"foe-atk{engine.state.event_sequence}",
                                         decision_id=attack.decision_id, candidate_id=attack.candidate_id,
                                         state_version=attack.state_version, actor_id=FOE, target_ids=attack.target_ids))


def _conditions(actor, condition_id):
    return [held for held in actor.conditions.values() if held.condition_id == condition_id]


def _clone_state(engine):
    return _conditions(engine.state.actors[ME], "condition:typed.shadow_clone_array")


def _clone_count(engine):
    held = _clone_state(engine)
    return int((held[0].data or {}).get("clones") or 0) if held else 0


def _offered(engine, actor=ME):
    return {getattr(engine.action_catalog.get(c.source_definition_id), "display_name", None)
            for c in engine.legal_candidates()
            if c.actor_id == actor and c.source_definition_id in engine.action_catalog}


# ------------------------------------------------------------------------------------------------ Shadow Clone Array
def test_shadow_clone_array_activation_creates_two_clones_once_per_scene():
    engine = _ninja()
    me = engine.state.actors[ME]
    assert not _clone_state(engine)
    assert "Shadow Clone Array" in _offered(engine)
    assert sum(1 for action in engine.action_catalog.values() if action.owner_id == ME
               and action.display_name == "Shadow Clone Array") == 1
    _act(engine, "Shadow Clone Array")
    me = engine.state.actors[ME]
    assert _clone_count(engine) == 2
    assert me.resources["resource:core.qi"] == SHEET["ability_scores_and_statistics"]["primary_resource"]["maximum"] - 7
    assert "Shadow Clone Array" not in _offered(engine)  # once per scene
    _turn(engine, FOE)
    _turn(engine, ME)
    assert "Shadow Clone Array" not in _offered(engine)  # ...for the whole scene, not just the turn


def test_clone_interposition_makes_a_hitting_attack_miss_and_spends_a_clone():
    engine = _ninja()
    _act(engine, "Shadow Clone Array")
    _turn(engine, FOE)
    _foe_attack(engine, bonus=40)  # a natural hit against the ninja's AC
    assert _clone_count(engine) == 1
    assert not [event for event in engine.events
                if event.event_type == "DAMAGE_COMMITTED" and event.actor_id == FOE]
    assert any("destroys a Shadow Clone" in str((event.payload or {}).get("log") or "")
               for event in engine.events if event.event_type == "PASSIVE_TRIGGERED")


def test_clone_interposition_is_once_per_round():
    engine = _ninja()
    _act(engine, "Shadow Clone Array")
    _turn(engine, FOE)
    _foe_attack(engine, bonus=40)  # interposes: the first hit misses
    assert _clone_count(engine) == 1
    engine.state.actors[FOE].action_available = True  # a second attack in the same round
    _foe_attack(engine, bonus=40)  # the second hit in the same round lands
    assert _clone_count(engine) == 1
    assert [event for event in engine.events
            if event.event_type == "DAMAGE_COMMITTED" and event.actor_id == FOE]


def test_no_clone_no_interposition():
    engine = _ninja(with_array=False)
    assert "Shadow Clone Array" not in _offered(engine)
    _turn(engine, FOE)
    _foe_attack(engine, bonus=40)
    assert [event for event in engine.events
            if event.event_type == "DAMAGE_COMMITTED" and event.actor_id == FOE]


def test_hidden_strike_deals_4d6_while_a_clone_remains():
    engine = _ninja()
    _act(engine, "Shadow Clone Array")
    _act(engine, "Unarmed Strike", bonus=40)  # the foe sees the ninja but cannot identify the real image
    foe = engine.state.actors[FOE]
    hidden = [event for event in engine.events
              if event.event_type == "DAMAGE_COMMITTED" and event.actor_id == ME
              and "hidden_strike" in str((event.payload or {}).get("display_source_id") or "")]
    assert hidden and 4 <= int(hidden[0].payload["hp_damage"]) <= 24  # 4d6
    assert any((event.payload or {}).get("trigger") == "Hidden Strike" for event in engine.events)


def test_hidden_strike_does_not_qualify_on_a_seen_target_without_clones():
    engine = _ninja(with_array=False)
    _act(engine, "Unarmed Strike", bonus=40)  # plainly seen, no concealment, no Step this turn
    assert not any((event.payload or {}).get("trigger") == "Hidden Strike" for event in engine.events)


def test_replace_a_clone_restores_one_clone_once_per_activation():
    engine = _ninja()
    _act(engine, "Shadow Clone Array")
    _turn(engine, FOE)
    _foe_attack(engine, bonus=40)  # interposition spent one Clone
    assert _clone_count(engine) == 1
    _turn(engine, ME)
    assert "Replace a Clone" in _offered(engine)
    _act(engine, "Replace a Clone")
    assert _clone_count(engine) == 2
    assert "Replace a Clone" not in _offered(engine)  # once per activation
    engine.state.actors[ME].resources["resource:core.qi"] = 30
    _act(engine, "Unarmed Strike", bonus=40)  # a Harmful Action on the ninja's own turn
    _turn(engine, FOE)
    _foe_attack(engine, bonus=40)
    assert _clone_count(engine) == 1
    _turn(engine, ME)
    # The array is itself once per scene, so its single activation already
    # replaced its Clone: the once-per-activation clock only resets with a
    # new activation, and the scene allows none.
    assert "Replace a Clone" not in _offered(engine)


def test_replace_clone_remains_available_after_both_clones_are_destroyed():
    engine = _ninja()
    _act(engine, "Shadow Clone Array")
    _turn(engine, FOE)
    _foe_attack(engine, bonus=40)
    _turn(engine, ME)
    _turn(engine, FOE)
    _foe_attack(engine, bonus=40)
    assert _clone_count(engine) == 0
    _turn(engine, ME)
    assert "Replace a Clone" in _offered(engine)
    _act(engine, "Replace a Clone")
    assert _clone_count(engine) == 1


def test_shadow_step_array_replaces_the_base_step_while_a_clone_remains():
    engine = _ninja()
    _act(engine, "Smoke Veil", at=(4, 6))  # concealment at both ends of the Step
    engine.state.actors[ME].bonus_action_available = True
    names = _offered(engine)
    assert "Shadow Step" in names and "Shadow Step (Array)" not in names  # no Clones yet
    _act(engine, "Shadow Clone Array")
    engine.state.actors[ME].bonus_action_available = True
    names = _offered(engine)
    assert "Shadow Step (Array)" in names and "Shadow Step" not in names  # the range becomes 60 feet, 0 Qi
    array_step = next(c for c in engine.legal_candidates() if c.actor_id == ME
                      and c.source_definition_id in engine.action_catalog
                      and engine.action_catalog[c.source_definition_id].display_name == "Shadow Step (Array)")
    assert engine.action_catalog[array_step.source_definition_id].range_ft == 60
    assert not engine.action_catalog[array_step.source_definition_id].costs
    _act(engine, "Shadow Step (Array)", at=(5, 6))
    me = engine.state.actors[ME]
    assert (me.position.x, me.position.y) == (5, 6)
    engine.state.actors[ME].bonus_action_available = True
    assert "Shadow Step (Array)" not in _offered(engine)  # once per turn


def test_clone_assault_misdirection_denies_the_targets_reactions_after_a_hit():
    engine = _ninja()
    _act(engine, "Shadow Clone Array")
    _act(engine, "Unarmed Strike", bonus=40)  # a hit while a Clone remains
    foe = engine.state.actors[FOE]
    assert any(condition.condition_id == "condition:typed.reaction_denied" for condition in foe.conditions.values())
    assert any("Clone Assault Misdirection" in str((event.payload or {}).get("log") or "")
               for event in engine.events if event.event_type == "PASSIVE_TRIGGERED")


def test_clone_opportunity_exemption():
    engine = _ninja()
    _act(engine, "Shadow Clone Array")
    foe = engine.state.actors[FOE]
    # The ninja moves away from the foe on its own turn: a creature unable to
    # identify the true body among the Clones provokes no Opportunity Attack.
    # The move ends out of the foe's 5-foot reach, so it would otherwise provoke.
    move = next(c for c in engine.legal_candidates() if c.actor_id == ME
                and c.display_name.startswith("Move to") and c.destination is not None
                and abs(c.destination.x - foe.position.x) + abs(c.destination.y - foe.position.y) >= 2)
    engine.execute_intent(ActionIntent(intent_id=f"move{engine.state.event_sequence}", decision_id=move.decision_id,
                                          candidate_id=move.candidate_id, state_version=move.state_version,
                                          actor_id=ME, target_ids=move.target_ids, destination=move.destination))
    assert not any(event.event_type == "REACTION_WINDOW_OPENED" and event.actor_id == FOE
                   for event in engine.events)


# ------------------------------------------------------------------------------------------------ Vanishing Technique
def test_vanishing_technique_grants_invisible_and_its_state():
    engine = _ninja()
    me = engine.state.actors[ME]
    assert not _conditions(me, "condition:typed.invisible")
    _act(engine, "Vanishing Technique")
    me = engine.state.actors[ME]
    assert _conditions(me, "condition:typed.invisible")
    assert _conditions(me, "condition:typed.vanishing_state")
    assert me.resources["resource:core.qi"] == SHEET["ability_scores_and_statistics"]["primary_resource"]["maximum"] - 5


def test_vanishing_harmful_action_lifecycle():
    engine = _ninja()
    _act(engine, "Vanishing Technique")
    _act(engine, "Unarmed Strike", bonus=40)  # making an attack is a Harmful Action
    me = engine.state.actors[ME]
    assert not _conditions(me, "condition:typed.invisible")  # visible until the end of the current turn
    assert _conditions(me, "condition:typed.vanishing_state")  # the feature itself lasts
    engine._append_event("TURN_ENDED", "system:turn", actor_id=ME, payload={})
    _turn(engine, FOE)
    me = engine.state.actors[ME]
    assert _conditions(me, "condition:typed.invisible")  # Invisible again at turn end, no Hide needed


@pytest.mark.parametrize("effect,event", [
    ({"type": "damage", "applies_to": "target", "flat": 1, "formula": "none", "damage_types": ["FIRE"]}, "DAMAGE_COMMITTED"),
    ({"type": "save", "applies_to": "target", "ability": "CON", "on_fail": [], "on_success": []}, "SAVE_ROLLED"),
    ({"type": "condition", "applies_to": "target", "condition": "prone"}, "CONDITION_APPLIED"),
])
def test_vanishing_lifecycle_covers_damage_saves_and_conditions(effect, event):
    engine = _ninja()
    _act(engine, "Vanishing Technique")
    me = engine.state.actors[ME]
    assert _conditions(me, "condition:typed.invisible")
    # Replace only this fixture's payload: each execution has exactly one
    # harmful effect and no attack, so another hook cannot mask a broken one.
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.display_name == "Unarmed Strike")
    action.parameters["typed"]["effects"] = [effect]
    mark = len(engine.events)
    _act(engine, "Unarmed Strike")
    assert any(e.event_type == event for e in engine.events[mark:])
    assert not any(e.event_type == "ATTACK_ROLLED" for e in engine.events[mark:])
    me = engine.state.actors[ME]
    assert not _conditions(me, "condition:typed.invisible")


def test_vanishing_technique_offers_the_30_foot_forms():
    from types import SimpleNamespace
    from combat.ext.tabik_ninpo import ninpo_candidates
    engine = _ninja()
    _act(engine, "Smoke Veil", at=(4, 6))
    engine.state.actors[ME].bonus_action_available = True  # the veil spent the Bonus Action
    _act(engine, "Vanishing Technique")
    engine.state.actors[ME].bonus_action_available = True
    names = _offered(engine)
    assert "Shadow Step (Vanishing)" in names and "Shadow Step" not in names
    step = next(c for c in engine.legal_candidates() if c.actor_id == ME
                and c.source_definition_id in engine.action_catalog
                and engine.action_catalog[c.source_definition_id].display_name == "Shadow Step (Vanishing)")
    assert engine.action_catalog[step.source_definition_id].range_ft == 30
    assert engine.action_catalog[step.source_definition_id].costs == (("resource:core.qi", 1),)
    veil_moves = {name for name in names if name and name.startswith("Smoke Veil: move")}
    assert veil_moves == {"Smoke Veil: move (Vanishing)"}  # the veil moves 30 feet each turn
    move = next(action for action in engine.action_catalog.values()
                if action.display_name == "Smoke Veil: move (Vanishing)")
    assert ninpo_candidates(engine, engine.state.actors[ME],
                            SimpleNamespace(destination=Position(x=10, y=6)), move) is True


def test_vanishing_shadow_step_spends_one_qi_and_remains_an_ai_option():
    engine = _ninja()
    _act(engine, "Smoke Veil", at=(4, 6))
    engine.state.actors[ME].bonus_action_available = True
    _act(engine, "Vanishing Technique")
    engine.state.actors[ME].bonus_action_available = True
    action = next(a for a in engine.action_catalog.values()
                  if a.display_name == "Shadow Step (Vanishing)")
    assert action.parameters.get("player_only") is not True
    before = engine.state.actors[ME].resources["resource:core.qi"]
    _act(engine, "Shadow Step (Vanishing)")
    assert engine.state.actors[ME].resources["resource:core.qi"] == before - 1


def test_array_takes_precedence_over_vanishing_for_the_step_range():
    engine = _ninja()
    _act(engine, "Smoke Veil", at=(4, 6))
    engine.state.actors[ME].bonus_action_available = True  # the veil spent the Bonus Action
    _act(engine, "Shadow Clone Array")
    engine.state.actors[ME].bonus_action_available = True  # the array spent the Bonus Action
    _act(engine, "Vanishing Technique")
    engine.state.actors[ME].bonus_action_available = True
    names = _offered(engine)
    assert "Shadow Step (Array)" in names  # 60 feet beats the Vanishing 30
    assert "Shadow Step (Vanishing)" not in names and "Shadow Step" not in names


# ------------------------------------------------------------------------------------------------ Shadow Step riders
def test_shadow_step_grants_the_next_stealth_check_advantage():
    engine = _ninja()
    _act(engine, "Smoke Veil", at=(4, 6))
    engine.state.actors[ME].bonus_action_available = True
    _act(engine, "Shadow Step", at=(5, 6))
    me = engine.state.actors[ME]
    stealth = [held for held in me.conditions.values()
               if held.condition_id == "condition:typed.hidden_strike_stealth"]
    assert stealth and (stealth[0].data or {}).get("rule", {}).get("check_mode", {}).get("Stealth") == "ADVANTAGE"
    # ...and the first Opportunity Attack against it before its next turn has Disadvantage (unchanged).
    assert any(held.condition_id == "condition:typed.shadow_step_oa" for held in me.conditions.values())


def test_shadow_step_draw_and_stow_are_free_engine_actions():
    engine = _ninja()
    # The drawn dagger offers the free Stow; stowing it offers the free Draw
    # back, so both engine actions ride the printed "draw or stow one weapon".
    assert "Stow Bi Shou (Dagger) (frees 1 hand; no Action)" in _offered(engine)
    _act(engine, "Stow Bi Shou (Dagger) (frees 1 hand; no Action)")
    assert "Draw Bi Shou (Dagger) (uses 1 hand; no Action)" in _offered(engine)


# ------------------------------------------------------------------------------------------------ Smoke Veil roster
def test_smoke_veil_chooses_pb_creatures_that_see_it_lightly_obscured():
    engine = _ninja()
    _act(engine, "Smoke Veil", at=(4, 6))
    smoke = next(zone for zone in engine.state.zones.values()
                 if zone.active and zone.trigger_profile.get("name") == "Smoke Veil")
    assert smoke.trigger_profile.get("owner_sees")
    # The table's only ally is the ninja itself; the roster is the PB creatures
    # it chose (here: none beyond it, the foe is hostile and stays out).
    assert smoke.trigger_profile.get("lightly_obscured_viewer_ids") == []
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    # The maker sees through its own veil (no Disadvantage) while the foe,
    # which chose nothing, cannot see the maker inside it (the maker attacks
    # with Advantage); the reverse attack is the obscured creature's Disadvantage.
    assert zones.attack_mode(engine, me, foe) == "ADVANTAGE"
    assert zones.attack_mode(engine, foe, me) == "DISADVANTAGE"


def test_smoke_veil_roster_can_include_an_ally():
    # A second hand-controlled ally in the pool: the ninja chooses it (up to PB).
    from combat.factory_compiler import compile_character as compile_
    features = [feature for feature in NINPO if "shadow_clone_array" not in feature and "vanishing_technique" not in feature]
    me_sheet = {**SHEET, "equipment": [{"starting_kit": KIT}],
                "path_and_subpath": {"path_feature_record_ids": features},
                "spheres_and_talents": {"sphere_record_ids": [], "learned_talent_record_ids": []}}
    ally_sheet = {**SHEET, "equipment": [{"starting_kit": KIT}],
                  "spheres_and_talents": {"sphere_record_ids": [], "learned_talent_record_ids": []}}
    ally = "actor:factory.ally"
    mine = compile_(me_sheet, actor_id=ME)
    theirs = compile_(ally_sheet, actor_id=ally)
    engine = Gate4ControllerEngine(ROOT, match_seed="A2R09ROSTER", typed_bundles=(mine, theirs),
                                       roster_setup={"primary_actor_ids": [ME, ally], "team_by_actor": {ME: "team:a", ally: "team:a"},
                                                     "starting_positions": {ME: {"x": 3, "y": 6}, ally: {"x": 5, "y": 6}}})
    _turn(engine, ME)
    _act(engine, "Smoke Veil", at=(4, 6))
    smoke = next(zone for zone in engine.state.zones.values()
                 if zone.active and zone.trigger_profile.get("name") == "Smoke Veil")
    assert smoke.trigger_profile.get("lightly_obscured_viewer_ids") == [ally]  # the one ally, within PB
    ally_state = engine.state.actors[ally]
    foe = None
    assert zones.attack_mode(engine, ally_state, engine.state.actors[ME]) is None  # the chosen ally sees through
