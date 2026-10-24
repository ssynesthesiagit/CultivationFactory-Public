"""Composed Daemonic capacity ending through PR24's exact-instance lifecycle."""
import pytest
from tests.worker2_support import OWNER, fixture, candidate, settle, reload
from tests.test_a2_daemonic_second import capacity_setup, ESSENCE, P
from tests.cw2_service_support import add_action, seal


def test_capacity_withdrawal_retains_receipt_and_cold_reloads(tmp_path):
    def setup(bundles):
        capacity_setup(bundles)
        add_action(bundles[0], 'Grant capacity', [
            {'type': 'condition', 'applies_to': 'self', 'condition': 'prone', 'expires_on': 'UNTIL_REMOVED'},
            {'type': 'resource_capacity', 'resource_id': ESSENCE,
             'anchor': 'condition:typed.prone', 'amount': 2}], target='SELF')
        add_action(bundles[0], 'Withdraw capacity', [
            {'type': 'remove_condition', 'applies_to': 'self', 'condition': 'resource_capacity'}], target='SELF')
        seal(bundles[0])

    combat, table, mid = fixture(tmp_path, [P + 'DEMON_SEED'], bundle_transform=setup)
    settle(table, mid, candidate(combat, mid, 'Grant capacity').candidate_id)
    assert reload(tmp_path, mid).state.actors[OWNER].resource_maximums[ESSENCE] == 14
    settle(table, mid, candidate(combat, mid, 'Withdraw capacity').candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resource_maximums[ESSENCE] == 12
    ending = next(event for event in reversed(engine.events)
                  if event.event_type == 'CONDITION_REMOVED'
                  and event.payload.get('condition_id') == 'condition:typed.resource_capacity')
    receipt = ending.payload['removed_condition']
    assert receipt['target_id'] == OWNER
    assert receipt['data']['retain_removal_data']
    assert receipt['condition_id'] == 'condition:typed.resource_capacity'
    assert combat.verify(mid)['status'] == 'PASS'


def test_unowned_temporary_hp_hooks_are_inert_at_table_commit(tmp_path):
    def setup(bundles):
        add_action(bundles[0], 'Temporary guard', [
            {'type': 'temp_hp', 'flat': 3, 'applies_to': 'self'}], target='SELF')
        seal(bundles[0])

    combat, table, mid = fixture(tmp_path, [], bundle_transform=setup)
    settle(table, mid, candidate(combat, mid, 'Temporary guard').candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].temporary_hp == 3
    offers = [event for event in engine.events if event.event_type == 'TEMP_HP_GRANTED'
              and event.target_ids == (OWNER,)]
    assert len(offers) == 1 and offers[0].payload['offered'] == 3
    assert combat.verify(mid)['status'] == 'PASS'


def test_flustered_bookkeeping_keeps_reaction_restore_receipt(tmp_path):
    from tests.test_auto65_jester import flustered_fixture
    from tests.worker2_support import FOE, turn

    combat, table, mid = flustered_fixture(tmp_path)
    before = next(condition for condition in reload(tmp_path, mid).state.actors[FOE].conditions.values()
                  if condition.condition_id == 'condition:typed.flustered')
    assert before.data['reaction_suppression_restore']
    settle(table, mid, candidate(combat, mid, 'Actual skill check', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    after = engine.state.actors[FOE].conditions[before.instance_id]
    assert after.data['disadvantage'] is False
    assert not (after.data.get('rule') or {}).get('check_mode')
    assert not (after.data.get('rule') or {}).get('attacks_have')
    assert after.data['reaction_suppression_restore'] == before.data['reaction_suppression_restore']
    assert after.expires_on == before.expires_on
    turn(table, mid, OWNER)
    assert reload(tmp_path, mid).state.actors[FOE].reaction_available


@pytest.mark.parametrize('storage', ['display_trigger', 'moment'])
def test_prompt_keeps_action_provenance_and_printed_consequences(storage):
    from combat.decision_text import build_decision_text

    consequence = 'Gain 1 Corruption; once until your next Long Rest.'
    context = {'reactor_id': 'hero', 'reaction_source_id': 'choice:recovery', 'extension_choice': True,
        'choice_trigger': {'action_name': 'Lethal blast', 'action_actor_id': 'foe',
            'affected_id': 'hero'}}
    supplied = {'reaction': 'Recovery', 'reactor': 'Hero', 'moment': 'Survive the damage'}
    if storage == 'display_trigger':
        context['choice_trigger']['display_trigger'] = consequence
    else:
        supplied['moment'] = consequence
    prompt = build_decision_text(None, context, supplied,
        {'hero': 'Hero', 'foe': 'Enemy'}, {}, {})
    assert 'Lethal blast' in prompt['trigger']
    assert 'Hero' in prompt['trigger']
    assert 'Corruption' in prompt['trigger'] and 'Long Rest' in prompt['trigger']


def test_qi_scaling_compiler_ignores_other_plugin_payloads():
    from types import SimpleNamespace
    from combat.ext.qi_subpaths_four import character_actions

    typed = {'effects': [{'type': 'rider', 'effects': {'manual': 'GM chooses'}}]}
    action = SimpleNamespace(parameters={'typed': typed})
    assert character_actions(action, {'owned_ids': []}) is None
    assert typed['effects'][0]['effects'] == {'manual': 'GM chooses'}
    mixed_menu = {'effects': [{'type': 'rider', 'effects': [{'type': 'qi_character_mend'}]}]}
    assert character_actions(SimpleNamespace(parameters={'typed': mixed_menu}), {'owned_ids': []}) is None


def test_roll_provenance_keeps_saving_throw_kind_with_action_context():
    from combat.decision_text import trigger_text

    context = {'checkpoint': 'TYPED:D20_ROLL_BONUS@1',
        'choice_trigger': {'roll_kind': 'save', 'save_ability': 'WIS', 'action_name': 'Demand save',
                           'action_actor_id': 'foe', 'affected_id': 'hero'}}
    prompt = {'reactor': 'Hero', 'action': 'Demand save', 'affected': 'Hero', 'by': 'Enemy',
              'moment': 'Resolve the saving throw'}
    text = trigger_text(context, prompt, {'hero': 'Hero', 'foe': 'Enemy'}, {})
    assert 'saving throw' in text and 'Demand save' in text and 'Hero' in text
