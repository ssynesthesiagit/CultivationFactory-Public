"""Theft's selective movement and Moon's named recipients at the real table."""
import copy
from tests.r1i_service_support import OWNER, FOE, SECOND, THIRD, candidate
from tests.test_auto85f1_monkey_review import (
    M, MOON_ATTACK, _ranged_miss, _to_turn, _labels, drive, monkey_fixture,
)
from tests.test_sph_monkey_style_r1 import _rehash
from tests.test_r1i_round3 import reload


def test_theft_step_exempts_only_the_triggering_creature_after_reload(tmp_path):
    def prepare(bundles):
        # A granted OA may legitimately miss; make its fixture weapon accurate
        # so the commit/reload assertion proves damage as well as the attack.
        reactor = next(b for b in bundles if b['actor_id'] == SECOND)
        for action in reactor['action_catalog']:
            if action['display_name'] == 'Opportunity Attack':
                action['attack_bonus'] = 100
                action['parameters']['typed']['numbers']['attack_bonus'] = 100
        _rehash(reactor)
        owner = next(b for b in bundles if b['actor_id'] == OWNER)
        probe = copy.deepcopy(next(a for a in owner['action_catalog'] if a['display_name'] == 'Unarmed Strike'))
        probe.update(source_definition_id='test:monkey_r4.save', display_name='Test saving throw',
                     economy='NONE', costs=[], range_ft=30, target_kind='ANY_CREATURE')
        probe['parameters']['typed'].update(range={'kind': 'feet', 'feet': 30},
            effects=[{'type': 'save', 'ability': 'dex', 'dc': 10, 'on_fail': [], 'on_success': []}])
        probe['parameters']['typed']['numbers']['save_dc'] = 10
        owner['action_catalog'].append(probe)
        owner['actor_template']['action_ids'].append(probe['source_definition_id'])
        _rehash(owner)
    _, table, mid, send, _ = monkey_fixture(tmp_path,
        [M + 'LAUGHING_THEFT_OF_TIMING', M + 'HEAVEN_UPROOTING_STAFF'], bundle_transform=prepare,
        positions={OWNER: {'x': 3, 'y': 6}, FOE: {'x': 4, 'y': 6}, SECOND: {'x': 3, 'y': 7}})
    drive(send, candidate(table, mid, 'Capering Footwork', OWNER), use=())
    drive(send, candidate(table, mid, 'Heaven-Uprooting Staff'), use=())
    held = reload(tmp_path, mid)
    hp = held.state.actors[OWNER].current_hp
    budget = held.state.actors[OWNER].movement_remaining_ft
    prompts = drive(send, candidate(table, mid, 'Test saving throw', FOE),
        use=('Laughing Theft of Timing', 'Opportunity Attack'),
        pick=['move 10 feet', 'Step to 2,5'])
    assert any('move 10 feet' in label for p in prompts for label in _labels(p)), prompts
    after = reload(tmp_path, mid)
    save = next(e for e in after.events if e.event_type == 'SAVE_ROLLED'
                and e.source_definition_id == 'test:monkey_r4.save')
    penalty = next(r.total for r in after.rolls if r.reason == 'REACTION:' + M + 'LAUGHING_THEFT_OF_TIMING')
    assert save.payload['dc'] - penalty <= save.payload['total'] < save.payload['dc']
    assert after.state.actors[OWNER].position.model_dump(mode='json') == {'x': 2, 'y': 5}
    assert after.state.actors[OWNER].movement_remaining_ft == budget
    swings = [e for e in after.events if e.event_type == 'ATTACK_ROLLED'
              and e.actor_id in (FOE, SECOND) and OWNER in e.target_ids]
    assert [e.actor_id for e in swings] == [SECOND]
    assert after.state.actors[OWNER].current_hp < hp
    assert after.state.actors[FOE].reaction_available
    assert not after.state.actors[SECOND].reaction_available


def test_moon_duplicate_names_identify_and_attack_the_selected_recipient_after_reload(tmp_path):
    def prepare(bundles):
        _ranged_miss(bundles)
        for bundle in bundles:
            if bundle['actor_id'] in (FOE, THIRD):
                bundle['actor_template']['display_name'] = 'Bandit'
                _rehash(bundle)
    _, table, mid, send, _ = monkey_fixture(tmp_path, [M + 'MONKEY_CATCHES_THE_MOON'],
        bundle_transform=prepare, allies=(SECOND,), extra_foe=True,
        positions={OWNER: {'x': 5, 'y': 6}, SECOND: {'x': 5, 'y': 7},
                   FOE: {'x': 3, 'y': 6}, THIRD: {'x': 7, 'y': 6}})
    reload(tmp_path, mid)
    _to_turn(table, mid, FOE)
    prompts = drive(send, candidate(table, mid, 'Test longbow', SECOND),
        use=('Monkey Catches the Moon',),
        pick=['Stay where you are', MOON_ATTACK, 'Bandit at square 7,6'])
    menus = [p for p in prompts if 'Choose the creature within 20 feet' in str(p.get('moment') or '')]
    assert len(menus) == 1
    assert set(_labels(menus[0])) == {
        'Attack Bandit at square 3,6 with your improvised weapon',
        'Attack Bandit at square 7,6 with your improvised weapon'}
    after = reload(tmp_path, mid)
    swings = [e for e in after.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER]
    assert len(swings) == 1 and THIRD in swings[0].target_ids


def test_moon_step_keeps_its_printed_exemption_from_all_creatures_after_reload(tmp_path):
    _, table, mid, send, _ = monkey_fixture(tmp_path, [M + 'MONKEY_CATCHES_THE_MOON'],
        bundle_transform=_ranged_miss,
        positions={OWNER: {'x': 3, 'y': 6}, FOE: {'x': 4, 'y': 6}, SECOND: {'x': 3, 'y': 7}})
    _to_turn(table, mid, FOE)
    held = reload(tmp_path, mid)
    hp = held.state.actors[OWNER].current_hp
    prompts = drive(send, candidate(table, mid, 'Test longbow', OWNER),
        use=('Monkey Catches the Moon', 'Opportunity Attack'),
        pick=['Step to 2,5', 'create a Monkey Link'])
    assert any(any(label.startswith('Step to 2,5 ') for label in _labels(p))
               for p in prompts if _labels(p))
    after = reload(tmp_path, mid)
    assert after.state.actors[OWNER].position.model_dump(mode='json') == {'x': 2, 'y': 5}
    assert after.state.actors[OWNER].current_hp == hp
    swings = [e for e in after.events if e.event_type == 'ATTACK_ROLLED'
              and e.actor_id in (FOE, SECOND) and OWNER in e.target_ids]
    assert len(swings) == 1 and swings[0].source_definition_id == 'test:auto85f1.ranged_miss'
    assert after.state.actors[FOE].reaction_available and after.state.actors[SECOND].reaction_available
