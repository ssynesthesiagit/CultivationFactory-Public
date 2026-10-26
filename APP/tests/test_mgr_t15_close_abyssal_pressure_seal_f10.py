"""Sol F10 review regressions for the Abyssal Pressure Seal lane.

F1: the nested-flight seal gate rolls a Water check and writes events, so it must not
    run on the pure effect_allowed query that Life-Severing Sword offers and
    attack_modifiers.effect_can_apply ask before consent and payment. It runs on the
    execution-only effect_execution_allowed hook instead, which the executor calls inside
    the loop that runs each effect (F15R: the guard reads that loop's executed nodes, and a
    nested flight row executed for the sealed traveller is denied).
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


def _executed_nodes(node):
    """Every node one pass of the effect loop runs: blocks and expressions, but no nested definition.

    A nested function, lambda or class body runs only when something calls it, so a hook call
    parked in an uncalled helper gates no effect; it must not satisfy the guard below.
    """
    import ast

    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
        return
    yield node
    for child in ast.iter_child_nodes(node):
        yield from _executed_nodes(child)


def _effect_loop_nodes():
    """The nodes the one "for effect in effects" loop of _run_effects_in_chain runs per effect."""
    import ast
    from pathlib import Path

    tree = ast.parse((Path(__file__).resolve().parents[1] / 'combat/typed_executor.py').read_text())
    owner = next(node for node in ast.walk(tree)
                 if isinstance(node, ast.FunctionDef) and node.name == '_run_effects_in_chain')
    loops = [node for node in ast.walk(owner) if isinstance(node, ast.For)
             and isinstance(node.target, ast.Name) and node.target.id == 'effect'
             and isinstance(node.iter, ast.Name) and node.iter.id == 'effects']
    assert len(loops) == 1, [loop.lineno for loop in loops]
    return list(_executed_nodes(loops[0]))


def test_f1_executor_calls_the_execution_gate_after_the_pure_query():
    # Review F13R/F14R/F15R: source.index() searched the whole module, and walking the whole function
    # still counted nested function bodies, so both hook calls parked in an uncalled helper inside the
    # loop passed while gating nothing. Read the three statements out of the loop that actually runs
    # each effect, nested definitions excluded.
    import ast

    body = _effect_loop_nodes()
    calls = {}
    for node in body:
        if isinstance(node, ast.Call):
            func = node.func
            if (isinstance(func, ast.Attribute) and func.attr == 'run_strict' and node.args
                    and isinstance(node.args[0], ast.Constant) and node.args[0].value in
                    {'effect_allowed', 'effect_execution_allowed'}):
                calls.setdefault(node.args[0].value, []).append(node.lineno)
    gates = [node.lineno for node in body if isinstance(node, ast.Subscript)
             and isinstance(node.value, ast.Attribute) and node.value.attr == 'damage_cache'
             and 'modifier_once' in ast.dump(node.slice)]
    assert len(calls.get('effect_allowed', [])) == 1, calls
    assert len(calls.get('effect_execution_allowed', [])) == 1, calls
    assert len(gates) == 1, gates
    assert calls['effect_allowed'][0] < calls['effect_execution_allowed'][0] < gates[0]


def test_f1_nested_flight_execution_is_stopped_by_the_seal(tmp_path):
    # Review F15R: prove it at the level the bug shows. Executing a nested flight row for the sealed
    # traveller must roll the Water check and grant nothing, rather than only the ability's top-level
    # declaration hook stopping it.
    from combat import typed_executor
    from combat.ext.general_flight_skills import FLIGHT_CONDITION

    c, t, mid = fixture(tmp_path, flight=True, water_success=False)
    settle(t, mid, rows(c, mid, COURT)[0].candidate_id)
    settle(t, mid, rows(c, mid, SEAL, TARGET)[0].candidate_id)
    turn(t, mid, TARGET)
    engine = cold(tmp_path, mid)
    assert any(r.data.get('abyssal_pressure_seal') for r in engine.state.actors[TARGET].conditions.values()), \
        'the seal is in force'
    target = engine.state.actors[TARGET]
    ctx = states.context(engine, target, 'tianxia.subpath.qi.cloud_walker.feature.cloud_step', [target], {'pb': 6})
    before = len(_water_checks(engine))
    typed_executor.run_effects(ctx, [dict(FLIGHT)])
    checks = _water_checks(engine)[before:]
    assert checks and not checks[-1].payload.get('success'), [v.payload for v in _water_checks(engine)]
    assert not [i for i, held in engine.state.actors[TARGET].conditions.items()
                if held.condition_id == FLIGHT_CONDITION], 'a failed Water check grants no flight'
