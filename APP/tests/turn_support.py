"""Turn helper shared by effect-duration and Wax combat tests."""


def end_turn(engine):
    engine.end_turn()
    return engine.state.current_actor_id
