"""Sol F10 review regressions for the Abyssal Pressure Seal lane.

F1: the nested-flight seal gate rolls a Water check and writes events, so it must not
    run on the pure effect_allowed query that Life-Severing Sword offers and
    attack_modifiers.effect_can_apply ask before consent and payment. It runs on the
    execution-only effect_execution_allowed hook instead, which the executor calls.
"""
from __future__ import annotations

from combat.ext import _HOOKS, _load, run_strict
from combat.ext import states
from combat.ext import attack_modifiers
from tests.test_mgr_t15_close_abyssal_pressure_seal import (
    COURT, SEAL, TARGET, cold, fixture, rows, settle, turn)

FLIGHT = {'type': 'general_flight', 'applies_to': 'self', 'speed_ft': 30, 'hover': False,
          'duration': {'kind': 'minutes', 'amount': 1}}


def _water_checks(engine):
    return [v for v in engine.events if v.event_type == 'CHECK_ROLLED' and v.payload.get('check') == 'Water Check']


def test_f1_nested_flight_offer_query_rolls_nothing(tmp_path):
    # Without the fix, effect_allowed runs seal_nested_flight: the sealed traveller's Water check
    # is rolled and events are appended while an offer is merely being built.
    c, t, mid = fixture(tmp_path, flight=True, water_success=False)
    settle(t, mid, rows(c, mid, COURT)[0].candidate_id)
    settle(t, mid, rows(c, mid, SEAL, TARGET)[0].candidate_id)
    turn(t, mid, TARGET)
    engine = cold(tmp_path, mid)
    target = engine.state.actors[TARGET]
    assert any(r.data.get('abyssal_pressure_seal') for r in target.conditions.values()), 'the seal is in force'
    ctx = states.context(engine, target, 'tianxia.subpath.qi.cloud_walker.feature.cloud_step', [target], {'pb': 6})
    events, checks, state = len(engine.events), len(_water_checks(engine)), engine.state.model_dump(mode='json')
    assert run_strict('effect_allowed', ctx, FLIGHT) == []
    assert attack_modifiers.effect_can_apply(ctx, FLIGHT) is True
    assert len(engine.events) == events
    assert len(_water_checks(engine)) == checks
    assert engine.state.model_dump(mode='json') == state


def test_f1_nested_flight_gate_is_registered_on_the_execution_hook_only(tmp_path):
    from combat.ext import water_second_pass
    _load()
    assert water_second_pass.seal_nested_flight in _HOOKS['effect_execution_allowed']
    assert water_second_pass.seal_nested_flight not in _HOOKS.get('effect_allowed', ())


def test_f1_executor_calls_the_execution_gate_after_the_pure_query():
    # Review F13R/F14R: source.index() searched the whole module and only proved that some
    # occurrence of each line exists, in a file-wide order. Parse the executor instead and
    # read the three statements out of the one loop body that runs effects, so an
    # effect_allowed call added anywhere after that loop cannot pass this guard.
    import ast
    from pathlib import Path

    tree = ast.parse((Path(__file__).resolve().parents[1] / 'combat/typed_executor.py').read_text())
    owner = next(node for node in ast.walk(tree)
                 if isinstance(node, ast.FunctionDef) and node.name == '_run_effects_in_chain')
    calls = {}
    for node in ast.walk(owner):
        if isinstance(node, ast.Call):
            func = node.func
            if (isinstance(func, ast.Attribute) and func.attr == 'run_strict' and node.args
                    and isinstance(node.args[0], ast.Constant) and node.args[0].value in
                    {'effect_allowed', 'effect_execution_allowed'}):
                calls.setdefault(node.args[0].value, []).append(node.lineno)
    gates = [node.lineno for node in ast.walk(owner) if isinstance(node, ast.Subscript)
             and isinstance(node.value, ast.Attribute) and node.value.attr == 'damage_cache'
             and 'modifier_once' in ast.dump(node.slice)]
    assert len(calls.get('effect_allowed', [])) == 1, calls
    assert len(calls.get('effect_execution_allowed', [])) == 1, calls
    assert len(gates) == 1, gates
    assert calls['effect_allowed'][0] < calls['effect_execution_allowed'][0] < gates[0]
