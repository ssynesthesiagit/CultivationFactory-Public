"""Flight uses ordinary move intents, reach, shared payment and persistence."""
from combat import flight
from combat.gate2_runtime_models import ActionIntent, Position, ReactionDecision
from combat.gate5_service import CombatService
from tests.h1_support import ROOT, ME, FOE, duel
from tests.test_tabletop_hunt6 import table_fight, on_hold, HOLD, LEFT
from tests.test_lock2_persistence import act


def grant(engine, actor, speed=30, **data):
    engine._apply_condition(actor, "condition:typed.test_flight", "test:flight", actor.entity_id,
                            expires_on="END_OF_CURRENT_TURN", data={"fly_speed_ft": speed, **data})


def request(candidate):
    return ActionIntent(intent_id="test:flight", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
        state_version=candidate.state_version, actor_id=candidate.actor_id, destination=candidate.destination)


def test_fly_up_spends_movement_and_leaving_reach_upward_opens_opportunity():
    e = duel([])
    actor = e.state.actors[ME]
    grant(e, actor)
    before = actor.movement_remaining_ft
    seen = []
    def provider(row):
        seen.append(row)
        return ReactionDecision(checkpoint=row["checkpoint"], reactor_id=row["reactor_id"],
            reaction_source_id=row["reaction_source_id"], selection="DECLINE"), None
    e.set_reaction_provider(provider)
    destination = actor.position.model_copy(update={"z": 2})
    candidate = next(c for c in e.legal_candidates() if c.kind == "MOVE" and c.destination == destination)
    e.execute_intent(request(candidate))
    actor = e.state.actors[ME]
    assert actor.position == destination and actor.movement_remaining_ft == before - 10
    assert any(row["reactor_id"] == FOE for row in seen)
    assert e._distance_actor_to_actor(actor, e.state.actors[FOE]) == 10


def test_zero_speed_and_grounding_prohibit_vertical_candidates():
    e = duel([])
    actor = e.state.actors[ME]
    grant(e, actor, cannot_gain_altitude=1)
    assert all(c.destination.z == 0 for c in e.legal_candidates() if c.kind == "MOVE")
    e._apply_condition(actor, "condition:typed.grappled", "test:pin", FOE, expires_on=None)
    assert not any(c.kind == "MOVE" for c in e.legal_candidates())


def test_fly_speed_and_walking_share_spent_distance_without_extra_walk_speed():
    e = duel([])
    actor = e.state.actors[ME]
    grant(e, actor, 60)
    walking = actor.movement_remaining_ft
    assert flight.remaining(e, actor, "fly") == 60
    flight.spend(actor, 40)
    assert flight.remaining(e, actor, "fly") == 20
    assert flight.remaining(e, actor, "walk") == max(0, walking - 40)
    actor.movement_remaining_ft += e._effective_speed(actor)
    flight.dash(e, actor)
    assert flight.remaining(e, actor, "fly") == 80
    assert flight.remaining(e, actor, "walk") == max(0, 2 * walking - 40)


def test_slow_flight_uses_only_its_own_speed():
    e = duel([])
    actor = e.state.actors[ME]
    grant(e, actor, 10)
    assert flight.remaining(e, actor, "fly") == 10
    routes = flight.reachable(e, actor)
    assert any(mode == "walk" and cost > 10 for _, cost, mode in routes.values())
    assert all(cost <= 10 for _, cost, mode in routes.values() if mode == "fly")
    flight.spend(actor, 10)
    assert flight.remaining(e, actor, "fly") == 0
    assert flight.remaining(e, actor, "walk") == e._effective_speed(actor) - 10
    assert flight.reachable(e, actor)  # exhausting Fly Speed does not erase unused walking movement


def test_reachable_keeps_volumes_separate_above_another_creature():
    e = duel([])
    actor, target = e.state.actors[ME], e.state.actors[FOE]
    grant(e, actor)
    route = flight.reachable(e, actor)
    above = target.position.model_copy(update={"z": 2})
    assert above in route and target.position not in route
    path, _, mode = route[above]
    assert mode == "fly"
    assert all(e.grid.volume_step_legal(a, b, footprint=e._footprint(actor),
        occupied_cells=e._occupied_volumes_except(ME)) for a, b in zip(path, path[1:]))


def test_spatial_routes_quote_drag_cost_for_both_walk_and_fly(monkeypatch):
    e = duel([])
    actor = e.state.actors[ME]
    grant(e, actor)
    monkeypatch.setattr(e, '_drag_multiplier', lambda subject: 2)
    for path, cost, mode in flight.reachable(e, actor).values():
        assert cost == sum(flight.step_cost(e, actor, a, b, mode, e._hostile_difficult_cells(actor))
                           for a,b in zip(path,path[1:]))
        assert cost <= flight.remaining(e, actor, mode)


def test_table_flight_altitude_and_allowance_survive_reload(monkeypatch, tmp_path):
    combat, table, mid = table_fight(tmp_path, [])
    def prepare(engine):
        grant(engine, engine.state.actors[LEFT], flight_hover=1)
        for actor in engine.state.actors.values():
            if actor.entity_id != LEFT:
                actor.reaction_available = False
                engine._append_event("REACTION_RESOLVED", "test:no_reaction", actor_id=actor.entity_id)
    on_hold(monkeypatch, prepare)
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    e = combat._load_session(mid).engine
    actor = e.state.actors[LEFT]
    before = actor.movement_remaining_ft
    destination = actor.position.model_copy(update={"z": 2})
    c = next(c for c in e.legal_candidates() if c.kind == "MOVE" and c.destination == destination)
    assert table.act(mid, c.candidate_id, c.decision_id, c.state_version, table.state(mid)["last_sequence"])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[LEFT]
    assert actor.position == destination and actor.movement_remaining_ft == before - 10
    token = next(row for row in table.state(mid)["presentation"]["actors"] if row["entity_id"] == LEFT)
    assert token["altitude_ft"] == 10 and token["fly_speed_ft"] == 30
    assert token["hover"] is True
    assert token["flying_movement_remaining_ft"] == 20
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"
