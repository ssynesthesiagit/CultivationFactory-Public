import pytest
"""Temporary NOACTRELOAD1F3 diagnostic; removed before the fix commit."""
from combat.table_facts import action_matches, records
from combat.ext.fate_reader import thread_live_branches
from tests.test_a2_group_traditions_2 import scene, use, advance, cold, _record_fate_prediction, ME, FOE


def test_diag_predicted_strike(tmp_path):
    read = 'tianxia.tradition.spirit.fate_reader.feature.read_the_thread'
    s, t, m = scene(tmp_path, [read])
    _record_fate_prediction(s, t, m, 'ACTION')
    engine = s._load_session(m).engine
    foe = engine.state.actors[FOE]
    live = list(thread_live_branches(engine, foe))
    pred = live[0][1] if live else None
    info = {'foe_name': foe.display_name, 'live': len(live),
            'pred': pred.model_dump(mode='json') if pred else None,
            'facts': sorted(records(engine).keys())}
    advance(s, t, m, FOE)
    engine = s._load_session(m).engine
    strikes = [(c.kind.value, list(c.target_ids), list(c.option_ids or []), c.candidate_id)
               for c in engine.legal_candidates()
               if engine.action_catalog.get(c.source_definition_id).display_name == 'Test: strike']
    info['strikes'] = strikes
    prompts = use(s, t, m, 'Test: strike', ME, picks=(ME, 'cell:4,5'))
    info['prompts'] = [str(p)[:300] for p in prompts]
    e = cold(tmp_path, m)
    info['events'] = [(v.event_type, v.actor_id, str(v.payload)[:120]) for v in e.events][-25:]
    pytest_fail = repr(info)
    raise AssertionError(pytest_fail)

