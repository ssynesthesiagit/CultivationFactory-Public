"""Swift Movement composition guard and all-Speeds bonus invariant (F13R optional notes).

The composition re-entry guard is thread-local, so one thread's nested read
never hides another thread's composition of the same creature. The
all-Speeds bonus is subtracted by `effective_speed(include_all_movement_bonus=False)`;
that subtraction is exact only while `motion.speed_bonus` is the sole carrier
of the bonus, which this file pins.
"""
import threading

from combat import speed_contributions
from combat.movement_speeds import all_bonus
from tests.test_auto_athletics import _engine, _me
from tests.test_mgr_t15_swift_movement import FOCUS, SWIFT


def test_composition_guard_is_thread_local():
    key = ('engine-id', 'actor-id')
    speed_contributions._composing().add(key)
    try:
        seen = {}

        def other_thread():
            seen['other'] = key in speed_contributions._composing()

        worker = threading.Thread(target=other_thread)
        worker.start()
        worker.join()
        assert seen['other'] is False, 'another thread saw this thread\'s reentry guard'
        assert key in speed_contributions._composing()
    finally:
        speed_contributions._composing().discard(key)


def test_excluding_all_bonus_removes_exactly_the_swift_contribution():
    engine = _engine([SWIFT])
    actor = _me(engine)
    actor.resources[FOCUS] = 1
    with_bonus = speed_contributions.effective_speed(engine, actor)
    without = speed_contributions.effective_speed(engine, actor, include_all_movement_bonus=False)
    granted = all_bonus(engine, actor)
    assert granted == 10, 'Swift Movement grants +10 feet while Martial Focus is held'
    assert with_bonus > 0
    assert with_bonus - without == granted
