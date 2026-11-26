"""Crown of Black Thorns answers at the step that meets it, and a failed save ends the move in that space (combat/ext/step_reactions.py)."""
from tests.test_riders_c7 import FOE, ME, SPINE, THORN, _typed_foe, answers, bundle, fight, turn, use


def _crown(spines=2, foe_at=(4, 9), *, briar=False):
    features = [THORN + "crown_of_black_thorns"] + ([THORN + "calamity_briar_incarnation"] if briar else [])
    engine = fight(bundle(features), foe=_typed_foe(), foe_at=foe_at)
    engine._gain_resource(engine.state.actors[ME], SPINE, spines, "test")
    answers(engine)
    if briar:
        use(engine, "Calamity Briar Incarnation")
    turn(engine, FOE)
    return engine, engine.state.actors[ME], engine.state.actors[FOE]


def test_a_failed_save_ends_the_move_in_the_space_where_the_foe_entered_reach():
    engine, me, foe = _crown()
    use(engine, "Move to 4,5", actor_id=FOE)
    # (4,5) is two squares inside the reach; the move ended in the first square of it
    assert engine.grid.distance_ft(foe.position, me.position) == 5 and (foe.position.x, foe.position.y) != (4, 5)
    assert me.resources[SPINE] == 1


def test_the_trigger_is_answered_once_not_again_after_the_move():
    engine, me, foe = _crown()
    use(engine, "Move to 4,5", actor_id=FOE)
    assert me.resources[SPINE] == 1  # one Spine, though the move also ends within reach


def test_without_a_spine_the_move_is_not_stopped():
    engine, me, foe = _crown(spines=0)
    use(engine, "Move to 4,5", actor_id=FOE)
    assert (foe.position.x, foe.position.y) == (4, 5)


def test_bleeding_applied_mid_move_does_not_count_the_feet_already_walked():
    engine, me, foe = _crown(foe_at=(9, 6))
    use(engine, "Move to 4,6", actor_id=FOE)
    bleeding = [c for c in foe.conditions.values() if c.condition_id == "condition:typed.bleeding"]
    assert bleeding and bleeding[0].data["thorn_bleeding"]["moved_ft"] == 0


def test_crown_uses_the_active_unarmed_reach_for_the_stop_space():
    engine, me, foe = _crown(foe_at=(9, 6), briar=True)
    spines = me.resources[SPINE]  # Calamity Briar Incarnation fills the Spines to their transformed maximum
    use(engine, "Move to 4,5", actor_id=FOE)
    assert engine.grid.distance_ft(foe.position, me.position) == 15
    assert me.resources[SPINE] == spines - 1


def test_crown_accumulates_ten_feet_across_separate_moves_within_reach():
    # Both moves are inside the owner's unarmed reach: (4,5), (4,6) and (4,7) are all within 5 feet of the owner at (3,6).
    engine, me, foe = _crown(foe_at=(4, 5))
    use(engine, "Move to 4,6", actor_id=FOE)
    assert me.resources[SPINE] == 2  # five feet walked inside the reach: the threshold is not met yet
    use(engine, "Move to 4,7", actor_id=FOE)
    assert me.resources[SPINE] == 1  # ten feet walked inside the reach: the trigger answers here


def test_crown_answers_on_the_step_of_one_move_that_completes_ten_feet_inside_reach():
    # One route, two steps inside the reach: the trigger answers on the second step, where the tenth foot is walked.
    engine, me, foe = _crown(foe_at=(4, 5))
    use(engine, "Move to 4,7", actor_id=FOE)
    assert me.resources[SPINE] == 1
