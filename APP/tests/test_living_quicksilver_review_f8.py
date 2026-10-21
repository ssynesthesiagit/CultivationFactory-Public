"""Native review gates: private Body facts and transactional travel vetoes."""
import pytest

from combat.senses import perception
from combat.tabletop_service import TabletopService
from tests.test_living_quicksilver_native import (
    A, B, setup, engine, use, turn, settle,
)


def test_body_information_is_projected_only_to_its_owner_after_cold_load(tmp_path, monkeypatch):
    from tests.test_living_quicksilver_native import combat

    cold, jid, _, _ = setup(tmp_path, monkeypatch, 14)
    table, mid = combat(cold, jid, tmp_path)
    created = use(cold, table, mid, 'Create Quicksilver Body: 2 Qi')
    body = next(o for o in created.state.objects.values() if o.component.get('quicksilver_body'))
    loaded = engine(cold, mid)
    before = loaded.state.model_dump(mode='json')
    count = len(loaded.events)
    owner = perception(loaded, loaded.state.actors[A])
    other = perception(loaded, loaded.state.actors[B])
    facts = owner.get('information', [])
    body_fact = next((r for r in facts if r['kind'] == 'quicksilver_body'), None)
    assert body_fact is not None, 'Distributed Existence must reach the actual private perception caller.'
    assert body_fact['details']['position'] == body.position.model_dump(mode='json')
    assert body_fact['details']['hp'] == 28
    assert any(r['kind'] == 'qi_presence' for r in facts)
    assert not any(r['kind'] in ('quicksilver_body', 'qi_presence') for r in other.get('information', []))
    assert loaded.state.model_dump(mode='json') == before and len(loaded.events) == count
    assert engine(cold, mid).state.model_dump(mode='json') == before


@pytest.mark.parametrize('traveler', [A, B])
def test_body_occupancy_veto_survives_journey_preview_commit_and_reload(tmp_path, monkeypatch, traveler):
    cold, jid, act, _ = setup(tmp_path, monkeypatch, 6,
        positions={A: {'x': 3, 'y': 3}, B: {'x': 4, 'y': 4}})
    state = cold().journey_state(jid)
    mid = cold().journey_start_combat(jid, state['revision'], {A: 'team:a', B: 'team:b'},
        maximum_rounds=1)['match_id']
    table = TabletopService(cold(), tmp_path)
    turn(table, mid, A)
    created = use(cold, table, mid, 'Create Quicksilver Body: 2 Qi')
    body = next(o for o in created.state.objects.values() if o.component.get('quicksilver_body'))
    for _ in range(8):
        if engine(cold, mid).state.terminal_result is not None:
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    assert engine(cold, mid).state.terminal_result is not None
    state = cold().journey_state(jid)
    resumed = cold().journey_resume(jid, state['revision'])
    destination = body.position.model_dump(mode='json')
    menu = cold().journey_menu(jid, traveler)
    assert not any(o['kind'] == 'move' and all(
        o['payload']['path'][0].get(axis, 0) == destination[axis] for axis in ('x', 'y', 'z'))
        for o in menu['options']), 'Preview must honor gameplay vetoes.'
    with pytest.raises(ValueError, match='occupies'):
        act('move', {'path': [destination]}, who=traveler)
    assert cold().journey_state(jid) == resumed
    # Reject just the occupied volume, not every route or the nonowner's movement.
    legal = next(o for o in menu['options'] if o['kind'] == 'move')
    after = act('move', legal['payload'], who=traveler)
    assert after['actors'][traveler]['position'] != destination
    assert cold().journey_state(jid) == after


def test_conversion_training_none_sheet_commits_time_without_recompiling_parent(tmp_path, monkeypatch):
    from copy import deepcopy
    from tests.test_living_quicksilver_native import FAMILY
    from combat.ext.mgr_reserve_living_quicksilver_immortal_embryo_living_mercury_body import OLD

    cold, jid, act, world = setup(tmp_path, monkeypatch, 3, acquire=False, own_features=[OLD[0]])
    world('source_access', 'conversion', {'variant': FAMILY, 'route': 'conversion',
        'source_rule': 'A native inheritance permits conversion of the attained Mercurial feature.'})
    act('declare_fact', {'source': FAMILY, 'subject': A, 'kind': 'cultivation_environment',
        'scope': 'calm', 'value': {'calm': 1, 'ambient_qi': 1},
        'expires_at': 20000, 'readers': [A]})
    before = cold().journey_state(jid)
    bundle = deepcopy(before['actors'][A]['bundle'])
    resources = deepcopy(before['actors'][A]['resources'])
    after = cold().journey_acquire_source(jid, before['revision'], A, FAMILY,
        {'access_scope': 'conversion', 'procedure': 'train', 'environment_scope': 'calm'})
    assert after['seconds'] == before['seconds'] + 7200
    assert after['revision'] == before['revision'] + 1
    assert after['actors'][A]['source_states'][FAMILY]['training'] == 1
    assert after['actors'][A]['bundle'] == bundle
    assert after['actors'][A]['resources'] == resources
    assert any(e['kind'] == 'QUICKSILVER_CONVERSION_SESSION' for e in after['events'])
    assert cold().journey_state(jid) == after
