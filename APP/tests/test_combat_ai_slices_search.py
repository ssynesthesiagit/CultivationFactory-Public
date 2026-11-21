"""Personal search stays consistent with committed sightings, without transports."""
import pytest

from combat.gate2_runtime_models import Position
from combat.gate4_context import build_decision_context
from combat.gate5_service import CombatService
from combat.target_knowledge import located
from tests.test_combat_ai_slices import offline
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import table_fight, on_hold, LEFT, ALLY, RIGHT, HOLD, ROOT


@pytest.mark.parametrize('prepared', [False, True], ids=['direct', 'prepared-service'])
def test_teammate_sighting_cannot_redirect_personal_search(tmp_path, monkeypatch, prepared):
    monkeypatch.setenv('CF_COMBAT_AI_SLICES_1_2', '1')
    old, new = Position(x=7, y=4), Position(x=10, y=1)
    combat, table, mid = table_fight(tmp_path, [], ally_talents=[],
        starts={'team1': [[1, 4], [1, 5]], 'team2': [[old.x, old.y]]})

    def teammate_only_move(engine):
        # Synthetic committed setup: Left loses sight; Ally still observes Right.
        # Normal transaction receipts/persistence record both knowledge scopes.
        viewer, target = engine.state.actors[LEFT], engine.state.actors[RIGHT]
        engine._apply_condition(viewer, 'condition:typed.blinded', 'test:blind',
            RIGHT, expires_on='UNTIL_REMOVED')
        target.position = new
        engine._append_event('MOVEMENT_COMMITTED', 'test:teammate-sighting', actor_id=RIGHT,
            payload={'destination': new.model_dump(mode='json'),
                     'path': [new.model_dump(mode='json')], 'cost_ft': 15})

    on_hold(monkeypatch, teammate_only_move)
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'

    def read(service):
        session = service._load_session(mid)
        engine = session.engine
        assert not located(engine, engine.state.actors[LEFT], engine.state.actors[RIGHT])
        assert located(engine, engine.state.actors[ALLY], engine.state.actors[RIGHT])
        assert engine.state.observations[engine.state.actors[LEFT].team_id][RIGHT] == new
        policy, _ = service.policies.for_actor(LEFT)
        ctx = (service.ai_decision_context(session) if prepared else
               build_decision_context(engine, policy, for_ai=True))
        remembered = next(a for a in ctx.own_knowledge.creatures if a.entity_id == RIGHT)
        assert remembered.mode == 'LAST_OBSERVED'
        assert remembered.position == (old.x, old.y, old.z)
        ally_receipt = next(e.payload['personal_observations'][ALLY] for e in reversed(engine.events)
                            if 'personal_observations' in e.payload)
        assert ally_receipt['creatures'][RIGHT]['position'] == [new.x, new.y, new.z]
        row = next(c for c in ctx.legal_candidates if c.candidate_id == ctx.search_move_candidate_id)
        assert row.destination == old, 'Search must investigate its own last sighting, not team evidence'
        assert service.controller.choose_primary_action(ctx).intent.candidate_id == row.candidate_id
        return ctx

    before = read(combat)
    fresh = CombatService(ROOT, tmp_path)
    after = read(fresh)
    assert before.own_knowledge == after.own_knowledge
    assert before.search_move_candidate_id == after.search_move_candidate_id
    state = table.state(mid)
    assert table.act(mid, after.search_move_candidate_id, after.decision_id,
                     after.state_version, state['last_sequence'])['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[LEFT].position == old
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
