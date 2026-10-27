"""The temporary-AC denial participates in the engine's AC hook dispatch."""
from combat import ext
from combat.ext import sabers_riders
from tests import test_mgr_t17_shield_hacking_providers as providers
from tests import test_mgr_t17_shield_hacking_rhythm as base


def test_denial_is_dispatched_with_provider():
    engine, foe = providers.fight()
    providers.grant(engine, foe, 'cover')
    base._hit_with(engine, base.RHYTHM)
    results = ext.run('ac', engine, foe, _with_handlers=True)
    assert (sabers_riders.shield_hacking_takes_the_bonus, -2) in results, [(f.__module__, f.__name__, v) for f, v in results]
    assert engine._ac_modifier(foe) == 0, [(f.__module__, f.__name__, v) for f, v in results]
