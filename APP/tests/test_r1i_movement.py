from tests.test_riders_lane1 import _claw_engine, _rider_use, _answers, _rider_strike, CLAW, ME, AN


def test_black_claw_off_turn_move_uses_owners_start_and_budget():
    engine = _claw_engine()
    _rider_use(engine, CLAW)
    owner = engine.state.actors[ME]
    enemy = engine.state.actors[AN]
    start, budget, enemy_start = owner.position, owner.movement_remaining_ft, enemy.position
    engine.state.current_actor_id = AN
    engine.state.current_slot_index = engine.state.initiative_order.index(AN)
    seen = _answers(engine, {"black_claw": ["move"], "black_claw_step": ["cell:2,6"]})
    events = _rider_strike(engine, ME, AN)
    assert owner.position.x == 2 and owner.position.y == 6
    assert enemy.position == enemy_start
    assert owner.movement_remaining_ft == budget
    movement = next(e for e in events if e.event_type == "MOVEMENT_COMMITTED")
    assert movement.actor_id == ME
    assert movement.payload["path"][0] == start.model_dump(mode="json")
    prompt = next(r for r in seen if r["reaction_source_id"].endswith("black_claw_step"))
    context = prompt["choice_trigger"]
    assert "Black-Claw Manifestation" in context["prompt"]
    assert enemy.display_name in context["prompt"] and owner.display_name in context["prompt"]
    assert "Move to (2, 6), 5 feet" == context["labels"]["cell:2,6"]
