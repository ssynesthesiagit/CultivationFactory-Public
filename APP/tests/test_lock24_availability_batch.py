"""Batch explanations preserve exact refusals and one Table query after reload."""
import copy
import cProfile
from pathlib import Path
import pstats

from combat import action_legality
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_lock18_action_reasons import fixture, SOURCE, QI
from tests.test_lock2_persistence import table_match, act, ROOT


def test_batch_matches_independent_queries_and_refreshes_after_resource_change():
    engine, actor = fixture(costs=((QI, 2),))
    actor.resources[QI] = 1
    original = engine.action_catalog[SOURCE]
    for source, parameters in [('test:restricted', {'requires_condition': 'condition:test.absent'}),
                               ('test:free', {})]:
        engine.action_catalog[source] = original.model_copy(update={
            'source_definition_id': source, 'costs': (), 'parameters': parameters})
        actor.action_ids += (source,)
    sources = (SOURCE, 'test:restricted', 'test:free', 'test:missing')
    before = copy.deepcopy(engine.__dict__)
    answers = engine.action_availabilities(actor.entity_id, sources)
    assert answers == {source: engine.action_availability(actor.entity_id, source) for source in sources}
    assert answers[SOURCE]['code'] == 'COST'
    assert answers['test:restricted']['code'] == 'REQUIRES_CONDITION'
    assert answers['test:free'] == {'available': True, 'reason': None}
    assert answers['test:missing']['code'] == 'NOT_OWNED'
    assert engine.state == before['state'] and engine.events == before['events'] and engine.rolls == before['rolls']
    assert engine.roller.counter == before['roller'].counter
    for key in before:
        if 'cache' in key or key == '_augment_families':
            assert engine.__dict__[key] == before[key]
    actor.resources[QI] = 2
    assert engine.action_availabilities(actor.entity_id, sources)[SOURCE]['available']


def test_table_reloaded_explanations_build_candidates_once(tmp_path):
    _, table, mid = table_match(tmp_path)
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    fresh = CombatService(ROOT, tmp_path)
    engine = fresh._load_session(mid).engine
    before = engine.state.model_dump(mode='json'), list(engine.events), list(engine.rolls), engine.roller.counter
    profile = cProfile.Profile()
    state = profile.runcall(TabletopService(fresh, tmp_path).state, mid)
    assert len(state['unavailable_reasons']) >= 2
    builds = sum(call[0] for (file, _, name), entry in pstats.Stats(profile).stats.items()
                 if Path(file).name == 'gate4_engine.py' and name == 'legal_candidates'
                 for (caller, _, _), call in entry[4].items())
    assert builds == 1
    assert (engine.state.model_dump(mode='json'), engine.events, engine.rolls, engine.roller.counter) == before
    assert fresh._load_session(mid).verify()['status'] == 'PASS'


def test_empty_batch_does_not_inspect_or_copy_an_engine():
    assert action_legality.query_many(object(), 'actor:unused', ()) == {}


def test_observed_refusals_are_reused_only_for_the_exact_candidate_state(monkeypatch):
    """Diagnostics share the checked pass but cannot outlive a state/catalogue edit."""
    engine, actor = fixture(costs=((QI, 2),))
    actor.resources[QI] = 1
    with action_legality.observe(engine) as observations:
        candidates = engine.legal_candidates()
    action_legality.remember(engine, candidates, observations)
    generate = type(engine).legal_candidates
    calls = []

    def counted(self):
        calls.append(True)
        return generate(self)

    monkeypatch.setattr(type(engine), 'legal_candidates', counted)
    before = copy.deepcopy(engine.state)
    answer = engine.action_availability(actor.entity_id, SOURCE)
    assert answer['code'] == 'COST' and calls == []
    answer['reason'] = 'caller mutation'
    assert engine.action_availability(actor.entity_id, SOURCE)['reason'] != 'caller mutation'
    assert engine.state == before

    actor.resources[QI] = 2
    assert engine.action_availability(actor.entity_id, SOURCE)['available']
    assert len(calls) == 1
    with action_legality.observe(engine) as observations:
        candidates = engine.legal_candidates()
    action_legality.remember(engine, candidates, observations)
    engine.action_catalog[SOURCE] = engine.action_catalog[SOURCE].model_copy(update={'costs': ((QI, 3),)})
    assert engine.action_availability(actor.entity_id, SOURCE)['code'] == 'COST'
    assert len(calls) == 3
