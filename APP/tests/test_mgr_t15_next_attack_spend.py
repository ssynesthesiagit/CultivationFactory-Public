"""Next-attack benefits against a creature: a single-use grant is spent by one attack roll, a sustained mode is not."""
from tests.h1_support import duel, ME, FOE, script

GRANT = 'test:single_use_grant'
SUSTAINED = 'test:guardian_style_disadvantage'


def strike(e):
    script(e, [11, 12, 1, 1])
    e._resolve_attack_spec(e.state.actors[ME], e.state.actors[FOE],
                           {'attack_bonus': 0, 'reach_ft': 100}, e._active_intent,
                           source_definition_id='test:native-strike')
    return next(x.payload for x in reversed(e.events) if x.event_type == 'ATTACK_ROLLED')


def incoming(e):
    return [m for m in e.state.actors[FOE].modifiers.values() if m.target_field == 'incoming_attack_mode']


def test_single_use_grant_is_spent_by_the_next_attack_roll_only():
    e = duel([])
    e._add_modifier(e.state.actors[FOE], GRANT, 'incoming_attack_mode', 'SET', 'ADVANTAGE', 'NEXT_ATTACK',
                    expires_on='START_OF_SOURCE_NEXT_TURN', source_actor_id=ME, spend_on_roll=True)
    assert strike(e)['mode'] == 'ADVANTAGE'
    assert incoming(e) == []
    assert any(x.event_type == 'MODIFIER_REMOVED' and x.payload.get('reason') == 'CONSUMED' for x in e.events)
    assert strike(e)['mode'] == 'NORMAL'


def test_sustained_next_attack_disadvantage_survives_the_roll():
    e = duel([])
    e._add_modifier(e.state.actors[FOE], SUSTAINED, 'incoming_attack_mode', 'SET', 'DISADVANTAGE', 'NEXT_ATTACK',
                    expires_on='START_OF_SOURCE_NEXT_TURN', source_actor_id=ME)
    assert strike(e)['mode'] == 'DISADVANTAGE'
    assert [m.source_definition_id for m in incoming(e)] == [SUSTAINED]
    assert strike(e)['mode'] == 'DISADVANTAGE'


def test_unflagged_advantage_with_a_turn_lifetime_is_not_spent_by_a_roll():
    e = duel([])
    e._add_modifier(e.state.actors[FOE], GRANT, 'incoming_attack_mode', 'SET', 'ADVANTAGE', 'NEXT_ATTACK',
                    expires_on='START_OF_SOURCE_NEXT_TURN', source_actor_id=ME)
    assert strike(e)['mode'] == 'ADVANTAGE'
    assert [m.source_definition_id for m in incoming(e)] == [GRANT]
