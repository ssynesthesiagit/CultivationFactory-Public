"""A purchased vertical vault survives walking until takeoff actually commits."""
from combat import ext
from combat.ext import athletics
from combat.gate2_runtime_models import Position
from tests.test_mgr_t16_athletics4_vault_air import vault_fight, buy_vault
from tests.test_tabletop_hunt6 import LEFT
from tests.test_walkable_roofs import route, cold


def test_interrupted_vault_approach_preserves_receipt_until_committed_takeoff(tmp_path, monkeypatch):
    combat, table, mid = vault_fight(tmp_path, monkeypatch)
    buy_vault(combat, table, mid, False)
    ext.effects()
    original = list(ext._HOOKS.get('movement_attempt', ()))

    def stop_ascent(engine, mover, previous, nxt, intent):
        if mover.entity_id == LEFT and nxt.z > previous.z:
            return {'stop': True, 'source_id': 'test:stop-ascent', 'label': 'Takeoff interrupted.'}

    monkeypatch.setitem(ext._HOOKS, 'movement_attempt', [*original, stop_ascent])
    route(combat, table, mid, [(1, 3, 0), (2, 3, 0), (3, 3, 0), (3, 3, 1)], mode='jump')
    combat, table, session = cold(combat, tmp_path, mid)
    actor = session.engine.state.actors[LEFT]
    assert actor.position == Position(x=3, y=3, z=0)
    receipt = next(e for e in reversed(session.engine.events) if e.event_type == 'MOVEMENT_COMMITTED')
    assert receipt.payload['interrupted'] and len(receipt.payload['path']) == 3
    assert receipt.payload['cost_ft'] == 10
    held = next((c for c in actor.conditions.values() if c.condition_id == athletics.VAULTER_JUMP), None)
    assert held is not None, 'Walking an interrupted approach must not spend the purchased vault'
    assert held.data['jump_bonus_ft'] == held.data['movement_credit_ft'] == 5
    assert actor.resources[athletics.FOCUS] == 0 and actor.movement_remaining_ft == 20
    assert session.mechanical.replay()['status'] == 'PASS'

    monkeypatch.setitem(ext._HOOKS, 'movement_attempt', original)
    route(combat, table, mid, [(3, 3, 0), (3, 3, 1)], mode='jump')
    _, _, session = cold(combat, tmp_path, mid)
    actor = session.engine.state.actors[LEFT]
    # An unsupported jump lands via native falling after its ascent commits.
    assert actor.position == Position(x=3, y=3, z=0)
    assert actor.movement_remaining_ft == 20
    assert not any(c.condition_id == athletics.VAULTER_JUMP for c in actor.conditions.values())
    receipt = next(e for e in reversed(session.engine.events) if e.event_type == 'MOVEMENT_COMMITTED'
                   and e.payload.get('movement_mode') == 'jump')
    assert receipt.payload['destination'] == Position(x=3, y=3, z=1).model_dump(mode='json')
    assert receipt.payload['movement_credit_spent_ft'] == 5 and receipt.payload['cost_ft'] == 0
    removed = [e for e in session.engine.events if e.event_type == 'CONDITION_REMOVED'
               and e.payload.get('condition_id') == athletics.VAULTER_JUMP]
    assert len(removed) == 1
    assert session.mechanical.replay()['status'] == 'PASS'
