"""An explicitly selected self formula resolves, pays once and expires normally."""
import copy
import pytest
from tests import test_lock8_alchemy_table as T
from tests.test_lock_choices import install
from tests.test_lock2_persistence import act
from tests.test_hidden_targeting import turn
from tests.r10_fixup_support import cast_sender, commit


@pytest.mark.parametrize('dc,saved', [(50, False), (-40, True)])
def test_meridian_self_release_table_save_payment_denial_expiry(monkeypatch, tmp_path, dc, saved):
    combat, table, mid = T.fight(monkeypatch, tmp_path, T.SEAL, dc=dc, foe_hp=60)
    e = combat._load_session(mid).engine
    before = copy.deepcopy(e.state.actors[T.OWNER])
    seq = e.state.event_sequence
    name = 'Field Formula: Meridian-Sealing Pill'
    release = next(a for a in e.action_catalog.values() if a.owner_id == T.OWNER and a.display_name == name)
    commit(cast_sender(combat, table, mid, name, target=T.OWNER))
    e = T.reload_checked(tmp_path, mid)
    actor = e.state.actors[T.OWNER]
    for resource, amount in release.costs:
        assert actor.resources[resource] == before.resources[resource] - amount
    saves = [ev for ev in e.events if ev.sequence > seq and ev.event_type == 'SAVE_ROLLED']
    assert saves and all(T.OWNER in ev.target_ids or ev.actor_id == T.OWNER for ev in saves)
    assert all(ev.payload['success'] is saved for ev in saves)
    def denied(engine, kind, kwargs):
        if kind == 'HOLD_POSITION_COMMITTED' and kwargs['actor_id'] == T.OWNER:
            who = engine.state.actors[T.OWNER]
            engine._spend_resource(who, T.CP, 2, 'test:open-pool')
            engine._gain_resource(who, T.CP, 2, 'test:self-formula-denial')
    install(monkeypatch, 'event', denied)
    prior = actor.resources[T.CP]
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    e = T.reload_checked(tmp_path, mid)
    assert e.state.actors[T.OWNER].resources[T.CP] == prior - 2
    def sealed(engine):
        return any(c.condition_id == 'condition:typed.no_cp_regain'
                   for c in engine.state.actors[T.OWNER].conditions.values())
    assert sealed(e)
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    e = T.reload_checked(tmp_path, mid)
    assert sealed(e)  # even a successful save lasts until the user's next turn
    turn(table, mid, T.OWNER)
    e = T.reload_checked(tmp_path, mid)
    assert sealed(e) is not saved
    if not saved:
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
        assert not sealed(T.reload_checked(tmp_path, mid))
