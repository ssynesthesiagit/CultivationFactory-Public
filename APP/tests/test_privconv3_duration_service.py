"""Attack-only AC at the engine boundary (PRIVCONV3 F6).

The reviewed authority stores a lifetime as a typed dict ({"kind": "triggering_attack"} for an AC that answers
one attack). A consumer that compares the lifetime string matches nothing, so the +2 AC never reaches the attack
it was declared against; a consumer that ignores the lifetime leaves it behind as a lasting modifier.

The row below is synthetic, shaped exactly as the authority's rows are (the typed effect Active Defense prints:
"applies_to": "self", "flat": 2, the lifetime "triggering_attack"), so this file also runs on the public copy,
whose printed prose is scrambled and whose shipped Active Defense compiles no Reaction row at all. The shipped
record's own path is covered by the private tests/test_mgr_t14_active_defense.py, which reads the owner's words.
"""
from tests.test_riders_lane9 import _shield_fight, _stab, ME, THEM
from tests.test_auto_lane4 import _script

FEATURE = "test:privconv3.attack_only_defense"
#: The typed lifetime the authority now carries, and the string form it replaced.
TYPED_LIFETIME = {"kind": "triggering_attack", "anchor": "kind"}
STRING_LIFETIME = "triggering_attack"


def _row(duration):
    """A generic "attacked" Reaction that answers one attack with +2 AC, in the authority's own shape."""
    return {
        "feature_id": FEATURE, "name": "Test attack-only defence",
        "block": "generic", "kind": "attacked", "ask": False, "range_ft": 60, "costs": [], "numbers": {"pb": 2},
        "effects": [{"type": "ac_bonus", "applies_to": "self", "flat": 2, "duration": duration,
                     "evidence": "+2 AC against the triggering attack"}],
    }


def _defending_fight(duration):
    """A fighter without Active Defense, holding the attack-only AC row: the row is the only answer to an attack."""
    engine = _shield_fight([], bases=False)
    engine.typed_reaction_rows[ME] = [*engine.typed_reaction_rows.get(ME, []), _row(duration)]
    return engine


def _stabbed_target_ac(events):
    [rolled] = [e for e in events if e.event_type == "ATTACK_ROLLED" and ME in e.target_ids]
    return rolled.payload["target_ac"]


def test_an_attack_only_ac_bonus_reaches_the_attack_it_was_declared_against():
    engine = _defending_fight(TYPED_LIFETIME)
    me = engine.state.actors[ME]
    me.armor_class = 60  # the attack misses on its own; the defence is still offered
    _script(engine, [5])
    first = _stab(engine)
    assert _stabbed_target_ac(first) == 62  # the +2 covers the attack it was declared against
    # The +2 belongs to that attack: it is not left behind as a lasting modifier.
    assert engine._ac_modifier(me) == 0
    assert not any(m.target_field == "armor_class" and int(m.value) == 2 for m in me.modifiers.values())


def test_an_attack_only_ac_bonus_does_not_reach_the_next_attack():
    engine = _defending_fight(TYPED_LIFETIME)
    me = engine.state.actors[ME]
    me.armor_class = 60
    _script(engine, [5])
    _stab(engine)
    # The Reaction was spent answering the first attack, so the next one is not answered at all.
    assert me.reaction_available is False
    _script(engine, [5])
    second = _stab(engine)
    assert _stabbed_target_ac(second) == 60
    assert not any(e.event_type == "REACTION_WINDOW_OPENED" and e.source_definition_id == FEATURE for e in second)


def test_a_typed_lifetime_and_the_string_it_replaced_behave_alike():
    """The lifetime is read in either form: a typed dict must not silently match nothing."""
    typed = _defending_fight(TYPED_LIFETIME)
    typed.state.actors[ME].armor_class = 60
    _script(typed, [5])
    assert _stabbed_target_ac(_stab(typed)) == 62

    written = _defending_fight(STRING_LIFETIME)
    written.state.actors[ME].armor_class = 60
    _script(written, [5])
    assert _stabbed_target_ac(_stab(written)) == 62
