"""Printed Hidden Strike: 'you are Invisible to it' / 'were unseen by the target'."""
import pytest
from tests.hunt36_support import HIDDEN, LEFT, RIGHT, act, fight, reload, send, setup_hidden, turn, weapon


@pytest.mark.parametrize("ai", [False, True])
@pytest.mark.parametrize("owned", [False, True])
def test_invisible_hit_qualifies_only_for_hidden_strike_owner(tmp_path, ai, owned):
    combat, table, mid = setup_hidden(tmp_path, owned=owned)
    candidate = weapon(combat, mid)
    send(combat, table, mid, candidate.candidate_id, ai=ai)
    engine = reload(combat, mid)
    attack = next(e for e in engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == LEFT)
    assert attack.payload["mode"] == "ADVANTAGE" and attack.payload["provisional_hit"]
    assert any(c.condition_id == "condition:typed.invisible" for c in engine.state.actors[LEFT].conditions.values())
    bonuses = [e for e in engine.events if e.event_type == "PASSIVE_TRIGGERED" and e.source_definition_id == f"passive:{HIDDEN}"]
    assert len(bonuses) == int(owned), "Printed: Hidden Strike qualifies when you are Invisible to it"


def test_invisible_does_not_qualify_against_reaching_blindsight(tmp_path):
    combat, table, mid = fight(tmp_path, [HIDDEN],
        effects=[{"type": "condition", "condition": "invisible", "applies_to": "self", "expires_on": "UNTIL_REMOVED"}],
        right_effects=[{"type": "gain_sense", "sense": "blindsight", "range_ft": 30}])
    turn(combat, table, mid)
    act(combat, table, mid, "Test setup")
    act(combat, table, mid, "end")
    act(combat, table, mid, "Test setup")
    act(combat, table, mid, "end")
    prompts = send(combat, table, mid, weapon(combat, mid).candidate_id)
    engine = reload(combat, mid)
    from combat import senses
    assert senses.sees_hidden(engine, engine.state.actors[RIGHT], engine.state.actors[LEFT])
    assert not prompts
    attack = next(e for e in engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == LEFT)
    assert attack.payload["mode"] == "NORMAL" and attack.payload["provisional_hit"]
    assert not any(e.event_type == "PASSIVE_TRIGGERED" and e.source_definition_id == f"passive:{HIDDEN}" for e in engine.events), "Invisible must be Invisible to this target, not just a global condition"
