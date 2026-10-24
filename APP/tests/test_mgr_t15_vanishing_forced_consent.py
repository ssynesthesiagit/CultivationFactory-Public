"""Sol review MGR-T15 blocking finding: Vanishing Technique's forced-movement reveal reads the printed
"directly manipulating an unwilling creature" clause. A consenting creature's push must not reveal the owner;
an unwilling creature's push must still reveal it."""
from combat import typed_executor as te
from tests.test_mgr_t15_vanishing_native import setup, activate, held
from tests.worker2_support import OWNER, FOE, reload
from combat.gate2_runtime_models import Position
from combat.ext import tabik_ninpo  # noqa: F401  (registers the hook)


def _push_row(**extra):
    return {"type": "forced_movement", "distance_ft": 5, "applies_to": "target", "direction": "away", **extra}


def _push(tmp_path, mid_row):
    combat, table, mid = setup(tmp_path)
    activate(combat, table, mid)
    engine = reload(tmp_path, mid)
    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    owner.position = Position(x=4, y=4, z=owner.position.z)
    foe.position = Position(x=4, y=5, z=foe.position.z)
    assert held(owner, "invisible")
    ctx = te.Context(engine, owner, next(iter(engine.action_catalog.values())), None,
                     {"numbers": {}, "effects": []}, [foe], foe, {})
    before = (foe.position.x, foe.position.y)
    te.block_forced_movement(ctx, mid_row)
    return engine, owner, foe, before


def test_consenting_five_foot_push_does_not_reveal_owner(tmp_path):
    engine, owner, foe, before = _push(tmp_path, _push_row(willing=True))
    assert (foe.position.x, foe.position.y) != before, "the consenting push must actually move the creature"
    assert held(engine.state.actors[OWNER], "invisible"), "a consenting creature's push revealed the owner"


def test_unwilling_five_foot_push_still_reveals_owner(tmp_path):
    engine, owner, foe, before = _push(tmp_path, _push_row())
    assert (foe.position.x, foe.position.y) != before, "the unwilling push must actually move the creature"
    assert not held(engine.state.actors[OWNER], "invisible"), "an unwilling creature's push did not reveal the owner"
    assert held(engine.state.actors[OWNER], "vanishing_state")
