"""Paired offline decision timings on early frames of all six stock fights.

Both arms see the same native state. The baseline disables only AIWALK1's new
annotation hook; the measured frame includes menu generation and controller
selection. No live model transport, browser or external process is used.
"""
import json
import statistics
import time
import warnings

import pytest

from combat import ext
from combat.gate4_context import build_decision_context, build_reaction_context
from combat.gate4_controller import LocalDeterministicController
from combat.gate4_policy import PolicyLibrary
from tests.h1_support import ROOT
from tests.test_save_reload_equivalence import STOCK_SEEDS, _start_stock


@pytest.mark.parametrize('seed', STOCK_SEEDS)
def test_paired_stock_decision_timing(tmp_path, monkeypatch, seed):
    session, _ = _start_stock(tmp_path, seed)
    controller, policies = LocalDeterministicController(), PolicyLibrary(ROOT)
    ext._load()
    baseline, fixed, trajectories, diagnostics = [], [], [], []
    baseline_cpu, fixed_cpu = [], []
    annotations = list(ext._HOOKS.get('ai_decision_annotations', []))
    assert annotations, 'AIWALK1 annotation must be installed for the timing comparison'
    def react(request):
        policy, _ = policies.for_actor(request['reactor_id'])
        pick = controller.choose_reaction(build_reaction_context(session.engine, policy, request))
        return pick.decision, pick.record.model_dump(mode='json')
    for index in range(3):
        if session.engine.state.terminal_result:
            break
        policy, _ = policies.for_actor(session.engine.state.current_actor_id)
        answers, contexts = {}, {}
        # One warmup, then three alternating pairs on the unchanged real state.
        # CPU time separates added work from shared-runner scheduling noise.
        for repetition in range(4):
            for arm in (('baseline', 'fixed') if (index + repetition) % 2 == 0 else ('fixed', 'baseline')):
                with monkeypatch.context() as patch:
                    patch.setitem(ext._HOOKS, 'ai_decision_annotations', [] if arm == 'baseline' else annotations)
                    start = time.perf_counter()
                    cpu_start = time.process_time()
                    context = build_decision_context(session.engine, policy, for_ai=True)
                    pick = controller.choose_primary_action(context)
                    elapsed = (time.perf_counter() - start) * 1000
                    cpu_elapsed = (time.process_time() - cpu_start) * 1000
                answers[arm] = pick
                contexts[arm] = context
                if repetition:
                    (baseline if arm == 'baseline' else fixed).append(elapsed)
                    (baseline_cpu if arm == 'baseline' else fixed_cpu).append(cpu_elapsed)
        trajectories.append(answers['baseline'].intent.model_dump(mode='json') ==
                            answers['fixed'].intent.model_dump(mode='json'))
        context = contexts['fixed']
        def selected(arm):
            intent = answers[arm].intent
            candidate = next(c for c in contexts[arm].legal_candidates if c.candidate_id == intent.candidate_id)
            return {'source': candidate.source_definition_id, 'kind': candidate.kind,
                    'destination': intent.destination.model_dump() if intent.destination else None}
        diagnostics.append({'actor': context.active_actor_id,
            'baseline': selected('baseline'), 'fixed': selected('fixed'),
            'forecasts': [{'destination': c.destination.model_dump(), 'attack': c.metadata['walk_attack']}
                          for c in context.legal_candidates if c.metadata.get('walk_attack')]})
        session.submit_intent(answers['fixed'].intent,
            primary_decision_record=answers['fixed'].record, reaction_provider=react)
    warnings.warn('AIWALK1_TIMING ' + json.dumps({'seed': seed, 'samples': len(fixed),
        'baseline_ms': baseline, 'fixed_ms': fixed,
        'baseline_cpu_ms': baseline_cpu, 'fixed_cpu_ms': fixed_cpu,
        'median_baseline_ms': statistics.median(baseline),
        'median_fixed_ms': statistics.median(fixed),
        'same_choice': trajectories, 'diagnostics': diagnostics}), UserWarning)
