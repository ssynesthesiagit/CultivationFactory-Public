"""Rest choice -> journey commit -> combat genesis and cold mechanical replay."""
import pytest
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from tests.h1_support import ROOT, sheet
from combat.ext import mgr_reserve_mercurial_cultivator_mercurial_qi as m

A = FACTORY_ACTOR_PREFIX + 'mercurial'
B = FACTORY_ACTOR_PREFIX + 'other'


def journey(tmp_path, monkeypatch):
    monkeypatch.setattr(CombatService, '_factory_owner_sheet', lambda self, pid:
        sheet([m.PREFIX + 'mercurial_qi'] if pid == 'mercurial' else [], cl=3, name=pid))
    arena = {'stable_id': 'journey:mercurial', 'width_squares': 10, 'height_squares': 5,
             'square_size_ft': 5, 'starting_positions': {}, 'terrain_regions': []}
    monkeypatch.setattr(CombatService, 'factory_arenas', lambda self, **kwargs: {'scene': arena})
    def cold():
        return CombatService(ROOT, tmp_path)
    def create():
        return cold().create_journey(project_ids=['mercurial', 'other'], arena_id='scene',
            positions={A: {'x': 1, 'y': 1}, B: {'x': 6, 'y': 1}}, base_paces={A: 500, B: 500})
    return cold, create


def test_rest_choice_is_earned_persistent_and_reaches_combat(tmp_path, monkeypatch):
    monkeypatch.setattr(CombatService, '_factory_owner_sheet', lambda self, pid:
        sheet([m.PREFIX + 'mercurial_qi'] if pid == 'mercurial' else [], cl=3, name=pid))
    arena = {'stable_id': 'journey:mercurial', 'width_squares': 10, 'height_squares': 5,
             'square_size_ft': 5, 'starting_positions': {}, 'terrain_regions': []}
    monkeypatch.setattr(CombatService, 'factory_arenas', lambda self, **kwargs: {'scene': arena})
    def cold():
        return CombatService(ROOT, tmp_path)
    initial = cold().create_journey(project_ids=['mercurial', 'other'], arena_id='scene',
        positions={A: {'x': 1, 'y': 1}, B: {'x': 6, 'y': 1}}, base_paces={A: 500, B: 500})
    jid = initial['journey_id']
    def act(aid, kind, payload=None):
        before = cold().journey_state(jid)
        after = cold().journey_act(jid, before['revision'], aid, kind, payload)
        assert after == cold().journey_state(jid)
        return after
    with pytest.raises(ValueError):
        act(A, 'mercurial_alloy', {'damage_type': 'FIRE'})
    state = act(A, 'long_rest')
    assert state['seconds'] == 28800
    with pytest.raises(ValueError):
        act(B, 'mercurial_alloy', {'damage_type': 'FIRE'})
    with pytest.raises(ValueError):
        act(A, 'mercurial_alloy', {'damage_type': 'FORCE'})
    state = act(A, 'mercurial_alloy', {'damage_type': 'FIRE'})
    assert state['actors'][A]['source_selections'][m.PREFIX + 'mercurial_qi']['damage_type'] == 'FIRE'
    with pytest.raises(ValueError):
        act(A, 'mercurial_alloy', {'damage_type': 'COLD'})
    state = act(A, 'long_rest')
    assert state['actors'][A]['source_selections'][m.PREFIX + 'mercurial_qi']['damage_type'] == 'FIRE'
    state = act(A, 'mercurial_alloy', {'damage_type': 'COLD'})
    match = cold().journey_start_combat(jid, state['revision'], {A: 'team:a', B: 'team:b'})
    loaded = cold()._load_session(match['match_id'])
    assert loaded.mechanical.replay()['status'] == 'PASS'
    assert m.held(loaded.engine.state.actors[A], 'alloy').data['damage_type'] == 'COLD'


def test_full_cultivation_requires_native_owner_environment_and_two_hours(tmp_path, monkeypatch):
    cold, create = journey(tmp_path, monkeypatch)
    jid = create()['journey_id']
    def act(kind, payload=None, aid=A):
        state = cold().journey_state(jid)
        after = cold().journey_act(jid, state['revision'], aid, kind, payload)
        assert after == cold().journey_state(jid)
        return after
    with pytest.raises(ValueError):
        act('mercurial_cultivation_session')
    declaration = {'authority': 'GM', 'calm': 1, 'energy_source': 'Native GM declaration: the local spring supplies ambient Qi'}
    with pytest.raises(ValueError):
        act('mercurial_cultivation_environment', declaration, aid=B)
    act('mercurial_cultivation_environment', declaration)
    state = act('mercurial_cultivation_session')
    assert state['seconds'] == 7200
    assert any(e['kind'] == 'FULL_CULTIVATION_SESSION_COMPLETED' for e in state['events'])
    with pytest.raises(ValueError):
        act('mercurial_cultivation_session')
    state = act('mercurial_alloy', {'damage_type': 'THUNDER'})
    assert state['actors'][A]['source_selections'][m.PREFIX + 'mercurial_qi']['damage_type'] == 'THUNDER'
    state = act('finish')
    fresh = create()
    assert fresh['actors'][A]['source_selections'][m.PREFIX + 'mercurial_qi']['damage_type'] == 'THUNDER'
    assert not any(r['kind'] == 'mercurial_cultivation_session' for r in cold().journey_menu(fresh['journey_id'], A)['options'])
    before_resources = {aid: dict(actor['resources']) for aid, actor in fresh['actors'].items()}
    scene = cold().journey_act(fresh['journey_id'], fresh['revision'], A, 'mercurial_scene_transition',
        {'authority': 'GM', 'reason': 'The journey party has finished the meaningful situation; a new scene begins.'})
    assert scene == cold().journey_state(fresh['journey_id'])
    assert scene['actors'][A]['source_selections'][m.PREFIX + 'scene']['number'] == 1
    assert not scene['actors'][B]['source_selections']
    assert {aid: actor['resources'] for aid, actor in scene['actors'].items()} == before_resources


@pytest.mark.parametrize('value', [1.5, True, None])
def test_persistent_source_selection_rejects_noninteger_nonstring_leaves(tmp_path, monkeypatch, value):
    cold, create = journey(tmp_path, monkeypatch)
    initial = create()
    session = cold().journeys.load(initial['journey_id'])
    session.state['actors'][A]['source_selections']['test:invalid'] = {'value': value}
    with pytest.raises(ValueError, match='integer/string'):
        cold().journeys.save(session)
    assert cold().journey_state(initial['journey_id']) == initial
