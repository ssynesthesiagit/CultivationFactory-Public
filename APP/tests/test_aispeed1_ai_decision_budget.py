"""Owner 2026-10-20 speed regression: whole moves, not one-square shuffles.

A flier shuffled one square per decision because search picked the nearest
unvisited frontier after reaching the map centre. The flier now commits the
whole move; ground search keeps main's choice because the saved AI replays pin
it. These tests use synthetic sheets but the native combat runtime.
"""
from combat import ai_search
from combat.gate2_runtime_models import Position
from tests.ai_tiers_native_support import fight, context_for, selected, OWNER, FOE
from tests.test_hidden_targeting import LEFT, RIGHT
from tests.test_sol175_search import context as search_context, yard


def _remembered_search(tmp_path, *, viewer_at, memory_at, foe_at, large=False, spent=True):
    """A yard search against a remembered hostile at ``memory_at``.

    The real hostile is parked where this viewer has no sight line, so search
    runs on the remembered copy alone, driven by ``sightings`` (the caller
    shaped input ``search_move`` documents). Rows, policy and projection are
    exactly what ``build_decision_context`` would hand it (see
    test_sol175_search's direct ``search_move`` regressions).
    """
    combat, _, mid = yard(tmp_path)
    engine = combat._load_session(mid).engine
    viewer = engine.state.actors[LEFT]
    engine.state.actors[RIGHT].position = Position(x=foe_at[0], y=foe_at[1])
    if large:
        engine.state.actors[RIGHT].transformed_size_category = 'Large'
    viewer.position = Position(x=viewer_at[0], y=viewer_at[1])
    viewer.movement_remaining_ft = viewer.speed_ft
    if spent:
        viewer.action_available = viewer.bonus_action_available = False
    decision = search_context(engine)
    known = [engine.state.actors[RIGHT].model_copy(
        update={'position': Position(x=memory_at[0], y=memory_at[1])})]
    sightings = {RIGHT: ((memory_at[0], memory_at[1]), engine.events[-1].sequence)}
    return engine, viewer, decision, known, sightings


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
    assert next_candidate.kind == "END_TURN", "already in range: do not shuffle"


def test_search_is_not_offered_while_a_known_hostile_is_in_contact(tmp_path):
    """Walking is not how a mover searches for a creature already beside it.

    The pillar corner at 9,6 clips the sight ray from 8,6 to 9,5, so the foe is
    remembered rather than located while standing 5 ft away. Search must not
    spend the mover's last step pacing there; the turn ends instead.
    """
    combat, _, session = fight(tmp_path, melee=True, seed="AISPEED1")
    engine = session.engine
    actor = engine.state.actors[OWNER]
    actor.action_available = actor.bonus_action_available = False
    choice, candidate = selected(context_for(combat, session))
    engine.execute_intent(choice.intent)
    assert engine._distance_actor_to_actor(actor, engine.state.actors[FOE]) <= 5
    assert context_for(combat, session).search_move_candidate_id is None


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


def test_spent_contact_search_fallback_must_not_pace(tmp_path):
    """The contact guard also holds on search's restart and obstruction fallbacks.

    The caller offers only rows that cannot advance toward the remembered
    hostile at (3, 6), so the planner answers from its fallback; a spent mover
    in 5 ft contact must get no pacing step out of it (MAINREDTRICKY1 review:
    the fallback returns used to bypass the guard). With actions left, the
    same answer stays a normal search step.
    """
    engine, viewer, decision, known, sightings = _remembered_search(
        tmp_path, viewer_at=(2, 5), memory_at=(3, 6), foe_at=(22, 5))
    westward = tuple(row for row in decision.legal_candidates if row.kind == 'MOVE'
                     and row.destination.x < viewer.position.x)
    assert westward, "fixture: westward steps must exist"
    assert engine._distance_actor_to_actor(viewer, known[0]) <= 5
    result = ai_search.search_move(engine, viewer, westward, decision.policy,
                                   known, (), sightings=sightings)
    assert result is None, "a spent turn in contact must not take a pacing fallback step"
    viewer.action_available = viewer.bonus_action_available = True
    assert ai_search.search_move(engine, viewer, westward, decision.policy,
                                 known, (), sightings=sightings)


def test_contact_guard_measures_the_body_not_the_anchor_cell(tmp_path):
    """Contact uses the planner's footprint-aware distance, not the anchor cell.

    A Large hostile remembered anchored at (15, 11) fills (15..16, 11..12); the
    mover at (17, 10) is 5 ft from its northeast corner but 10 ft from the
    remembered anchor. The anchor metric misses that contact and lets the
    non-closing step to (16, 10) through; the planner's distance must not
    (MAINREDTRICKY1 review: point-to-point distance_ft ignores the footprint).
    """
    engine, viewer, decision, known, sightings = _remembered_search(
        tmp_path, viewer_at=(17, 10), memory_at=(15, 11), foe_at=(2, 0), large=True)
    assert engine._distance_actor_to_actor(viewer, known[0]) <= 5
    assert engine.grid.distance_ft(viewer.position, known[0].position) > 5
    body_cells = {(15, 11), (16, 11), (15, 12), (16, 12)}
    away = tuple(row for row in decision.legal_candidates if row.kind == 'MOVE'
                 and (row.destination.x, row.destination.y) not in body_cells)
    assert away, "fixture: steps off the remembered body must exist"
    result = ai_search.search_move(engine, viewer, away, decision.policy,
                                   known, (), sightings=sightings)
    assert result is None, "footprint contact must block the non-closing search step"
    far_known = [known[0].model_copy(update={'position': Position(x=20, y=3)})]
    far_sightings = {RIGHT: ((20, 3), engine.events[-1].sequence)}
    assert ai_search.search_move(engine, viewer, away, decision.policy,
                                 far_known, (), sightings=far_sightings)
