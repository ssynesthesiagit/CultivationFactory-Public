"""BRS1F14R finding 1: the UNTIL_SHORT_REST boundary is wired to a real caller.

A Body Refining Temporary HP marker (condition:typed.br_variant_temp, expires_on UNTIL_SHORT_REST) must
survive a saved fight, be accepted by the encounter snapshot, and end at the real Short Rest journey
action. Before this fix no caller existed: the marker stayed forever and the once-per-short-rest grant
could never be given again. The test goes through JourneySession.command, not Gate2Engine.short_rest().
"""
import json
from types import SimpleNamespace

import pytest

from combat import journey
from combat.gate2_runtime_models import ConditionInstance
from combat.ext import journey_setup
from combat.ext import life_state

MARKER = 'condition:typed.br_variant_temp'
PERMANENT = 'condition:typed.permanent_example'


def marker(expires_on):
    return ConditionInstance(instance_id='i1', condition_id=MARKER, source_definition_id='tianxia.brvariant.x',
                             source_actor_id='actor:a', target_id='actor:a', applied_sequence=1,
                             expires_on=expires_on)


def saved_fight(conditions):
    return {'current_hp': 10, 'maximum_hp': 20, 'temporary_hp': 0, 'active': 1, 'life_state': '',
            'conditions': {key: json.dumps(c.model_dump(mode='json', exclude_none=True), sort_keys=True)
                           for key, c in conditions.items()},
            'death_saves': {}}


def session_with(snapshot):
    state = {'phase': 'travel', 'seconds': 0, 'events': [], 'revision': 1, 'battlefield': {},
             'actors': {'actor:a': {'name': 'Body Student', 'incapacitated': False, 'long_rests': 0,
                                    'bundle': {'actor_template': {'speed_ft': 30}, 'typed_passives': []},
                                    'resources': {}, 'position': {'x': 0, 'y': 0, 'z': 0},
                                    'encounter_snapshot': snapshot}}}
    session = journey.JourneySession.__new__(journey.JourneySession)
    session.state = state
    return session


@pytest.fixture(autouse=True)
def no_death_saves(monkeypatch):
    monkeypatch.setattr(life_state, 'encounter_death_saves', lambda actor: {})


def test_a_saved_fight_may_carry_the_short_rest_marker_into_the_snapshot():
    """Before the fix the marker's UNTIL_SHORT_REST expiry was rejected at snapshot time, so the fight could never save."""
    actor = SimpleNamespace(current_hp=10, maximum_hp=20, temporary_hp=0, active=True, life_state='',
                            modifiers={}, concentration=None, transformed_size_category=None,
                            maximum_hp_base=None, maximum_hp_adjustments={}, conditions={'m': marker('UNTIL_SHORT_REST')})
    snapshot = journey_setup.encounter_snapshot(actor)
    assert list(snapshot['conditions'].values())[0] and json.loads(list(snapshot['conditions'].values())[0])['expires_on'] == 'UNTIL_SHORT_REST'


def test_the_short_rest_journey_action_ends_the_marker_and_keeps_permanent_state():
    snapshot = saved_fight({'m': marker('UNTIL_SHORT_REST'), 'p': ConditionInstance(
        instance_id='i2', condition_id=PERMANENT, source_definition_id='s', source_actor_id='actor:a',
        target_id='actor:a', applied_sequence=2, expires_on='UNTIL_REMOVED')})
    session = session_with(snapshot)
    session.command('actor:a', 'short_rest', {})
    left = session.state['actors']['actor:a']['encounter_snapshot']['conditions']
    assert not any(json.loads(v)['condition_id'] == MARKER for v in left.values())
    assert any(json.loads(v)['condition_id'] == PERMANENT for v in left.values())
    assert session.state['seconds'] == 3600
    assert session.state['events'][-1]['kind'] == 'SHORT_REST'


def test_grant_rest_grant_again_spans_the_short_rest():
    """Spans a short rest: marker granted in a fight, saved, rested, then granted again succeeds."""
    fight = session_with(saved_fight({'m': marker('UNTIL_SHORT_REST')}))
    assert any(json.loads(v)['condition_id'] == MARKER
               for v in fight.state['actors']['actor:a']['encounter_snapshot']['conditions'].values())
    fight.command('actor:a', 'short_rest', {})
    after = fight.state['actors']['actor:a']['encounter_snapshot']['conditions']
    assert not any(json.loads(v)['condition_id'] == MARKER for v in after.values())
    # The next grant is a fresh marker in the next fight; the snapshot accepts it.
    regrant = SimpleNamespace(current_hp=10, maximum_hp=20, temporary_hp=0, active=True, life_state='',
                              modifiers={}, concentration=None, transformed_size_category=None,
                              maximum_hp_base=None, maximum_hp_adjustments={},
                              conditions={'m2': marker('UNTIL_SHORT_REST')})
    assert journey_setup.encounter_snapshot(regrant)['conditions']


def test_short_rest_is_one_hour_and_takes_no_payload():
    session = session_with(saved_fight({}))
    with pytest.raises(Exception):
        session.command('actor:a', 'short_rest', {'x': 1})
    assert session.state['seconds'] == 0
