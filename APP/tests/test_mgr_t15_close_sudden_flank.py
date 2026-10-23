"""Earn Sudden Flank at a persisted native table; no benefit is injected.

Native actions use the published ATTACK/MULTI_ATTACK wire format, sealed at
match genesis. Talents, skill bonuses and base actions compile from a portable
source-shaped sheet. Every transaction is continued through a fresh service.
"""
import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionDefinition, DiceSpec, EconomyKind
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService, TabletopError

ROOT = Path(__file__).resolve().parents[1]
FLANK = 'TAL_ATHLETICS_SUDDEN_FLANK'
FLIP = 'TAL_ATHLETICS_WHIRLWIND_FLIP'
OWNER, FOE, OTHER = [FACTORY_ACTOR_PREFIX + 'sudden-' + n for n in ('owner', 'foe', 'other')]
IDS = (OWNER, FOE, OTHER)
# Explicit literal dynamic dependencies for the approved safe exporter.
RESOURCES = ('authority/Tianxia_Typed_Mechanics_Authority_R1.json',
             'authority/typed_mechanics/rules_text.json',
             'combat/rules/feature_blocks.d/auto8-athletics.json',
             'combat/rules/feature_blocks.json',
             'combat/rules/feature_status.d/bodya.json')


def setup(tmp_path, *, success=True, owned=True, blind=False):
    authority = json.loads((ROOT / RESOURCES[0]).read_text())['mechanics']
    sphere = authority[FLANK]['sphere_id']
    bases = [mid for mid, r in authority.items() if r.get('sphere_id') == sphere and r.get('kind') == 'base_ability']
    bundles = []
    for aid, name in zip(IDS, ('Flanker', 'Guard', 'Bystander')):
        skilled = success if aid == OWNER else not success
        talents = [FLANK if owned else FLIP] if aid == OWNER else []
        doc = {'identity': {'name': name, 'display_name': name, 'cultivation_level': 17,
                           'proficiency_bonus': 6, 'path': 'Qi Cultivation', 'key_ability': 'DEX'},
               'ability_scores_and_statistics': {
                   'abilities': [{'ability': a, 'score': 20 if skilled else 10, 'modifier': 5 if skilled else 0}
                                 for a in ('STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA')],
                   'primary_resource': {'name': 'Stamina', 'maximum': 30}, 'armor_class': {'base_value': 14},
                   'hit_points': {'maximum': 400}, 'speed': {'walking_ft': 30},
                   'technique_save_dc': 16, 'technique_attack_bonus': 11,
                   'skills': [{'skill': 'Acrobatics', 'bonus': 17 if skilled else 0,
                               'proficiency': 'expertise' if skilled else 'none'}]},
               'spheres_and_talents': {'sphere_record_ids': [sphere] if talents else [],
                   'learned_talent_record_ids': talents, 'automatic_sphere_component_record_ids': bases if talents else []}}
        if aid == OWNER:
            # An actual source Path feature supplies further typed attacks;
            # never fabricate an extra attack or an earned flank at runtime.
            doc['identity']['path'] = 'Body Refining'
            doc['path_and_subpath'] = {'path_feature_record_ids': [
                'tianxia.path.body_refining.feature.extra_attack']}
        folder = tmp_path / 'portable_characters' / aid.removeprefix(FACTORY_ACTOR_PREFIX)
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
        bundle = compile_character(doc, actor_id=aid, reaction_plan={'ask': True})
        if aid == OWNER:
            # Native test actions are pre-genesis ordinary strikes, not talent
            # effects. Pair uses one Action; single uses a Bonus Action.
            for key, economy, count in (('single', EconomyKind.BONUS_ACTION, 1), ('pair', EconomyKind.ACTION, 2)):
                action = ActionDefinition(source_definition_id='action:test.sudden.native_' + key,
                    display_name='Native ' + key, owner_id=aid, economy=economy,
                    resolution_kind='ATTACK' if count == 1 else 'MULTI_ATTACK', attack_count=count,
                    target_kind='HOSTILE_ENTITY', reach_ft=5, attack_bonus=11,
                    damage=DiceSpec(count=1, sides=4, modifier=5), damage_type='BLUDGEONING')
                bundle['action_catalog'].append(action.model_dump(mode='json'))
                bundle['actor_template']['action_ids'].append(action.source_definition_id)
            if blind:
                action = ActionDefinition(source_definition_id='action:test.sudden.close_eyes', display_name='Close eyes',
                    owner_id=aid, economy=EconomyKind.NONE, resolution_kind='TYPED', target_kind='SELF',
                    parameters={'free_primary': True, 'typed': {'effects': [{'type': 'condition', 'condition': 'blinded', 'applies_to': 'self'}],
                        'numbers': {}, 'riders': [], 'duration': {'kind': 'instant'}}})
                bundle['action_catalog'].append(action.model_dump(mode='json'))
                bundle['actor_template']['action_ids'].append(action.source_definition_id)
        bundles.append(bundle)
    combat = CombatService(ROOT, tmp_path)
    mid = combat._finish_factory_match(bundles, list(IDS), {OWNER: 'team:a', FOE: 'team:b', OTHER: 'team:b'},
        {OWNER: {'x': 3, 'y': 6}, FOE: {'x': 4, 'y': 6}, OTHER: {'x': 5, 'y': 7}},
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'], [OWNER], [FOE, OTHER],
        control_modes={aid: 'MANUAL' for aid in IDS}, match_seed='MGR-SUDDEN', maximum_rounds=10,
        display_name='Sudden Flank native regression')['match_id']
    game = (tmp_path, mid)
    for _ in range(12):
        if menu(game)['actor_id'] == OWNER:
            break
        commit(game, menu(game)['end_turn'])
    assert menu(game)['actor_id'] == OWNER
    return game


def services(game):
    root, mid = game
    combat = CombatService(ROOT, root)
    return combat, TabletopService(combat, root), mid


def engine(game):
    combat, _, mid = services(game)
    return combat._load_session(mid).engine


def menu(game):
    _, table, mid = services(game)
    return table.state(mid)['menu']


def verify(game):
    combat, _, mid = services(game)
    session = combat._load_session(mid)
    assert session.verify()['status'] == 'PASS'
    assert session.mechanical.replay()['status'] == 'PASS'
    fresh = engine(game)
    assert session.engine.state.model_dump(mode='json') == fresh.state.model_dump(mode='json')
    assert [e.model_dump(mode='json') for e in session.engine.events] == [e.model_dump(mode='json') for e in fresh.events]
    assert session.engine.roller.counter == fresh.roller.counter


def commit(game, candidate):
    _, table, mid = services(game)
    m = menu(game)
    answers = []
    for _ in range(20):
        result = table.act(mid, candidate, m['decision_id'], m['state_version'], 0, answers)
        if result['status'] == 'COMMITTED':
            verify(game)
            return result
        assert result['status'] == 'REACTION_REQUIRED', result
        answers.append({**result['reaction']['context'], 'selection': 'DECLINE'})
    raise AssertionError('unsettled reaction')


def act(game, label, target=FOE):
    option = next(o for g in menu(game)['actions'] for o in g['options']
                  if label in o['label'] and (o.get('target_ids') == [target] or target is None))
    return commit(game, option['candidate_id'])


def move(game, path):
    _, table, mid = services(game)
    m = menu(game)
    points = [{'x': x, 'y': y} for x, y in path]
    quote = table.preview_move_path(mid, m['decision_id'], m['state_version'], OWNER, points)
    answers = []
    for _ in range(20):
        result = table.commit_move_path(mid, quote['candidate']['candidate_id'], m['decision_id'], m['state_version'], OWNER, points, reactions=answers)
        if result['status'] == 'COMMITTED':
            verify(game)
            return
        assert result['status'] == 'REACTION_REQUIRED', result
        answers.append({**result['reaction']['context'], 'selection': 'DECLINE'})
    raise AssertionError('unsettled movement')


def benefits(game):
    return [m for m in engine(game).state.actors[OWNER].modifiers.values() if m.source_definition_id == FLANK]


def rolls(game):
    return [e for e in engine(game).events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER]


def earn(game):
    before = engine(game).state.actors[OWNER]
    act(game, 'Tumble (Bonus Action)')
    after = engine(game).state.actors[OWNER]
    receipt = next(e for e in reversed(engine(game).events) if e.event_type == 'CHECK_ROLLED' and e.actor_id == OWNER)
    assert receipt.target_ids == (FOE,)
    assert receipt.payload['roll_kind'] == 'opposed_check' and receipt.payload['success'] is True
    assert receipt.payload['skill'] == receipt.payload['target_skill'] == 'Acrobatics'
    assert receipt.payload['actor']['roll_id'] != receipt.payload['target']['roll_id']
    assert after.action_available and not after.bonus_action_available
    assert after.movement_remaining_ft == before.movement_remaining_ft
    assert after.resources == before.resources
    assert not benefits(game), 'winning the contest without passage is insufficient'
    move(game, [(3, 6), (4, 6), (5, 6)])
    rows = benefits(game)
    assert len(rows) == 1 and rows[0].value == 'ADVANTAGE:' + FOE
    assert rows[0].expires_on == 'END_OF_CURRENT_TURN'
    verify(game)


def test_exact_source_and_registry():
    rules = json.loads((ROOT / RESOURCES[1]).read_text())
    assert hashlib.sha256(rules[FLANK].encode()).hexdigest() == '927a2f66268a342507f0fd5698f85ff910171156c92245d80f5821545a833ba6'
    registry = json.loads((ROOT / RESOURCES[2]).read_text())
    assert registry['features'][FLANK]['kind'] == 'sudden_flank'


@pytest.mark.parametrize('native', [True, False])
def test_earned_next_attack_consumed_once_after_cold_reload(tmp_path, native):
    game = setup(tmp_path)
    earn(game)
    mid = benefits(game)[0].modifier_id
    act(game, 'Native pair' if native else 'Unarmed Strike')
    attack = rolls(game)
    assert len(attack) >= 2, 'native and typed sequences both need a second real attack'
    assert attack[0].payload['mode'] == 'ADVANTAGE'
    assert all(e.payload['mode'] == 'NORMAL' for e in attack[1:])
    assert not benefits(game)
    removed = [e for e in engine(game).events if e.event_type == 'MODIFIER_REMOVED' and e.payload.get('modifier_id') == mid]
    assert len(removed) == 1 and removed[0].payload['reason'] == 'CONSUMED'
    if native:
        assert len(attack) == 2
    verify(game)


def test_other_target_preserves_eligible_benefit(tmp_path):
    game = setup(tmp_path)
    act(game, 'Tumble (Action)')
    move(game, [(3, 6), (4, 6), (5, 6)])
    original = benefits(game)[0].modifier_id
    act(game, 'Native single', OTHER)
    assert rolls(game)[-1].payload['mode'] == 'NORMAL'
    assert benefits(game)[0].modifier_id == original
    verify(game)


def test_advantage_cancellation_still_consumes_next_native_roll(tmp_path):
    game = setup(tmp_path, blind=True)
    earn(game)
    act(game, 'Close eyes', None)
    options = [o for g in menu(game)['actions'] for o in g['options'] if 'native_pair' in g['source_definition_id']]
    assert options
    commit(game, next(o for o in options if o.get('target_ids') == [FOE])['candidate_id'])
    assert [e.payload['mode'] for e in rolls(game)] == ['NORMAL', 'DISADVANTAGE']
    assert not benefits(game)


@pytest.mark.parametrize('owned,success', [(True, False), (False, True)])
def test_failed_tumble_or_no_owner_never_earns_flank(tmp_path, owned, success):
    game = setup(tmp_path, success=success, owned=owned)
    act(game, 'Tumble (Bonus Action)')
    receipt = next(e for e in reversed(engine(game).events) if e.event_type == 'CHECK_ROLLED' and e.actor_id == OWNER)
    assert receipt.target_ids == (FOE,) and receipt.payload['success'] is success
    assert receipt.payload['roll_kind'] == 'opposed_check'
    if success:
        move(game, [(3, 6), (4, 6), (5, 6)])
    else:
        with pytest.raises(TabletopError):
            move(game, [(3, 6), (4, 6), (5, 6)])
    assert not benefits(game)
    verify(game)


def test_declined_tumble_wrong_target_and_illegal_stop_never_earn(tmp_path):
    game = setup(tmp_path)
    with pytest.raises(TabletopError):
        move(game, [(3, 6), (4, 6), (5, 6)])
    act(game, 'Tumble (Bonus Action)')
    with pytest.raises(TabletopError):
        move(game, [(3, 6), (4, 6)])
    with pytest.raises(TabletopError):
        move(game, [(3, 6), (3, 7), (4, 7), (5, 7), (6, 7)])
    assert not benefits(game)
    verify(game)


def test_natural_end_turn_expires_earned_benefit(tmp_path):
    game = setup(tmp_path)
    earn(game)
    commit(game, menu(game)['end_turn'])
    assert not benefits(game)
    assert not any(c.condition_id == 'condition:typed.athletics_tumble' for c in engine(game).state.actors[OWNER].conditions.values())
    verify(game)
