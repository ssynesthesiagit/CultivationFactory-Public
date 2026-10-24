"""Attack-only AC and Concentration-linked burial at the engine boundary (PRIVCONV3 F2).

The reviewed authority stores these durations as typed dicts. The consumers must read the lifetime name from either
form, or Active Defense's +2 outlives the attack it was declared against.
"""
from tests.test_riders_lane9 import _shield_fight, _stab, _turn, ME, THEM
from tests.test_auto_lane4 import _script


def test_active_defense_adds_ac_to_one_attack_only():
    engine = _shield_fight([])
    me = engine.state.actors[ME]
    me.armor_class = 60  # the attack misses on its own; Active Defense is still offered
    _script(engine, [5])
    first = _stab(engine)
    [rolled] = [e for e in first if e.event_type == "ATTACK_ROLLED" and ME in e.target_ids]
    assert rolled.payload["target_ac"] == 62  # the +2 covers the attack it was declared against

    # The defender's next turn has not started: a second attack from the same foe must not get the +2 too.
    _script(engine, [5])
    second = _stab(engine)
    [rolled_again] = [e for e in second if e.event_type == "ATTACK_ROLLED" and ME in e.target_ids]
    assert rolled_again.payload["target_ac"] == 60
    assert engine._ac_modifier(me) == 0


def test_active_defense_bonus_is_not_a_lasting_modifier():
    engine = _shield_fight([])
    me = engine.state.actors[ME]
    me.armor_class = 60
    _script(engine, [5])
    _stab(engine)
    _turn(engine, THEM)
    assert not any(m.target_field == "armor_class" and int(m.value) == 2 for m in me.modifiers.values())
    assert engine._ac_modifier(me) == 0
