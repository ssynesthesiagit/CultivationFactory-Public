"""Merge regressions: pauses restore deterministic history, including on previews."""
import pytest

from combat.ext import ControllerPause, mounts
from combat.gate5_service import CombatService, _ReactionRequired
from tests.test_mounts import ME, actors, fight, rider_bundle


@pytest.mark.parametrize("pause", [ControllerPause("choose"), _ReactionRequired(None, None), ValueError("bad effect")])
def test_transaction_unwinds_state_events_rolls_and_rethrows_the_same_exception(pause):
    engine = fight(rider_bundle())
    rider, _, _ = actors(engine)
    rider.resources[mounts.FOCUS] = 1
    before = engine.state.model_dump(mode="json")
    events, rolls, counter = list(engine.events), list(engine.rolls), engine.roller.counter

    with pytest.raises(type(pause)) as caught:
        with engine._transaction("test:rollback", "test:rollback", ME):
            engine._spend_resource(rider, mounts.FOCUS, 1, "test:rollback")
            engine.rolls.append(engine.roller.d20(modifier=0, actor_id=ME, reason="test:rollback"))
            raise pause

    assert caught.value is pause
    assert engine.state.model_dump(mode="json") == before
    assert engine.events == events and engine.rolls == rolls and engine.roller.counter == counter
    assert engine._transaction_id is None
    with engine._transaction("test:after", "test:after", ME):
        engine._spend_resource(engine.state.actors[ME], mounts.FOCUS, 1, "test:after")
    assert engine.state.actors[ME].resources[mounts.FOCUS] == 0
    assert engine.state.state_version == before["state_version"] + 1


def test_preview_transaction_is_bound_to_preview_and_pause_leaves_parent_untouched():
    engine = fight(rider_bundle())
    engine.state.actors[ME].resources[mounts.FOCUS] = 1
    before = engine.state.model_dump(mode="json")
    events = list(engine.events)
    clone = CombatService._clone_engine(engine.source_root, engine)
    with pytest.raises(ControllerPause):
        with clone._transaction("test:preview", "test:preview", ME):
            clone._spend_resource(clone.state.actors[ME], mounts.FOCUS, 1, "test:preview")
            raise ControllerPause("choose")
    assert clone.state.model_dump(mode="json") == before
    assert engine.state.model_dump(mode="json") == before and engine.events == events
    with clone._transaction("test:preview", "test:preview", ME):
        clone._spend_resource(clone.state.actors[ME], mounts.FOCUS, 1, "test:preview")
    assert clone.state.actors[ME].resources[mounts.FOCUS] == 0
    assert engine.state.model_dump(mode="json") == before and engine.events == events
