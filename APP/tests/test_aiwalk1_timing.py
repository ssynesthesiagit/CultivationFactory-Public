"""Paired offline decision timings on early frames of all six stock fights.

Both arms see the same native state. The baseline disables only AIWALK1's new
annotation hook; the measured frame includes menu generation and controller
selection. No live model transport, browser or external process is used.

Gates (review finding 1): the walk forecast is default-on for AI, so its cost is
bounded by an explicit CPU budget and every changed AI choice must be a MOVE to a
destination that carried a walk_attack forecast. Wall time is only recorded.
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

# Stated budget: median CPU of the forecast arm may exceed the baseline median by
# at most 25% plus 5 ms. Measured per-seed CPU medians in fix/AIWALK1-evidence/
# timing-final.json ranged from -3.6% to +20.8% (max +20.8% is within the budget).
BUDGET_RATIO = 1.25
BUDGET_SLACK_MS = 5.0


def within_budget(baseline_cpu, fixed_cpu):
    return statistics.median(fixed_cpu) <= BUDGET_RATIO * statistics.median(baseline_cpu) + BUDGET_SLACK_MS


def choice_change_ok(diagnostic):
    """An unchanged choice is fine; a changed one must be an AI MOVE onto a forecast destination."""
    if diagnostic['baseline'] == diagnostic['fixed']:
        return True
    fixed = diagnostic['fixed']
    if fixed['kind'] != 'MOVE' or fixed['destination'] is None:
        return False
    return any(f['destination'] == fixed['destination'] for f in diagnostic['forecasts'])


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
    record = {'seed': seed, 'samples': len(fixed),
        'baseline_ms': baseline, 'fixed_ms': fixed,
        'baseline_cpu_ms': baseline_cpu, 'fixed_cpu_ms': fixed_cpu,
        'median_baseline_ms': statistics.median(baseline),
        'median_fixed_ms': statistics.median(fixed),
        'same_choice': trajectories, 'diagnostics': diagnostics}
    warnings.warn('AIWALK1_TIMING ' + json.dumps(record), UserWarning)
    assert baseline_cpu, 'no timed samples were recorded'
    assert within_budget(baseline_cpu, fixed_cpu), (
        'walk forecast CPU exceeded the stated budget', statistics.median(baseline_cpu), statistics.median(fixed_cpu))
    bad = [d for d in diagnostics if not choice_change_ok(d)]
    assert not bad, ('a changed AI choice is not a move onto a forecast destination', bad)


def test_timing_budget_rejects_slowdown():
    """Regression for finding 1: the gate must fail on a real slowdown and pass the measured one."""
    assert within_budget([10.0] * 9, [11.0] * 9)
    assert not within_budget([10.0] * 9, [20.0] * 9)


def test_choice_change_gate_rejects_unrelated_change():
    """Regression for finding 1: a changed choice must be a forecast-backed move."""
    forecast = {'destination': {'x': 1, 'y': 0, 'z': 0}, 'attack': {'gain': 4}}
    move = {'source': 'move', 'kind': 'MOVE', 'destination': {'x': 1, 'y': 0, 'z': 0}}
    attack = {'source': 'sword', 'kind': 'ACTION', 'destination': None}
    assert choice_change_ok({'baseline': attack, 'fixed': move, 'forecasts': [forecast]})
    assert not choice_change_ok({'baseline': move, 'fixed': attack, 'forecasts': [forecast]})
    assert not choice_change_ok({'baseline': attack, 'fixed': {**move, 'destination': {'x': 9, 'y': 9, 'z': 0}},
                                 'forecasts': [forecast]})
