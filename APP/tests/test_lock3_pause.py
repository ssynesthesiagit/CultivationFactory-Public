"""Player pauses use the native transaction, including on a service preview clone."""
from combat.ext import ControllerPause
from combat.gate2_engine import Gate2Engine
from combat.gate5_service import CombatService
from tests.test_mounts import ME, actors, fight, rider_bundle


def test_player_pause_needs_no_runtime_transaction_patch():
    engine = fight(rider_bundle())
    assert engine._transaction.__func__ is Gate2Engine._transaction
    clone = CombatService._clone_engine(engine.source_root, engine)
    assert clone._transaction.__func__ is Gate2Engine._transaction
    actor, _, _ = actors(clone)
    before = clone.state.model_dump(mode='json')
    pause = ControllerPause('choose')
    try:
        with clone._transaction('test:pause', 'test:pause', ME):
            clone._grant_temp_hp(actor, 7, 'test:pause', ME)
            clone.rolls.append(clone.roller.d20(modifier=0, actor_id=ME, reason='test:pause'))
            raise pause
    except ControllerPause as caught:
        assert caught is pause
    else:
        raise AssertionError('The player pause was swallowed')
    assert clone.state.model_dump(mode='json') == before
    assert engine.state.model_dump(mode='json') == before
    assert clone.roller.counter == engine.roller.counter
