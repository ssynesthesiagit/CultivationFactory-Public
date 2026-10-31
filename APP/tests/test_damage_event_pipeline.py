"""Relevant-only regressions: real table commits and cold replay of damage phases.

All characters, actions, prices and defenses are synthetic public fixtures.
Scenario actions prepare state; the printed features still own their providers.
"""
import copy
import pytest

from combat.factory_compiler import compile_character
from combat.ext import foundation_combat as f
from tests.h1_support import sheet
from tests.cw2_service_support import add_action, seal
from tests.worker2_support import fixture, candidate, settle, reload, turn, OWNER, ALLY, FOE

PUMP = 'tianxia.path.body_refining.feature.blood_pump'
HELL = 'tianxia.subpath.body.jigoku.feature.hell_tempered'
MAW = 'tianxia.subpath.body.heaven_devouring_maw_body.feature.'
STAMINA = 'resource:core.stamina'


def damage(value, kind='force'):
    return {'type': 'damage', 'flat': value, 'damage_types': [kind], 'applies_to': 'target'}


def scene(tmp_path, *, features=(), foundation=None, token=1, transform=None):
    doc = sheet([], cl=18, primary='Stamina')
    doc['identity']['path'] = 'Body Refining'
    doc.setdefault('path_and_subpath', {})['path_feature_record_ids'] = list(features)
    doc['ability_scores_and_statistics']['hit_points']['maximum'] = 100
    doc['ability_scores_and_statistics']['primary_resource']['maximum'] = 100
    if foundation:
        doc['foundation'] = {'foundation_id': foundation, 'stage': 'Perfected', 'status': 'active',
            'resource': {'name': 'Scenario token', 'maximum': 1, 'current': token}}
    owner = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})

    def prepare(bundles):
        for b in bundles:
            b['actor_template']['maximum_hp'] = 100
        add_action(bundles[0], 'Wound', [damage(95)])
        add_action(bundles[2], 'Test blow', [damage(10)])
        if transform:
            transform(bundles)
        for b in bundles:
            seal(b)
    return fixture(tmp_path, [], owner_bundle=owner, ask=True, bundle_transform=prepare,
                   foe_position={'x': 4, 'y': 5}, seed='DAMAGE-PIPELINE')


def use(combat, table, mid, name, target=None, choices=None):
    c = candidate(combat, mid, name, target=target)
    return settle(table, mid, c.candidate_id, choices=choices or {})


def receipts(engine, target=OWNER):
    return [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and target in e.target_ids]


def test_final_reduction_precedes_blood_pump_and_does_not_spend_it(tmp_path):
    combat, table, mid = scene(tmp_path, features=[PUMP], foundation=f.GROUPS['integrity'][0])
    use(combat, table, mid, 'Wound', OWNER, {f.CHOICE+'foundation_combat': None})
    assert reload(tmp_path, mid).state.actors[OWNER].current_hp == 5
    turn(table, mid, FOE)
    prompts = use(combat, table, mid, 'Test blow', OWNER)
    e = reload(tmp_path, mid)
    assert e.state.actors[OWNER].current_hp == 5
    assert receipts(e)[-1].payload['reduced_to'] == 0
    assert not any(p['context']['reaction_source_id'].startswith('choice:life.survive:') for p in prompts)
    assert not any(ev.event_type == 'RESOURCE_SPENT' and ev.source_definition_id == PUMP for ev in e.events)


def test_final_zero_hp_window_chooses_one_row_and_pays_only_that_row(tmp_path):
    spare = 'test:damage_pipeline.spare_life'
    def prepare(bundles):
        row = copy.deepcopy(next(r for r in bundles[0]['typed_reactions'] if r.get('feature_id') == PUMP))
        row.update(feature_id=spare, name='Spare Life')
        bundles[0]['typed_reactions'].append(row)
    combat, table, mid = scene(tmp_path, features=[PUMP], transform=prepare)
    use(combat, table, mid, 'Wound', OWNER)
    turn(table, mid, FOE)
    prompts = use(combat, table, mid, 'Test blow', OWNER,
                  {'choice:needle.zero_hp_replacement': ['1']})
    e = reload(tmp_path, mid)
    assert e.state.actors[OWNER].current_hp == 1
    paid = [ev for ev in e.events if ev.event_type == 'RESOURCE_SPENT' and ev.source_definition_id in {PUMP, spare}]
    assert len(paid) == 1 and paid[0].source_definition_id == spare
    assert paid[0].payload['amount'] == 6
    assert e.state.actors[OWNER].reaction_available
    prompt = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.zero_hp_replacement')
    assert len(prompt['choice']['options']) == 2
    assert 'Test blow' in prompt['moment']


@pytest.mark.parametrize('flags,amount', [
    (['no_zero_hp_substitution'], 10), (['total_bodily_destruction'], 10), ([], 105)])
def test_blood_pump_cannot_replace_forbidden_or_instant_death_packet(tmp_path, flags, amount):
    def prepare(bundles):
        a = next(a for a in bundles[2]['action_catalog'] if a['display_name'] == 'Test blow')
        a['parameters']['typed'].update(effects=[damage(amount)], damage_source_flags=flags)
    combat, table, mid = scene(tmp_path, features=[PUMP], transform=prepare)
    use(combat, table, mid, 'Wound', OWNER)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Test blow', OWNER)
    e = reload(tmp_path, mid)
    assert e.state.actors[OWNER].current_hp == 0
    assert not any(ev.event_type == 'RESOURCE_SPENT' and ev.source_definition_id == PUMP for ev in e.events)


@pytest.mark.parametrize('flag', ['', 'harmless', 'deliberately_weakened', 'staged_hazard'])
def test_eat_the_flame_reads_source_intent_from_committed_fire_packet(tmp_path, flag):
    def prepare(bundles):
        a = next(a for a in bundles[2]['action_catalog'] if a['display_name'] == 'Test blow')
        a['parameters']['typed'].update(effects=[damage(10, 'fire')], damage_source_flags=[flag] if flag else [])
    combat, table, mid = scene(tmp_path, features=[HELL], transform=prepare)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Test blow', OWNER)
    e = reload(tmp_path, mid)
    owner = e.state.actors[OWNER]
    assert receipts(e)[-1].payload['hp_damage'] == 5
    assert owner.temporary_hp == (0 if flag else 5)
    assert owner.reaction_available == bool(flag)
    assert owner.resources[STAMINA] == (100 if flag else 99)
    assert receipts(e)[-1].payload.get('source_flags', []) == ([flag] if flag else [])


@pytest.mark.parametrize('barred', [False, True])
def test_swallow_respects_source_consumption_ban_without_removing_other_options(tmp_path, barred):
    def prepare(bundles):
        a = next(a for a in bundles[2]['action_catalog'] if a['display_name'] == 'Test blow')
        a['parameters']['typed'].update(effects=[damage(1, 'fire')],
            damage_source_flags=['cannot_be_consumed'] if barred else [])
    combat, table, mid = scene(tmp_path, features=[MAW+'swallow_the_technique'], transform=prepare)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Test blow', OWNER,
        {'reaction:typed.'+MAW+'swallow_the_technique': 'use'})
    e = reload(tmp_path, mid)
    assert receipts(e)[-1].payload['hp_damage'] == (1 if barred else 0)
    assert e.state.actors[OWNER].resources[STAMINA] == (100 if barred else 97)
    assert e.state.actors[OWNER].reaction_available == barred


@pytest.mark.parametrize('protected', [False, True])
def test_devour_failed_feast_downgrades_immunity_without_allowing_resistance_suppression(tmp_path, protected):
    def prepare(bundles):
        add_action(bundles[0], 'Store three Essence', [
            {'type': 'gain_resource', 'resource_id': 'resource:named.devoured_essence', 'flat': 3, 'applies_to': 'self'},
            {'type': 'condition', 'condition': 'devoured_types', 'applies_to': 'self',
             'condition_data': {'types': ['FIRE', 'FIRE', 'FIRE']}}], target='SELF')
        add_action(bundles[0], 'Scenario unarmed hit', [
            {'type': 'attack', 'attack_kind': 'unarmed', 'count': 1}],
            typed={'attack_bonus': 100, 'numbers': {'pb': 4, 'key_mod': 2, 'cl': 18, 'save_dc': 100}})
        add_action(bundles[0], 'Measure Fire', [damage(10, 'fire')])
        bundles[2]['typed_passives'].append({'block': 'defense', 'kind': 'immunity',
            'feature_id': 'test:fire_immunity', 'damage_types': ['FIRE'],
            **({'immunity_downgrade_min_cl': 19} if protected else {})})
        # Ordinary suppression must not erase Resistance derived from Immunity.
        add_action(bundles[0], 'Suppress ordinary Resistance', [
            {'type': 'suppress_resistance', 'damage_types': ['FIRE'], 'applies_to': 'target',
             'duration': {'kind': 'until_removed'}}])
    combat, table, mid = scene(tmp_path, features=[MAW+'feast_upon_protection', MAW+'devour_heaven_and_earth'],
                              transform=prepare)
    use(combat, table, mid, 'Devour Heaven and Earth')
    use(combat, table, mid, 'Store three Essence')
    use(combat, table, mid, 'Scenario unarmed hit', FOE,
        {'choice:needle.maw_types': ['spend'], 'choice:needle.feast_protection': ['immunity:FIRE']})
    e = reload(tmp_path, mid)
    assert any(m.target_field == 'damage_immunity_as_resistance' for m in e.state.actors[FOE].modifiers.values()) == (not protected)
    use(combat, table, mid, 'Suppress ordinary Resistance', FOE)
    use(combat, table, mid, 'Measure Fire', FOE)
    assert receipts(reload(tmp_path, mid), FOE)[-1].payload['hp_damage'] == (0 if protected else 5)
    turn(table, mid, FOE); turn(table, mid, OWNER)
    use(combat, table, mid, 'Measure Fire', FOE)
    assert receipts(reload(tmp_path, mid), FOE)[-1].payload['hp_damage'] == 0


@pytest.mark.parametrize('anti_life', [False, True])
def test_mercy_bloom_boosts_original_temp_hp_offer_and_stabilizes_only_legal_wound(tmp_path, anti_life):
    def prepare(bundles):
        add_action(bundles[0], 'Support', [{'type': 'temp_hp', 'flat': 2, 'applies_to': 'target'}],
                   typed={'foundation_alignment': ['spring']})
        add_action(bundles[2], 'Drop ally', [damage(100)])
        if anti_life:
            add_action(bundles[0], 'Anti-life wound', [
                {'type': 'condition', 'condition': 'scenario_anti_life', 'applies_to': 'target',
                 'condition_data': {'rule': {'anti_life_wound': True}}}])
    combat, table, mid = scene(tmp_path, foundation='verdant_returning_spring_v0_2B', transform=prepare)
    if anti_life:
        use(combat, table, mid, 'Anti-life wound', ALLY)
    turn(table, mid, FOE); use(combat, table, mid, 'Drop ally', ALLY); turn(table, mid, OWNER)
    use(combat, table, mid, 'Support', ALLY)
    e = reload(tmp_path, mid)
    assert e.state.actors[ALLY].temporary_hp == 8
    assert e.state.actors[ALLY].current_hp == 0
    assert e.state.actors[ALLY].life_state == ('DYING' if anti_life else 'STABLE')
    assert e.state.actors[OWNER].resources[f.pool('spring')] == 0


def test_mercy_cannot_spend_dew_generated_by_an_earlier_value_of_same_support_event(tmp_path):
    def prepare(bundles):
        add_action(bundles[0], 'Double support', [
            {'type': 'temp_hp', 'flat': 2, 'applies_to': 'target'},
            {'type': 'temp_hp', 'flat': 3, 'applies_to': 'target'}],
            typed={'foundation_alignment': ['spring']})
    combat, table, mid = scene(tmp_path, foundation='verdant_returning_spring_v0_2B', token=0, transform=prepare)
    use(combat, table, mid, 'Double support', ALLY)
    e = reload(tmp_path, mid)
    assert e.state.actors[ALLY].temporary_hp == 3
    assert e.state.actors[OWNER].resources[f.pool('spring')] == 1
    assert not any(ev.event_type == 'RESOURCE_SPENT' and
                   ev.source_definition_id == f.feature('spring', 'verdant_mercy_bloom') for ev in e.events)


def test_jade_release_increases_one_paid_reaction_reduction_value_before_hp_commit(tmp_path):
    source = 'test:damage_pipeline.paid_ward'
    def prepare(bundles):
        add_action(bundles[0], 'Paid ward method', [], typed={'foundation_alignment': ['furnace']})
        action = next(a for a in bundles[0]['action_catalog'] if a['display_name'] == 'Paid ward method')
        old = action['source_definition_id']
        action['source_definition_id'] = source
        bundles[0]['actor_template']['action_ids'].remove(old)
        bundles[0]['actor_template']['action_ids'].append(source)
        bundles[0]['typed_reactions'].append({'block': 'generic', 'kind': 'ally_damaged',
            'feature_id': source, 'name': 'Paid Ward', 'reaction': True, 'ask': True,
            'range_ft': 60, 'costs': [[STAMINA, 1]], 'numbers': {'pb': 4, 'key_mod': 2, 'cl': 15},
            'effects': [{'type': 'damage_modifier', 'flat': 2, 'applies_to': 'target'}]})
    combat, table, mid = scene(tmp_path, foundation=f.GROUPS['furnace'][0], transform=prepare)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Test blow', ALLY, {'reaction:typed.'+source: 'use'})
    e = reload(tmp_path, mid)
    assert receipts(e, ALLY)[-1].payload['hp_damage'] == 2
    assert e.state.actors[OWNER].resources[f.pool('furnace')] == 0
    assert not e.state.actors[OWNER].reaction_available


@pytest.mark.parametrize('suppressed', [False, True])
def test_oath_mark_uses_packet_type_and_guard_obeys_source_suppression(tmp_path, suppressed):
    def prepare(bundles):
        add_action(bundles[0], 'Scenario strike',
            [{'type': 'attack', 'attack_kind': 'unarmed', 'count': 1}],
            typed={'attack_bonus': 100})
        add_action(bundles[0], 'Suppress Oath', [
            {'type': 'condition', 'condition': 'scenario_suppression', 'applies_to': 'self',
             'condition_data': {'rule': {'unavailable_foundations': [f.GROUPS['oath'][0]]}}}], target='SELF')
    combat, table, mid = scene(tmp_path, foundation=f.GROUPS['oath'][0], transform=prepare)
    use(combat, table, mid, 'Declare Protected Subject', choices={f.CHOICE+'foundation_subject': [ALLY]})
    if suppressed:
        use(combat, table, mid, 'Suppress Oath')
    turn(table, mid, FOE)
    use(combat, table, mid, 'Test blow', ALLY, {f.CHOICE+'foundation_combat': None})
    e = reload(tmp_path, mid)
    assert e.state.actors[ALLY].current_hp == 90
    turn(table, mid, OWNER)
    use(combat, table, mid, 'Scenario strike', FOE)
    e = reload(tmp_path, mid)
    paid = [ev for ev in e.events if ev.event_type == 'RESOURCE_SPENT'
            and ev.source_definition_id == f.feature('oath', 'oath_mark_strike')]
    assert len(paid) == (0 if suppressed else 1)
    if not suppressed:
        packet = receipts(e, FOE)[-1]
        rolled = next(ev for ev in reversed(e.events) if ev.event_type == 'DAMAGE_ROLLED' and ev.actor_id == OWNER)
        assert packet.payload['rolled_or_pending_damage'] == rolled.payload['total'] + 4
        assert packet.payload['damage_type'].upper() == 'BLUDGEONING'


def test_refined_verdant_guard_stacks_base_and_perfected_on_one_spend_without_healing(tmp_path):
    combat, table, mid = scene(tmp_path, foundation='weak_reed_tendons_v0_2B')
    use(combat, table, mid, 'Foundation expression: Refined: Verdant Sinews')
    use(combat, table, mid, 'Wound', OWNER)
    before = reload(tmp_path, mid).state.actors[OWNER].current_hp
    turn(table, mid, FOE)
    guard = 'foundation.weak_reed_tendons_v0_2B.bend_without_breaking_guard'
    use(combat, table, mid, 'Test blow', OWNER, {'reaction:typed.'+guard: 'use'})
    e = reload(tmp_path, mid)
    assert e.state.actors[OWNER].current_hp == before
    assert receipts(e)[-1].payload['reduced_to'] == 0
    paid = [ev for ev in e.events if ev.event_type == 'RESOURCE_SPENT' and ev.source_definition_id == guard]
    assert len(paid) == 1 and paid[0].payload['amount'] == 1
    assert not e.state.actors[OWNER].reaction_available
