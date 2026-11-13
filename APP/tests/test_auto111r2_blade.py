"""Blade physical-copy identity and synthetic pre-change saved-key continuation.

All attacks and condition setup commit through the table; fresh-service reloads
also check deterministic mechanical replay. No live saves are used.
"""
import hashlib

import pytest

from combat.ext import elements_earth as blade
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.auto_worker1_support import LEFT, RIGHT, act, fight, reload, turn, action_sender
from tests.h1_support import ROOT

DAGGER = 'weapon.bi_shou'
SOURCE = 'action:typed.' + hashlib.sha256(RIGHT.encode('utf-8')).hexdigest()[:10] + '.' + DAGGER
PAIR = {'items': [{'item_id': 'tianxia.mortal.weapon.bi_shou',
                   'name': 'Bi Shou (Dagger)', 'quantity': 2}]}


def _pending(combat, mid):
    return [c for c in reload(combat, mid).state.actors[RIGHT].conditions.values()
            if c.condition_id == blade.HEAVY]


def _mode(combat, mid):
    engine = reload(combat, mid)
    return next(e.payload['mode'] for e in reversed(engine.events)
                if e.event_type == 'ATTACK_ROLLED')


def _burden(tmp_path, source, *, advance=True, **kwargs):
    combat, table, mid = fight(tmp_path, [blade.FEATURE], left_score=2, right_score=30,
        prepare=[{'type': 'mark', 'mark': 'Burden Mark', 'applies_to': 'target',
                  'duration': {'kind': 'until_removed'}}], **kwargs)
    assert act(table, mid, 'Prepare', target_id=RIGHT)['status'] == 'COMMITTED'
    turn(table, mid, RIGHT)
    send = action_sender(combat, table, mid, source, target_id=LEFT)
    result = send([])
    assert result['status'] == 'REACTION_REQUIRED', result
    prompt = result['reaction']
    assert 'Burden the Blade' in str(prompt)
    assert send([{**prompt['context'], 'selection': 'USE',
                  'option_ids': ['SPEND']}])['status'] == 'COMMITTED'
    assert _pending(combat, mid)
    turn(table, mid, LEFT)
    if advance:
        turn(table, mid, RIGHT)
    return combat, table, mid


def test_distinct_daggers_do_not_spend_each_others_pending_penalty(tmp_path):
    combat, table, mid = _burden(tmp_path, DAGGER, right_kit=PAIR)
    # Copy 2 opens copy 1's ordinary off-hand attack. That variant belongs to
    # the burdened physical copy, despite using a different action button.
    assert act(table, mid, DAGGER + '.copy2', target_id=LEFT)['status'] == 'COMMITTED'
    assert _mode(combat, mid) == 'NORMAL'
    assert _pending(combat, mid)[0].data['weapon'] == SOURCE
    assert act(table, mid, DAGGER + '#offhand', target_id=LEFT)['status'] == 'COMMITTED'
    assert _mode(combat, mid) == 'DISADVANTAGE'
    assert not _pending(combat, mid)


@pytest.mark.parametrize('first,followup', [(DAGGER, DAGGER + '#thrown'),
                                          (DAGGER + '#thrown', DAGGER)])
def test_variants_of_one_dagger_share_pending_penalty(tmp_path, first, followup):
    combat, table, mid = _burden(tmp_path, first)
    if first.endswith('#thrown'):
        # A thrown weapon really leaves the holder's inventory. Retrieve that
        # same copy through the table before using its melee variant.
        assert act(table, mid, 'Pick up Bi Shou (Dagger)')['status'] == 'COMMITTED'
    assert act(table, mid, followup, target_id=LEFT)['status'] == 'COMMITTED'
    assert _mode(combat, mid) == 'DISADVANTAGE'
    assert not _pending(combat, mid)


@pytest.mark.parametrize('saved_key', [SOURCE, SOURCE + '#thrown', 'tianxia.mortal.weapon.bi_shou'])
def test_pre_change_pending_blade_save_continues_commits_and_reloads(tmp_path, saved_key):
    # 8409faab stored the source string (including # variants) for compiled
    # weapons; f6be8347 stored implement_id. Recreate those serialized records
    # with a committed fixture effect, not by mutating a loaded engine.
    combat, table, mid = fight(tmp_path, prepare=[{
        'type': 'condition', 'condition': 'earth_blade_heavy', 'applies_to': 'target',
        'duration': {'kind': 'until_end_of_next_turn'},
        'condition_data': {'weapon': saved_key, 'except_roll': 'historical-trigger-roll',
                           'label': 'Burden the Blade: next attack with this weapon has disadvantage'},
    }])
    assert act(table, mid, 'Prepare', target_id=RIGHT)['status'] == 'COMMITTED'
    assert _pending(combat, mid)[0].data['weapon'] == saved_key
    # Continue the saved table using entirely new service instances.
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    turn(table, mid, RIGHT)
    # Use melee so adjacent-enemy ranged disadvantage cannot mask a missing
    # historical Blade penalty. The saved #thrown key still tests variants.
    assert act(table, mid, DAGGER, target_id=LEFT)['status'] == 'COMMITTED'
    assert _mode(combat, mid) == 'DISADVANTAGE'
    assert not _pending(combat, mid)
