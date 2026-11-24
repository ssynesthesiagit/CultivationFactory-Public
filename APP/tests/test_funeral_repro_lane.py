from tests.test_mgr_t14_ash_parent import native_fixture
from tests.worker2_support import OWNER, FOE, turn, candidate, sealed_native_attack
from tests.table_act_support import act

def test_repro(tmp_path):
    def prepare(bundles):
        sealed_native_attack(bundles[2], 'Synthetic Slash', damage_type='SLASHING')
    combat, table, mid = native_fixture(tmp_path, bundle_transform=prepare,
        positions={OWNER: {'x':3,'y':6}, 'actor:factory.worker2-ally': {'x':4,'y':6}, FOE: {'x':6,'y':6}})
    turn(table, mid, FOE)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    row = candidate(combat, mid, 'Synthetic Slash', target=OWNER)
    result = act(table, mid, row.candidate_id, [])
    assert False, repr(result)
