"""Hunt 29 regressions through persisted manual/AI tables; no browsers or live data."""
import pytest

from tests.hunt28_support import ALLY, FOE, OWNER, act, fixture, options, owner_turn, reload, send


def named(table, mid, prefix):
    return [o for g in table.state(mid)['menu']['actions'] if g['label'].startswith(prefix) for o in g['options']]


@pytest.mark.parametrize('auto', [False, True])
@pytest.mark.parametrize('primary', ['Qi', 'Stamina'])
@pytest.mark.parametrize('talent,label,price', [
    ('TAL_GRAVITY_WEIGHT_OF_THE_MOUNTAIN', 'Weight of the Mountain', 4),
    ('TAL_GRAVITY_EXTERNAL_WEIGHT_SHIFT', 'External Weight Shift', 1),
])
def test_gravity_pays_full_printed_price_before_effects(tmp_path, auto, primary, talent, label, price):
    combat, table, mid = fixture(tmp_path, [talent], cp=price, primary=primary)
    cid = next(o['candidate_id'] for o in named(table, mid, label) if o['target_ids'] == [FOE])
    assert send(combat, table, mid, cid, auto)['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert engine.state.actors[OWNER].resources['resource:core.' + primary.lower()] == 0
    spends = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT' and e.actor_id == OWNER]
    assert any(e.payload.get('amount') == price for e in spends)
    owner_turn(table, mid, next_turn=True)
    assert not named(table, mid, label)



@pytest.mark.parametrize('auto', [False, True])
@pytest.mark.parametrize('talent,label', [('TAL_GRAVITY_WEIGHT_OF_THE_MOUNTAIN', 'Weight of the Mountain'), ('TAL_GRAVITY_EXTERNAL_WEIGHT_SHIFT', 'External Weight Shift')])
def test_gravity_with_zero_cp_cannot_apply(tmp_path, auto, talent, label):
    combat, table, mid = fixture(tmp_path, [talent], cp=0)
    assert not named(table, mid, label)
    assert send(combat, table, mid, options(table, mid, 'Dodge')[0]['candidate_id'], auto)['status'] == 'COMMITTED'
    reload(combat, mid)


@pytest.mark.parametrize('auto', [False, True])
@pytest.mark.parametrize('talent,label', [('TAL_GRAVITY_WEIGHT_OF_THE_MOUNTAIN', 'Weight of the Mountain'), ('TAL_GRAVITY_EXTERNAL_WEIGHT_SHIFT', 'External Weight Shift')])
def test_old_unpaid_fixed_alternative_fails_closed(tmp_path, auto, talent, label):
    combat, table, mid = fixture(tmp_path, [talent], legacy_unpaid=True)
    assert not named(table, mid, label)
    assert send(combat, table, mid, options(table, mid, 'Dodge')[0]['candidate_id'], auto)['status'] == 'COMMITTED'
    reload(combat, mid)


def test_movement_and_turn_candidates_have_no_payment_action(tmp_path, caplog):
    combat, table, mid = fixture(tmp_path, [])
    assert act(table, mid, table.state(mid)['menu']['end_turn'])['status'] == 'COMMITTED'
    reload(combat, mid)
    assert not any('option_payments' in record.message and 'failed' in record.message for record in caplog.records)
