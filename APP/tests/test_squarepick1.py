"""Spatial continuation choices stay on the map; real Blossom commits survive reload."""
from pathlib import Path
import subprocess

import pytest

from combat.choice_presentation import space_choice
from combat.ext import placed
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from tests.hunt12_support import ME, FOE, reload
from tests.test_a2_flowers import scene
from tests.test_menuspeed3_review import offline_menu_embeddings


def blossom_pause(tmp_path):
    combat, table, mid = scene(tmp_path, ['TAL_FLOWERS_CULTIVATE_BLOSSOM'])
    menu = table.state(mid)['menu']
    group = next(g for g in menu['actions'] if g['label'] == 'Cultivate Blossom (bloom at once)')
    assert group['placement_picker']
    request = dict(candidate_id=group['options'][0]['candidate_id'],
                   decision_id=menu['decision_id'], state_version=menu['state_version'], after=0)
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    result = table.act(mid, **request)
    assert result['status'] == 'REACTION_REQUIRED'
    assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
    return combat, table, mid, request, before, result['reaction']


def test_bloom_at_once_map_answer_commits_and_reloads(tmp_path):
    combat, _, mid, request, before, prompt = blossom_pause(tmp_path)
    choice = prompt['choice']
    assert choice['map_pick']['prompt'] == 'Cultivate Blossom: choose where the blossom blooms.'
    assert choice['map_pick']['cells'] == [o['cell'] for o in choice['options']]
    assert 'reaction affecting' not in prompt['trigger']
    assert prompt['trigger'].count('uses Cultivate Blossom') <= 1
    assert prompt['cancel_action']
    chosen = next(o for o in choice['options'] if o['cell'] == {'x': 3, 'y': 6, 'z': 0})
    table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    pending = table.state(mid)['pending_action']
    assert pending['reaction'] == prompt
    answer = {**prompt['context'], 'selection': 'USE', 'option_ids': [chosen['id']]}
    result = table.act(mid, **request, reactions=[answer])
    assert result['status'] == 'COMMITTED'
    engine = reload(tmp_path, mid)
    assert not placed.of(engine, 'blossom', owner_id=ME), 'immediate bloom consumes the dormant blossom'
    assert engine.state.actors[ME].action_available is False
    assert engine.state.actors[ME].resources['resource:core.stamina'] == before['actors'][ME]['resources']['resource:core.stamina'] - 1
    assert any('blooms: Medicinal Blossom' in str(e.payload) for e in engine.events)
    assert TabletopService(CombatService(ROOT, tmp_path), tmp_path).state(mid)['pending_action'] is None


def test_esc_cancel_seam_discards_only_initial_manual_placement(tmp_path):
    combat, table, mid, request, before, prompt = blossom_pause(tmp_path)
    from combat.tabletop import TabletopError
    with pytest.raises(TabletopError):
        table.cancel_placement(mid, **{**prompt['cancel_action'], 'candidate_id': 'candidate:stale'})
    assert table.state(mid)['pending_action']
    assert table.cancel_placement(mid, **prompt['cancel_action'])['status'] == 'CANCELLED'
    assert reload(tmp_path, mid).state.model_dump(mode='json') == before
    assert table.state(mid)['pending_action'] is None
    assert table.act(mid, **request)['status'] == 'REACTION_REQUIRED', 'the player can aim again'


def test_http_answer_and_own_page_routes(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.api import create_app
    from app.core import Settings
    _, _, mid, request, _, prompt = blossom_pause(tmp_path)
    app = create_app(Settings.from_env(ROOT, tmp_path))
    monkeypatch.setattr(app.state.agent_seats, 'kick', lambda *args, **kwargs: None)
    chosen = next(o for o in prompt['choice']['options'] if o['cell'] == {'x': 3, 'y': 6, 'z': 0})
    answer = {**prompt['context'], 'selection': 'USE', 'option_ids': [chosen['id']]}
    with TestClient(app) as client:
        headers = {'x-foundry-token': client.get('/api/session').json()['token']}
        # /play belongs to the phone client (main's mobile_play_page); /tabletop stays the desktop table.
        assert client.get('/tabletop').content == (ROOT / 'static' / 'tabletop' / 'tabletop.html').read_bytes()
        assert client.get('/play').content == (ROOT / 'static' / 'play' / 'play.html').read_bytes()
        response = client.post(f'/api/tabletop/matches/{mid}/act', headers=headers,
                               json={**request, 'reactions': [answer]})
        assert response.status_code == 200, response.text
        assert response.json()['status'] == 'COMMITTED'
    assert reload(tmp_path, mid).state.actors[ME].action_available is False


def test_http_cancel_retains_resources_and_the_action(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.api import create_app
    from app.core import Settings
    _, _, mid, _, before, prompt = blossom_pause(tmp_path)
    app = create_app(Settings.from_env(ROOT, tmp_path))
    monkeypatch.setattr(app.state.agent_seats, 'kick', lambda *args, **kwargs: None)
    with TestClient(app) as client:
        response = client.post(f'/api/tabletop/matches/{mid}/placement/cancel',
                               headers={'x-foundry-token': client.get('/api/session').json()['token']}, json=prompt['cancel_action'])
        assert response.status_code == 200, response.text
        assert response.json()['status'] == 'CANCELLED'
    assert reload(tmp_path, mid).state.model_dump(mode='json') == before


def test_renewed_aim_rejects_the_previous_attempt_cancel(tmp_path):
    """Cancel → aim the same action again → the first attempt's Cancel must not answer the new aim."""
    combat, table, mid, request, before, prompt = blossom_pause(tmp_path)
    stale = prompt['cancel_action']
    assert table.cancel_placement(mid, **stale)['status'] == 'CANCELLED'
    fresh_prompt = table.act(mid, **request)['reaction']
    fresh = fresh_prompt['cancel_action']
    assert fresh['pending_id'] != stale['pending_id'], 'a renewed aim must bind its own cancel attempt id'
    from combat.tabletop import TabletopError
    with pytest.raises(TabletopError):
        table.cancel_placement(mid, **stale)
    pending = table.state(mid)['pending_action']
    assert pending, 'the renewed aim stays waiting after the stale Cancel was rejected'
    assert pending['pending_id'] == fresh['pending_id']
    assert table.cancel_placement(mid, **fresh)['status'] == 'CANCELLED', 'the fresh aim can still be cancelled'
    assert reload(tmp_path, mid).state.model_dump(mode='json') == before


def test_http_cancel_binds_to_the_renewed_attempt(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.api import create_app
    from app.core import Settings
    _, _, mid, request, before, prompt = blossom_pause(tmp_path)
    app = create_app(Settings.from_env(ROOT, tmp_path))
    monkeypatch.setattr(app.state.agent_seats, 'kick', lambda *args, **kwargs: None)
    stale = prompt['cancel_action']
    table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    with TestClient(app) as client:
        headers = {'x-foundry-token': client.get('/api/session').json()['token']}
        url = f'/api/tabletop/matches/{mid}/placement/cancel'
        assert client.post(url, headers=headers, json=stale).status_code == 200
        fresh_prompt = table.act(mid, **request)['reaction']
        fresh = fresh_prompt['cancel_action']
        response = client.post(url, headers=headers, json=stale)
        assert response.status_code == 409, f'the previous attempt is stale: {response.text}'
        assert table.state(mid)['pending_action']['pending_id'] == fresh['pending_id']
        assert client.post(url, headers=headers, json=fresh).status_code == 200
    assert reload(tmp_path, mid).state.model_dump(mode='json') == before


@pytest.mark.parametrize('kind', ['square', 'multiple'])
def test_spatial_choices_need_no_ability_specific_map_hook(tmp_path, kind):
    combat, table, mid = scene(tmp_path, ['TAL_FLOWERS_CULTIVATE_BLOSSOM'])
    engine = combat._load_session(mid).engine
    options = [{'id': 'cell:3,6'}, {'id': 'cell:5,6'}]
    prompt = {'title': 'Choose', 'reaction': 'Test ability',
              'choice': {'options': options, 'minimum': 1, 'maximum': 2 if kind == 'multiple' else 1}}
    shown = space_choice(prompt, {'reactor_id': ME, 'reaction_source_id': 'choice:test.spatial'}, engine)
    assert len(shown['choice']['map_pick']['cells']) == len(options)
    assert [o['id'] for o in shown['choice']['options']] == [o['id'] for o in options]
    assert shown['choice']['maximum'] == prompt['choice']['maximum']


def test_plain_creature_choice_keeps_its_list(tmp_path):
    """Regression (F8R 1): a choice whose options are only creature IDs is not a map choice."""
    combat, table, mid = scene(tmp_path, ['TAL_FLOWERS_CULTIVATE_BLOSSOM'])
    engine = combat._load_session(mid).engine
    prompt = {'title': 'Reaction', 'reaction': 'Test ability',
              'choice': {'options': [{'id': ME, 'label': 'Mei'}, {'id': FOE, 'label': 'Foe'}],
                         'minimum': 1, 'maximum': 1}}
    shown = space_choice(prompt, {'reactor_id': ME, 'reaction_source_id': 'choice:test.creature'}, engine)
    assert shown is prompt, 'a creature list must come back unchanged'
    assert 'map_pick' not in shown['choice'] and 'space_map' not in shown['choice']
    assert all('cell' not in o for o in shown['choice']['options'])
    assert [o['label'] for o in shown['choice']['options']] == ['Mei', 'Foe']


def test_creature_in_a_spatial_choice_is_its_token_square(tmp_path):
    """A creature option inside a choice the engine marked with squares is answered on its token's square."""
    combat, table, mid = scene(tmp_path, ['TAL_FLOWERS_CULTIVATE_BLOSSOM'])
    engine = combat._load_session(mid).engine
    prompt = {'title': 'Choose', 'reaction': 'Test ability',
              'choice': {'options': [{'id': 'cell:3,6'}, {'id': FOE}], 'minimum': 1, 'maximum': 1}}
    shown = space_choice(prompt, {'reactor_id': ME, 'reaction_source_id': 'choice:test.mixed'}, engine)
    by_id = {o['id']: o for o in shown['choice']['options']}
    assert by_id[FOE]['target_id'] == FOE and by_id[FOE]['cell']
    assert by_id['cell:3,6']['cell'] == {'x': 3, 'y': 6}


def test_spatial_dom_regressions():
    app = Path(__file__).resolve().parents[1]
    # Both browser-side suites: the map-pick routing, and the phone's answer path (no other runner executes the phone file).
    result = subprocess.run(['node', '--test', str(app / 'static/tabletop/tabletop_map_pick.test.mjs'),
                             str(app / 'tests/mobile_play_map_pick.test.mjs')],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
