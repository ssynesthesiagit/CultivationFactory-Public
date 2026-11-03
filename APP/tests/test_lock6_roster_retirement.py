"""New selections exclude retired samples; historical saves have a separate loader."""
import json

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.core import Settings
from combat.gate2_runtime_content import AN, BAI, CUI, LEE, LING, REACTION_PARAMETERS
from combat.gate5_service import CombatService
from combat.roster_selection import RETIRED_MESSAGE
from combat.tabletop import TeamPresetStore, TabletopError
from combat.typed_numbers import authority_mechanics, required_ac_reaction
from tests.test_factory_live_match import _install, ROOT


def test_public_catalog_and_default_api_match_exclude_retired_samples(tmp_path):
    with TestClient(create_app(Settings.from_env(ROOT, tmp_path))) as client:
        token = client.get('/api/session').json()['token']
        headers = {'x-foundry-token': token}
        catalog = client.get('/api/combat/catalog').json()
        serialized = json.dumps(catalog)
        assert not any(name in serialized for name in (LEE, LING, 'Ling Qi', 'Lee Jia'))
        assert {r['runtime_entity_id'] for r in catalog['projections']} == {AN, BAI, CUI}
        demo = client.get('/api/combat/accepted-demo/preflight').json()
        assert demo['ready'] and demo['expected']['combatants'] == 2
        assert not any(name in json.dumps(demo) for name in (LEE, LING, 'Ling Qi', 'Lee Jia'))
        visuals = client.get('/api/combat/visual-assets').json()
        assert not any(aid in (LEE, LING) for row in visuals['tokens'] for aid in row.get('stable_actor_ids', []))
        response = client.post('/api/combat/matches', headers=headers, json={
            'encounter_id': catalog['encounters'][0]['stable_id'], 'match_seed': 'LOCK6-ROSTER', 'control_modes': {}})
        assert response.status_code == 200, response.text
        body = response.json()
        assert {row['entity_id'] for row in body['state']['actors']} == {AN, BAI, CUI}
        assert client.app.state.combat._load_session(body['match_id']).verify()['status'] == 'PASS'
        for actor_id in (LING, LEE):
            refused = client.post('/api/combat/matches', headers=headers, json={
                'encounter_id': catalog['encounters'][0]['stable_id'], 'control_modes': {actor_id: 'MANUAL'}})
            assert refused.status_code == 409
            assert RETIRED_MESSAGE in refused.text


@pytest.mark.parametrize('actor_id', [LING, LEE])
def test_creation_rejects_retired_setup_and_factory_opponents(tmp_path, actor_id):
    _install(tmp_path, 'left')
    service = CombatService(ROOT, tmp_path)
    with pytest.raises(Exception, match='retired sample fighters'):
        service.create_factory_match(project_ids=['left'], opponent_actor_ids=[actor_id])
    with pytest.raises(Exception, match='retired sample fighters'):
        service.create_match(encounter_id=service.catalog()['encounters'][0]['stable_id'],
            display_name=None, match_seed='retired', control_modes={},
            setup_binding={'participants': [{'actor_id': actor_id}]})


def test_presets_hide_retired_samples_without_rewriting_saved_file(tmp_path):
    store = TeamPresetStore(tmp_path)
    good = {'name': 'Finished fighters', 'teams': [[{'pid': 'left'}], [{'pid': 'right'}]]}
    store.save(good)
    for aid in (LING, LEE):
        with pytest.raises(TabletopError, match='retired sample fighters'):
            store.save({'name': 'Retired', 'teams': [[{'pid': aid}], [{'pid': 'left'}]]})
    document = json.loads(store.path.read_text())
    document['Historical setup'] = {'name': 'Historical setup', 'teams': [[{'pid': LING}], [{'pid': LEE}]]}
    store.path.write_text(json.dumps(document))
    original = store.path.read_bytes()
    assert [row['name'] for row in store.list()] == ['Finished fighters']
    assert store.path.read_bytes() == original


def test_legacy_qi_armor_numbers_follow_the_typed_owner_record(monkeypatch):
    record_id = 'tianxia.path.qi_cultivation.feature.qi_armor'
    assert required_ac_reaction(record_id, 'qi') == {'cost': 2, 'ac_bonus': 5}
    assert REACTION_PARAMETERS['reaction:ling_qi.qi_armor']['ac_bonus'] == 5
    # A future authority edit changes generation too, without another literal.
    import combat.typed_numbers as numbers
    monkeypatch.setattr(numbers, 'authority_mechanics', lambda: {record_id: {
        'cost': [[{'resource': 'qi', 'amount': 4}]], 'effects': [{'type': 'ac_bonus', 'flat': 7}]}})
    assert required_ac_reaction(record_id, 'qi') == {'cost': 4, 'ac_bonus': 7}
    from combat.gate2a import build_gate2a_lock
    armor = next(row for row in build_gate2a_lock().profiles if row.source_definition_id == 'reaction:ling_qi.qi_armor')
    assert armor.costs[0].amount == 4
