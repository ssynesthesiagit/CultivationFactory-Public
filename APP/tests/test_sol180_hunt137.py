"""Opt-in read-only replay of owner-supplied HUNT137 evidence (no GUI).

No private fight fixture is shipped. Set SOL180_HUNT137_COPY to the supplied
copied fight directory to run the exact counterfactual.
"""
import json
import os
from pathlib import Path

import pytest

from combat import area_safety, senses, target_knowledge, zones
from combat.area_knowledge import STAMP, ORIGIN_AUTHORITY, bind_origin_permissions
from combat.gate2_runtime_models import MatchState, CombatEvent, RollRecord, Position
from combat.gate3_reducer import Gate3EventReducer, canonical_state_sha256
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate4_context import build_decision_context
from combat.gate4_controller import LocalDeterministicController
from combat.gate4_policy import PolicyLibrary
from tests.h1_support import ROOT


@pytest.mark.skipif(not os.environ.get('SOL180_HUNT137_COPY'), reason='owner evidence copy is opt-in')
def test_hunt137_counterfactual_candidate_metadata_and_scores_are_identical():
    folder = Path(os.environ['SOL180_HUNT137_COPY'])
    genesis = json.loads((folder / 'GenesisState.json').read_text())
    state = MatchState.model_validate(genesis['state'])
    events, rolls = list(genesis['initial_events']), list(genesis['initial_rolls'])
    checks = 0
    for row in map(json.loads, (folder / 'Journal.ndjson').read_text().splitlines()):
        if row['record_type'] == 'PREPARE':
            if row['pre_state_version'] == 61:
                break
        else:
            state = Gate3EventReducer().apply_events(state, row['events'])
            state.state_version = row['post_state_version']
            state.roll_counter = row['roll_counter_end']
            assert canonical_state_sha256(state) == row['post_state_sha256']
            checks += 1
            events.extend(row['events'])
            rolls.extend(row['rolls'])
    assert checks and state.state_version == 61
    engine = Gate4ControllerEngine(ROOT, match_seed=state.match_seed,
        typed_bundles=tuple(json.loads((folder / 'Typed_Character_Bundles.json').read_text())),
        battlefield=json.loads((folder / 'Arena_Battlefield.json').read_text()),
        roster_setup={'actor_ids': list(genesis['state']['actors'])})
    engine.state = state
    engine.events = [CombatEvent.model_validate(row) for row in events]
    engine.rolls = [RollRecord.model_validate(row) for row in rolls]
    engine.roller.counter = state.roll_counter
    zones.sync_walls(engine)
    actor = state.actors[state.current_actor_id]
    target = next(a for a in state.actors.values() if a.position == Position(x=14, y=14))
    action = next(a for a in engine.action_catalog.values()
                  if a.owner_id == actor.entity_id and a.parameters.get('typed', {}).get('source') == 'FIRE_TAL_FIREBALL_ART')
    at = Position(x=15, y=11)
    assert not senses.perceives_cell(engine, actor, at)
    assert target_knowledge.knowledge(engine, actor, target) is None
    # Apply the new-fight rule to a counterfactual in-memory engine only.
    next(e for e in engine.events if e.event_type == 'MATCH_CREATED').payload[STAMP] = 1
    next(e for e in engine.events if e.event_type == 'MATCH_CREATED').payload[ORIGIN_AUTHORITY] = bind_origin_permissions(ROOT)
    policy = PolicyLibrary(ROOT).fallback()
    controller = LocalDeterministicController()

    def signature():
        context = build_decision_context(engine, policy, for_ai=True)
        candidates = [c for c in context.legal_candidates if c.source_definition_id == action.source_definition_id]
        assert all(senses.perceives_cell(engine, actor, c.destination) for c in candidates)
        return [(c.model_dump(mode='json'), controller._score_candidate(context, c, ()).model_dump(mode='json'))
                for c in candidates]

    before = signature()
    preview = area_safety.preview(engine, actor, action, at)
    target.position = Position(x=6, y=13)
    assert target_knowledge.knowledge(engine, actor, target) is None
    assert signature() == before
    assert area_safety.preview(engine, actor, action, at) == preview
