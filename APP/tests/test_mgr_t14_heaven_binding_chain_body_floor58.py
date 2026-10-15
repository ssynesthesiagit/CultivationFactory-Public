"""Chain Body uses acquired sheet records, real table intents and cold replay.

No effect/trigger/ownership receipts are injected into a running fight.
"""
import json
import zipfile

from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.test_riders_c7 import sheet, ROOT, CHAIN, WHIP
from tests.test_lock2_persistence import act

OWNER = FACTORY_ACTOR_PREFIX + 'chain-owner'
TARGET = FACTORY_ACTOR_PREFIX + 'chain-target'


def acquired_fight(tmp_path, features, *, cl=18):
    for name, ids in [('chain-owner', features), ('chain-target', [])]:
        document = sheet([CHAIN + fid for fid in ids], cl=cl, items=(WHIP,), spheres={})
        document['identity']['display_name'] = name
        path = tmp_path / 'portable_characters' / name
        path.mkdir(parents=True)
        with zipfile.ZipFile(path / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document))
    service = CombatService(ROOT, tmp_path)
    service.tabletop_maps.save({'display_name': 'Chain evidence yard', 'width_squares': 16, 'height_squares': 12,
        'walls': [], 'starts': {'team1': [[3, 4]], 'team2': [[4, 4]]}})
    mid = service.create_factory_match(project_ids=['chain-owner'], opponent_actor_ids=[TARGET],
        control_modes={OWNER: 'MANUAL', TARGET: 'MANUAL'},
        arena_id='battlefield:map.chain-evidence-yard', match_seed='CHAIN-NATIVE-58')['match_id']
    table = TabletopService(service, tmp_path)
    while table.state(mid)['menu']['actor_id'] != OWNER:
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
    return service, table, mid


def commit(table, mid, source, *, choose=None):
    state = table.state(mid)
    menu = state['menu']
    group = next(g for g in menu['actions'] if source in g['source_definition_id'])
    candidate = group['options'][0]['candidate_id']
    answers = []
    for _ in range(24):
        result = table.act(mid, candidate, menu['decision_id'], menu['state_version'], state['last_sequence'], answers)
        if result['status'] == 'COMMITTED':
            return result
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        answer = {**prompt['context'], 'selection': 'USE'}
        if prompt.get('choice'):
            options = prompt['choice']['options']
            answer['option_ids'] = [choose if choose in {o['id'] for o in options} else options[0]['id']]
        answers.append(answer)
    raise AssertionError('unbounded reaction prompts')


def cold(service, mid):
    loaded = CombatService(ROOT, service.userdata_root)._load_session(mid)
    assert loaded.verify()['status'] == 'PASS'
    assert loaded.mechanical.replay()['status'] == 'PASS'
    return loaded.engine


def test_meridian_records_source_and_removal_contract_after_native_hit(tmp_path):
    service, table, mid = acquired_fight(tmp_path, ['chain_body_integration'])
    for _ in range(8):
        commit(table, mid, '.weapon.', choose='tether')
        engine = cold(service, mid)
        held = [c for c in engine.state.actors[TARGET].conditions.values()
                if c.condition_id == 'condition:typed.meridian_tether']
        if held:
            condition = held[0]
            assert condition.source_actor_id == OWNER
            assert condition.source_definition_id == CHAIN + 'chain_body_integration'
            assert condition.data['source_cl'] == 18
            assert condition.data['sense_ft'] == 60
            assert condition.data['hostile_forced'] == 0
            assert 'END_OF_SOURCE_TURN_AT:' in condition.expires_on
            return
        for _ in range(2):
            assert act(table, mid, 'end')['status'] == 'COMMITTED'
    raise AssertionError('no qualifying committed chain hit')


def test_prison_records_source_dc_and_separate_radius_after_commit(tmp_path):
    service, table, mid = acquired_fight(tmp_path, ['heaven_binding_prison'])
    commit(table, mid, 'heaven_binding_prison')
    engine = cold(service, mid)
    held = [c for c in engine.state.actors[TARGET].conditions.values()
            if c.condition_id == 'condition:typed.prison_tether']
    assert held
    assert held[0].data['source_cl'] == 18
    assert held[0].data['dc'] == 50
    assert held[0].data['radius_ft'] == 30


def native_tether(service, table, mid):
    for _ in range(8):
        commit(table, mid, '.weapon.', choose='tether')
        engine = cold(service, mid)
        held = [c for c in engine.state.actors[TARGET].conditions.values()
                if c.condition_id == 'condition:typed.meridian_tether']
        if held:
            return engine
        for _ in range(2):
            assert act(table, mid, 'end')['status'] == 'COMMITTED'
    raise AssertionError('no qualifying committed chain hit')


def test_release_is_source_owned_free_and_replays(tmp_path):
    service, table, mid = acquired_fight(tmp_path, ['chain_body_integration'])
    native_tether(service, table, mid)
    before = cold(service, mid).state.actors[OWNER].resources['resource:core.stamina']
    commit(table, mid, 'release_meridian_tether')
    engine = cold(service, mid)
    assert not any(c.condition_id == 'condition:typed.meridian_tether'
                   for c in engine.state.actors[TARGET].conditions.values())
    assert engine.state.actors[OWNER].resources['resource:core.stamina'] == before
    assert not any('release_meridian_tether' in g['source_definition_id'] for g in table.state(mid)['menu']['actions'])


def test_unowned_source_is_inert_after_committed_weapon_attack(tmp_path):
    service, table, mid = acquired_fight(tmp_path, [])
    commit(table, mid, '.weapon.')
    engine = cold(service, mid)
    assert not any(c.condition_id in {'condition:typed.meridian_tether', 'condition:typed.prison_tether'}
                   for actor in engine.state.actors.values() for c in actor.conditions.values())
    assert not any('release_meridian_tether' in a.source_definition_id for a in engine.action_catalog.values())


def test_network_willing_step_inside_reach_uses_one_normal_reaction(tmp_path):
    service, table, mid = acquired_fight(tmp_path, ['chain_body_integration', 'thousand_link_meridian_network'])
    native_tether(service, table, mid)
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    state = table.state(mid)
    menu = state['menu']
    assert menu['actor_id'] == TARGET
    move = next(m for m in menu['moves'] if m['destination'] == {'x': 4, 'y': 5})
    answers = []
    for _ in range(24):
        result = table.act(mid, move['candidate_id'], menu['decision_id'], menu['state_version'], state['last_sequence'], answers)
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        answer = {**prompt['context'], 'selection': 'USE'}
        if prompt.get('choice'):
            answer['option_ids'] = [prompt['choice']['options'][0]['id']]
        answers.append(answer)
    assert result['status'] == 'COMMITTED'
    engine = cold(service, mid)
    assert not engine.state.actors[OWNER].reaction_available
    assert any(e.event_type == 'REACTION_USED' and e.actor_id == OWNER for e in engine.events)
