"""Sword Saint activation registers hit damage instead of hurting its caster."""
import pytest
from tests.hunt12_support import ME, FOE, STAMINA, candidate, fight, hit_dice, reload, send

SWORD = "tianxia.subpath.body.kensei.feature.sword_saint_incarnation"


@pytest.mark.parametrize("auto", [False, True])
@pytest.mark.parametrize("option", ["Deny Reactions", "Reduce Speed"])
def test_activation_and_first_hit_survive_table_reload(tmp_path, monkeypatch, auto, option):
    combat, table, mid = fight(tmp_path, [SWORD, "TAL_IRON_FIST_IRON_FIST_TRAINING"], dc=18)
    # riders/c7 (merge de0c0817) asks for the reach result after a failed save,
    # not at activation; one state/zone plug-in replaces the old typed options.
    chosen = candidate(combat, mid, lambda c: c.display_name == "Sword Saint Incarnation")
    before = combat._load_session(mid).engine.state.actors[ME]
    hp, stamina = before.current_hp, before.resources[STAMINA]
    if auto:
        combat.set_controller_mode(mid, actor_id=ME, controller_mode="LOCAL_AUTO")
    result = send(combat, table, mid, chosen, auto=auto)
    assert result["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ME].current_hp == hp
    assert engine.state.actors[ME].resources[STAMINA] == stamina - 7
    assert any(c.condition_id == "condition:typed.state.sword_saint_incarnation"
               for c in engine.state.actors[ME].conditions.values())
    assert not any(e.event_type == "DAMAGE_COMMITTED" and ME in e.target_ids for e in engine.events)
    hit_dice(monkeypatch)
    chosen = candidate(combat, mid, lambda c: ".natural.iron_fist" in c.source_definition_id and "#" not in c.source_definition_id and tuple(c.target_ids) == (FOE,))
    assert send(combat, table, mid, chosen, auto=auto)["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    bonus = [e for e in engine.events if e.event_type == "DAMAGE_ROLLED" and e.payload.get("expression") == "3d8+0"]
    assert len(bonus) == 1 and bonus[0].target_ids == (FOE,)

    # The owner chooses separately when the enemy starts its turn in reach.
    # Keep both old option cases, now at the printed failed-save checkpoint.
    combat.set_controller_mode(mid, actor_id=ME, controller_mode="MANUAL")
    hit_dice(monkeypatch, save_roll=1)
    chosen = candidate(combat, mid, lambda c: c.kind.value == "END_TURN")
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    result = send(combat, table, mid, chosen)
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert prompt["context"]["reaction_source_id"] == "choice:needle.path_results.sword_saint"
    assert prompt["context"]["reactor_id"] == ME
    assert "Sword Saint Incarnation" in prompt["moment"] and "failed its save" in prompt["moment"]
    assert {o["id"] for o in prompt["choice"]["options"]} == {"No Reactions", "Speed -10"}
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    assert send(combat, table, mid, chosen)["reaction"] == prompt
    selected = "No Reactions" if option == "Deny Reactions" else "Speed -10"
    answer = {**prompt["context"], "selection": "USE", "option_ids": [selected]}
    assert send(combat, table, mid, chosen, [answer])["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    foe = engine.state.actors[FOE]
    assert engine.state.current_actor_id == FOE
    assert engine.state.actors[ME].resources[STAMINA] == stamina - 7
    reach_damage = [e for e in engine.events if e.event_type == "DAMAGE_ROLLED"
                    and e.payload.get("expression") == "3d8+0" and e.target_ids == (FOE,)]
    assert len(reach_damage) == 2  # one hit rider, one independent failed reach save
    if option == "Deny Reactions":
        rows = [c for c in foe.conditions.values() if c.condition_id == "condition:typed.reaction_denied"]
        assert not any(m.target_field == "speed_ft" and m.value == -10 for m in foe.modifiers.values())
    else:
        rows = [m for m in foe.modifiers.values() if m.target_field == "speed_ft" and m.value == -10]
        assert not any(c.condition_id == "condition:typed.reaction_denied" for c in foe.conditions.values())
    assert len(rows) == 1
    if option == "Deny Reactions":
        assert rows[0].expires_on == f"START_OF_TURN_AT:{FOE}:{foe.turns_started + 1}"
        stored_id = rows[0].instance_id
    else:
        # Modifiers are filed under the acting enemy; this native expiry names
        # its next turn, not the Sword Saint owner's next turn.
        assert rows[0].source_actor_id == FOE
        assert rows[0].expires_on == "START_OF_SOURCE_NEXT_TURN"
        stored_id = rows[0].modifier_id
    from tests.test_lock2_persistence import act

    assert act(table, mid, "end")["status"] == "COMMITTED"
    foe = reload(tmp_path, mid).state.actors[FOE]
    assert stored_id in {**foe.conditions, **foe.modifiers}
    # Passing the next save avoids a second failed-save choice and must remove
    # the previous result, replacing it only with the printed 5-foot slowdown.
    monkeypatch.undo()  # restore the saving-roll helper before scripting success
    hit_dice(monkeypatch, save_roll=20)
    assert act(table, mid, "end")["status"] == "COMMITTED"
    foe = reload(tmp_path, mid).state.actors[FOE]
    assert stored_id not in {**foe.conditions, **foe.modifiers}
    assert not any(c.condition_id == "condition:typed.reaction_denied" for c in foe.conditions.values())
    assert [m.value for m in foe.modifiers.values() if m.target_field == "speed_ft"] == [-5]
