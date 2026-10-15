"""Actual sphere acquisition -> native learning intent -> encounter -> cold replay."""
import json
import zipfile

import pytest

from canonical_catalog.service import CanonicalCatalogAuthorityService
from sphere_component_authority import attach_sphere_automatic_component_receipt
from combat.gate5_service import CombatService
from combat.ext.wenxue_saber_methods import SOURCE, KEY, METHODS, practices
from tests.h1_support import ROOT, sheet

OWNER = 'actor:factory.saber-method-owner'
FOE = 'actor:factory.saber-method-visitor'
POSITIONS = {OWNER: {'x': 3, 'y': 6}, FOE: {'x': 6, 'y': 6}}


def native_journey(tmp_path, *, mode='MANUAL', owns=True):
    for actor_id in (OWNER, FOE):
        doc = sheet([], cl=1, name=actor_id.rsplit('.', 1)[-1],
            kit={'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.dao', 'quantity': 1}]}})
        if actor_id == OWNER and owns:
            ledger = {}
            packet = attach_sphere_automatic_component_receipt(ledger,
                CanonicalCatalogAuthorityService(ROOT).get_sphere(SOURCE), {
                    'event_id': 'native-saber-method-learning', 'legal_channel': 'sphere_acquisition',
                    'advancement': {'target_cl': 1}})
            doc['spheres_and_talents'] = {'sphere_record_ids': [SOURCE], 'learned_talent_record_ids': [],
                'automatic_sphere_component_record_ids': packet['component_ids'],
                'automatic_sphere_component_receipts': ledger['automatic_sphere_component_receipts'],
                'automatic_sphere_components': ledger['automatic_sphere_components']}
        folder = tmp_path / 'portable_characters' / actor_id.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
    service = CombatService(ROOT, tmp_path)
    saved = service.tabletop_maps.save({'display_name': 'Saber learning courtyard',
        'width_squares': 20, 'height_squares': 18, 'objects': []})
    arena = 'battlefield:map.' + saved['map_id']
    def create():
        return CombatService(ROOT, tmp_path).create_journey(
            project_ids=['saber-method-owner', 'saber-method-visitor'], arena_id=arena,
            positions=POSITIONS, base_paces={OWNER: 1000, FOE: 1000},
            control_modes={OWNER: mode, FOE: 'MANUAL'})
    return service, create(), create


def options(service, jid, actor=OWNER):
    return [row for row in service.journey_menu(jid, actor)['options']
        if row['kind'] == 'source_selection' and row['payload'].get('source') == SOURCE]


def enter_and_verify(tmp_path, jid):
    service = CombatService(ROOT, tmp_path)
    state = service.journey_state(jid)
    result = service.journey_start_combat(jid, state['revision'], {OWNER: 'keepers', FOE: 'visitors'})
    session = CombatService(ROOT, tmp_path)._load_session(result['match_id'])
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'
    return session.engine


def test_manual_learning_keeps_all_methods_and_continues_across_finished_journeys(tmp_path):
    service, state, create = native_journey(tmp_path)
    jid = state['journey_id']
    menu = options(service, jid)
    assert {row['payload']['method'] for row in menu} == set(METHODS)
    with pytest.raises(ValueError, match='Choose the Saber Method'):
        service.journey_start_combat(jid, state['revision'], {OWNER: 'keepers', FOE: 'visitors'})
    assert service.journey_state(jid) == state
    selected = next(row for row in menu if row['payload']['method'] == 'cruel_edge')
    after = service.journey_act(jid, state['revision'], OWNER, selected['kind'], selected['payload'])
    assert after['seconds'] == state['seconds']
    assert after['actors'][OWNER]['resources'] == state['actors'][OWNER]['resources']
    assert after['actors'][OWNER]['source_selections'][KEY]['method'] == 'cruel_edge'
    assert after['events'][-1]['kind'] == 'SOURCE_SELECTION_COMMITTED'
    service = CombatService(ROOT, tmp_path)
    assert not options(service, jid)
    with pytest.raises(ValueError, match='already chose'):
        service.journey_act(jid, after['revision'], OWNER, selected['kind'], selected['payload'])
    assert service.journey_state(jid) == after
    service.journey_act(jid, after['revision'], OWNER, 'finish', {})
    later = create()
    assert later['actors'][OWNER]['source_selections'][KEY]['method'] == 'cruel_edge'
    assert not options(service, later['journey_id'])
    engine = enter_and_verify(tmp_path, later['journey_id'])
    assert practices(engine, engine.state.actors[OWNER], 'cruel_edge')
    assert not practices(engine, engine.state.actors[FOE], 'cruel_edge')


@pytest.mark.parametrize('method', list(METHODS))
def test_automatic_actor_can_select_every_legal_method_without_hidden_information(tmp_path, method):
    service, state, _ = native_journey(tmp_path, mode='LOCAL_AUTO')
    jid = state['journey_id']
    menu = options(service, jid)
    assert {row['payload']['method'] for row in menu} == set(METHODS)
    choice = next(row for row in menu if row['payload']['method'] == method)
    after = service.journey_auto_step(jid, state['revision'], OWNER, option_id=choice['id'])
    assert after['actors'][OWNER]['source_selections'][KEY]['method'] == method
    engine = enter_and_verify(tmp_path, jid)
    assert practices(engine, engine.state.actors[OWNER], method)


def test_wrong_owner_unknown_method_and_extra_fields_cannot_create_practice(tmp_path):
    service, state, _ = native_journey(tmp_path)
    jid = state['journey_id']
    assert not options(service, jid, FOE)
    for actor, payload in [(FOE, {'source': SOURCE, 'method': 'cruel_edge'}),
                           (OWNER, {'source': SOURCE, 'method': 'unknown'}),
                           (OWNER, {'source': SOURCE, 'method': []}),
                           (OWNER, {'source': SOURCE, 'method': 'cruel_edge', 'grant_wound': 1})]:
        with pytest.raises(ValueError):
            service.journey_act(jid, state['revision'], actor, 'source_selection', payload)
        assert service.journey_state(jid) == state


def test_default_automatic_learning_settles_before_movement(tmp_path):
    service, state, _ = native_journey(tmp_path, mode='LOCAL_AUTO')
    after = service.journey_auto_step(state['journey_id'], state['revision'], OWNER)
    assert after['actors'][OWNER]['source_selections'][KEY]['method'] in METHODS
    assert after['actors'][OWNER]['position'] == state['actors'][OWNER]['position']
    assert after['seconds'] == state['seconds']
