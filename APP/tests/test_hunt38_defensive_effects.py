"""Public synthetic H38 mounted-occupancy regression; private replay stays external."""
from types import SimpleNamespace

import pytest

from combat.canonical import canonical_sha256
from combat.ext import end_effect, mounts
from combat.gate5_service import CombatService
from combat.typed_executor import mark_condition_id
from tests.h1_support import ROOT
from tests.r1i_service_support import OWNER, FOE, SECOND, fixture, force_ai_candidate

LINE = 'tianxia.talent.sabers.battlefield_beheading_line'
SHOVE = 'tianxia.talent.sabers.battleline_shove_cut'


@pytest.mark.parametrize('name', ['mounted', 'carrying', 'held', 'shared_occupancy',
                                'unknown_relationship', 'mark.test', 'concentration_held'])
def test_structural_and_unknown_conditions_are_not_selectable_benefits(name):
    item = SimpleNamespace(condition_id='condition:typed.' + name, data={})
    assert not end_effect.helpful(item, 'condition')
    assert not end_effect.helpful(item, 'condition', defensive_only=True)


@pytest.mark.parametrize('name,rule,defense', [
    ('guarding', {}, True), ('stance.test', {}, True),
    ('invisible', {}, True), ('custom_ward', {'cover': 'HALF'}, True),
    ('custom_buff', {'effect_kind': 'benefit'}, False),
    ('ignore_difficult', {}, False), ('custom_attack', {'attacks_have': 'ADVANTAGE'}, False),
    ('custom_check', {'check_against': {'mode': 'ADVANTAGE'}}, False),
    ('custom_save', {'save_against': {'mode': 'ADVANTAGE'}}, True),
    ('carrying', {'cover': 'TOTAL'}, False),
    ('mounted', {'effect_kind': 'defense', 'cover': 'TOTAL'}, False),
])
def test_benefit_classification_distinguishes_defenses_from_other_buffs(name, rule, defense):
    item = SimpleNamespace(condition_id='condition:typed.' + name, data={'rule': rule})
    assert end_effect.helpful(item, 'condition', defensive_only=True) is defense
    assert end_effect.helpful(item, 'condition') is (name not in ('carrying', 'mounted'))


def _mount_survives(bundles):
    # Test-owned initial templates, persisted by the ordinary match constructor.
    foe = next(b for b in bundles if b['actor_id'] == FOE)
    horse = foe['summons'][0]['actor_template']
    horse['maximum_hp'] = 500
    horse['saving_throws']['DEX'] = -100
    for bundle in bundles:
        bundle.pop('bundle_sha256', None)
        bundle['bundle_sha256'] = canonical_sha256(bundle)


@pytest.mark.parametrize('auto', [False, True])
def test_beheading_line_and_shove_cut_preserve_mount_bond_after_table_reload(tmp_path, auto):
    combat, table, mid, send, commit = fixture(
        tmp_path, [LINE, SHOVE], foe_talents=['BEASTMASTERY_BASE_RIDER_PACKAGE'],
        positions={OWNER: {'x': 3, 'y': 6}, FOE: {'x': 7, 'y': 6}, SECOND: {'x': 11, 'y': 6}},
        bundle_transform=_mount_survives, seed='H38-MOUNT-POSTURE')
    engine = combat._load_session(mid).engine
    horse_id = mounts.mount_of(engine, engine.state.actors[FOE]).entity_id
    # Real 10-foot move enables the printed Battleline Shove-Cut trigger.
    move = next(m['candidate_id'] for m in table.state(mid)['menu']['moves']
                if m['destination'] == {'x': 5, 'y': 6})
    assert commit(move)['status'] == 'COMMITTED'
    cid = next(o['candidate_id'] for g in table.state(mid)['menu']['actions']
               # Line makes a DEX save, not an attack hit. Shove-Cut's printed
               # "When you hit" cannot be attached to this save delivery.
               if g['label'] == 'Battlefield Beheading Line'
               for o in g['options'] if horse_id in o.get('target_ids', []))
    if auto:
        force_ai_candidate(combat, mid, OWNER, cid)
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    answers = []
    prompts = []
    for _ in range(16):
        result = send(cid, answers, auto=auto)
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED', result
        p = result['reaction']
        prompts.append(p)
        assert 'end_effect' not in p['context']['reaction_source_id']
        assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
        answer = {**p['context'], 'selection': 'USE'}
        if p.get('choice'):
            options = p['choice']['options']
            # Choose forced movement rather than Prone's separate fall handling.
            option = next((o for o in options if 'push' in o.get('label', '').lower()), options[0])
            answer['option_ids'] = [option['id']]
        answers.append(answer)
    else:
        pytest.fail('post-hit choices never committed')
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    rider, horse = fresh.engine.state.actors[FOE], fresh.engine.state.actors[horse_id]
    assert horse.active and 0 < horse.current_hp < horse.maximum_hp
    assert mounts.mount_of(fresh.engine, rider) is horse
    assert mounts.rider_of(fresh.engine, horse) is rider
    assert rider.position == horse.position
    assert not any('suppressed.carrying' in c.condition_id for c in horse.conditions.values())
    assert any(c.condition_id == mark_condition_id('Guard Pressured', OWNER) for c in horse.conditions.values())
    chosen = next(c for c in combat._load_session(mid).engine.action_catalog.values()
                  if LINE == (c.parameters.get('typed') or {}).get('source')
                  and not (c.parameters.get('typed') or {}).get('modifier'))
    assert not any('Battleline Shove-Cut' in str(p) for p in prompts)
    assert not any(e.event_type == 'ATTACK_ROLLED' and e.source_definition_id == chosen.source_definition_id
                   for e in fresh.engine.events)
    assert any(e.source_definition_id == chosen.source_definition_id and e.event_type == 'DAMAGE_COMMITTED'
               and horse_id in e.target_ids for e in fresh.engine.events)
    assert fresh.verify()['status'] == fresh.mechanical.replay()['status'] == 'PASS'


def test_beheading_line_selects_real_defensive_stance_but_keeps_mounted_relationship(tmp_path):
    combat, table, mid, send, commit = fixture(
        tmp_path, [LINE], foe_talents=['BEASTMASTERY_BASE_RIDER_PACKAGE', 'TAL_EARTH_DEEP_ROOT_STANCE'],
        positions={OWNER: {'x': 3, 'y': 6}, FOE: {'x': 7, 'y': 6}, SECOND: {'x': 11, 'y': 6}},
        bundle_transform=_mount_survives, seed='H38-REAL-STANCE')
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id'] != FOE:
        commit(table.state(mid)['menu']['end_turn'])
    from tests.r1i_service_support import candidate
    commit(candidate(table, mid, 'Deep Root Stance'))
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id'] != OWNER:
        commit(table.state(mid)['menu']['end_turn'])
    cid = candidate(table, mid, 'Battlefield Beheading Line', FOE)
    pause = send(cid)
    assert pause['status'] == 'REACTION_REQUIRED'
    p = pause['reaction']
    assert p['context']['reaction_source_id'] == 'choice:needle.end_effect'
    guard_key = next(k for k, c in combat._load_session(mid).engine.state.actors[FOE].conditions.items()
                     if c.condition_id == 'condition:typed.deep_root')
    option = next(o for o in p['choice']['options'] if o['id'] == guard_key)
    assert 'deep root' in option['label'].lower() and 'Foe' in option['label']
    relationship_keys = {k for k, c in combat._load_session(mid).engine.state.actors[FOE].conditions.items()
                         if c.condition_id in (mounts.MOUNTED, mounts.CARRYING)}
    assert relationship_keys.isdisjoint(o['id'] for o in p['choice']['options'])
    assert send(cid, [{**p['context'], 'selection': 'USE', 'option_ids': [option['id']]}])['status'] == 'COMMITTED'
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    rider = fresh.engine.state.actors[FOE]
    assert any(c.condition_id == 'condition:typed.suppressed.deep_root' for c in rider.conditions.values())
    assert not any(c.condition_id == 'condition:typed.deep_root' for c in rider.conditions.values())
    horse = mounts.mount_of(fresh.engine, rider)
    assert horse is not None and mounts.rider_of(fresh.engine, horse) is rider
    assert rider.position == horse.position
    assert fresh.verify()['status'] == fresh.mechanical.replay()['status'] == 'PASS'
