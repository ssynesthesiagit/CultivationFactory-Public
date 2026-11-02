"""Dotted Factory owner IDs must never become part of a printed mark name."""
import pytest
from combat.history_feed import format_history_feed
from combat.typed_executor import mark_condition_id
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.r1i_service_support import fixture, candidate, force_ai_candidate, OWNER, FOE


@pytest.mark.parametrize('owner', ['actor:factory.owner', 'actor:factory.owner.with.dots'])
@pytest.mark.parametrize('mark', ['Resonance', 'Fracture Mark', 'Dream Seed'])
def test_mark_history_uses_printed_name_without_owner_id(owner, mark):
    event = {'event_type': 'CONDITION_APPLIED', 'sequence': 1, 'actor_id': owner,
             'target_ids': ['actor:factory.target'], 'source_definition_id': 'test:ability',
             'payload': {'condition_id': mark_condition_id(mark, owner), 'instance_id': 'test:mark'}}
    rows = format_history_feed([event], [], pre_state={}, post_state={},
        actor_names={owner: 'Lin', 'actor:factory.target': 'Chen'}, definition_names={'test:ability': 'Spirit technique'})
    assert rows
    text = ' '.join(row['summary'] for row in rows)
    assert mark in text
    assert 'Resonance.Actor' not in text and 'Owner.With' not in text


@pytest.mark.parametrize('auto', [False, True])
def test_resonance_and_revealed_information_are_plain_after_table_reload(tmp_path, auto):
    mind = 'tianxia.path.spirit_awakening.feature.mind_spike'
    def spirit(bundles):
        doc = sheet([mind], cl=17, dc=100, primary='Resonance')
        doc['identity'].update(path='Spirit Awakening', display_name='Lin')
        doc['ability_scores_and_statistics']['primary_resource']['maximum'] = 100
        bundles[0] = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})
    combat, table, mid, send, commit = fixture(tmp_path, [mind], bundle_transform=spirit)
    commit(candidate(table, mid, 'Spiritual Pressure: Revealed Disturbance'))
    commit(candidate(table, mid, 'Mind Spike', FOE))
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id'] != OWNER:
        commit(table.state(mid)['menu']['end_turn'])
    action = candidate(table, mid, 'Mind Spike', FOE)
    if auto:
        force_ai_candidate(combat, mid, OWNER, action)
        assert send(action, auto=True)['status'] == 'COMMITTED'
    else:
        commit(action)
    fresh = CombatService(ROOT, tmp_path)
    assert fresh._load_session(mid).mechanical.replay()['status'] == 'PASS'
    summaries = [e['summary'] for e in TabletopService(fresh, tmp_path).events(mid, 0)['events']]
    assert any('Resonance' in s and 'placed' in s for s in summaries)
    information = next(s for s in summaries if 'Revealed Disturbance:' in s)
    assert 'Foe' in information and 'actor:factory' not in information
    assert 'skipped' not in information and 'Not automated' not in information
