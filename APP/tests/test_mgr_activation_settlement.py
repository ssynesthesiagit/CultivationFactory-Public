"""Real activation receipts and strict rollback guards for the general seam."""
import pytest
from combat import ext
from tests.worker2_support import fixture, candidate, settle, reload, turn, OWNER, FOE


def test_native_settlement_uses_only_executed_source_and_replays(tmp_path, monkeypatch):
    ext.effects()
    seen = []
    def observe(ctx, receipt):
        seen.append(receipt)
    monkeypatch.setitem(ext._HOOKS, 'activation_settlement', [*ext._HOOKS.get('activation_settlement', ()), observe])
    combat, table, mid = fixture(tmp_path, ['FIRE_BASE_IGNITE'], cl=10, seed='SETTLEMENT')
    turn(table, mid, OWNER)  # initiative order is not this test's subject
    settle(table, mid, candidate(combat, mid, 'Ignite: Push Target', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    receipt = next(r for r in reversed(seen) if r['source_id'] == 'FIRE_BASE_IGNITE')
    assert receipt['source_kind'] == 'Sphere'
    assert receipt['source_cl'] == 10 and receipt['qi_powered'] == 1
    assert receipt['weapon_delivery'] == 0
    packets = [e for e in engine.events[receipt['first_sequence']:receipt['last_sequence']]
               if e.event_type == 'DAMAGE_COMMITTED' and e.source_definition_id == receipt['action_id']
               and e.actor_id == OWNER]
    assert receipt['damage_types'] == sorted({e.payload['damage_type'] for e in packets})
    assert receipt['dealt_damage_types'] == sorted({str(e.payload['damage_type']).upper() for e in packets
        if int(e.payload.get('hp_damage') or 0) + int(e.payload.get('temporary_hp_absorbed') or 0) > 0})
    assert set(receipt['recipient_ids']) == {tid for e in packets for tid in e.target_ids}
    assert not any('catalog' in key or 'unactivated' in key for key in receipt)


def test_native_settlement_failure_rolls_back_entire_table_intent(tmp_path, monkeypatch):
    combat, table, mid = fixture(tmp_path, ['FIRE_BASE_IGNITE'], cl=10)
    turn(table, mid, OWNER)  # initiative order is not this test's subject
    before = reload(tmp_path, mid).state.model_dump(mode='json')
    c = candidate(combat, mid, 'Ignite: Push Target', target=FOE)
    ext.effects()
    def reject(ctx, receipt):
        raise ValueError('settlement rejected')
    monkeypatch.setitem(ext._HOOKS, 'activation_settlement', [*ext._HOOKS.get('activation_settlement', ()), reject])
    # The service reports a commit failure through its own diagnostic layer, so the guard is that the
    # intent does not commit at all: the call must fail and the persisted fight must be byte-identical.
    failed = False
    try:
        settle(table, mid, c.candidate_id)
    except Exception:
        failed = True
    assert failed, 'the rejecting settlement hook must stop the table intent'
    assert reload(tmp_path, mid).state.model_dump(mode='json') == before
