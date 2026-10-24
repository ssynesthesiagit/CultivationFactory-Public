"""Core Tempering's scaling, critical rider and printed turn boundaries at the table."""
import json
import subprocess
import sys

import pytest

from tests.hunt14_support import ME, FOE, OTHER, ROOT, act, advance, fight, reload


@pytest.mark.parametrize("auto", [False, True])
def test_blood_furnace_can_benefit_on_enemy_turn_after_owner_turn(tmp_path, auto):
    combat, table, mid = fight(tmp_path, cl=12, offturn=True)
    act(table, mid, "core_tempering_expression.blood_furnace")
    act(table, mid, "end")
    advance(table, mid, FOE)
    act(table, mid, "natural.iron_fist", ME, selection="DECLINE")
    act(table, mid, "end")
    advance(table, mid, ME)
    act(table, mid, "tianxia.path.body_refining.feature.iron_voice", OTHER)
    before = reload(tmp_path, mid).state.actors[ME].current_hp
    assert before < 60
    act(table, mid, "end")
    advance(table, mid, FOE)
    start = table.state(mid)["last_sequence"]
    if auto:
        combat.set_controller_mode(mid, actor_id=FOE, controller_mode="LOCAL_AUTO")
    stamina_before = reload(tmp_path, mid).state.actors[ME].resources["resource:core.stamina"]
    # fix/hunt10b (merge bb8f59ad) lets Ask-me players choose the Guard payment.
    # Choose the printed PB cap explicitly so this probe still fully soaks the hit.
    prompts = act(table, mid, "natural.iron_fist", ME, auto=auto, option="4")
    assert any(p["reaction"] == "Stamina Guard" for p in prompts)
    engine = reload(tmp_path, mid)
    events = [e for e in engine.events if e.sequence > start and e.actor_id == ME]
    guard = next(e for e in events if e.event_type == "REACTION_RESOLVED" and "spend" in e.payload)
    assert guard.payload["spend"] == 4
    assert guard.payload["pending_after"] == 0
    assert engine.state.actors[ME].resources["resource:core.stamina"] == stamina_before - 4
    assert any(e.event_type == "RESOURCE_SPENT" for e in events)
    assert len([e for e in events if e.event_type == "HEALING_APPLIED"]) == 1
    assert engine.state.actors[ME].current_hp == before + 4


@pytest.mark.parametrize("auto", [False, True])
def test_mountain_rending_rearms_on_enemy_turn_after_consuming_owner_turn_hit(tmp_path, auto):
    from combat.ext.bodya_body_refining import READY_CONDITION
    combat, table, mid = fight(tmp_path, cl=12, offturn=True)
    act(table, mid, "core_tempering_expression.mountain_rending")
    act(table, mid, "mountain_rending_choice.deny_reactions")
    act(table, mid, "end")
    advance(table, mid, FOE)
    act(table, mid, "natural.iron_fist", ME, selection="DECLINE")
    act(table, mid, "end")
    advance(table, mid, ME)
    act(table, mid, "tianxia.path.body_refining.feature.iron_voice", OTHER)
    assert any(c.condition_id == READY_CONDITION for c in reload(tmp_path, mid).state.actors[ME].conditions.values())
    act(table, mid, "natural.iron_fist", FOE)
    assert not any(c.condition_id == READY_CONDITION for c in reload(tmp_path, mid).state.actors[ME].conditions.values())
    act(table, mid, "end")
    advance(table, mid, FOE)
    if auto:
        combat.set_controller_mode(mid, actor_id=FOE, controller_mode="LOCAL_AUTO")
    prompts = act(table, mid, "natural.iron_fist", ME, auto=auto)
    assert any(p["reaction"] == "Stamina Guard" for p in prompts)
    engine = reload(tmp_path, mid)
    assert any(c.condition_id == READY_CONDITION for c in engine.state.actors[ME].conditions.values())
