"""Printed Hidden Strike: 'Once per turn when you hit with an attack'."""
import pytest
from combat.tabletop import ButtonStore
from tests.hunt36_support import HIDDEN, LEFT, RIGHT, act, reload, send, setup_hidden, turn, weapon


@pytest.mark.parametrize("consumed", [False, True])
@pytest.mark.parametrize("legacy_hidden", [False, True])
def test_hidden_strike_refreshes_on_other_creatures_turn(tmp_path, consumed, legacy_hidden):
    combat, table, mid = setup_hidden(tmp_path, smoke=True, legacy_hidden=legacy_hidden)
    bundles = next(tmp_path.rglob("Typed_Character_Bundles.json"))
    bundle_bytes = bundles.read_bytes()
    ButtonStore(tmp_path / "tabletop_buttons").save_reactions("36000001", {"mode": "ask"}, {"opportunity_attack"})
    if consumed:
        send(combat, table, mid, weapon(combat, mid).candidate_id)
    engine = reload(combat, mid)
    assert sum(e.event_type == "PASSIVE_TRIGGERED" and e.source_definition_id == f"passive:{HIDDEN}" for e in engine.events) == int(consumed)
    act(combat, table, mid, "end")
    state = table.state(mid)
    cid = next(m["candidate_id"] for m in state["menu"]["moves"] if m["destination"] == {"x": 5, "y": 6})
    prompts = send(combat, table, mid, cid, ai=True)
    assert prompts, "manual owner should be asked about the Opportunity Attack on an AI turn"
    assert any(p.get("choice") and {o["id"] for o in p["choice"]["options"]} == {"withdraw", "sever", "vanish", "mislead", "smoke"}
               for p in prompts), "Hidden Strike's manual owner must also choose its rider on an AI turn"
    engine = reload(combat, mid)
    attacks = [e for e in engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == LEFT]
    assert len(attacks) == 1 + int(consumed) and all(e.payload["provisional_hit"] for e in attacks)
    assert sum(e.event_type == "PASSIVE_TRIGGERED" and e.source_definition_id == f"passive:{HIDDEN}" for e in engine.events) == 1 + int(consumed), "Printed once per turn includes a qualifying reaction on another creature's turn"
    assert bundles.read_bytes() == bundle_bytes, "legacy chooser metadata must not rewrite a sealed saved bundle"


def test_multiple_hits_on_one_turn_use_hidden_strike_only_once(tmp_path):
    combat, table, mid = setup_hidden(tmp_path, extra=["tianxia.path.body_refining.feature.extra_attack"])
    send(combat, table, mid, weapon(combat, mid).candidate_id, ai=True)
    engine = reload(combat, mid)
    assert len([e for e in engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == LEFT and e.payload["provisional_hit"]]) >= 2
    assert sum(e.event_type == "PASSIVE_TRIGGERED" and e.source_definition_id == f"passive:{HIDDEN}" for e in engine.events) == 1
    gate = engine.state.actors[LEFT].turn_flags["_round_hidden_strike_turn"]
    assert isinstance(gate, str) and LEFT in gate


def test_shadow_step_from_owner_turn_does_not_qualify_visible_off_turn_hit(tmp_path):
    """Printed: 'used Shadow Step during the current turn', not a prior turn."""
    combat, table, mid = setup_hidden(tmp_path, smoke=True,
        extra=["tianxia.subpath.qi.ninpo_adept.feature.shadow_step"],
        right_effects=[{"type": "gain_sense", "sense": "blindsight", "range_ft": 30}])
    ButtonStore(tmp_path / "tabletop_buttons").save_reactions("36000001", {"mode": "ask"}, {"opportunity_attack"})
    act(combat, table, mid, "end")
    act(combat, table, mid, "Test setup")
    act(combat, table, mid, "end")
    menu = table.state(mid)["menu"]
    cid = next(o["candidate_id"] for g in menu["actions"] if g["label"] == "Shadow Step" for o in g["options"] if o.get("destination") == {"x": 3, "y": 5})
    send(combat, table, mid, cid)
    send(combat, table, mid, weapon(combat, mid).candidate_id, pick=lambda o: o["id"] == "sever")
    engine = reload(combat, mid)
    from combat import senses
    assert senses.sees_hidden(engine, engine.state.actors[RIGHT], engine.state.actors[LEFT])
    assert sum(e.event_type == "PASSIVE_TRIGGERED" and e.source_definition_id == f"passive:{HIDDEN}" for e in engine.events) == 1
    act(combat, table, mid, "end")
    menu = table.state(mid)["menu"]
    cid = next(m["candidate_id"] for m in menu["moves"] if m["destination"] == {"x": 5, "y": 6})
    send(combat, table, mid, cid, ai=True, pick=lambda o: o["id"] == "sever")
    engine = reload(combat, mid)
    attacks = [e for e in engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == LEFT]
    assert len(attacks) == 2 and all(e.payload["provisional_hit"] for e in attacks)
    assert sum(e.event_type == "PASSIVE_TRIGGERED" and e.source_definition_id == f"passive:{HIDDEN}" for e in engine.events) == 1, "Shadow Step's qualification expires when the owner's turn ends, even though Hidden Strike itself refreshes for reactions"
