"""Native Stars acquisition -> timed preparation -> table Starbolt -> cold replay."""
import json
import zipfile
import pytest

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.ext.stars_preparations import KEY, PREPARE, END
from tests.h1_support import ROOT, sheet
from tests.test_mgr_t14_starbolt_base import acquired_starbolt
from tests.test_mgr_t14_stars_celestial_reference import far_options
from tests.auto_worker1_support import LEFT, RIGHT, act, resolve, turn


def scene(tmp_path, *, native_doc=None):
    for aid in (LEFT, RIGHT):
        doc = sheet([], cl=1, kit={'starting_kit': {'items': [
            {'item_id': 'tianxia.mortal.weapon.dao', 'quantity': 1}]}}, score=30)
        if aid == LEFT and native_doc is not None:
            from copy import deepcopy
            doc = deepcopy(native_doc)
            # Authored portable starting equipment enters through the native
            # inventory compiler, never through a running-fight object fixture.
            doc['equipment'] = [{'starting_kit': {'items': [
                {'item_id': 'tianxia.mortal.gear.map', 'quantity': 1}]}}]
        else:
            acquired_starbolt(doc, aid)
        stats = doc['ability_scores_and_statistics']
        stats['armor_class']['base_value'] = 0
        stats['hit_points']['maximum'] = 1000
        stats['technique_attack_bonus'] = 100
        folder = tmp_path / 'portable_characters' / aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
    service = CombatService(ROOT, tmp_path)
    saved = service.tabletop_maps.save({'display_name': 'Stars preparation courtyard',
        'width_squares': 25, 'height_squares': 18, 'objects': []})
    def create():
        return service.create_journey(project_ids=[aid.removeprefix('actor:factory.') for aid in (LEFT, RIGHT)],
            arena_id='battlefield:map.' + saved['map_id'],
            positions={LEFT: {'x': 0, 'y': 1}, RIGHT: {'x': 19, 'y': 1}},
            base_paces={LEFT: 1000, RIGHT: 1000}, control_modes={LEFT: 'MANUAL', RIGHT: 'MANUAL'})
    return service, create(), create


def menu(service, state, actor=LEFT):
    return [row for row in service.journey_menu(state['journey_id'], actor)['options']
        if row['payload'].get('feature') == PREPARE]


@pytest.mark.parametrize('surface', ['location', 'body', 'item'])
def test_real_ten_minute_basic_anchor_enables_aligned_starbolt_after_cold_return(tmp_path, surface):
    service, state, _ = scene(tmp_path)
    assert not menu(service, state, RIGHT)
    choice = next(row for row in menu(service, state) if row['payload']['surface']['kind'] == surface)
    balances = dict(state['actors'][LEFT]['resources'])
    state = service.journey_act(state['journey_id'], state['revision'], LEFT, choice['kind'], choice['payload'])
    assert state['seconds'] == 600
    assert state['actors'][LEFT]['resources'] == balances
    assert len(state['actors'][LEFT]['source_states'][KEY]) == 1
    service = CombatService(ROOT, tmp_path)
    result = service.journey_start_combat(state['journey_id'], state['revision'],
        {LEFT: 'keepers', RIGHT: 'visitors'})
    mid = result['match_id']
    table = TabletopService(service, tmp_path)
    turn(table, mid, LEFT)
    assert far_options(table, mid)
    resolve(lambda answers: act(table, mid, 'Starbolt (Aligned: +30 ft)', answers, target_id=RIGHT))
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'
    assert any(e.event_type == 'ATTACK_ROLLED' and RIGHT in e.target_ids for e in session.engine.events)
    assert session.engine.state.actors[RIGHT].current_hp < 1000


def test_exact_lifetime_continuation_cap_and_owner_bound_ending(tmp_path):
    service, state, create = scene(tmp_path)
    pb = state['actors'][LEFT]['bundle']['actor_template']['proficiency_bonus']
    for _ in range(pb):
        choice = next(row for row in menu(service, state) if row['payload']['surface']['kind'] == 'location')
        state = service.journey_act(state['journey_id'], state['revision'], LEFT, choice['kind'], choice['payload'])
    assert not menu(service, state)
    ends = [row for row in service.journey_menu(state['journey_id'], LEFT)['options']
        if row['payload'].get('feature') == END]
    assert len(ends) == pb
    with pytest.raises(ValueError):
        service.journey_act(state['journey_id'], state['revision'], RIGHT, 'activate', ends[1]['payload'])
    before = state['seconds']
    for ending in ends[1:]:
        state = service.journey_act(state['journey_id'], state['revision'], LEFT, 'activate', ending['payload'])
    assert state['seconds'] == before
    retained = dict(state['actors'][LEFT]['source_states'][KEY])
    remaining = int(next(iter(retained.values()))['expires']) - state['seconds']
    service.journey_act(state['journey_id'], state['revision'], LEFT, 'finish', {})
    state = create()
    assert state['seconds'] == 0
    record = next(iter(state['actors'][LEFT]['source_states'][KEY].values()))
    assert set(state['actors'][LEFT]['source_states'][KEY]) == set(retained)
    assert record['expires'] == str(remaining)
    state = service.journey_act(state['journey_id'], state['revision'], LEFT, 'wait', {'seconds': remaining - 1})
    assert len(state['actors'][LEFT]['source_states'][KEY]) == 1
    state = service.journey_act(state['journey_id'], state['revision'], LEFT, 'wait', {'seconds': 1})
    assert not state['actors'][LEFT]['source_states'][KEY]
