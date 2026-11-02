"""The printed missed-melee Charge works against legacy and typed enemies."""
import json
import zipfile

import pytest

from combat.ext.unbroken_bolt import FEATURE, BONE, POOL
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import Position
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from combat.typed_executor import Context, block_attack
from tests.test_auto_tabik import ROOT, ME
from tests.test_lock_choices import intent
from tests.test_lock2_persistence import act


def sheet(owned=True):
    return {
        'identity': {'proficiency_bonus': 4, 'cultivation_level': 14, 'path': 'Body Refining', 'key_ability': 'CON'},
        'ability_scores_and_statistics': {
            'abilities': [{'ability': a, 'score': 14, 'modifier': 2} for a in ('STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA')],
            'primary_resource': {'name': 'Stamina', 'maximum': 60}, 'armor_class': {'base_value': 1000},
            'hit_points': {'maximum': 80}, 'speed': {'walking_ft': 30}, 'technique_save_dc': 16, 'technique_attack_bonus': 8},
        'path_and_subpath': {'path_feature_record_ids': [FEATURE] if owned else []},
        'spheres_and_talents': {'sphere_record_ids': ['tianxia.sphere.iron_fist'],
                              'automatic_sphere_component_record_ids': ['TAL_IRON_FIST_IRON_FIST_TRAINING']},
    }


def fight(owned=True):
    bundle = compile_character(sheet(owned), actor_id=ME)
    engine = Gate4ControllerEngine(ROOT, match_seed='LOCK4-BOLT', typed_bundles=(bundle,),
        roster_setup={'primary_actor_ids': [ME, AN], 'team_by_actor': {ME: 'a', AN: 'b'},
                      'starting_positions': {ME: {'x': 3, 'y': 6}, AN: {'x': 4, 'y': 6}}})
    return engine


def miss(engine, ranged=False):
    return engine._resolve_attack_spec(engine.state.actors[AN], engine.state.actors[ME],
        {'attack_bonus': -1000, 'damage': None, 'range_ft': 30 if ranged else None}, intent(engine),
        source_definition_id='test:ordinary')


def test_legacy_miss_shared_round_limit_exception_and_maximum():
    engine = fight()
    target = engine.state.actors[ME]
    assert target.resources[POOL] == 0 and target.resource_maximums[POOL] == 4
    target.reaction_available = False
    assert not miss(engine) and target.resources[POOL] == 1
    assert not miss(engine) and target.resources[POOL] == 1
    engine._gain_resource(target, POOL, 1, 'test:other-normal-generator')
    assert target.resources[POOL] == 1
    engine._gain_resource(target, POOL, 1, BONE)
    assert target.resources[POOL] == 2
    engine._append_event('ROUND_STARTED', 'test:next-round', payload={'round': engine.state.round_number + 1})
    engine._gain_resource(target, POOL, 1, 'test:other-normal-generator')
    assert not miss(engine) and target.resources[POOL] == 3
    engine._gain_resource(target, POOL, 1, BONE)
    assert target.resources[POOL] == 4
    engine._append_event('ROUND_STARTED', 'test:next-round', payload={'round': engine.state.round_number + 2})
    assert not miss(engine) and target.resources[POOL] == 4


@pytest.mark.parametrize('case', ['unowned', 'ally', 'ranged', 'outside'])
def test_ineligible_misses_do_not_gain(case):
    engine = fight(case != 'unowned')
    actor, target = engine.state.actors[AN], engine.state.actors[ME]
    if case == 'ally':
        actor.team_id = target.team_id
    if case == 'outside':
        actor.position = Position(x=6, y=6)
    miss(engine, ranged=case == 'ranged')
    assert target.resources.get(POOL, 0) == 0
    assert not any(e.event_type == 'RESOURCE_GAINED' for e in engine.events)


def test_typed_miss_also_gains_once():
    engine = fight()
    attacker, target = engine.state.actors[AN], engine.state.actors[ME]
    action = engine.action_catalog['action:an_eui.paired_bi_shou_assault']
    typed = {'source': action.source_definition_id, 'range_ft': None,
             'numbers': {'attack_bonus': -1000, 'pb': 4}, 'effects': []}
    ctx = Context(engine, attacker, action, intent(engine), typed, [target], target)
    block_attack(ctx, {'type': 'attack', 'attack_kind': 'unarmed', 'no_damage': True})
    assert target.resources[POOL] == 1


def test_current_extended_reach_counts_even_after_spending_reaction():
    engine = fight()
    target = engine.state.actors[ME]
    target.reaction_available = False
    engine.state.actors[AN].position = Position(x=5, y=6)
    miss(engine)
    assert target.resources[POOL] == 0
    row = next(r for r in engine.typed_reaction_rows[ME] if r.get('block') == 'opportunity')
    row['reach_ft'] = 10
    assert target.resources[POOL] == 0  # expanding reach cannot retroactively award a Charge
    miss(engine)
    assert target.resources[POOL] == 1


def test_table_legacy_attack_charge_survives_commit_reload_and_replay(tmp_path):
    archive = tmp_path / 'portable_characters/bolt/current.zip'
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive, 'w') as zipped:
        zipped.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(sheet()))
    service = CombatService(ROOT, tmp_path)
    service.tabletop_maps.save({'display_name': 'Bolt yard', 'width_squares': 12, 'height_squares': 8,
        'walls': [], 'starts': {'team1': [[1, 1]], 'team2': [[0, 0]]}})
    me = FACTORY_ACTOR_PREFIX + 'bolt'
    view = service.create_factory_match(project_ids=['bolt'], opponent_actor_ids=[AN],
        control_modes={me: 'MANUAL', AN: 'MANUAL'}, arena_id='battlefield:map.bolt-yard', match_seed='LOCK4-BOLT-TABLE')
    mid, table = view['match_id'], TabletopService(service, tmp_path)
    if table.state(mid)['menu']['actor_id'] != AN:
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
    current = table.state(mid)['menu']
    assert any(g['source_definition_id'] == 'action:an_eui.paired_bi_shou_assault' for g in current['actions']), (
        current['actor_id'], [(g['source_definition_id']) for g in current['actions']],
        [(a.entity_id, a.position) for a in service._load_session(mid).engine.state.actors.values()])
    assert act(table, mid, 'action:an_eui.paired_bi_shou_assault')['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[me].resources[POOL] == 1
    gains = [e for e in loaded.engine.events if e.event_type == 'RESOURCE_GAINED' and e.source_definition_id == FEATURE]
    assert len(gains) == 1
    assert loaded.verify()['status'] == 'PASS'
    assert loaded.mechanical.replay()['status'] == 'PASS'
