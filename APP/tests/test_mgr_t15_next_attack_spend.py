"""Next-attack Advantage grants against a creature are spent by the next attack roll against that creature.

Every writer grants Advantage on "the next attack roll against it has Advantage". The next roll against the
creature spends the grant whatever its settled mode, including a roll cancelled to NORMAL, because the grant is
used up by the attack it was meant for. Sustained Disadvantage is not a next-roll grant and is never spent by a
roll. One grant is spent per roll. (review F17R finding 2; supersedes the per-writer spend_on_roll flag.)
"""
import pytest

from tests.h1_support import duel, ME, FOE, script

GRANT = 'test:single_use_grant'
SUSTAINED = 'test:guardian_style_disadvantage'
ACTOR_DIS = 'test:own_disadvantage'


def strike(e):
    script(e, [11, 12, 1, 1])
    e._resolve_attack_spec(e.state.actors[ME], e.state.actors[FOE],
                           {'attack_bonus': 0, 'reach_ft': 100}, e._active_intent,
                           source_definition_id='test:native-strike')
    return next(x.payload for x in reversed(e.events) if x.event_type == 'ATTACK_ROLLED')


def incoming(e):
    return [m for m in e.state.actors[FOE].modifiers.values() if m.target_field == 'incoming_attack_mode']


def cancel_to_normal(e):
    """ME's own Disadvantage (sustained) against FOE's Advantage grant: the roll is cancelled to NORMAL."""
    e._add_modifier(e.state.actors[ME], ACTOR_DIS, 'attack_mode', 'SET', 'DISADVANTAGE', 'NEXT_ATTACK',
                    expires_on='START_OF_SOURCE_NEXT_TURN', source_actor_id=FOE)


# Every engine writer of an incoming next-attack Advantage, with the lifetime it is created with.
WRITER_SHAPES = [
    pytest.param('action:core.break_guard_advantage', 'CONSUMED', id='gate2_engine-break-guard'),
    pytest.param('TAL_BRUTE_BRUTAL_SHOVE', 'CONSUMED', id='gu_brute-brutal-shove'),
    pytest.param('exploit:test', 'START_OF_SOURCE_NEXT_TURN', id='tabik-exploited-opening'),
    pytest.param('TAL_WATER_MIRROR_WATER_REPLY', 'START_OF_SOURCE_NEXT_TURN', id='water-reply-opening'),
]


@pytest.mark.parametrize('source,expires', WRITER_SHAPES)
def test_writer_grant_is_spent_by_an_advantage_roll(source, expires):
    e = duel([])
    e._add_modifier(e.state.actors[FOE], source, 'incoming_attack_mode', 'SET', 'ADVANTAGE', 'NEXT_ATTACK',
                    expires_on=expires, source_actor_id=ME)
    assert strike(e)['mode'] == 'ADVANTAGE'
    assert incoming(e) == []


@pytest.mark.parametrize('source,expires', WRITER_SHAPES)
def test_writer_grant_is_spent_by_a_roll_cancelled_to_normal(source, expires):
    e = duel([])
    e._add_modifier(e.state.actors[FOE], source, 'incoming_attack_mode', 'SET', 'ADVANTAGE', 'NEXT_ATTACK',
                    expires_on=expires, source_actor_id=ME)
    cancel_to_normal(e)
    assert strike(e)['mode'] == 'NORMAL'
    assert incoming(e) == []


def test_grant_is_spent_by_the_next_roll_only():
    e = duel([])
    e._add_modifier(e.state.actors[FOE], GRANT, 'incoming_attack_mode', 'SET', 'ADVANTAGE', 'NEXT_ATTACK',
                    expires_on='START_OF_SOURCE_NEXT_TURN', source_actor_id=ME)
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
