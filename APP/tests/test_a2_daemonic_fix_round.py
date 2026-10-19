"""Review regressions: committed table intents and cold mechanical reloads."""
import pytest
from tests.worker2_support import OWNER, FOE, fixture, settle, candidate, reload, turn
from tests.test_auto103_daemonic import sow, cycle
from tests.test_a2_daemonic_second import (
    circulation_bundle, circulation_setup, capacity_setup, P, INSIGHT, ESSENCE,
)
from tests.cw2_service_support import add_action, seal


def sun_setup(b):
    circulation_setup(b)
    b[2]['actor_template']['saving_throws']['WIS'] = -100
    add_action(b[2], 'Spend Qi', [], target='SELF')
    pool = b[2]['actor_template']['resources'][0]['resource_id']
    b[2]['action_catalog'][-1]['costs'] = [[pool, 1]]
    seal(b[2])


def sun_fixture(tmp_path, setting):
    combat, table, mid = fixture(tmp_path, [],
        owner_bundle=circulation_bundle(extra=[P+'BLACK_SUN_OVER_THE_DANTIAN']),
        bundle_transform=sun_setup)
    sow(combat, table, mid)
    settle(table, mid, candidate(combat, mid, 'Devil-Qi Circulation: '+setting.title()).candidate_id)
    cycle(table, mid, OWNER)
    e = reload(tmp_path, mid)
    sun = next(c for c in e.legal_candidates() if c.target_ids == (FOE,)
        and e.action_catalog[c.source_definition_id].display_name.startswith('Black Sun Over the Dantian'))
    return combat, table, mid, sun


@pytest.mark.parametrize('first,obsolete,reward', [('necrotic','psychic',1), ('psychic','necrotic',0)])
def test_black_sun_has_one_final_type_and_matching_reward(tmp_path, first, obsolete, reward):
    combat, table, mid, sun = sun_fixture(tmp_path, 'necrotic')
    prompts = settle(table, mid, sun.candidate_id, {
        'choice:needle.devil_qi_damage': first,
        # Counterfactual conflicting answer: this old independent checkpoint
        # must never be opened, in either direction.
        'choice:needle.black_sun_damage': obsolete})
    e = reload(tmp_path, mid)
    armed = next(c for c in e.state.actors[FOE].conditions.values()
                 if c.condition_id == 'condition:typed.black_sun_spend')
    assert armed.data['damage_type'] == first
    type_prompts = [p['context']['reaction_source_id'] for p in prompts
                    if p['context']['reaction_source_id'] in
                    {'choice:needle.devil_qi_damage', 'choice:needle.black_sun_damage'}]
    assert type_prompts == ['choice:needle.devil_qi_damage']
    assert len([ev for ev in e.events if ev.event_type == 'RESOURCE_GAINED'
                and ev.source_definition_id == INSIGHT]) == reward
    assert e.state.actors[OWNER].resources[ESSENCE] == 5 + reward


@pytest.mark.parametrize('changed', [False, True])
def test_delayed_original_type_never_reopens_after_application(tmp_path, changed):
    combat, table, mid, sun = sun_fixture(tmp_path, 'fire')
    settle(table, mid, sun.candidate_id, {'choice:needle.devil_qi_damage':'psychic',
                                        'choice:needle.black_sun_damage':'psychic'})
    e = reload(tmp_path, mid)
    armed = next(c for c in e.state.actors[FOE].conditions.values()
                 if c.condition_id == 'condition:typed.black_sun_spend')
    assert armed.data['damage_type'] == 'psychic'
    assert not [ev for ev in e.events if ev.event_type == 'DAMAGE_COMMITTED']
    if changed:
        settle(table, mid, candidate(combat, mid, 'Devil-Qi Circulation: Acid').candidate_id)
        reload(tmp_path, mid)
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, 'Spend Qi').candidate_id,
                     {'choice:needle.devil_qi_damage':'acid' if changed else 'fire'})
    e = reload(tmp_path, mid)
    assert not [p for p in prompts if p['context']['reaction_source_id'] in
                {'choice:needle.devil_qi_damage', 'choice:needle.black_sun_damage'}]
    packets = [ev for ev in e.events if ev.event_type == 'DAMAGE_COMMITTED']
    assert len(packets) == 1 and packets[0].payload['damage_type'] == 'PSYCHIC'
    assert packets[0].target_ids == (FOE,)
    assert not [ev for ev in e.events if ev.event_type == 'RESOURCE_GAINED'
                and ev.source_definition_id == INSIGHT]
    assert not any(c.condition_id == 'condition:typed.black_sun_spend'
                   for c in e.state.actors[FOE].conditions.values())


@pytest.mark.parametrize('stacked', [False, True])
def test_direct_capacity_removal_restores_clamps_and_regrants(tmp_path, stacked):
    def setup(b):
        capacity_setup(b)
        for name, amount in [('A',2), ('B',4)]:
            anchor = 'prone' if name == 'A' else 'poisoned'
            add_action(b[0], 'Grant '+name, [
                {'type':'condition','applies_to':'self','condition':anchor,'expires_on':'UNTIL_REMOVED'},
                {'type':'resource_capacity','resource_id':ESSENCE,'anchor':'condition:typed.'+anchor,'amount':amount}], target='SELF')
            add_action(b[0], 'End '+name, [{'type':'remove_condition','applies_to':'self','condition':anchor}], target='SELF')
        add_action(b[0], 'Withdraw ledgers', [{'type':'remove_condition','applies_to':'self','condition':'resource_capacity'}], target='SELF')
        add_action(b[0], 'Fill pool', [{'type':'gain_resource','applies_to':'self','resource_id':ESSENCE,'flat':20}], target='SELF')
        seal(b[0])
    combat, table, mid = fixture(tmp_path, [P+'DEMON_SEED'], bundle_transform=setup)
    settle(table, mid, candidate(combat, mid, 'Grant A').candidate_id)
    if stacked:
        settle(table, mid, candidate(combat, mid, 'Grant B').candidate_id)
    maximum = 18 if stacked else 14
    assert reload(tmp_path, mid).state.actors[OWNER].resource_maximums[ESSENCE] == maximum
    settle(table, mid, candidate(combat, mid, 'Fill pool').candidate_id)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[ESSENCE] == maximum
    settle(table, mid, candidate(combat, mid, 'Withdraw ledgers').candidate_id)
    e = reload(tmp_path, mid)
    owner = e.state.actors[OWNER]
    assert owner.resource_maximums[ESSENCE] == owner.resources[ESSENCE] == 12
    assert not any(c.condition_id == 'condition:typed.resource_capacity' for c in owner.conditions.values())
    assert [ev.payload['maximum'] for ev in e.events if ev.event_type == 'RESOURCE_MAXIMUM_CHANGED'] == (
        [14,18,16,12] if stacked else [14,12])
    for name in ['A', 'B'] if stacked else ['A']:
        settle(table, mid, candidate(combat, mid, 'End '+name).candidate_id)
        assert reload(tmp_path, mid).state.actors[OWNER].resource_maximums[ESSENCE] == 12
    settle(table, mid, candidate(combat, mid, 'Grant A').candidate_id)
    assert reload(tmp_path, mid).state.actors[OWNER].resource_maximums[ESSENCE] == 14
    settle(table, mid, candidate(combat, mid, 'End A').candidate_id)
    assert reload(tmp_path, mid).state.actors[OWNER].resource_maximums[ESSENCE] == 12


def test_initial_circulation_prompt_identifies_action_and_creature(tmp_path):
    def setup(b):
        circulation_setup(b)
        b[0]['actor_template']['display_name'] = 'Cultivator'
        b[2]['actor_template']['display_name'] = 'Intruder'
        seal(b[0]); seal(b[2])
    combat, table, mid = fixture(tmp_path, [], owner_bundle=circulation_bundle(), bundle_transform=setup)
    sow(combat, table, mid)
    cycle(table, mid, OWNER)
    e = reload(tmp_path, mid)
    mark = next(c for c in e.legal_candidates() if c.target_ids == (FOE,)
                and e.action_catalog[c.source_definition_id].display_name.startswith('Demon Mark'))
    action_name = e.action_catalog[mark.source_definition_id].display_name
    creature_name = e.state.actors[FOE].display_name
    prompts = settle(table, mid, mark.candidate_id, {'choice:needle.devil_qi_circulation':'acid'})
    p = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.devil_qi_circulation')
    assert p['affected'] == creature_name
    assert p['action'] == action_name
    assert action_name in p['moment'] and creature_name in p['moment']
    assert 'Cultivator' not in p['by']
    assert 'choice:' not in p['moment'] and 'actor:' not in p['moment']
    assert any(c.data.get('kind') == 'acid' for c in reload(tmp_path, mid).state.actors[OWNER].conditions.values())
