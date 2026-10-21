"""Compiler and final-roll contracts exposed by the F7 integrated review."""
from pathlib import Path

import pytest

from combat import ext, typed_executor as te, typed_reactions
from combat.ext import athletics_grip_lungs
from combat import roof_movement as climbing
from tests.h1_support import duel, ME, FOE, script
from tests.test_lock_choices import install

# Dynamic runtime inputs must accompany this file in a public test export.
ATHLETICS_BLOCK = Path('combat/rules/feature_blocks.d/athletics-second-pass.json')


@pytest.mark.parametrize('owned', [True, False])
def test_canonical_grip_row_drives_climbing_and_holds_together(owned):
    engine = duel(['TAL_ATHLETICS_SURE_GRIP'] if owned else [])
    actor = engine.state.actors[ME]
    rows = [r for r in engine.typed_passive_rows[ME]
            if r.get('feature_id') == 'TAL_ATHLETICS_SURE_GRIP']
    assert len(rows) == int(owned)
    assert bool(athletics_grip_lungs.maintain_grip(engine, actor)) is owned
    assert ('ADVANTAGE' in climbing.profile(engine, actor).check_modes) is owned


@pytest.mark.parametrize('outcome', ['success', 'failure'])
def test_declared_save_reaches_all_notifications_and_is_consumed_once(monkeypatch, outcome):
    engine = duel([])
    actor, target = engine.state.actors[ME], engine.state.actors[FOE]
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME)
    ctx = te.Context(engine, actor, action, None, {}, [target], target)
    seen = []
    markers = []
    monkeypatch.setattr(typed_reactions, 'after_d20',
                        lambda *a, **kw: seen.append(('d20', not kw['success'])))
    monkeypatch.setattr(typed_reactions, 'on_creature_event',
                        lambda e, s, name: seen.append(('event', name == 'creature_save_failed')))
    def after_save(c, s, a, n, failed):
        seen.append(('save', failed))
        markers.append(c.engine._typed_roll_outcome.get(s.entity_id))
    install(monkeypatch, 'after_save', after_save)
    engine._typed_roll_outcome = {FOE: outcome}
    expected = outcome == 'failure'
    assert te.settle_typed_save(ctx, target, 'CHA', None, not expected, set(), set(), 0) is expected
    assert seen == [('d20', expected), ('event', expected), ('save', expected)]
    assert markers == [outcome]  # Later reactions must see that the outcome was already declared.
    assert FOE not in engine._typed_roll_outcome
    seen.clear()
    assert te.settle_typed_save(ctx, target, 'CHA', None, not expected, set(), set(), 0) is not expected


@pytest.mark.parametrize('hazards, expected', [(['poisoned'], True), ([], False)])
def test_opposed_check_transports_its_own_pressure_to_native_roll_hooks(monkeypatch, hazards, expected):
    engine = duel([])
    actor, target = engine.state.actors[ME], engine.state.actors[FOE]
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME)
    ctx = te.Context(engine, actor, action, None, {}, [target], target)
    seen = []
    def observe(e, roll, intent):
        context = e.d20_context(roll)
        if context and context.get('kind') == 'check':
            seen.append('poisoned' in context['named'])
    install(monkeypatch, 'd20_bonus', observe)
    script(engine, [10])
    te.resolve_opposed_check(ctx, target,
        {'kind': 'check', 'ability': 'STR', 'hazards': hazards}, {'kind': 'dc', 'dc': 12})
    assert seen and all(value is expected for value in seen)
