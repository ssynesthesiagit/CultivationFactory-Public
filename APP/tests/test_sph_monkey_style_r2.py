"""Free weapon attacks use shared geometry and remembered aims at the table."""
import copy

import pytest

from combat.target_knowledge import can_see, knowledge
from tests.r1i_service_support import OWNER, FOE, SECOND, candidate
from tests.test_auto85f1_monkey_review import (
    M, REVERSAL_RESULTS, _labels, _to_turn, _ranged_miss,
    _foe_certain_strike, drive, monkey_fixture,
)
from tests.test_sph_monkey_style_r1 import _rehash
from tests.test_r1i_round3 import reload


def _setup(bundles, who, label, effects):
    bundle = next(b for b in bundles if b['actor_id'] == who)
    action = copy.deepcopy(next(a for a in bundle['action_catalog'] if a['resolution_kind'] == 'TYPED'))
    action.update(source_definition_id='test:r2.' + label, display_name=label,
                  economy='BONUS_ACTION', target_kind='SELF', costs=[], range_ft=0, attack_bonus=None)
    action['parameters'] = {'typed': {'effects': effects, 'numbers': {'cl': 17, 'pb': 4},
                                    'duration': {'kind': 'instant'}, 'riders': []}}
    bundle['action_catalog'].append(action)
    bundle['actor_template']['action_ids'].append(action['source_definition_id'])
    _rehash(bundle)


def _invisibility(bundles, who):
    _setup(bundles, who, 'Become invisible', [{'type': 'condition', 'condition': 'invisible',
        'applies_to': 'self', 'expires_on': 'UNTIL_REMOVED'}])


@pytest.mark.parametrize('ability,weapon', [('uncatchable', 'melee'), ('reversal', 'melee'), ('reversal', 'improvised')])
def test_offered_attack_reaches_large_footprint_after_commit_reload(tmp_path, ability, weapon):
    target = SECOND if ability == 'uncatchable' else FOE
    def prepare(bundles):
        (_ranged_miss if ability == 'uncatchable' else _foe_certain_strike)(bundles)
        bundle = next(b for b in bundles if b['actor_id'] == target)
        _setup(bundles, target, 'Grow large', [{'type': 'size_change', 'size': 'Large', 'expires_on': 'UNTIL_REMOVED'}])
        for bundle in bundles:
            for action in bundle['action_catalog']:
                if bundle['actor_id'] == OWNER and 'weapon' in str(action['parameters'].get('typed', {}).get('source', '')):
                    action['range_ft'] = 5
                if action['source_definition_id'] == 'test:auto85f1.foe_hit':
                    action['range_ft'] = 60
            _rehash(bundle)
    talent = 'GREAT_SAGE_EQUAL_TO_HEAVEN' if ability == 'uncatchable' else 'IMPOSSIBLE_APE_REVERSAL'
    positions = {OWNER: {'x': 5, 'y': 6}, target: {'x': 3, 'y': 6},
                 (FOE if target == SECOND else SECOND): {'x': 8, 'y': 6}}
    combat, table, mid, send, _ = monkey_fixture(tmp_path, [M + talent, M + 'IMPROVISED_MASTER'],
        bundle_transform=prepare, positions=positions)
    if ability == 'uncatchable':
        drive(send, candidate(table, mid, 'Great Sage Equal to Heaven', OWNER), use=())
    _to_turn(table, mid, target)
    drive(send, candidate(table, mid, 'Grow large'), use=())
    _to_turn(table, mid, FOE)
    held = reload(tmp_path, mid)
    assert held._footprint(held.state.actors[target]).width_cells == 2
    prompts = drive(send, candidate(table, mid, 'Test longbow' if ability == 'uncatchable' else 'Test Unarmed', OWNER),
        use=('Impossible Ape Reversal',), pick=(f'Attack Second with your melee weapon' if ability == 'uncatchable'
                                              else [REVERSAL_RESULTS[4], f'{weapon} weapon']))
    assert any(f'{weapon} weapon' in label for p in prompts for label in _labels(p))
    after = reload(tmp_path, mid)
    swings = [e for e in after.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER]
    assert len(swings) == 1 and target in swings[0].target_ids


@pytest.mark.parametrize('moved', [False, True])
def test_uncatchable_offers_known_unseen_square_without_following_hidden_move(tmp_path, moved):
    def prepare(bundles):
        _ranged_miss(bundles)
        _invisibility(bundles, SECOND)
    combat, table, mid, send, _ = monkey_fixture(tmp_path, [M + 'GREAT_SAGE_EQUAL_TO_HEAVEN'],
        bundle_transform=prepare,
        positions={OWNER: {'x': 3, 'y': 6}, FOE: {'x': 8, 'y': 6}, SECOND: {'x': 4, 'y': 6}})
    drive(send, candidate(table, mid, 'Great Sage Equal to Heaven', OWNER), use=())
    _to_turn(table, mid, SECOND)
    drive(send, candidate(table, mid, 'Become invisible'), use=())
    if moved:
        menu = table.state(mid)['menu']
        move = next(m for m in menu['moves'] if m['destination'] == {'x': 5, 'y': 6})
        assert send(move['candidate_id'])['status'] == 'COMMITTED'
    held = reload(tmp_path, mid)
    assert not can_see(held, held.state.actors[OWNER], held.state.actors[SECOND])
    assert knowledge(held, held.state.actors[OWNER], held.state.actors[SECOND]).position.x == 4
    _to_turn(table, mid, FOE)
    prompts = drive(send, candidate(table, mid, 'Test longbow', OWNER), use=(), pick='last saw Second')
    labels = [label for p in prompts for label in _labels(p)]
    assert any('last saw Second' in label for label in labels), labels
    assert not any('5,6' in label for label in labels)
    after = reload(tmp_path, mid)
    swings = [e for e in after.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER]
    misses = [e for e in after.events if e.event_type == 'ATTACK_LOCATION_MISSED' and e.actor_id == OWNER]
    if moved:
        assert not swings and len(misses) == 1
        assert misses[0].payload['destination'] == {'x': 4, 'y': 6}
    else:
        assert len(swings) == 1 and SECOND in swings[0].target_ids
        assert swings[0].payload['mode'] == 'DISADVANTAGE'


@pytest.mark.parametrize('weapon', ['melee', 'improvised'])
def test_reversal_offers_both_weapons_against_known_unseen_trigger(tmp_path, weapon):
    def prepare(bundles):
        _foe_certain_strike(bundles)
        _invisibility(bundles, FOE)
    combat, table, mid, send, _ = monkey_fixture(tmp_path, [M + 'IMPOSSIBLE_APE_REVERSAL', M + 'IMPROVISED_MASTER'],
        bundle_transform=prepare)
    _to_turn(table, mid, FOE)
    drive(send, candidate(table, mid, 'Become invisible'), use=())
    held = reload(tmp_path, mid)
    assert not can_see(held, held.state.actors[OWNER], held.state.actors[FOE])
    prompts = drive(send, candidate(table, mid, 'Test Unarmed', OWNER), use=('Impossible Ape Reversal',),
                    pick=[REVERSAL_RESULTS[4], f'{weapon} weapon'])
    labels = [label for p in prompts for label in _labels(p)]
    assert any('melee weapon' in label for label in labels) and any('improvised weapon' in label for label in labels)
    after = reload(tmp_path, mid)
    swings = [e for e in after.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER]
    assert len(swings) == 1 and FOE in swings[0].target_ids
    assert swings[0].payload['mode'] == 'DISADVANTAGE'
