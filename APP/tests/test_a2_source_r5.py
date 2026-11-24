"""Grouped Speed removal through actual casts, table commits and cold replay."""
import pytest
from tests.h1_support import sheet
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload
from tests.test_a2_source_second_pass import PULSE, CIRCUIT, arena
from tests.test_a2_source_r3 import ordered_attacks, reseal
from tests.test_auto49_life import option
from tests.cw2_service_support import add_action

MERIDIAN = 'tianxia.talent.life.meridian_unbinding'


def penalties(engine):
    return {key: c for key, c in engine.state.actors[FOE].conditions.items()
            if c.data.get('speed_penalty_group')}


def setup(bundles):
    ordered_attacks(bundles)
    # Same team as the patient: this benefit must never be offered as hostile harm.
    add_action(bundles[2], 'Recorded Speed benefit', [
        {'type': 'speed', 'flat': 5, 'applies_to': 'self', 'duration': {'kind': 'until_removed'}}])
    add_action(bundles[2], 'Recorded movement removal', [
        {'type': 'end_effect', 'categories': ['movement'], 'select': 'hostile',
         'choose_instance': True, 'applies_to': 'self'}])
    add_action(bundles[2], 'Recorded movement suppression', [
        {'type': 'end_effect', 'categories': ['movement'], 'select': 'hostile',
         'choose_instance': True, 'on_success': 'suppress', 'success_rounds': 10,
         # Explicit condition also isolates the grouped-data reader on the old head.
         'conditions': ['source_pulse_slow'],
         'applies_to': 'self'}])
    from combat.typed_executor import mark_condition_id
    bundles[2]['typed_passives'].append({'block': 'motion', 'kind': 'speed_floor',
        'while': mark_condition_id('source_r5_floor', FOE), 'feature_id': 'test:source_r5_floor'})
    add_action(bundles[2], 'Recorded Speed floor', [
        {'type': 'mark', 'mark': 'source_r5_floor', 'applies_to': 'self',
         'duration': {'kind': 'until_removed'}}])
    reseal(bundles[2])


@pytest.mark.parametrize('two_casters,remove_strong', [(False, True), (True, True), (True, False)])
def test_actual_pulse_meridian_selects_one_hostile_speed_instance(tmp_path, two_casters, remove_strong):
    combat, table, mid = fixture(tmp_path, [PULSE, CIRCUIT],
        ally_talents=[PULSE] if two_casters else [], foe_sheet=sheet([MERIDIAN], cl=15),
        battlefield=arena(), bundle_transform=setup)
    settle(table, mid, candidate(combat, mid, 'Source Circuit', target=OWNER).candidate_id)
    settle(table, mid, candidate(combat, mid, 'Source Pulse', target=FOE).candidate_id)
    if two_casters:
        turn(table, mid, ALLY)
        settle(table, mid, candidate(combat, mid, 'Source Pulse', target=FOE).candidate_id)
    turn(table, mid, FOE)
    before = reload(tmp_path, mid)
    live = penalties(before)
    assert len(live) == (2 if two_casters else 1)
    assert before._effective_speed(before.state.actors[FOE]) == 10
    chosen_source = OWNER if remove_strong else ALLY
    chosen = next(key for key, c in live.items() if c.source_actor_id == chosen_source)
    cp = before.state.actors[FOE].resources['resource:core.qi']
    cast = option(combat, mid, ['Purify the Pulse: Remove Poisoned', 'Meridian Unbinding'], target=FOE)
    prompts = settle(table, mid, cast.candidate_id,
                     {'choice:needle.purify_extra': 'speed', 'choice:needle.end_effect': chosen})
    speed_prompt = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.purify_extra']
    assert speed_prompt and any(o['id'] == 'speed' and o['label'] == 'Remove a Speed reduction'
                               for o in speed_prompt[-1]['choice']['options'])
    instance_prompt = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.end_effect']
    assert instance_prompt and {o['id'] for o in instance_prompt[-1]['choice']['options']} == set(live)
    after = reload(tmp_path, mid)
    assert set(penalties(after)) == set(live) - {chosen}
    assert after._effective_speed(after.state.actors[FOE]) == (30 if not two_casters else 20 if remove_strong else 10)
    assert after.state.actors[FOE].resources['resource:core.qi'] == cp - 2
    removed = [e for e in after.events if e.event_type == 'CONDITION_REMOVED' and e.payload.get('instance_id') == chosen]
    assert len(removed) == 1 and removed[0].payload['reason'] == 'ENDED'
    if two_casters:
        turn(table, mid, OWNER if not remove_strong else ALLY)
        clean = reload(tmp_path, mid)
        assert not penalties(clean)
        assert clean._effective_speed(clean.state.actors[FOE]) == 30


def test_shared_movement_category_removes_actual_pulse_and_preserves_friendly_bonus(tmp_path):
    combat, table, mid = fixture(tmp_path, [PULSE], foe_sheet=sheet([], cl=15),
        battlefield=arena(), bundle_transform=setup)
    settle(table, mid, candidate(combat, mid, 'Source Pulse', target=FOE).candidate_id)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Recorded Speed benefit', target=FOE).candidate_id)
    before = reload(tmp_path, mid)
    assert before._effective_speed(before.state.actors[FOE]) == 25
    live = penalties(before)
    prompts = settle(table, mid, candidate(combat, mid, 'Recorded movement removal', target=FOE).candidate_id,
                     {'choice:needle.end_effect': next(iter(live))})
    assert {o['id'] for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.end_effect'
            for o in p['choice']['options']} == set(live)
    after = reload(tmp_path, mid)
    assert not penalties(after)
    assert after._effective_speed(after.state.actors[FOE]) == 35


def test_movement_suppression_ignores_grouped_data_and_never_resurrects_expired_pulse(tmp_path):
    combat, table, mid = fixture(tmp_path, [PULSE], foe_sheet=sheet([], cl=15),
        battlefield=arena(), bundle_transform=setup)
    settle(table, mid, candidate(combat, mid, 'Source Pulse', target=FOE).candidate_id)
    turn(table, mid, FOE)
    before = reload(tmp_path, mid)
    [key] = penalties(before)
    assert before._effective_speed(before.state.actors[FOE]) == 20
    settle(table, mid, candidate(combat, mid, 'Recorded movement suppression', target=FOE).candidate_id,
           {'choice:needle.end_effect': key})
    suppressed = reload(tmp_path, mid)
    assert suppressed._effective_speed(suppressed.state.actors[FOE]) == 30
    assert penalties(suppressed)[key].condition_id.startswith('condition:typed.suppressed.')
    from combat.ext.end_effect import found
    assert not found(suppressed, suppressed.state.actors[FOE], {'categories': ['movement'], 'select': 'hostile'})
    turn(table, mid, OWNER)
    expired = reload(tmp_path, mid)
    assert not penalties(expired)
    for _ in range(10):
        turn(table, mid, FOE)
        turn(table, mid, OWNER)
    clean = reload(tmp_path, mid)
    assert not penalties(clean)
    assert clean._effective_speed(clean.state.actors[FOE]) == 30


def test_meridian_menu_does_not_offer_floor_ignored_pulse(tmp_path):
    combat, table, mid = fixture(tmp_path, [PULSE], foe_sheet=sheet([MERIDIAN], cl=15),
        battlefield=arena(), bundle_transform=setup)
    settle(table, mid, candidate(combat, mid, 'Source Pulse', target=FOE).candidate_id)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Recorded Speed floor', target=FOE).candidate_id)
    floored = reload(tmp_path, mid)
    assert penalties(floored)
    assert floored._effective_speed(floored.state.actors[FOE]) == 30
    from combat.ext.end_effect import found
    assert not found(floored, floored.state.actors[FOE], {'categories': ['speed'], 'select': 'hostile'})
    cast = option(combat, mid, ['Purify the Pulse: Remove Poisoned', 'Meridian Unbinding'], target=FOE)
    prompts = settle(table, mid, cast.candidate_id)
    assert not [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.purify_extra']
    assert set(penalties(reload(tmp_path, mid))) == set(penalties(floored))
