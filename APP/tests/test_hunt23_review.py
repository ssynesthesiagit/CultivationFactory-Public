"""Review regressions through committed tables; all fixtures are synthetic/sealed."""
import copy

import pytest

from combat.canonical import canonical_sha256, sha256_file
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService, INTEGRATION_SCHEMA
from combat.portable_runtime_authority import runtime_actor_id
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.hunt23_support import LEFT, RIGHT, ALLY, act, action_sender, fight, reload, turn
from tests.test_c3ar_runtime_executability import adapter, bundle, runtime_package

EVASION = 'tianxia.subpath.qi.abyssal_depths_cultivator.feature.flowing_evasion'
DEEP = 'tianxia.subpath.qi.abyssal_depths_cultivator.feature.deep_s_embrace'
SEAL = 'tianxia.talent.karma.ledger_seal_scripture'


def add_action(bundle, name, effects, *, economy='ACTION', target='HOSTILE_ENTITY', **typed):
    """Seal explicit fixture effects before genesis; never patch engine functions."""
    row = copy.deepcopy(next(a for a in bundle['action_catalog'] if a['resolution_kind'] == 'TYPED'))
    row.update(source_definition_id=f"action:test.review23.{bundle['actor_id']}.{name}", display_name=name,
               economy=economy, target_kind=target, range_ft=60, costs=[])
    row['parameters'] = {'typed': {'effects': effects, 'numbers': {'cl': 15, 'pb': 4, 'save_dc': 1},
                                 'duration': {'kind': 'instant'}, 'riders': [], **typed}}
    bundle['action_catalog'].append(row)
    bundle['actor_template']['action_ids'].append(row['source_definition_id'])


def settle(send, *, distance='5', destination='cell:3,5', ability='STR'):
    answers, prompts = [], []
    for _ in range(10):
        result = send(answers)
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            return prompts
        prompt = result['reaction']; prompts.append(prompt)
        name = prompt['reaction'].lower()
        option = ability if 'slip the grasp' in name else distance if 'distance' in name else destination if 'movement' in name else 'halve'
        answers.append({**prompt['context'], 'selection': 'USE', 'option_ids': [option]})
    raise AssertionError('too many choices')


@pytest.mark.parametrize('ai', [False, True])
@pytest.mark.parametrize('automatic', [False, True])
def test_portable_attack_completion_table(tmp_path, bundle, runtime_package, ai, automatic):
    # A real C3AR bundle/package and a compiled typed defender share one saved table.
    project = 'review23-portable'; package_hash = sha256_file(runtime_package)
    aid = runtime_actor_id(project, package_hash)
    raw = {'schema': 'TianxiaPortableCombatRuntimeAuthority.v1', 'runtime_actor_id': aid,
           'candidate_entry_id': 'test:review23', 'project_id': project, 'package_sha256': package_hash,
           'project_revision': 1, 'source_actor_id': bundle.actor_template.entity_id,
           'bundle': bundle.model_dump(mode='json', by_alias=True),
           'mechanics_lock_sha256': bundle.mechanics_lock_sha256,
           'primitive_registry_sha256': bundle.primitive_registry_sha256,
           'runtime_adapter_id': bundle.adapter_id, 'runtime_adapter_version': bundle.adapter_version,
           'runtime_engine_version': bundle.engine_version,
           'source_package_relative_path':'SourceCharacterPackage.zip', 'display_prose_parsed':False,
           'package_build_state_resource_values_used':False, 'source_package_mutated':False}
    for key in ('event_head_hash', 'replay_state_hash', 'content_lock_hash', 'combat_sheet_id',
                'combat_sheet_commitment_sha256', 'actor_template_commitment_sha256'):
        raw[key] = canonical_sha256({'fixture': key})
    raw['authority_sha256'] = canonical_sha256(raw)
    defender = compile_character(sheet([EVASION]), actor_id=LEFT, reaction_plan={'ask': True})
    defender['actor_template']['armor_class'] = 0
    defender.pop('bundle_sha256'); defender['bundle_sha256'] = canonical_sha256(defender)
    svc = CombatService(ROOT, tmp_path); table = TabletopService(svc, tmp_path)
    arena = svc.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    session = svc.persistence.create_match(match_seed='LOCK4-PORTABLE', maximum_rounds=3,
        runtime_authority=raw, source_package=runtime_package, typed_bundles=(defender,), battlefield=arena,
        roster_setup={'primary_actor_ids': [aid, LEFT], 'team_by_actor': {aid:'a', LEFT:'b'},
                      'starting_positions': {aid:{'x':4,'y':6}, LEFT:{'x':3,'y':6}}})
    mid = session.match_id
    svc._write_metadata(mid, {'schema': INTEGRATION_SCHEMA, 'integration_schema_version':'1.0.0',
        'match_id':mid, 'display_name':'Portable completion regression',
        'encounter_id':svc._catalog_cache['encounters'][0]['stable_id'], 'battlefield_id':arena['stable_id'],
        'participant_control_modes':{aid:'MANUAL', LEFT:'MANUAL'},
        'paused':False, 'local_auto_running':False, 'ui_preferences':{}, 'visual_assets':{}})
    turn(table, mid, aid)
    if automatic:
        svc.set_controller_mode(mid, actor_id=LEFT, controller_mode='LOCAL_AUTO')
    prompts = settle(action_sender(svc, table, mid, 'action:core.unarmed_strike', ai=ai))
    assert len(prompts) == (0 if automatic else 3)
    engine = reload(svc, mid); actor = engine.state.actors[LEFT]
    assert actor.resources['resource:core.qi'] == 28 and not actor.reaction_available
    assert actor.position.model_dump(mode='json') != {'x':3,'y':6}
    packet = next(e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and LEFT in e.target_ids)
    move = next(e for e in engine.events if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == LEFT)
    assert packet.payload['hp_damage'] == packet.payload['rolled_or_pending_damage']//2
    assert move.sequence > packet.sequence
    assert svc._load_session(mid).verify()['status'] == 'PASS'


@pytest.mark.parametrize('ai', [False, True])
@pytest.mark.parametrize('automatic', [False, True])
def test_liquid_body_slip_save_table(tmp_path, ai, automatic):
    def prepare(b):
        if b['actor_id'] == RIGHT:
            add_action(b, 'Physical hold', [{'type':'condition','condition':'grappled',
                'hold_kind':'ordinary_physical','duration':{'kind':'until_removed'}, 'condition_data':{'save_dc':1}}], economy='BONUS_ACTION')
    svc, table, mid = fight(tmp_path, [EVASION, DEEP], effects=[
        {'type':'attack','attack_kind':'cultivation','attack_bonus':100,'on_hit':[
            {'type':'damage','damage_type':'FORCE','flat':4}]}], target='HOSTILE_ENTITY', prepare_bundle=prepare,
        typed_parameters={'numbers':{'cl':15,'pb':4,'save_dc':1,'attack_bonus':100}})
    turn(table, mid, LEFT)
    assert act(table, mid, 'Deep’s Embrace')['status'] == 'COMMITTED'
    turn(table, mid, RIGHT)
    assert act(table, mid, 'Physical hold')['status'] == 'COMMITTED'
    engine = reload(svc, mid)
    assert any(c.condition_id.endswith('.grappled') for c in engine.state.actors[LEFT].conditions.values())
    if automatic:
        svc.set_controller_mode(mid, actor_id=LEFT, controller_mode='LOCAL_AUTO')
    prompts = settle(action_sender(svc, table, mid, 'Test setup', ai=ai))
    assert any('Slip the Grasp' in p['reaction'] for p in prompts) != automatic
    engine = reload(svc, mid)
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.source_definition_id == EVASION]
    assert len(saves) == 1 and saves[0].payload['success']
    assert saves[0].payload['mode'] == 'ADVANTAGE' and len(saves[0].payload['dice']) == 2
    assert not any(c.condition_id.endswith('.grappled') for c in engine.state.actors[LEFT].conditions.values())
    assert engine.state.actors[LEFT].resources['resource:core.qi'] == 25


@pytest.mark.parametrize('ai', [False, True])
@pytest.mark.parametrize('hazard', ['damage', 'hold', 'incapacitated', 'willing'])
def test_path_stops_after_hazard_and_is_voluntary(tmp_path, ai, hazard):
    def prepare(b):
        if b['actor_id'] != RIGHT:
            return
        effects = ([{'type':'damage','damage_type':'FORCE','flat':1000}] if hazard == 'damage' else
                   [{'type':'condition','condition':'grappled' if hazard == 'hold' else 'incapacitated',
                     'duration':{'kind':'until_removed'}}] if hazard in {'hold', 'incapacitated'} else
                   [{'type':'damage','damage_type':'FORCE','flat':3}])
        spec = {'name':'Test hazardous space','shape':'cube','size_ft':5,'duration':{'kind':'rounds','amount':3},
                'triggers':[] if hazard == 'willing' else [{'id':'test-enter','name':'Test entry','on':['enter'],'who':'hostile','effects':effects}]}
        if hazard == 'willing':
            spec['move_through'] = {'min_ft':5,'inclusive':True,'who':'any','effects':effects}
        add_action(b, 'Hazard setup', [{'type':'zone'}], economy='BONUS_ACTION', target='CELL', zone_spec=spec,
                   area={'shape':'cube','size_ft':5})
    svc, table, mid = fight(tmp_path, [EVASION], effects=[{'type':'attack','attack_bonus':100,
        'attack_kind':'cultivation','on_hit':[{'type':'damage','damage_type':'FORCE','flat':4}]}],
        target='HOSTILE_ENTITY', prepare_bundle=prepare,
        typed_parameters={'numbers':{'cl':15,'pb':4,'save_dc':1,'attack_bonus':100}})
    turn(table, mid, RIGHT)
    state = table.state(mid); menu = state['menu']
    group = next(g for g in menu['actions'] if g['label'] == 'Hazard setup')
    cid = next(o['candidate_id'] for o in group['options'] if o.get('destination') == {'x':3,'y':5})
    assert table.act(mid, cid, menu['decision_id'], menu['state_version'], state['last_sequence'], [])['status'] == 'COMMITTED'
    reload(svc, mid)
    settle(action_sender(svc, table, mid, 'Test setup', ai=ai), distance='10', destination='cell:3,4')
    engine = reload(svc, mid); defender = engine.state.actors[LEFT]
    moves = [e for e in engine.events if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == LEFT]
    assert len(moves) == (2 if hazard == 'willing' else 1)
    assert defender.position.model_dump(mode='json') == {'x':3,'y':4 if hazard == 'willing' else 5}
    if hazard == 'damage':
        assert defender.current_hp == 0
    elif hazard == 'hold':
        assert engine._effective_speed(defender) == 0
    elif hazard == 'incapacitated':
        assert any(c.condition_id.endswith('.incapacitated') for c in defender.conditions.values())
    else:
        terrain_damage = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
                          and 'Hazard setup' in e.source_definition_id and LEFT in e.target_ids]
        assert terrain_damage and sum(e.payload['hp_damage'] for e in terrain_damage) == 3
    assert defender.resources['resource:core.qi'] == 28


@pytest.mark.parametrize('ai', [False, True])
@pytest.mark.parametrize('blocked_corner', [False, True])
def test_path_revalidates_diagonal_after_zone_push(tmp_path, ai, blocked_corner):
    def prepare(b):
        if b['actor_id'] == RIGHT:
            spec = {'name': 'Test pushing space', 'shape': 'cube', 'size_ft': 5,
                    'duration': {'kind': 'rounds', 'amount': 3},
                    'triggers': [{'id': 'test-push-enter', 'name': 'Test entry push',
                                  'on': ['enter'], 'who': 'hostile',
                                  'effects': [{'type': 'forced_movement', 'distance_ft': 5,
                                               'direction': 'away', 'applies_to': 'target'}]}]}
            add_action(b, 'Push setup', [{'type': 'zone'}], economy='BONUS_ACTION',
                       target='CELL', zone_spec=spec, area={'shape': 'cube', 'size_ft': 5})

    svc, table, mid = fight(tmp_path, [EVASION], ally=[],
        positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 4, 'y': 5},
                   ALLY: {'x': 2, 'y': 4} if blocked_corner else {'x': 1, 'y': 4}},
        effects=[{'type': 'attack', 'attack_bonus': 100, 'attack_kind': 'cultivation',
                  'on_hit': [{'type': 'damage', 'damage_type': 'FORCE', 'flat': 4}]}],
        target='HOSTILE_ENTITY', prepare_bundle=prepare,
        typed_parameters={'numbers': {'cl': 15, 'pb': 4, 'save_dc': 1, 'attack_bonus': 100}})
    turn(table, mid, RIGHT)
    state = table.state(mid); menu = state['menu']
    group = next(g for g in menu['actions'] if g['label'] == 'Push setup')
    cid = next(o['candidate_id'] for o in group['options'] if o.get('destination') == {'x': 3, 'y': 5})
    assert table.act(mid, cid, menu['decision_id'], menu['state_version'], state['last_sequence'], [])['status'] == 'COMMITTED'
    reload(svc, mid)
    settle(action_sender(svc, table, mid, 'Test setup', ai=ai), distance='10', destination='cell:3,4')
    engine = reload(svc, mid); defender = engine.state.actors[LEFT]
    moves = [e for e in engine.events if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == LEFT]
    assert [e.payload['destination'] for e in moves] == [
        {'x': 3, 'y': 5}, {'x': 2, 'y': 5},
        *([] if blocked_corner else [{'x': 3, 'y': 4}])]
    assert defender.position.model_dump(mode='json') == ({'x': 2, 'y': 5} if blocked_corner else {'x': 3, 'y': 4})
    assert defender.resources['resource:core.qi'] == 28 and not defender.reaction_available
    assert svc._load_session(mid).verify()['status'] == 'PASS'


@pytest.mark.parametrize('ai', [False, True])
@pytest.mark.parametrize('kind', ['debt','grace'])
def test_ledger_seal_resource_and_imprint_table(tmp_path, ai, kind):
    def prepare(b):
        setup = [{'type':'reaction_denied','duration':{'kind':'rounds','amount':1}}]
        if kind == 'grace':
            setup.append({'type':'damage','damage_type':'FORCE','flat':2})
        add_action(b, 'Deny reactions', setup, economy='BONUS_ACTION')
    effects = ([{'type':'damage','damage_type':'FORCE','flat':2}] if kind == 'debt' else
               [{'type':'healing','flat':2,'applies_to':'target'}])
    svc, table, mid = fight(tmp_path, ['TAL_KARMA_RECORD_THE_DEED', SEAL], effects=effects,
        target='HOSTILE_ENTITY' if kind == 'debt' else 'ALLY_OR_SELF', ally=[] if kind == 'grace' else None,
        prepare_bundle=prepare)
    turn(table, mid, RIGHT)
    denied = act(table, mid, 'Deny reactions', target_id=LEFT)
    if denied['status'] == 'REACTION_REQUIRED':
        denied = act(table, mid, 'Deny reactions', [{**denied['reaction']['context'], 'selection':'DECLINE'}], target_id=LEFT)
    assert denied['status'] == 'COMMITTED'
    if kind == 'grace':
        turn(table, mid, ALLY)
    send = action_sender(svc, table, mid, 'Test setup', ai=ai, target_id=LEFT)
    result = send([]); assert result['status'] == 'REACTION_REQUIRED', result
    prompt = result['reaction']
    assert '1 Cultivation Point from your Qi pool' in prompt['cost'] and 'no Reaction' in prompt['cost']
    assert 'Debt Imprints let your Karma abilities punish' in prompt['summary']
    assert 'Grace Imprints let them protect or bless' in prompt['summary']
    assert kind.title() + ' Imprint' in prompt['trigger']
    assert send([{**prompt['context'], 'selection':'USE'}])['status'] == 'COMMITTED'
    engine = reload(svc, mid)
    from combat.ext.karma_imprints import held
    assert held(engine.state.actors[RIGHT if kind == 'debt' else ALLY], LEFT, kind)
    assert engine.state.actors[LEFT].resources['resource:core.qi'] == 29
    spent = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT' and e.source_definition_id == SEAL]
    assert len(spent) == 1
