"""Poison delivery through table intent, saved bundles and cold mechanical replay.

Setup attacks model sealed Poison cultivation provenance; Coated Weapon and
Venomous Strike themselves are the actual compiled printed abilities.
"""
import pytest

from combat.ext import poison
from tests.auto_worker1_support import LEFT, RIGHT, fight, act, reload, action_sender
from tests.auto_worker1_stars_support import resolve, turn

STRIKE = poison.STRIKE
COATED = poison.COATED
POOL = 'resource:core.qi'
CHOICE = 'choice:needle.venomous_strike'
DAGGER = 'action:typed.945a1f5770.weapon.bi_shou'


def strike_events(engine, event_type):
    return [e for e in engine.events if e.event_type == event_type
            and (e.source_definition_id == STRIKE or e.payload.get('display_source_id') == STRIKE)]


def attacks(kind='unarmed', hits=1):
    return [{'type': 'attack', 'attack_kind': kind, 'count': hits,
             'on_hit': [{'type': 'damage', 'flat': 1, 'damage_types': ['poison'], 'applies_to': 'target'}],
             'on_miss': []}]


@pytest.mark.parametrize('ai', [False, True])
@pytest.mark.parametrize('accept', [False, True])
def test_coated_weapon_offers_strike_and_keeps_both_payments(tmp_path, ai, accept):
    c, t, m = fight(tmp_path, [COATED, STRIKE], left_score=30, right_score=1,
                     right_kit={'items': []})
    resolve(lambda a: act(t, m, 'Coat a Weapon', a),
            {'choice:needle.poison_coated_weapon': [DAGGER]})
    result, prompts = resolve(action_sender(c, t, m, 'Bi Shou (Dagger) attack', ai=ai, target_id=RIGHT),
                              {CHOICE: ['STRIKE'] if accept else []})
    assert result['status'] == 'COMMITTED'
    e = reload(c, m)
    taken = accept or ai
    assert [v.payload['amount'] for v in strike_events(e, 'RESOURCE_SPENT')] == ([1] if taken else [])
    assert len(strike_events(e, 'SAVE_ROLLED')) == int(taken)
    assert e.state.actors[LEFT].resources[POOL] == 99 - int(taken)
    assert any(v.source_definition_id == COATED for v in e.events if v.event_type == 'SAVE_ROLLED')
    if not ai:
        prompt = next(p['moment'] for p in prompts if CHOICE in str(p.get('context')))
        assert all(word in prompt for word in ('Bi Shou', 'Visitor', '1 Qi', 'Poisoned', 'next ability check'))


@pytest.mark.parametrize('kind,source', [
    ('unarmed', 'tianxia.talent.poison.test_unarmed_delivery'),
    ('natural', 'tianxia.talent.poison.test_natural_delivery'),
    ('forged', 'test.forged_unarmed_delivery'),
])
@pytest.mark.parametrize('failed', [False, True])
def test_poison_cultivation_hit_resolves_final_save_and_target_turn_expiry(tmp_path, kind, source, failed):
    def natural_bundle(bundle):
        if kind not in ('natural', 'forged'):
            return
        for action in bundle['action_catalog']:
            if action['display_name'] == 'Prepare':
                if kind == 'forged':
                    action['parameters']['typed']['forged_from'] = poison.DELIVER
                else:
                    old = action['source_definition_id']
                    action['source_definition_id'] = old + '.natural.poison'
                    ids = bundle['actor_template']['action_ids']
                    ids[ids.index(old)] = action['source_definition_id']
    c, t, m = fight(tmp_path, [STRIKE], prepare=attacks(), prepare_source=source,
                     prepare_attack_bonus=100, left_save_dc=100 if failed else -100,
                     bundle_edit=natural_bundle)
    resolve(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT), {CHOICE: ['STRIKE']})
    e = reload(c, m)
    assert len(strike_events(e, 'DAMAGE_ROLLED')) == 1
    assert len(strike_events(e, 'SAVE_ROLLED')) == 1
    target = e.state.actors[RIGHT]
    assert any(v.condition_id == 'condition:poisoned' or v.condition_id.endswith('.poisoned')
               for v in target.conditions.values()) == failed
    assert any(v.condition_id == poison.NEXT_CHECK for v in target.conditions.values()) == (not failed)
    turn(t, m, RIGHT)
    target = reload(c, m).state.actors[RIGHT]
    assert not any(v.source_definition_id == STRIKE for v in target.conditions.values())


@pytest.mark.parametrize('cl,dice', [(1, 1), (10, 2), (15, 3)])
def test_multiple_poison_hits_offer_once_then_refresh_next_turn(tmp_path, cl, dice):
    c, t, m = fight(tmp_path, [STRIKE], cl=cl, prepare=attacks(hits=2),
                     prepare_source='tianxia.talent.poison.test_unarmed_delivery', prepare_attack_bonus=100)
    resolve(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT), {CHOICE: ['STRIKE']})
    e = reload(c, m)
    rolls = strike_events(e, 'DAMAGE_ROLLED')
    assert len(rolls) == 1 and len(rolls[0].payload['dice']) == dice
    assert len(strike_events(e, 'RESOURCE_SPENT')) == 1
    turn(t, m, RIGHT)
    turn(t, m, LEFT)
    resolve(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT), {CHOICE: ['STRIKE']})
    assert len(strike_events(reload(c, m), 'RESOURCE_SPENT')) == 2


@pytest.mark.parametrize('source,kind,owned', [
    ('test.ordinary_unarmed', 'unarmed', True),
    ('test.acid_unarmed', 'unarmed', True),
    ('tianxia.talent.poison.test_spell', 'cultivation_ranged', True),
    ('tianxia.talent.poison.test_unarmed_delivery', 'unarmed', False),
])
def test_unrelated_hits_and_nonowners_are_inert(tmp_path, source, kind, owned):
    c, t, m = fight(tmp_path, [STRIKE] if owned else [], prepare=attacks(kind),
                     prepare_source=source, prepare_attack_bonus=100)
    _, prompts = resolve(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT))
    e = reload(c, m)
    assert not any(CHOICE in str(p) for p in prompts)
    assert not strike_events(e, 'RESOURCE_SPENT') and not strike_events(e, 'SAVE_ROLLED')


def test_retained_strike_row_keeps_deliver_only_behavior(tmp_path):
    def predecessor(bundle):
        for row in bundle.get('typed_passives', []):
            row.pop('hit_delivery_policy', None)
    c, t, m = fight(tmp_path, [STRIKE], prepare=attacks(),
                     prepare_source='tianxia.talent.poison.test_unarmed_delivery',
                     prepare_attack_bonus=100, bundle_edit=predecessor)
    # The fixture seals the predecessor bundle before match creation.
    e = reload(c, m)
    assert all('hit_delivery_policy' not in r for r in e.typed_passive_rows[LEFT] if r.get('kind') == 'strike')
    _, prompts = resolve(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT))
    assert not any(CHOICE in str(p) for p in prompts)
    assert not strike_events(reload(c, m), 'RESOURCE_SPENT')


@pytest.mark.parametrize('reason', ['miss', 'no_funds'])
def test_ineligible_poison_hit_does_not_offer_or_spend(tmp_path, reason):
    def empty_pool(bundle):
        if reason == 'no_funds' and bundle['actor_id'] == LEFT:
            for pool in bundle['actor_template']['resources']:
                if pool['resource_id'] == POOL:
                    pool['initial'] = 0
    c, t, m = fight(tmp_path, [STRIKE], prepare=attacks(),
                     prepare_source='tianxia.talent.poison.test_unarmed_delivery',
                     prepare_attack_bonus=-100 if reason == 'miss' else 100, bundle_edit=empty_pool)
    _, prompts = resolve(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT))
    e = reload(c, m)
    assert not any(CHOICE in str(p) for p in prompts)
    assert not strike_events(e, 'RESOURCE_SPENT')
    assert not strike_events(e, 'SAVE_ROLLED')
    if reason == 'miss':
        rolls = [v for v in e.events if v.event_type == 'ATTACK_ROLLED']
        assert rolls and all(v.payload['modified_total'] < v.payload['target_ac'] for v in rolls)
        assert not any(v.event_type == 'DAMAGE_COMMITTED' for v in e.events)


def test_declining_one_hit_leaves_strike_available_on_the_next_hit(tmp_path):
    c, t, m = fight(tmp_path, [STRIKE], prepare=attacks(),
                     prepare_source='tianxia.talent.poison.test_unarmed_delivery', prepare_attack_bonus=100)
    resolve(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT), {CHOICE: []})
    assert not strike_events(reload(c, m), 'RESOURCE_SPENT')
    resolve(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT), {CHOICE: ['STRIKE']})
    assert len(strike_events(reload(c, m), 'RESOURCE_SPENT')) == 1


@pytest.mark.parametrize('deliver_first', [False, True])
def test_delivery_methods_share_one_strike_budget(tmp_path, deliver_first):
    c, t, m = fight(tmp_path, [STRIKE, poison.DELIVER], prepare=attacks(),
                     prepare_source='tianxia.talent.poison.test_unarmed_delivery',
                     prepare_attack_bonus=100, left_attack_bonus=100)
    labels = ['Deliver the Dose', 'Prepare'] if deliver_first else ['Prepare', 'Deliver the Dose']
    for label in labels:
        resolve(lambda a: act(t, m, label, a, target_id=RIGHT), {CHOICE: ['STRIKE']})
        reload(c, m)
    assert len(strike_events(reload(c, m), 'RESOURCE_SPENT')) == 1


def test_success_penalty_is_consumed_by_one_check_during_the_same_turn(tmp_path):
    check = {'type': 'skill_check', 'ability': 'wis', 'skill': 'Perception', 'applies_to': 'target'}
    c, t, m = fight(tmp_path, [STRIKE], prepare=attacks() + [check, check],
                     prepare_source='tianxia.talent.poison.test_unarmed_delivery',
                     prepare_attack_bonus=100, left_save_dc=-100)
    resolve(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT), {CHOICE: ['STRIKE']})
    e = reload(c, m)
    checks = [v for v in e.events if v.event_type == 'CHECK_ROLLED' and v.actor_id == RIGHT]
    assert [v.payload['actor']['mode'] for v in checks] == ['DISADVANTAGE', 'NORMAL']
    assert not any(v.condition_id == poison.NEXT_CHECK for v in e.state.actors[RIGHT].conditions.values())


@pytest.mark.parametrize('removed', [False, True])
def test_coating_matches_the_attacking_weapon_and_must_still_exist(tmp_path, removed):
    setup = [{'type': 'remove_condition', 'condition': poison.COATING, 'applies_to': 'self'}] if removed else []
    c, t, m = fight(tmp_path, [COATED, STRIKE], prepare=setup + attacks(),
                     prepare_attack_bonus=100, left_score=30, right_score=1, right_kit={'items': []})
    resolve(lambda a: act(t, m, 'Coat a Weapon', a), {'choice:needle.poison_coated_weapon': [DAGGER]})
    _, prompts = resolve(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT))
    e = reload(c, m)
    assert not any(CHOICE in str(p) for p in prompts)
    assert not strike_events(e, 'RESOURCE_SPENT')
    assert any(v.condition_id == poison.COATING for v in e.state.actors[LEFT].conditions.values()) == (not removed)


@pytest.mark.parametrize('ai', [False, True])
def test_real_compiled_natural_weapon_is_a_separate_printed_trigger(tmp_path, ai):
    natural = 'tianxia.path.body_refining.feature.iron_fist'
    c, t, m = fight(tmp_path, [STRIKE, natural], left_score=30, right_score=1,
                     right_kit={'items': []})
    e = reload(c, m)
    action = next(a for a in e.action_catalog.values()
                  if a.owner_id == LEFT and '.natural.iron_fist' in a.source_definition_id)
    assert action.parameters['typed']['source'] == natural
    resolve(action_sender(c, t, m, action.display_name, ai=ai, target_id=RIGHT), {CHOICE: ['STRIKE']})
    e = reload(c, m)
    assert [v.payload['amount'] for v in strike_events(e, 'RESOURCE_SPENT')] == [1]
    assert len(strike_events(e, 'SAVE_ROLLED')) == 1
    assert len(strike_events(e, 'DAMAGE_ROLLED')) == 1
    assert not strike_events(e, 'GM_RIDER')
