"""The Unmaking sphere (owner 2026-09-28, "automate every aspect"): Black Trace's reviewed options, Ruin Channel's charged
hit, Black Vein Strain's Ruin Backlash, and "cannot take Reactions against you". combat/unmaking.py."""

from pathlib import Path

from combat import unmaking
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_carry import KIT
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.ruin"


def _engine():
    sheet = {**SHEET, "equipment": [{"starting_kit": KIT}],
             "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.unmaking"],
                                     "learned_talent_record_ids": ["TAL_UNMAKING_BLACK_TRACE", "TAL_UNMAKING_RUIN_CHANNEL"]}}
    bundle = compile_character(sheet, actor_id=ME)
    engine = Gate4ControllerEngine(ROOT, match_seed="RUIN", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine, bundle


def _do(engine, name):
    candidate = next(c for c in engine.legal_candidates() if c.display_name == name)
    engine.execute_intent(ActionIntent(intent_id=name, decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids,
                                       destination=candidate.destination))


def test_black_trace_offers_its_trace_effects_each_with_realm_damage():
    _engine_, bundle = _engine()
    names = [row["display_name"] for row in bundle["action_catalog"]]
    assert {"Black Trace: Fray", "Black Trace: Sting", "Black Trace: Mark", "Black Trace: Sting, Unbound Trace"} <= set(names)
    sting = next(row for row in bundle["action_catalog"] if row["display_name"] == "Black Trace: Sting")
    on_hit = sting["parameters"]["typed"]["effects"][0]["on_hit"]
    assert on_hit[0]["type"] == "damage" and on_hit[0]["dice_by_cl"] and on_hit[1]["type"] == "deny_reactions_against"
    assert "Overdraw: ready" in names


def test_ruin_channel_charges_the_next_hit_and_costs_black_vein_strain():
    engine, _bundle = _engine()
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    _do(engine, "Ruin Channel")
    assert any(c.condition_id == unmaking.CHANNEL for c in me.conditions.values())
    for attempt in range(8):  # until a hit lands
        attack = next((c for c in engine.legal_candidates() if c.display_name.endswith(" attack") and ".weapon." in c.source_definition_id), None)
        if attack is None:
            break
        typed = engine.action_catalog[attack.source_definition_id].parameters["typed"]
        typed["numbers"] = {**typed["numbers"], "attack_bonus": 30}  # the fixture's dagger rarely hits this opponent
        engine.execute_intent(ActionIntent(intent_id=f"a{attempt}", decision_id=attack.decision_id, candidate_id=attack.candidate_id,
                                           state_version=attack.state_version, actor_id=ME, target_ids=attack.target_ids))
        if not any(c.condition_id == unmaking.CHANNEL for c in me.conditions.values()):
            break
        me.action_available = True
    assert not any(c.condition_id == unmaking.CHANNEL for c in me.conditions.values())
    # Printed cost (rider lane C5): a held weapon is an External Channel, so it gains 1 Crack (the AI's pick; the other printed
    # choice is 1d6 + PB Ruin self-damage); only an Internal Channel (an unarmed strike) gives Black Vein Strain.
    from combat.ext import unmaking_channels

    assert me.resources[unmaking.STRAIN] == 0
    assert sum(unmaking_channels.cracked_channels(me).values()) == 1
    assert any(e.event_type == "DAMAGE_COMMITTED" and str(e.source_definition_id).endswith(".ruin_channel") for e in engine.events)
    del foe


def test_six_black_vein_strain_is_a_ruin_backlash_back_to_three():
    engine, _bundle = _engine()
    me = engine.state.actors[ME]
    hp = me.current_hp
    unmaking.gain_strain(engine, me, 6, "test")
    assert me.resources[unmaking.STRAIN] == 3 and me.current_hp < hp


def test_sting_stops_only_reactions_against_its_maker():
    engine, _bundle = _engine()
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    engine._apply_condition(foe, unmaking.NO_REACTIONS_AGAINST, "test", ME, expires_on="START_OF_SOURCE_NEXT_TURN", data={"against": ME})
    assert unmaking.reactions_denied_against(foe, me)
    assert not unmaking.reactions_denied_against(foe, foe)
