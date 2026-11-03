"""Sol review MGR-T15 blocking finding: Vanishing Technique's forced-movement reveal must follow the printed
"directly manipulating an unwilling creature" clause. A consenting creature's push must not reveal the owner;
an unwilling creature's push must still reveal it."""
from tests.test_mgr_t15_vanishing_native import setup, activate, held
from tests.worker2_support import OWNER, FOE, reload
from combat.ext import tabik_ninpo


def test_consenting_push_receipt_does_not_reveal_owner(tmp_path):
    combat, table, mid = setup(tmp_path)
    activate(combat, table, mid)
    engine = reload(tmp_path, mid)
    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    assert held(owner, "invisible")
    tabik_ninpo.vanishing_manipulation(engine, owner, foe, 5, "push", unwilling=False)
    assert held(engine.state.actors[OWNER], "invisible"), "a consenting creature's push revealed the owner"


def test_unwilling_push_receipt_still_reveals_owner(tmp_path):
    combat, table, mid = setup(tmp_path)
    activate(combat, table, mid)
    engine = reload(tmp_path, mid)
    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    assert held(owner, "invisible")
    tabik_ninpo.vanishing_manipulation(engine, owner, foe, 5, "push", unwilling=True)
    assert not held(engine.state.actors[OWNER], "invisible"), "an unwilling creature's push did not reveal the owner"
    assert held(engine.state.actors[OWNER], "vanishing_state")
