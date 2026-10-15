"""Actual compiled delivery paths share Blade's persisted physical weapon key."""
import pytest

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.ext import elements_earth as blade
from tests.auto_worker1_support import LEFT, RIGHT, act, fight, reload, turn
from tests.h1_support import ROOT
from tests.test_auto111r2_blade import _burden, _pending, _mode, SOURCE, DAGGER, PAIR

HEW = 'Fu (Short Axe) (copy 2) attack: Hewing Strike: Hamper'
HERON = 'tianxia.subpath.body.white_heron_crescent_body.feature.crescent_body_integration'


def _fresh(tmp_path, combat, mid):
    reload(combat, mid)  # state equality and deterministic mechanical replay
    combat = CombatService(ROOT, tmp_path)
    return combat, TabletopService(combat, tmp_path)


def _move(table, mid, x, y, *, opportunity=False):
    state = table.state(mid)
    menu = state['menu']
    move = next(row for row in menu['moves'] if row['destination'] == {'x': x, 'y': y})
    answers = []
    for _ in range(3):
        result = table.act(mid, move['candidate_id'], menu['decision_id'],
                           menu['state_version'], state['last_sequence'], answers)
        if result['status'] == 'COMMITTED':
            return
        assert opportunity and result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        assert 'Opportunity Attack' in str(prompt), prompt
        answers.append({**prompt['context'], 'selection': 'USE'})
    raise AssertionError('movement did not commit')


@pytest.mark.parametrize('other_copy', [False, True])
def test_normal_attack_then_opportunity_attack_matches_only_its_copy_after_reload(tmp_path, other_copy):
    combat, table, mid = _burden(tmp_path, DAGGER, advance=False,
                               **({'right_kit': PAIR} if other_copy else {}))
    assert _pending(combat, mid)[0].data['weapon'] == SOURCE
    combat, table = _fresh(tmp_path, combat, mid)
    sequence = reload(combat, mid).state.event_sequence
    _move(table, mid, 2, 6, opportunity=True)
    engine = reload(combat, mid)
    rolls = [e for e in engine.events if e.sequence > sequence and e.event_type == 'ATTACK_ROLLED']
    assert len(rolls) == 1 and rolls[0].actor_id == RIGHT
    assert rolls[0].source_definition_id.endswith('.opportunity_attack')
    assert rolls[0].payload['mode'] == ('NORMAL' if other_copy else 'DISADVANTAGE')
    assert bool(_pending(combat, mid)) == other_copy


@pytest.mark.parametrize('kind', ['technique', 'reach'])
def test_historical_delivery_action_keys_match_ordinary_attack_after_reload(tmp_path, kind):
    prefix = SOURCE.removesuffix(DAGGER)
    if kind == 'technique':
        saved = prefix + 'TAL_AXES_HEWING_STRIKE#opt4'
        weapon, talents = 'fu', ['TAL_AXES_HEWING_STRIKE']
    else:
        saved = prefix + 'weapon.ji.combined_reach'
        weapon, talents = 'ji', [HERON]
    combat, table, mid = fight(tmp_path, right_talents=talents,
        right_kit={'items': [{'item_id': 'tianxia.mortal.weapon.' + weapon}]},
        prepare=[{'type': 'condition', 'condition': 'earth_blade_heavy', 'applies_to': 'target',
                  'duration': {'kind': 'until_end_of_next_turn'},
                  'condition_data': {'weapon': saved, 'except_roll': 'historical-roll'}}])
    assert act(table, mid, 'Prepare', target_id=RIGHT)['status'] == 'COMMITTED'
    assert _pending(combat, mid)[0].data['weapon'] == saved
    combat, table = _fresh(tmp_path, combat, mid)
    turn(table, mid, RIGHT)
    assert act(table, mid, 'weapon.' + weapon, target_id=LEFT)['status'] == 'COMMITTED'
    assert _mode(combat, mid) == 'DISADVANTAGE'
    assert not _pending(combat, mid)


@pytest.mark.parametrize('technique_first', [False, True])
@pytest.mark.parametrize('other_copy', [False, True])
def test_delivered_technique_and_ordinary_attack_share_only_delivering_copy(tmp_path, technique_first, other_copy):
    kit = {'items': [{'item_id': 'tianxia.mortal.weapon.fu', 'quantity': 2}]}
    ordinary = 'weapon.fu.copy2'  # compiler selects this physical copy for delivery
    first, followup = (HEW, ordinary) if technique_first else (ordinary, HEW)
    combat, table, mid = _burden(tmp_path, first, right_kit=kit,
                               right_talents=['TAL_AXES_HEWING_STRIKE'])
    engine = reload(combat, mid)
    technique = next(a for a in engine.action_catalog.values()
                     if a.owner_id == RIGHT and a.display_name == HEW)
    key = technique.parameters['typed']['delivered_by']
    assert key.endswith('.' + ordinary)
    assert _pending(combat, mid)[0].data['weapon'] == key
    combat, table = _fresh(tmp_path, combat, mid)
    assert act(table, mid, 'weapon.fu' if other_copy else followup, target_id=LEFT)['status'] == 'COMMITTED'
    assert _mode(combat, mid) == ('NORMAL' if other_copy else 'DISADVANTAGE')
    assert bool(_pending(combat, mid)) == other_copy
    if other_copy:
        assert _pending(combat, mid)[0].data['weapon'] == key


@pytest.mark.parametrize('extended_first', [False, True])
def test_extended_reach_and_ordinary_attack_share_the_same_halberd(tmp_path, extended_first):
    kit = {'items': [{'item_id': 'tianxia.mortal.weapon.ji'}]}
    ordinary = 'weapon.ji'
    extended = ordinary + '.combined_reach'
    first, followup = (extended, ordinary) if extended_first else (ordinary, extended)
    # Halberd base reach is 10 feet; Integration adds 5 on its owner's turn.
    combat, table, mid = _burden(tmp_path, first, advance=False, right_kit=kit,
        right_talents=[HERON], positions={LEFT: {'x': 1 if extended_first else 2, 'y': 6},
                                        RIGHT: {'x': 4, 'y': 6}})
    key = SOURCE.removesuffix(DAGGER) + ordinary
    assert _pending(combat, mid)[0].data['weapon'] == key
    combat, table = _fresh(tmp_path, combat, mid)
    assert act(table, mid, 'Disengage')['status'] == 'COMMITTED'
    _move(table, mid, 2 if extended_first else 1, 6)
    turn(table, mid, RIGHT)
    assert act(table, mid, followup, target_id=LEFT)['status'] == 'COMMITTED'
    assert _mode(combat, mid) == 'DISADVANTAGE'
    assert not _pending(combat, mid)
