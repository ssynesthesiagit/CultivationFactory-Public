"""Journey Qi spend seam used by Orbiting Shield Warden manifestations.

Before the fix, `journey_command` called JourneySession.spend_resource, which did
not exist, so every Manifest Ward / Constellation command raised AttributeError.
"""
import pytest
from combat.gate5_service import CombatService
from combat.journey import JourneyStore
from combat.factory_compiler import compile_character
from tests import r1i_service_support as s
from tests.h1_support import ROOT, sheet

P = 'tianxia.subpath.qi.orbiting_shield_warden.feature.'
RAISE = P + 'raise_the_orbiting_ward'
QI = 'resource:core.qi'


def _store(tmp_path, features, cl=3):
    bundle = compile_character(sheet(features, cl=cl), actor_id=s.OWNER)
    combat = CombatService(ROOT, tmp_path / 'combat')
    arena = combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    store = JourneyStore(tmp_path / 'journeys')
    state = store.create([bundle], arena, {s.OWNER: {'x': 3, 'y': 6}}, {s.OWNER: 3000})
    return store, state['journey_id'], state


def test_manifest_ward_pays_qi_and_survives_cold_reload(tmp_path):
    store, jid, state = _store(tmp_path, [RAISE])
    before = state['actors'][s.OWNER]['resources'][QI]
    state = store.act(jid, state['revision'], s.OWNER, 'warden_manifest', {'points': [{'x': 3, 'y': 5}]})
    assert state['actors'][s.OWNER]['resources'][QI] == before - 1
    assert any(e['kind'] == 'RESOURCE_SPENT' for e in state['events'])
    reloaded = store.load(jid).state
    assert reloaded['actors'][s.OWNER]['resources'][QI] == before - 1
    assert 'source:orbiting_shield_warden' in reloaded['actors'][s.OWNER]['source_states']


def test_spend_rejects_without_mutating_when_balance_is_short(tmp_path):
    store, jid, state = _store(tmp_path, [RAISE])
    session = store.load(jid)
    actor = session.state['actors'][s.OWNER]
    actor['resources'][QI] = 0
    before = dict(actor['resources'])
    events = len(session.state['events'])
    with pytest.raises(ValueError):
        session.spend_resource(s.OWNER, QI, 1, 'test')
    assert actor['resources'] == before
    assert len(session.state['events']) == events
