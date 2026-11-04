"""Shared turn-advance helper for wax and effect-duration tests."""


def end_turn(engine):
    engine.end_turn()
    return engine.state.current_actor_id
