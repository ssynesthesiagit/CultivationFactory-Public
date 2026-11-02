"""A shipped Nullification Seal can suppress the bounded Guard allowance."""
from combat.ext.benefit_suppression import benefits, SUPPRESSED
from combat.ext.returning_source_guard import allowance, CONDITION
from tests.h1_support import sheet
from tests.test_mgr_t14_ling_guard_sum import owner_bundle, add_action, REACTION
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload
from tests.test_mgr_t14_guard_producers import seal


def test_native_seal_suppresses_guard_and_eligible_roll_consumes_stored_allowance(tmp_path):
    def delivery(bundles):
        add_action(bundles[1], 'Maintained technique', [], target_kind='SELF')
        bundles[1]['action_catalog'][-1]['parameters']['typed']['duration'] = {
            'kind': 'minutes', 'amount': 1, 'concentration': True}
        seal(bundles[1])
        add_action(bundles[2], 'Small hostile strike', [
            {'type': 'damage', 'flat': 1, 'damage_types': ['force'], 'applies_to': 'target'}],
            economy='BONUS_ACTION')
        add_action(bundles[3], 'Next hostile strike', [
            {'type': 'damage', 'flat': 8, 'damage_types': ['force'], 'applies_to': 'target'}],
            economy='ACTION')
    combat, table, mid = fixture(tmp_path, [], owner_bundle=owner_bundle(2, 8),
        foe_sheet=sheet(['TAL_VOID_NULLIFICATION_SEAL'], dc=40),
        bundle_transform=delivery, seed='GUARD-SUPPRESSION', extra_foes=1)
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Maintained technique', target=ALLY).candidate_id)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Small hostile strike', target=ALLY).candidate_id,
           picks={REACTION: 'first'})
    engine = reload(tmp_path, mid)
    held = allowance(engine.state.actors[ALLY])
    assert held is not None
    benefit_id = 'condition:' + held.instance_id
    assert benefit_id in {r['id'] for r in benefits(engine, engine.state.actors[ALLY])}
    prompts = settle(table, mid, candidate(combat, mid, 'Nullification Seal', target=ALLY).candidate_id,
                     choices={'choice:needle.void_benefit': benefit_id})
    assert any('Returning Source Guard' in str(p) for p in prompts)
    engine = reload(tmp_path, mid)
    assert allowance(engine.state.actors[ALLY]) is None
    assert any(c.condition_id == SUPPRESSED for c in engine.state.actors[ALLY].conditions.values())
    turn(table, mid, FOE + '1')
    settle(table, mid, candidate(combat, mid, 'Next hostile strike', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    roll = next(e for e in reversed(engine.events) if e.event_type == 'SAVE_ROLLED'
                and e.source_definition_id == 'system:combat.concentration')
    assert roll.payload['mode'] == 'NORMAL'
    assert not any(c.condition_id == SUPPRESSED and (c.data.get('model') or {}).get('condition_id') == CONDITION
                   for c in engine.state.actors[ALLY].conditions.values())
    assert allowance(engine.state.actors[ALLY]) is None
