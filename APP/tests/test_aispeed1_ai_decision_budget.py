"""Owner 2026-10-20 speed regression: whole moves, not one-square shuffles.

A flier shuffled one square per decision because search picked the nearest
unvisited frontier after reaching the map centre. The flier now commits the
whole move; ground search keeps main's choice because the saved AI replays pin
it. These tests use synthetic sheets but the native combat runtime, so the CI
route treats the file as LOCAL (the runtime authority bundle is not in the
public export).
"""
from combat.gate2_runtime_models import Position
from tests.ai_tiers_native_support import fight, context_for, selected, OWNER, FOE
from tests.test_hidden_targeting import LEFT, RIGHT
from tests.test_sol175_search import context as search_context, yard


def test_flier_closes_to_attack_range_in_one_decision(tmp_path):
    combat, _, session = fight(tmp_path, flight=True, melee=True, seed="AISPEED1")
    actor = session.engine.state.actors[OWNER]
    actor.action_available = actor.bonus_action_available = False
    choice, candidate = selected(context_for(combat, session))
    assert candidate.kind == "MOVE"
    assert candidate.movement_cost_ft >= 25, "one decision must commit the whole move"
    assert session.engine._distance_actor_to_actor(
        actor, session.engine.state.actors[FOE], actor_position=candidate.destination) <= 5
    session.engine.execute_intent(choice.intent)
    _, next_candidate = selected(context_for(combat, session))
    # Once in range the flier may hold or reposition within its last 5 ft, but
    # must not leave range; the owner's complaint was the long one-square walk.
    assert next_candidate.movement_cost_ft <= 5, "only the remaining 5 ft is left to spend"
    where = next_candidate.destination or actor.position
    assert session.engine._distance_actor_to_actor(
        actor, session.engine.state.actors[FOE], actor_position=where) <= 5, "already in range: do not leave it"


def _search_from_the_centre(tmp_path, *, flying):
    combat, _, mid = yard(tmp_path)
    engine = combat._load_session(mid).engine
    viewer = engine.state.actors[LEFT]
    if flying:
        viewer.fly_speed_ft = 30
    # Keep the foe behind the yard's wall: search only runs with no located enemy.
    engine.state.actors[RIGHT].position = Position(x=2, y=0)
    centre = Position(x=engine.grid.width // 2, y=engine.grid.height // 2)
    before = centre.model_copy(update={"x": centre.x - 1})
    viewer.position = centre
    viewer.movement_remaining_ft = viewer.speed_ft
    sequence = engine.events[-1].sequence + 1
    engine.events.append(engine.events[-1].model_copy(update={
        "event_type": "MOVEMENT_COMMITTED", "actor_id": LEFT,
        "source_definition_id": "system:combat.movement", "sequence": sequence,
        "payload": {"path": [before.model_dump(mode="json"), centre.model_dump(mode="json")],
                    "destination": centre.model_dump(mode="json")}}))
    decision = search_context(engine)
    assert decision.search_move_candidate_id is not None
    return viewer, next(row for row in decision.legal_candidates
                        if row.candidate_id == decision.search_move_candidate_id)


def test_flier_search_after_reaching_the_centre_commits_a_whole_move(tmp_path):
    viewer, chosen = _search_from_the_centre(tmp_path, flying=True)
    assert chosen.movement_cost_ft > 5, "search must advance a whole move, not one square"
    assert chosen.movement_cost_ft >= viewer.speed_ft - 5


def test_ground_search_after_reaching_the_centre_keeps_the_stock_choice(tmp_path):
    # The saved AI replays pin ground search decision for decision; only the
    # flier path may commit a farther move.
    _, chosen = _search_from_the_centre(tmp_path, flying=False)
    assert chosen.movement_cost_ft == 5, "ground search must keep main's nearest-frontier choice"
