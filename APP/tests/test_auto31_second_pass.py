"""Actual failed checks trigger the saved, opted-in Chain curse once a round."""
import pytest

from tests.cw2_service_support import add_action, seal
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, reload, turn

CHAIN = 'TAL_FATE_CHAIN_OF_MISFORTUNE'
CONSEQUENCE = 'TAL_FATE_CONSEQUENCE_EDICT'


@pytest.mark.parametrize('case', ['actor_failure', 'defender_failure', 'success', 'warning', 'unowned', 'legacy'])
def test_chain_failed_check_commit_reload_and_round_limit(tmp_path, case):
    def prepare(bundles):
        for bundle, initiative in zip(bundles, [100, -100, 0]):
            bundle['actor_template']['initiative_bonus'] = initiative
            bundle['actor_template']['maximum_hp'] = 300
            bundle['skills'] = {'Test failure': -100, 'Test success': 100}
            add_action(bundle, 'Failed contest', [{'type': 'contest_against',
                'actor_check': {'ability': 'WIS', 'skill': 'Test failure'},
                'target_check': {'ability': 'WIS', 'skill': 'Test success'}}])
            add_action(bundle, 'Successful contest', [{'type': 'contest_against',
                'actor_check': {'ability': 'WIS', 'skill': 'Test success'},
                'target_check': {'ability': 'WIS', 'skill': 'Test failure'}}])
            seal(bundle)
        bundles[2]['actor_template']['saving_throws']['CHA'] = 100 if case == 'warning' else -100
        seal(bundles[2])
        if case == 'legacy':
            for action in bundles[0]['action_catalog']:
                typed = action.get('parameters', {}).get('typed', {})
                if typed.get('source') == CHAIN:
                    typed['effects'][0]['on_fail'][0].pop('failed_check', None)
            seal(bundles[0])

    combat, table, mid = fixture(tmp_path, [] if case == 'unowned' else [CHAIN], bundle_transform=prepare)
    if case != 'unowned':
        settle(table, mid, candidate(combat, mid, 'Chain of Misfortune', target=FOE).candidate_id)
    if case == 'defender_failure':
        target, name = FOE, 'Successful contest'
    else:
        turn(table, mid, FOE)
        target, name = ALLY, 'Successful contest' if case == 'success' else 'Failed contest'
    for _ in range(2):
        settle(table, mid, candidate(combat, mid, name, target=target).candidate_id,
               {'choice:needle.chain_of_misfortune': 'damage'})
        engine = reload(tmp_path, mid)
        check = next(e for e in reversed(engine.events) if e.event_type == 'CHECK_ROLLED')
        assert check.payload['success'] == (name == 'Successful contest')
        damage = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
                  and e.source_definition_id == CHAIN]
        assert len(damage) == int(case in ('actor_failure', 'defender_failure'))
        if damage:
            assert damage[0].target_ids == (FOE,)
            assert 2 <= damage[0].payload['hp_damage'] <= 16
        if case == 'warning':
            assert engine.state.actors[FOE].reaction_available
    if case == 'actor_failure':
        previous_round = engine.state.round_number
        settle(table, mid, table.state(mid)['menu']['end_turn'])
        turn(table, mid, FOE)
        settle(table, mid, candidate(combat, mid, name, target=target).candidate_id,
               {'choice:needle.chain_of_misfortune': 'damage'})
        engine = reload(tmp_path, mid)
        assert engine.state.round_number > previous_round
        assert len([e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
                    and e.source_definition_id == CHAIN]) == 2


@pytest.mark.parametrize('selection', [OWNER, FOE, None, 'legacy', 'automatic'])
def test_consequence_designated_immunity_is_chosen_and_saved(tmp_path, selection):
    def prepare(bundles):
        for bundle, initiative in zip(bundles, [100, -100, 0]):
            bundle['actor_template']['initiative_bonus'] = initiative
            bundle['actor_template']['maximum_hp'] = 300
            seal(bundle)
        add_action(bundles[0], 'Deal test damage', [{'type': 'damage', 'flat': 1,
                   'damage_types': ['psychic'], 'applies_to': 'target'}])
        if selection == 'legacy':
            for action in bundles[0]['action_catalog']:
                typed = action.get('parameters', {}).get('typed', {})
                if typed.get('source') == CONSEQUENCE:
                    typed['effects'][0].pop('immunity_choice', None)
            seal(bundles[0])
    combat, table, mid = fixture(tmp_path, [CONSEQUENCE], bundle_transform=prepare, ask=selection != 'automatic')
    settle(table, mid, candidate(combat, mid, 'Consequence Edict').candidate_id,
           {'choice:needle.consequence_immunity': None if selection == 'legacy' else selection})
    reload(tmp_path, mid)
    for _ in range(2):
        settle(table, mid, candidate(combat, mid, 'Deal test damage', target=ALLY).candidate_id)
        engine = reload(tmp_path, mid)
        damage = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
                  and e.source_definition_id == CONSEQUENCE]
        assert len(damage) == int(selection in (FOE, None))
        if damage:
            assert damage[0].target_ids == (OWNER,)
            assert damage[0].payload['hp_damage'] == 4
    zone = next(z for z in engine.state.zones.values() if z.active)
    if selection != 'legacy':
        expected = [OWNER, ALLY] if selection == 'automatic' else ([] if selection is None else [selection])
        assert zone.trigger_profile['fate_designated'] == expected
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == 98
