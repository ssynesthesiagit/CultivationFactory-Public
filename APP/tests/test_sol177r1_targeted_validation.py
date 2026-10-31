"""Fresh targeted/native differential checks; no browsers or live-data writes.

The retained lane driver imports assert_equivalent for every stock/historical
execution and each HUNT121 pre-state. Synthetic perturbations cover writes that
do not advance any engine version, the unsafe-reuse cases exposed by SOL177.
"""
from copy import deepcopy
import os
import random
import subprocess
import sys
from pathlib import Path

import pytest

from combat.canonical import canonical_bytes
from combat.diagnostics import CombatGate1Error
from combat.gate2_runtime_models import ActionIntent, Position
from tests.h1_support import ME, duel
from tests.test_tabletop_speed import ROOT, _fight, _to_the_humans_turn
from combat.gate5_service import CombatService


def intent_for(candidate):
    return ActionIntent(intent_id='sol177r1:differential', decision_id=candidate.decision_id,
                        candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                        actor_id=candidate.actor_id, target_ids=candidate.target_ids,
                        destination=candidate.destination)


def assert_equivalent(engine, intent, full=None, *, sample=True):
    """Compare exact candidate objects, not just membership or candidate IDs."""
    # Explicit commands have their own native generators, unchanged by this lane.
    if intent.relation_change is not None:
        from combat.relations import command_candidate
        native = command_candidate(engine, intent.relation_change)
        assert engine.candidates_for_intent(intent) == (native,)
        return 1
    if intent.movement_path is not None:
        from combat.movement_routes import explicit_candidate
        native = explicit_candidate(engine, intent.actor_id, intent.movement_path, intent.movement_mode or 'walk')
        assert engine.candidates_for_intent(intent) == (native,)
        return 1
    full = engine._generate_legal_candidates() if full is None else full
    expected = {c.candidate_id: c for c in full}
    intents = [intent]
    if sample and full:
        # Deterministic spread includes actions that were not chosen, and moves.
        picks = sorted({0, len(full)//3, 2*len(full)//3, len(full)-1})
        intents.extend(intent_for(full[n]) for n in picks)
        intents.extend([intent.model_copy(update={'candidate_id': 'candidate:illegal'}),
                        intent.model_copy(update={'target_ids': ('actor:missing',)}),
                        intent.model_copy(update={'destination': Position(x=999, y=999)}),
                        intent.model_copy(update={'option_ids': ('illegal-option',)})])
    for proposed in intents:
        native = expected.get(proposed.candidate_id)
        result = engine.candidates_for_intent(proposed)
        wanted = [] if native is None else [native.model_dump(mode='json')]
        actual = [c.model_dump(mode='json') for c in result]
        assert canonical_bytes(actual) == canonical_bytes(wanted), (proposed.model_dump(), wanted, actual)
    return len(intents)


def assert_perturbed(engine, intent, seed):
    """Five valid unversioned mutations of a real historical/HUNT pre-state."""
    rng = random.Random(seed)
    checked = 0
    for mode in ('movement', 'economy', 'resources', 'flags', 'mixed'):
        changed = deepcopy(engine)
        actor = changed.state.actors[changed.state.current_actor_id]
        if mode in ('movement', 'mixed'):
            actor.movement_remaining_ft = 0
        if mode in ('economy', 'mixed'):
            actor.action_available = not actor.action_available
            actor.bonus_action_available = not actor.bonus_action_available
        if mode in ('resources', 'mixed'):
            for resource in actor.resources:
                actor.resources[resource] = rng.choice([0, actor.resources[resource]])
        if mode in ('flags', 'mixed'):
            for key, value in actor.turn_flags.items():
                if type(value) in (int, bool):
                    actor.turn_flags[key] = 0 if value else 1
            actor.turn_flags['sol177_probe'] = 1
        checked += assert_equivalent(changed, intent, sample=False)
    return checked


def test_targeted_validation_matches_every_synthetic_candidate():
    engine = duel([])
    full = engine._generate_legal_candidates()
    assert full
    for candidate in full:
        assert_equivalent(engine, intent_for(candidate), full, sample=False)


def test_targeted_validation_ignores_issued_objects_after_nested_mutations():
    engine = duel([])
    full = engine._generate_legal_candidates()
    move = next(c for c in full if c.kind.value == 'MOVE')
    with engine._reuse_legal_candidates(full):
        engine.state.actors[engine.state.current_actor_id].movement_remaining_ft = 0
        assert_equivalent(engine, intent_for(move))
        assert not engine.candidates_for_intent(intent_for(move))
        with pytest.raises(CombatGate1Error, match='not legal'):
            engine.execute_intent(intent_for(move))


def test_recorded_route_is_used_only_for_its_exact_candidate(monkeypatch):
    engine = duel([])
    full = engine.legal_candidates()
    moves = [c for c in full if c.kind.value == 'MOVE' and c.destination.z == 0]
    recorded, other = moves[:2]
    engine.bind_recorded_move(intent_for(recorded), recorded.model_dump(mode='json'))
    original = engine.candidates_for_intent
    def checked(intent):
        assert engine._recorded_route_candidate is None
        return original(intent)
    monkeypatch.setattr(engine, 'candidates_for_intent', checked)
    engine.execute_intent(intent_for(other))
    assert engine.state.actors[other.actor_id].position == other.destination


def test_randomized_unversioned_perturbations():
    rng = random.Random(1771)
    template = duel([])
    old = template._generate_legal_candidates()
    for _ in range(32):
        engine = deepcopy(template)
        actor = engine.state.actors[engine.state.current_actor_id]
        actor.movement_remaining_ft = rng.choice([0, 5, 10, 30])
        actor.action_available = rng.choice([True, False])
        actor.bonus_action_available = rng.choice([True, False])
        for resource in actor.resources:
            actor.resources[resource] = rng.choice([0, actor.resources[resource]])
        actor.turn_flags.update({key: rng.choice([0, 1]) for key in actor.turn_flags})
        actor.turn_flags['sol177_probe'] = rng.randrange(2)
        actor.position = Position(x=rng.randrange(2, 8), y=rng.randrange(2, 8))
        assert_equivalent(engine, intent_for(rng.choice(old)))


def test_targeted_table_commit_reload_uses_fresh_generation(tmp_path):
    combat, table, mid = _fight(tmp_path, seed='SOL177R1-TABLE')
    state, _ = _to_the_humans_turn(table, mid)
    menu = state['menu']
    result = table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'], state['last_sequence'], [])
    assert result['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


def test_targeted_query_does_not_build_unrelated_area_metadata(monkeypatch):
    engine = duel([])
    chosen = next(c for c in engine.legal_candidates() if c.kind.value == 'END_TURN')
    def forbidden(*args, **kwargs):
        raise AssertionError('unrelated action generation during End Turn')
    monkeypatch.setattr(engine, '_action_candidates_impl', forbidden)
    assert engine.candidates_for_intent(intent_for(chosen)) == (chosen,)


@pytest.mark.skipif(not os.environ.get('SOL177R1_EVIDENCE_DRIVER'),
                    reason='opt-in owner historical/HUNT inputs, isolated disk copies only')
@pytest.mark.parametrize('kind', ['hunt', 'replays'])
def test_stock_historical_and_180_step_differential(kind):
    driver = Path(os.environ['SOL177R1_EVIDENCE_DRIVER'])
    subprocess.run([sys.executable, str(driver), kind, 'head'], check=True,
                   env={**os.environ, 'SOL177R1_DIFFERENTIAL': '1'})
