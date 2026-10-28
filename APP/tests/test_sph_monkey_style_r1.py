"""Monkey review round 1: actual table choices, turn boundaries and save receipts."""
import copy

import pytest

from combat.canonical import canonical_sha256
from combat.ext import monkey
from tests.r1i_service_support import OWNER, FOE, SECOND, THIRD, candidate, force_ai_candidate
from tests.test_auto85f1_monkey_review import (
    M, COVER, REVERSAL_RESULTS, _labels, _to_turn, _ranged_miss,
    _foe_certain_strike, _staff_hit, drive, monkey_fixture,
)
from tests.test_r1i_round3 import reload


def _rehash(bundle):
    bundle.pop('bundle_sha256', None)
    bundle['bundle_sha256'] = canonical_sha256(bundle)


def _save_probe(bundles):
    """Free fixture save delivered by an actual table action, with known actor geometry."""
    foe = next(b for b in bundles if b['actor_id'] == FOE)
    action = copy.deepcopy(next(a for a in foe['action_catalog'] if a['display_name'] == 'Unarmed Strike'))
    action.update(source_definition_id='test:monkey_r1.dex', display_name='Test Dexterity save',
                  economy='NONE', range_ft=60, target_kind='ANY_CREATURE', costs=[])
    action['parameters']['typed'].update(range={'kind': 'feet', 'feet': 60},
        effects=[{'type': 'save', 'ability': 'dex', 'dc': 10, 'on_fail': [], 'on_success': []}])
    action['parameters']['typed']['numbers']['save_dc'] = 1
    foe['action_catalog'].append(action)
    foe['actor_template']['action_ids'].append(action['source_definition_id'])
    _rehash(foe)


@pytest.mark.parametrize('delivery', ['finish', 'forced_save', 'event'])
def test_theft_ends_at_the_next_creatures_turn_after_commit_reload(tmp_path, delivery):
    talents = [M + 'LAUGHING_THEFT_OF_TIMING', M + 'HEAVEN_UPROOTING_STAFF']
    combat, table, mid, send, _ = monkey_fixture(tmp_path, talents,
        bundle_transform=lambda b: (_staff_hit(b), _foe_certain_strike(b)))
    drive(send, candidate(table, mid, 'Capering Footwork', OWNER), use=())
    if delivery == 'finish':
        drive(send, candidate(table, mid, 'Monkey Link (climb, swing, prop: GM)', OWNER), use=())
        drive(send, candidate(table, mid, 'Test Gun (Staff) attack', FOE), use=(), pick='Tap Finish')
    else:
        drive(send, candidate(table, mid, 'Heaven-Uprooting Staff'), use=())
    after = reload(tmp_path, mid)
    row = {'feature_id': M + 'LAUGHING_THEFT_OF_TIMING'}
    if delivery == 'event':
        # Exercise the real recorded condition/damage route independently of flags.
        after.state.actors[OWNER].turn_flags.clear()
    assert monkey.theft_subject(after, after.state.actors[OWNER], after.state.actors[FOE], row) is None
    _to_turn(table, mid, FOE)
    later = reload(tmp_path, mid)
    if delivery == 'event':
        later.state.actors[OWNER].turn_flags.clear()
    assert monkey.theft_subject(later, later.state.actors[OWNER], later.state.actors[FOE], row) is False
    prompts = drive(send, candidate(table, mid, 'Test Unarmed Strike', OWNER), use=())
    assert not [p for p in prompts if p.get('reaction') == 'Laughing Theft of Timing']


@pytest.mark.parametrize('automatic', [False, True])
@pytest.mark.parametrize('trigger', ['miss', 'dexterity_save'])
def test_uncatchable_can_attack_a_nearby_enemy_after_a_distant_archer_misses(tmp_path, automatic, trigger):
    combat, table, mid, send, _ = monkey_fixture(tmp_path, [M + 'GREAT_SAGE_EQUAL_TO_HEAVEN'],
        bundle_transform=lambda b: (_ranged_miss(b), _save_probe(b)),
        positions={OWNER: {'x': 3, 'y': 6}, FOE: {'x': 8, 'y': 6}, SECOND: {'x': 4, 'y': 6}})
    drive(send, candidate(table, mid, 'Great Sage Equal to Heaven', OWNER), use=())
    _to_turn(table, mid, FOE)
    label = 'Test longbow shot at the ally' if trigger == 'miss' else 'Test Dexterity save'
    cid = candidate(table, mid, label, OWNER)
    if automatic:
        force_ai_candidate(combat, mid, FOE, cid)
    prompts = drive(send, cid, use=(), pick='Attack Second with your melee weapon', automatic=automatic)
    offered = [p for p in prompts if any('melee weapon' in label for label in _labels(p))]
    assert offered, prompts
    assert any('Attack Second with your melee weapon' in _labels(p) for p in offered)
    assert not any('Attack Foe with your melee weapon' in _labels(p) for p in offered)
    assert all('Uncatchable' in p['moment'] and label in p['moment'] and 'Owner' in p['moment'] for p in offered)
    after = reload(tmp_path, mid)
    assert any(e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER and SECOND in e.target_ids for e in after.events)


@pytest.mark.parametrize('only_improvised', [False, True])
def test_reversal_preserves_the_improvised_weapon_choice_on_an_ai_turn(tmp_path, only_improvised):
    def prepare(bundles):
        _foe_certain_strike(bundles)
        if only_improvised:
            owner = next(b for b in bundles if b['actor_id'] == OWNER)
            removed = {a['source_definition_id'] for a in owner['action_catalog']
                       if str((a.get('parameters') or {}).get('typed', {}).get('source') or '').startswith('tianxia.mortal.weapon.')}
            owner['action_catalog'] = [a for a in owner['action_catalog'] if a['source_definition_id'] not in removed]
            owner['actor_template']['action_ids'] = [a for a in owner['actor_template']['action_ids'] if a not in removed]
            _rehash(owner)
    combat, table, mid, send, _ = monkey_fixture(tmp_path, [M + 'IMPOSSIBLE_APE_REVERSAL', M + 'IMPROVISED_MASTER'],
        bundle_transform=prepare)
    _to_turn(table, mid, FOE)
    prompts = drive(send, candidate(table, mid, 'Test Unarmed Strike', OWNER), use=('Impossible Ape Reversal',),
                    pick=[REVERSAL_RESULTS[4], 'improvised weapon'])
    weapon = [p for p in prompts if any('improvised weapon' in label for label in _labels(p))]
    assert weapon, [(_labels(p), p['moment']) for p in prompts]
    assert all('Impossible Ape Reversal' in p['moment'] and 'Foe' in p['moment'] for p in weapon)
    if not only_improvised:
        assert any('melee weapon' in label for p in weapon for label in _labels(p))
    after = reload(tmp_path, mid)
    swings = [e for e in after.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER and FOE in e.target_ids]
    assert swings and any('improvised' in e.source_definition_id.lower() for e in swings)
    damages = [r for r in after.rolls if r.actor_id == OWNER and r.reason.startswith('DAMAGE')]
    assert damages and any('d10' in r.expression for r in damages), damages


def test_moon_half_cover_adds_two_to_a_real_spatial_dexterity_save_after_reload(tmp_path):
    combat, table, mid, send, _ = monkey_fixture(tmp_path, [M + 'MONKEY_CATCHES_THE_MOON'],
        bundle_transform=lambda b: (_ranged_miss(b), _save_probe(b)), allies=(SECOND,),
        positions={OWNER: {'x': 6, 'y': 7}, FOE: {'x': 8, 'y': 5}, SECOND: {'x': 7, 'y': 6}})
    _to_turn(table, mid, FOE)
    drive(send, candidate(table, mid, 'Test longbow shot at the ally', SECOND), use=('Monkey Catches the Moon',), pick=COVER)
    held = reload(tmp_path, mid)
    assert held._cover_bonus_actor_to_actor(held.state.actors[FOE], held.state.actors[SECOND]) == 2
    drive(send, candidate(table, mid, 'Test Dexterity save', SECOND), use=())
    after = reload(tmp_path, mid)
    saves = [e for e in after.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == SECOND
             and e.source_definition_id == 'test:monkey_r1.dex']
    assert saves and saves[-1].payload.get('save_bonus_contributions', {}).get('cover') == 2, [e.payload for e in saves]
    condition = next(c for c in after.state.actors[SECOND].conditions.values() if c.condition_id == monkey.COVER)
    assert '+2 AC' in condition.data['label'] and '+2 to Dexterity saving throws' in condition.data['label']
    covered_roll = next(r for r in after.rolls if r.roll_id == saves[-1].payload['roll_id'])
    _to_turn(table, mid, OWNER)
    _to_turn(table, mid, FOE)
    drive(send, candidate(table, mid, 'Test Dexterity save', SECOND), use=())
    expired = reload(tmp_path, mid)
    bare = [e for e in expired.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == SECOND
            and e.source_definition_id == 'test:monkey_r1.dex'][-1]
    assert not bare.payload.get('save_bonus_contributions', {}).get('cover')
    bare_roll = next(r for r in expired.rolls if r.roll_id == bare.payload['roll_id'])
    assert covered_roll.modifier == bare_roll.modifier + 2


def test_a_reaction_trick_qualifies_for_theft_only_during_that_enemy_turn(tmp_path):
    """A Monkey can affect someone during another creature's turn; its current-turn record must remain usable."""
    combat, table, mid, send, _ = monkey_fixture(tmp_path,
        [M + 'IMPOSSIBLE_APE_REVERSAL', M + 'LAUGHING_THEFT_OF_TIMING'], bundle_transform=_foe_certain_strike)
    _to_turn(table, mid, FOE)
    drive(send, candidate(table, mid, 'Test Unarmed Strike', OWNER), use=('Impossible Ape Reversal',), pick='falls Prone')
    after = reload(tmp_path, mid)
    assert any(e.event_type == 'SAVE_ROLLED' and e.actor_id == FOE and 'APE_REVERSAL' in e.source_definition_id
               for e in after.events)
    row = {'feature_id': M + 'LAUGHING_THEFT_OF_TIMING'}
    assert monkey.theft_subject(after, after.state.actors[OWNER], after.state.actors[FOE], row) is None
    end = table.state(mid)['menu']
    assert table.act(mid, end['end_turn'], end['decision_id'], end['state_version'], 0, [])['status'] == 'COMMITTED'
    later = reload(tmp_path, mid)
    assert monkey.theft_subject(later, later.state.actors[OWNER], later.state.actors[FOE], row) is False


def test_ai_owned_uncatchable_decides_automatically_on_the_opponents_turn(tmp_path):
    combat, table, mid, send, _ = monkey_fixture(tmp_path, [M + 'GREAT_SAGE_EQUAL_TO_HEAVEN'],
        bundle_transform=_ranged_miss,
        positions={OWNER: {'x': 3, 'y': 6}, FOE: {'x': 8, 'y': 6}, SECOND: {'x': 4, 'y': 6}})
    drive(send, candidate(table, mid, 'Great Sage Equal to Heaven', OWNER), use=())
    _to_turn(table, mid, FOE)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    prompts = drive(send, candidate(table, mid, 'Test longbow shot at the ally', OWNER), use=())
    assert not [p for p in prompts if 'Uncatchable' in str(p.get('moment') or '')]
    after = reload(tmp_path, mid)
    assert any(c.condition_id == monkey.LINK for c in after.state.actors[OWNER].conditions.values())


def test_uncatchable_keeps_distinct_recipients_with_the_same_display_name(tmp_path):
    def prepare(bundles):
        _ranged_miss(bundles)
        for bundle in bundles:
            if bundle['actor_id'] in (SECOND, THIRD):
                bundle['actor_template']['display_name'] = 'Raider'
                _rehash(bundle)
    combat, table, mid, send, _ = monkey_fixture(tmp_path, [M + 'GREAT_SAGE_EQUAL_TO_HEAVEN'],
        bundle_transform=prepare, extra_foe=True,
        positions={OWNER: {'x': 3, 'y': 6}, FOE: {'x': 8, 'y': 6},
                   SECOND: {'x': 4, 'y': 6}, THIRD: {'x': 3, 'y': 7}})
    drive(send, candidate(table, mid, 'Great Sage Equal to Heaven', OWNER), use=())
    _to_turn(table, mid, FOE)
    cid = candidate(table, mid, 'Test longbow shot at the ally', OWNER)
    result = send(cid)
    assert result['status'] == 'REACTION_REQUIRED', result
    prompt = result['reaction']
    options = [o for o in prompt['choice']['options'] if o['label'].startswith('Attack Raider')]
    assert len(options) == 2 and len({o['id'] for o in options}) == 2
    assert {o['label'] for o in options} == {
        'Attack Raider at square 4,6 with your melee weapon', 'Attack Raider at square 3,7 with your melee weapon'}
    chosen = next(o['id'] for o in options if THIRD in o['id'])
    answers = [{**prompt['context'], 'selection': 'USE', 'option_ids': [chosen]}]
    for _ in range(10):
        result = send(cid, answers)
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED', result
        p = result['reaction']
        answers.append({**p['context'], 'selection': 'DECLINE'})
    assert result['status'] == 'COMMITTED'
    after = reload(tmp_path, mid)
    swings = [e for e in after.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER]
    assert len(swings) == 1 and THIRD in swings[0].target_ids
