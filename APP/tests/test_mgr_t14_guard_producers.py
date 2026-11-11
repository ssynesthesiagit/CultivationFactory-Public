"""Shipped source producers, not invented pressure names or staged toggles."""
import pytest

from combat.canonical import canonical_sha256
from combat.ext import formations
from combat.ext.soul_warden import DRAIN
from combat.ext.returning_source_guard import allowance
from tests.h1_support import sheet
from tests.guard_spirit_support import spirit_sheet
from tests.test_mgr_t14_ling_guard_sum import owner_bundle, add_action, REACTION, DEW, assert_guard_paid_before_new_dew
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload


def seal(bundle):
    bundle.pop('bundle_sha256', None)
    bundle['bundle_sha256'] = canonical_sha256(bundle)


def test_real_soul_drain_packet_grants_source_bound_guard(tmp_path):
    def delivery(bundles):
        bundles[1]['actor_template']['maximum_hp'] = 500
        seal(bundles[1])
    combat, table, mid = fixture(tmp_path, [], owner_bundle=owner_bundle(2, 8),
        foe_sheet=spirit_sheet([DRAIN], dc=40), bundle_transform=delivery, seed='GUARD-SOUL-DRAIN')
    turn(table, mid, FOE)
    row = candidate(combat, mid, 'Soul Drain and Death Custody: Necrotic', target=ALLY)
    settle(table, mid, row.candidate_id, picks={REACTION: 'first'})
    engine = reload(tmp_path, mid)
    held = allowance(engine.state.actors[ALLY])
    assert held is not None and held.data['pressure_kind'] == 'drain'
    assert held.data['pressure_source_id'] == row.source_definition_id
    assert held.data['pressure_actor_id'] == FOE
    assert_guard_paid_before_new_dew(engine)
    assert any(c.condition_id == 'condition:typed.no_cp_regain'
               for c in engine.state.actors[ALLY].conditions.values())
    assert not any(c.condition_id == 'condition:typed.no_cp_regain'
                   for c in engine.state.actors[OWNER].conditions.values())


def test_real_unstable_array_maintenance_check_uses_guard_once(tmp_path):
    # The donor is after the array's creator in initiative. The array check
    # happens before the donor's next start, through the real turn producer.
    def delivery(bundles):
        bundles[1] = owner_bundle(2, 8, actor_id=ALLY)
        add_action(bundles[2], 'Small hostile strike', [
            {'type': 'damage', 'flat': 1, 'damage_types': ['force'], 'applies_to': 'target'}],
            economy='BONUS_ACTION')
        seal(bundles[2])
    combat, table, mid = fixture(tmp_path,
        ['FORMATIONS_BASE_SET_ARRAY', 'FORMATIONS_BASE_FORMATION_TRAINING'],
        foe_sheet=sheet(['tianxia.talent.formations.disrupt_node'], dc=30),
        owner_dc=1, bundle_transform=delivery, seed='GUARD-PARENT')
    settle(table, mid, candidate(combat, mid, 'Combat Array: Nourishing Cycle', at=(5, 6)).candidate_id)
    engine = reload(tmp_path, mid)
    zone = formations.arrays(engine, OWNER)[0]
    eye = formations.record(zone)['eye']
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Disrupt Node', target=eye).candidate_id)
    engine = reload(tmp_path, mid)
    assert formations.record(engine.state.zones[zone.zone_id])['unstable']
    settle(table, mid, candidate(combat, mid, 'Small hostile strike', target=OWNER).candidate_id,
           picks={REACTION: 'first'})
    engine = reload(tmp_path, mid)
    assert allowance(engine.state.actors[OWNER]) is not None
    assert not [e for e in engine.events if e.event_type == 'SAVE_ROLLED'
                and e.source_definition_id == 'system:combat.concentration']
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    check = next(e for e in reversed(engine.events) if e.event_type == 'CHECK_ROLLED'
                 and e.source_definition_id == 'formation:disrupt_node')
    assert check.payload['actor']['mode'] == 'ADVANTAGE'
    assert allowance(engine.state.actors[OWNER]) is None


@pytest.mark.parametrize('keep_first', [False, True])
def test_real_fields_publish_backlash_for_the_next_same_source_save(tmp_path, keep_first):
    field = 'TAL_QIWEAVING_TURBULENT_FIELD'
    backlash = 'TAL_QIWEAVING_TURBULENT_BACKLASH'
    combat, table, mid = fixture(tmp_path, [], owner_bundle=owner_bundle(2, 8),
        ally_talents=['TAL_FATE_BINDING_WORD'], foe_sheet=sheet([field, backlash], dc=40),
        seed='GUARD-FIELD-RECEIPT')
    turn(table, mid, FOE)
    source = candidate(combat, mid, 'Turbulent Field').source_definition_id
    settle(table, mid, candidate(combat, mid, 'Turbulent Field').candidate_id)
    if keep_first:
        # The augment releases Concentration; the owner's unlimited-capacity
        # ruling also permits two copies without paying this optional augment.
        before = reload(tmp_path, mid).state.actors[FOE].resources['resource:core.qi']
        settle(table, mid, candidate(combat, mid,
            'Lingering Turbulence: keep Turbulent Field without Concentration (2 CP)').candidate_id)
        assert reload(tmp_path, mid).state.actors[FOE].resources['resource:core.qi'] == before - 2
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Turbulent Field').candidate_id)
    engine = reload(tmp_path, mid)
    fields = [z for z in engine.state.zones.values()
              if z.active and z.owner_id == FOE and z.source_definition_id == source]
    assert len(fields) == 2
    assert sum(z.concentration_link for z in fields) == (1 if keep_first else 2)
    turn(table, mid, ALLY)
    before = reload(tmp_path, mid)
    cp_before = before.state.actors[ALLY].resources['resource:core.qi']
    word = candidate(combat, mid, 'Binding Word', target=FOE)
    cost = sum(amount for resource, amount in before.action_catalog[word.source_definition_id].costs
               if resource == 'resource:core.qi')
    assert cost == 2  # Binding Word's printed cost, not a Guard refund.
    settle(table, mid, word.candidate_id,
           picks={REACTION: 'first', 'reaction:typed.' + backlash: 'first'})
    engine = reload(tmp_path, mid)
    rolls = [e for e in engine.events if e.event_type == 'SAVE_ROLLED'
             and e.source_definition_id == source and e.actor_id == ALLY]
    triggers = [e.payload for e in engine.events if e.event_type == 'PASSIVE_TRIGGERED'
                and e.source_definition_id == source and ALLY in e.target_ids]
    assert [e.payload['mode'] for e in rolls] == ['NORMAL', 'ADVANTAGE'], triggers
    receipts = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
                and e.source_definition_id == source and ALLY in e.target_ids]
    assert len(receipts) == 2
    assert all(e.payload['pressure_kind'] == 'backlash' for e in receipts)
    assert_guard_paid_before_new_dew(engine)
    assert allowance(engine.state.actors[ALLY]) is None
    assert engine.state.actors[ALLY].resources['resource:core.qi'] == cp_before - cost
