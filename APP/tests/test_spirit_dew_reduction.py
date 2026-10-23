"""Spirit Dew from a paid, compiled Ash Ward at the table boundary."""
import pytest

from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.test_a2_foundations3 import add_action, pool
from tests.worker2_support import OWNER, ALLY, FOE, act, fixture, candidate, settle, turn, reload

OWNER_ROW = 'foundation.origin_spirit_body_v0_2B.generate_spirit_source_dew'
WARD = 'tianxia.talent.ash.ash_ward'


def support_fight(tmp_path, *, owns=True, ask=True, ward_actor=OWNER, initial=0):
    doc = sheet(([WARD] if ward_actor == OWNER else []) + ([OWNER_ROW] if owns else []), name='Wren', foundation={
        'foundation_id': 'origin_spirit_body_v0_2B', 'stage': 'Awakened',
        'resource': {'name': 'Spirit-Source Dew', 'resource_id': 'tianxia.resource.test',
                     'maximum': 1, 'current': initial}})
    bundle = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': ask})

    def delivery(bundles):
        add_action(bundles[2], 'Force packet',
                   [{'type': 'attack', 'attack_kind': 'weapon', 'on_hit': [
                       {'type': 'damage', 'flat': 20, 'damage_types': ['force'], 'applies_to': 'target'}]}],
                   bonus=100)

    return fixture(tmp_path, [], owner_bundle=bundle, bundle_transform=delivery,
                   seed='SPIRIT-DEW-REDUCTION', named=True,
                   ally_talents=[WARD] if ward_actor == ALLY else [],
                   modes={OWNER: 'MANUAL', ALLY: 'MANUAL', FOE: 'MANUAL'})


@pytest.mark.parametrize('ask', [True, False])
def test_paid_outward_reduction_generates_after_native_receipt_and_replays(tmp_path, ask):
    combat, table, mid = support_fight(tmp_path, ask=ask)
    turn(table, mid, FOE)
    if not ask:
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    before = reload(tmp_path, mid)
    qi = before.state.actors[OWNER].resources['resource:core.qi']
    hp = before.state.actors[ALLY].current_hp
    for _ in range(3):
        cid = candidate(combat, mid, 'Force packet', target=ALLY).candidate_id
        table.state(mid)
        if ask:
            assert act(table, mid, cid, [])['status'] == 'REACTION_REQUIRED'
        preview = reload(tmp_path, mid)
        assert preview.state.actors[OWNER].resources[pool('spirit')] == 0
        assert preview.state.actors[OWNER].resources['resource:core.qi'] == qi
        assert preview.state.actors[ALLY].current_hp == hp
        assert len(preview.events) == len(before.events)
    prompts = settle(table, mid, cid, picks={'reaction:typed.' + WARD: 'first'})
    engine = reload(tmp_path, mid)
    receipt = next(e for e in engine.events if e.event_type == 'REACTION_RESOLVED'
                   and e.source_definition_id == WARD)
    assert receipt.actor_id == OWNER
    assert receipt.payload['protects'] == ALLY
    assert receipt.payload['pending_before'] >= 20
    assert 0 < receipt.payload['reduction'] <= receipt.payload['pending_before']
    assert receipt.payload['pending_after'] == receipt.payload['pending_before'] - receipt.payload['reduction']
    assert engine.state.actors[ALLY].current_hp == hp - receipt.payload['pending_after']
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == qi - 1
    assert engine.state.actors[OWNER].resources[pool('spirit')] == 1
    assert engine.state.actors[OWNER].reaction_available is False
    if ask:
        assert any(p['reaction'] == 'Ash Ward' for p in prompts)
    else:
        assert not prompts
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='MANUAL')
    turn(table, mid, OWNER)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[pool('spirit')] == 1
    turn(table, mid, ALLY)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[pool('spirit')] == 0


@pytest.mark.parametrize('target,accept,owns', [
    (OWNER, True, True), (ALLY, False, True), (ALLY, True, False)])
def test_self_declined_and_unowned_reductions_do_not_generate(tmp_path, target, accept, owns):
    combat, table, mid = support_fight(tmp_path, owns=owns)
    turn(table, mid, FOE)
    cid = candidate(combat, mid, 'Force packet', target=target).candidate_id
    settle(table, mid, cid, picks={'reaction:typed.' + WARD: 'first'} if accept else {})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources.get(pool('spirit'), 0) == 0
    receipts = [e for e in engine.events if e.event_type == 'REACTION_RESOLVED'
                and e.source_definition_id == WARD]
    if accept:
        assert receipts and receipts[-1].actor_id == OWNER
        assert receipts[-1].payload['reduction'] > 0
    else:
        assert not receipts


def test_another_providers_reduction_does_not_credit_spirit_observer(tmp_path):
    combat, table, mid = support_fight(tmp_path, ward_actor=ALLY)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Force packet', target=OWNER).candidate_id,
           picks={'reaction:typed.' + WARD: 'first'})
    engine = reload(tmp_path, mid)
    receipt = next(e for e in engine.events if e.event_type == 'REACTION_RESOLVED'
                   and e.source_definition_id == WARD)
    assert receipt.actor_id == ALLY and receipt.payload['protects'] == OWNER
    assert receipt.payload['reduction'] > 0
    assert engine.state.actors[OWNER].resources[pool('spirit')] == 0


def test_outward_reduction_does_not_stack_or_refresh_held_dew(tmp_path):
    from combat.pressure import CLOCK
    combat, table, mid = support_fight(tmp_path, initial=1)
    turn(table, mid, FOE)
    clock = reload(tmp_path, mid).state.actors[OWNER].turn_flags.get(CLOCK)
    settle(table, mid, candidate(combat, mid, 'Force packet', target=ALLY).candidate_id,
           picks={'reaction:typed.' + WARD: 'first'})
    engine = reload(tmp_path, mid)
    assert any(e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == WARD
               and e.payload['reduction'] > 0 for e in engine.events)
    assert engine.state.actors[OWNER].resources[pool('spirit')] == 1
    assert engine.state.actors[OWNER].turn_flags.get(CLOCK) == clock
