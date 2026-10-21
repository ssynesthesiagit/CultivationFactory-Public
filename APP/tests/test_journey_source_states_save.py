"""JourneyStore.save persists source_states and survives repeated saves.

Regression for the Sol round-3 finding: the source_states check ran in the prior-session
loop, where `actor` is unbound, so every save after the first raised UnboundLocalError.
Synthetic state only; no authority packs or private fixtures.
"""
import json
from types import SimpleNamespace

import pytest

from combat.journey import JourneyStore

JID = 'journey-' + 'a' * 24
ACTOR = 'hero'


def fresh_state(revision=0, source_states=None):
    actor = {'resources': {'resource:core.qi': 3}, 'long_rests': 0, 'travel_uses': 0,
             'exhaustion': 0, 'incapacitated': False, 'encounter_snapshot': None}
    if source_states is not None:
        actor['source_states'] = source_states
    return {'journey_id': JID, 'phase': 'travel', 'revision': revision,
            'actors': {ACTOR: actor}, 'scene_number': 0}


def test_second_save_with_source_states_persists(tmp_path):
    store = JourneyStore(tmp_path)
    states = {'mgr_storm': {'seals': 2, 'label': 'Thunder Seal'}}
    store.save(SimpleNamespace(state=fresh_state(0, states)))
    # The second save used to raise UnboundLocalError on the prior-session loop.
    store.save(SimpleNamespace(state=fresh_state(1, states)),
               command={'actor_id': ACTOR, 'kind': 'move', 'payload': {}},
               checkpoint=fresh_state(0, states))
    registry = json.loads((tmp_path / 'State.json').read_text())
    assert registry['sessions'][JID]['revision'] == 1
    assert registry['actors'][ACTOR]['source_states'] == states


def test_invalid_source_states_still_rejected_on_save(tmp_path):
    store = JourneyStore(tmp_path)
    store.save(SimpleNamespace(state=fresh_state(0)))
    with pytest.raises(ValueError, match='string keys'):
        store.save(SimpleNamespace(state=fresh_state(1, {'bad': object()})),
                   command={'actor_id': ACTOR, 'kind': 'move', 'payload': {}},
                   checkpoint=fresh_state(0))
