"""Origin-Spirit Vessel native values share one table-persisted round receipt."""
import pytest

from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, reload, turn
from tests.cw2_service_support import add_action
from tests.test_mgr_t14_spirit_vessel_value import VESSEL, LIFE, CHOICE, ROUND


def receipts(engine):
    return [e for e in engine.events if e.payload.get('receipt_kind') == 'origin_spirit_support_value']


def wound(bundles):
    add_action(bundles[0], 'Prepare wound', [{'type': 'damage', 'flat': 40,
        'damage_types': ['force'], 'applies_to': 'target'}])


def source_bound_owner(talents, *, score=14, actor_id=OWNER):
    """Compile the released Foundation installation, including its real pool.

    A bare Foundation id can project feature text without declaring the Dew
    resource; it is insufficient evidence for a paid supported method.
    """
    from tests.h1_support import sheet
    from combat.factory_compiler import compile_character
    from non_sphere_authority.foundation_mechanics import resolve_initial_foundation_mechanics, verified_foundation_records
    from stage2.formulas import evaluate_formula
    identity = 'origin_spirit_body_v0_2B'
    projection = resolve_initial_foundation_mechanics(verified_foundation_records()[identity],
        ['tianxia.path.spirit_awakening'], stage='Awakened')
    document = sheet(talents, cl=15, score=score, name='Wren', foundation={
        'foundation_id': identity, 'stage': 'Awakened', 'mechanics': projection,
        'resource': projection['initial_state']['resource']})
    document['ability_scores_and_statistics']['primary_resource']['maximum'] = 100
    document['ability_scores_and_statistics']['hit_points']['maximum'] += sum(
        evaluate_formula(r['formula']['root'], {'pb': 4}).value
        for r in projection['hp_maximum_modifiers'] if r['availability'] == 'available')
    return compile_character(document, actor_id=actor_id, reaction_plan={'ask': True})


@pytest.mark.parametrize('owns,accept', [(True, True), (True, False), (False, True)])
def test_native_healing_value_and_shared_round(tmp_path, owns, accept):
    combat, table, mid = fixture(tmp_path, [LIFE, *([VESSEL] if owns else [])],
                                bundle_transform=wound, named=True, seed='VESSEL-HEAL')
    settle(table, mid, candidate(combat, mid, 'Prepare wound', target=ALLY).candidate_id, picks={CHOICE: None})
    healing = candidate(combat, mid, 'Mend the Pulse', target=ALLY)
    settle(table, mid, healing.candidate_id, picks={CHOICE: 'increase' if accept else None})
    engine = reload(tmp_path, mid)
    found = receipts(engine)
    assert len(found) == int(owns and accept)
    if found:
        value = found[0].payload
        assert value['value_kind'] == 'healing'
        assert value['method'] == 'LIFE_BASE_MEND_THE_PULSE'
        assert value['beneficiary'] == ALLY and len(value['method_text_sha256']) == 64
        assert value['selected'] == value['original'] + 4
        assert value['final_result'] > 0
        assert engine.state.actors[OWNER].turn_flags[ROUND] == engine.state.round_number
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Borrowed Breath + Greater Invigorate', target=ALLY).candidate_id,
           picks={CHOICE: 'increase'})
    engine = reload(tmp_path, mid)
    assert len(receipts(engine)) == (2 if owns and accept else int(owns))


def test_healing_and_temp_hp_cannot_both_boost_in_same_round(tmp_path):
    from tests.worker2_support import sealed_native_attack
    def prepare(bundles):
        wound(bundles)
        for b in bundles:
            b['actor_template']['initiative_bonus'] = 1000 if b['actor_id'] == OWNER else -1000
            from tests.cw2_service_support import seal
            seal(b)
        sealed_native_attack(bundles[2], 'Trigger delayed treatment', count=1, sides=4,
                             modifier=10, attack_bonus=100, range_ft=5)
    combat, table, mid = fixture(tmp_path, [VESSEL, LIFE, 'tianxia.talent.life.latent_healing'],
                                bundle_transform=prepare, named=True, foe_position={'x': 5, 'y': 6})
    settle(table, mid, candidate(combat, mid, 'Borrowed Breath + Latent Healing', target=ALLY).candidate_id)
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Prepare wound', target=ALLY).candidate_id, picks={CHOICE: None})
    settle(table, mid, candidate(combat, mid, 'Mend the Pulse', target=ALLY).candidate_id,
               picks={CHOICE: 'increase'})
    used_round = reload(tmp_path, mid).state.round_number
    turn(table, mid, FOE)
    assert reload(tmp_path, mid).state.round_number == used_round
    settle(table, mid, candidate(combat, mid, 'Trigger delayed treatment', target=ALLY).candidate_id,
           picks={'choice:needle.latent_healing': 'use', CHOICE: 'increase'})
    assert len(receipts(reload(tmp_path, mid))) == 1


def test_native_water_shield_selected_roll_and_paid_source(tmp_path):
    from tests.test_auto38_water import prepare
    combat, table, mid = fixture(tmp_path, [VESSEL, 'TAL_WATER_WATER_SHIELD'],
                                bundle_transform=lambda b: prepare(b, area=True), named=True,
                                foe_position={'x': 3, 'y': 5})
    turn(table, mid, FOE)
    before = reload(tmp_path, mid).state.actors[OWNER].resources['resource:core.qi']
    settle(table, mid, candidate(combat, mid, 'Fixture area damage', at=(3, 6)).candidate_id,
           picks={'choice:needle.area_recipients': [ALLY], 'choice:needle.water_shield': 'use', CHOICE: 'increase'})
    engine = reload(tmp_path, mid)
    found = receipts(engine)
    assert len(found) == 1
    value = found[0].payload
    assert value['method'] == 'TAL_WATER_WATER_SHIELD'
    assert value['value_kind'] == 'damage_reduction'
    assert value['selected'] == value['original'] + 4
    assert value['final_result'] == min(30, max(0, value['selected']))
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == before - 1
    assert not engine.state.actors[OWNER].reaction_available


@pytest.mark.parametrize('method', ['Regulated Breathing', 'Calm the Wild Meridian'])
def test_native_backlash_support_has_actual_source_and_signed_value(tmp_path, method):
    from tests.h1_support import sheet
    from combat.factory_compiler import compile_character
    from combat.canonical import canonical_sha256
    talents = [VESSEL, 'TAL_QIWEAVING_REGULATED_BREATHING', 'TAL_QIWEAVING_CALM_THE_WILD_MERIDIAN']
    # A legitimately compiled low Key Ability score exercises signed support;
    # source and purpose still come from the shipped ability and Field marker.
    document = sheet(talents, cl=15, score=4, name='Wren')
    document['ability_scores_and_statistics']['primary_resource']['maximum'] = 100
    owner_bundle = compile_character(document, actor_id=OWNER, reaction_plan={'ask': True})
    def prepare(bundles):
        bundles[1]['actor_template']['saving_throws']['CON'] = -100
        for b in bundles:
            # Field, affected ally, helper: resolve support before the hostile
            # source's next turn can expire its native Turbulent marker.
            b['actor_template']['initiative_bonus'] = {FOE: 1000, ALLY: 0, OWNER: -1000}[b['actor_id']]
            b.pop('bundle_sha256', None)
            b['bundle_sha256'] = canonical_sha256(b)
    combat, table, mid = fixture(tmp_path, talents, ally_talents=[LIFE],
                                owner_bundle=owner_bundle, bundle_transform=prepare, named=True,
                                foe_sheet=sheet(['TAL_QIWEAVING_TURBULENT_FIELD'], cl=15))
    # Main's current area policy excludes allies from generic harmful areas.
    # A real hostile Field establishes the ally's instability; the helper then
    # uses its own printed support method, without changing that area policy.
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Turbulent Field', target=FOE).candidate_id)
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Borrowed Breath + Greater Invigorate', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    assert any(c.condition_id == 'condition:typed.turbulent' and c.source_actor_id == FOE
               for c in engine.state.actors[ALLY].conditions.values())
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, method, target=ALLY).candidate_id, picks={CHOICE: 'increase'})
    engine = reload(tmp_path, mid)
    value = receipts(engine)[-1].payload
    assert value['value_kind'] == 'backlash' and value['beneficiary'] == ALLY
    assert value['selected'] == value['original'] + 4
    if method == 'Regulated Breathing':
        assert value['original'] == -3 and value['selected'] == 1
        assert value['method'] == 'TAL_QIWEAVING_REGULATED_BREATHING'
    else:
        assert value['method'] == 'TAL_QIWEAVING_CALM_THE_WILD_MERIDIAN'
        check = next(e for e in reversed(engine.events) if e.event_type == 'CHECK_ROLLED' and e.actor_id == OWNER)
        assert value['final_result'] == check.payload['actor']['total']
    assert engine.state.actors[OWNER].turn_flags[ROUND] == engine.state.round_number


@pytest.mark.parametrize('target', [ALLY, OWNER])
def test_native_radiant_aegis_fear_save_uses_real_grant_and_beneficiary(tmp_path, target):
    aegis = 'tianxia.talent.radiance.radiant_aegis_of_the_heart'
    def prepare(bundles):
        add_action(bundles[2], 'Fear pressure', [{'type': 'save', 'ability': 'WIS', 'applies_to': 'target',
            'on_fail': [{'type': 'condition', 'condition': 'frightened', 'applies_to': 'target',
                         'duration': {'kind': 'until_end_of_your_next_turn'}}], 'on_success': []}])
    combat, table, mid = fixture(tmp_path, [VESSEL, aegis], bundle_transform=prepare, named=True)
    settle(table, mid, candidate(combat, mid, 'Radiant Aegis of the Heart', target=target).candidate_id)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Fear pressure', target=target).candidate_id, picks={CHOICE: 'increase'})
    engine = reload(tmp_path, mid)
    found = receipts(engine)
    assert len(found) == int(target != OWNER)
    save = next(e for e in reversed(engine.events) if e.event_type == 'SAVE_ROLLED' and e.actor_id == target)
    assert save.payload['mode'] == 'ADVANTAGE'
    if found:
        value = found[0].payload
        assert value['method'] == aegis and value['value_kind'] == 'fear'
        assert value['beneficiary'] == ALLY and value['selected'] == 4
        # The shipped typed save represents its flat additions as a reduced DC.
        assert save.payload['dc'] == 16 - 4


def test_initial_source_projection_preserves_one_pb_maximum_hp(tmp_path):
    from non_sphere_authority.foundation_mechanics import resolve_initial_foundation_mechanics, verified_foundation_records
    from stage2.formulas import evaluate_formula
    from tests.h1_support import sheet
    from combat.factory_compiler import compile_character
    identity = 'origin_spirit_body_v0_2B'
    record = verified_foundation_records()[identity]
    projection = resolve_initial_foundation_mechanics(record, ['tianxia.path.spirit_awakening'], stage='Awakened')
    contribution = sum(evaluate_formula(r['formula']['root'], {'pb': 4}).value
                       for r in projection['hp_maximum_modifiers'] if r['availability'] == 'available')
    assert contribution == 4
    document = sheet([VESSEL, LIFE], cl=15, foundation={'foundation_id': identity, 'stage': 'Awakened', 'mechanics': projection})
    document['ability_scores_and_statistics']['hit_points']['maximum'] = 60 + contribution
    bundle = compile_character(document, actor_id=OWNER, reaction_plan={'ask': True})
    combat, table, mid = fixture(tmp_path, [VESSEL, LIFE], owner_bundle=bundle)
    assert reload(tmp_path, mid).state.actors[OWNER].maximum_hp == 64
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    assert reload(tmp_path, mid).state.actors[OWNER].maximum_hp == 64


@pytest.mark.parametrize('purpose', ['rhythm', 'drain', 'curse_pressure', 'spiritual_exhaustion', 'stabilization', None])
def test_native_table_fact_qualifies_one_actual_suppression_check(tmp_path, purpose):
    method = 'tianxia.talent.life.reopen_the_living_meridian'
    context_choice = 'choice:needle.origin_spirit_support_context'
    def prepare(bundles):
        # This is an actual engine condition blocking recovery and talents.
        # No test-only support tags are supplied. The native controller must
        # obtain the scene consequence from its table response below.
        add_action(bundles[2], 'Seal the patient', [{'type': 'condition', 'condition': 'hollowed',
            'applies_to': 'target', 'duration': {'kind': 'until_removed'}}])
    combat, table, mid = fixture(tmp_path, [VESSEL, method], bundle_transform=prepare, named=True)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Seal the patient', target=ALLY).candidate_id)
    turn(table, mid, OWNER)
    chosen = candidate(combat, mid, 'Reopen the Living Meridian', target=ALLY)
    before = reload(tmp_path, mid).state.model_dump(mode='json')
    from tests.worker2_support import act
    for _ in range(2):
        assert act(table, mid, chosen.candidate_id)['status'] == 'REACTION_REQUIRED'
        assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
    prompts = settle(table, mid, chosen.candidate_id, picks={context_choice: purpose, CHOICE: 'increase'})
    engine = reload(tmp_path, mid)
    found = receipts(engine)
    assert len(found) == int(purpose is not None)
    contexts = [e for e in engine.events if e.payload.get('receipt_kind') == 'origin_spirit_support_context']
    assert len(contexts) == int(purpose is not None)
    if found:
        fact, value = contexts[0].payload, found[0].payload
        assert fact['method'] == method and fact['support_purpose'] == purpose
        assert fact['beneficiary'] == ALLY and fact['condition_source']
        assert value['method'] == method and value['value_kind'] == purpose
        assert value['selected'] == value['original'] + 4
        check = next(e for e in reversed(engine.events) if e.event_type == 'CHECK_ROLLED' and e.actor_id == OWNER)
        assert value['final_result'] == check.payload['actor']['total']
        assert engine.state.actors[OWNER].turn_flags[ROUND] == engine.state.round_number
    else:
        assert ROUND not in engine.state.actors[OWNER].turn_flags
    prompt = next(p for p in prompts if p['context']['reaction_source_id'] == context_choice)
    assert all(word in str(prompt) for word in ('Origin-Spirit Vessel', 'Reopen the Living Meridian', 'Tobin'))


def test_native_concentration_penalty_check_uses_represented_consequence(tmp_path):
    method = 'tianxia.talent.life.reopen_the_living_meridian'
    def prepare(bundles):
        add_action(bundles[2], 'Disrupt Concentration', [{'type': 'disadvantage',
            'on': 'Concentration saving throws', 'applies_to': 'target',
            'duration': {'kind': 'until_removed'}}])
    combat, table, mid = fixture(tmp_path, [VESSEL, method], bundle_transform=prepare, named=True)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Disrupt Concentration', target=ALLY).candidate_id)
    turn(table, mid, OWNER)
    prompts = settle(table, mid, candidate(combat, mid, 'Reopen the Living Meridian', target=ALLY).candidate_id,
                     picks={CHOICE: 'increase'})
    value = receipts(reload(tmp_path, mid))[-1].payload
    assert value['method'] == method and value['value_kind'] == 'concentration'
    assert value['selected'] == value['original'] + 4
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.origin_spirit_support_context' for p in prompts)


def test_native_fount_release_uses_shared_ordinary_healing_consumer(tmp_path):
    talent = 'tianxia.talent.life.fount_of_life'
    combat, table, mid = fixture(tmp_path, [VESSEL, talent], bundle_transform=wound, named=True)
    settle(table, mid, candidate(combat, mid, 'Prepare wound', target=ALLY).candidate_id, picks={CHOICE: None})
    settle(table, mid, candidate(combat, mid, 'Mend the Pulse + Fount of Life', target=OWNER).candidate_id)
    assert not receipts(reload(tmp_path, mid))
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Release Fount of Life', target=ALLY).candidate_id,
           picks={CHOICE: 'increase'})
    engine = reload(tmp_path, mid)
    value = receipts(engine)[-1].payload
    assert value['method'] == talent and value['value_kind'] == 'healing'
    assert value['selected'] == value['original'] + 4
    assert value['final_result'] == value['selected']


def test_native_borrowed_breath_keeps_printed_missing_hp_cap(tmp_path):
    def prepare(bundles):
        add_action(bundles[0], 'Small wound', [{'type': 'damage', 'flat': 1,
            'damage_types': ['force'], 'applies_to': 'target'}])
    combat, table, mid = fixture(tmp_path, [VESSEL, LIFE], bundle_transform=prepare, named=True)
    settle(table, mid, candidate(combat, mid, 'Small wound', target=ALLY).candidate_id, picks={CHOICE: None})
    engine = reload(tmp_path, mid)
    missing = engine.state.actors[ALLY].maximum_hp - engine.state.actors[ALLY].current_hp
    assert missing == 1
    settle(table, mid, candidate(combat, mid, 'Borrowed Breath', target=ALLY).candidate_id,
           picks={CHOICE: 'increase'})
    engine = reload(tmp_path, mid)
    value = receipts(engine)[-1].payload
    assert engine.state.actors[ALLY].temporary_hp <= missing
    assert value['selected'] == value['original'] + 4
    assert value['final_result'] <= missing


@pytest.mark.parametrize('key_score, expected', [(1, 3), (14, 10)])
def test_native_foundation_guard_uses_signed_value_before_floor(tmp_path, key_score, expected):
    from tests.h1_support import sheet
    from combat.factory_compiler import compile_character
    from tests.worker2_support import sealed_native_attack
    from tests.cw2_service_support import seal
    bundle = source_bound_owner([VESSEL, LIFE], score=key_score)
    def prepare(bundles):
        sealed_native_attack(bundles[2], 'Incoming strike', modifier=30, attack_bonus=100, range_ft=60)
        for b in bundles:
            b['actor_template']['initiative_bonus'] = 1000 if b['actor_id'] == OWNER else -1000
            seal(b)
    combat, table, mid = fixture(tmp_path, [VESSEL, LIFE], owner_bundle=bundle, bundle_transform=prepare, named=True)
    settle(table, mid, candidate(combat, mid, 'Borrowed Breath + Greater Invigorate', target=ALLY).candidate_id,
           picks={CHOICE: None})
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Incoming strike', target=ALLY).candidate_id,
           picks={'reaction:typed.foundation.origin_spirit_body_v0_2B.returning_source_guard': 'use', CHOICE: 'increase'})
    value = receipts(reload(tmp_path, mid))[-1].payload
    assert value['method'].endswith('.returning_source_guard')
    assert value['original'] == 4 + (key_score - 10) // 2
    assert value['selected'] == expected and value['final_result'] == expected
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources['resource:foundation.spirit_source_dew'] == 0
    assert not engine.state.actors[OWNER].reaction_available


def test_native_granted_check_value_asks_provider_on_beneficiary_turn(tmp_path):
    from tests.worker2_support import sealed_native_attack
    from tests.cw2_service_support import seal
    def prepare(bundles):
        sealed_native_attack(bundles[2], 'Incoming strike', modifier=30, attack_bonus=100, range_ft=60)
        add_action(bundles[1], 'Resolve the check', [{'type': 'contest_against', 'applies_to': 'target',
            'actor_check': {'kind': 'check', 'ability': 'CON',
                            'hazards': ['maintain:technique_rhythm']},
            'target_check': {'kind': 'dc'}, 'on_success': [], 'on_fail': []}])
        for b in bundles:
            b['actor_template']['initiative_bonus'] = {OWNER: 1000, FOE: 0, ALLY: -1000}[b['actor_id']]
            seal(b)
    combat, table, mid = fixture(tmp_path, [VESSEL, LIFE], owner_bundle=source_bound_owner([VESSEL, LIFE]),
                                bundle_transform=prepare, named=True)
    settle(table, mid, candidate(combat, mid, 'Borrowed Breath + Greater Invigorate', target=ALLY).candidate_id,
           picks={CHOICE: None})
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Incoming strike', target=ALLY).candidate_id,
           picks={'reaction:typed.foundation.origin_spirit_body_v0_2B.returning_source_guard': 'use', CHOICE: None})
    turn(table, mid, ALLY)
    prompts = settle(table, mid, candidate(combat, mid, 'Resolve the check', target=FOE).candidate_id,
                     picks={'choice:needle.origin_spirit_support_context': 'rhythm', CHOICE: 'increase'})
    engine = reload(tmp_path, mid)
    value = receipts(engine)[-1].payload
    assert value['method'].endswith('.returning_source_guard') and value['value_kind'] == 'rhythm'
    assert value['beneficiary'] == ALLY and value['selected'] == value['original'] + 4
    check = next(e for e in reversed(engine.events) if e.event_type == 'CHECK_ROLLED' and e.actor_id == ALLY)
    assert check.payload['actor']['total'] == value['final_result']
    assert any(p['context']['reactor_id'] == OWNER and p['context']['reaction_source_id'] == CHOICE for p in prompts)


def test_declined_native_guard_never_selects_or_spends_a_support_value(tmp_path):
    from tests.worker2_support import sealed_native_attack
    def prepare(bundles):
        sealed_native_attack(bundles[2], 'Incoming strike', modifier=30, attack_bonus=100, range_ft=60)
    combat, table, mid = fixture(tmp_path, [VESSEL, LIFE], owner_bundle=source_bound_owner([VESSEL, LIFE]),
                                bundle_transform=prepare, named=True)
    settle(table, mid, candidate(combat, mid, 'Borrowed Breath + Greater Invigorate', target=ALLY).candidate_id,
           picks={CHOICE: None})
    turn(table, mid, FOE)
    before = reload(tmp_path, mid)
    dew = before.state.actors[OWNER].resources['resource:foundation.spirit_source_dew']
    prompts = settle(table, mid, candidate(combat, mid, 'Incoming strike', target=ALLY).candidate_id,
        picks={'reaction:typed.foundation.origin_spirit_body_v0_2B.returning_source_guard': None, CHOICE: 'increase'})
    engine = reload(tmp_path, mid)
    assert not receipts(engine) and ROUND not in engine.state.actors[OWNER].turn_flags
    assert engine.state.actors[OWNER].resources['resource:foundation.spirit_source_dew'] == dew
    assert engine.state.actors[OWNER].reaction_available
    assert not any(p['context']['reaction_source_id'] == CHOICE for p in prompts)


def test_actual_ai_preserves_unknown_support_consequence(tmp_path):
    from tests.test_a2_daemonic import select_native_primary
    method = 'tianxia.talent.life.reopen_the_living_meridian'
    def prepare(bundles):
        add_action(bundles[2], 'Seal the patient', [{'type': 'condition', 'condition': 'hollowed',
            'applies_to': 'target', 'duration': {'kind': 'until_removed'}}])
    combat, table, mid = fixture(tmp_path, [VESSEL, method], bundle_transform=prepare, named=True)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Seal the patient', target=ALLY).candidate_id)
    turn(table, mid, OWNER)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    select_native_primary(combat, mid, 'Reopen the Living Meridian', ALLY)
    prompts = settle(table, mid, '', auto=True)
    engine = reload(tmp_path, mid)
    assert not receipts(engine)
    assert not any(e.payload.get('receipt_kind') == 'origin_spirit_support_context' for e in engine.events)
    assert not any(p['context']['reaction_source_id'] in (CHOICE, 'choice:needle.origin_spirit_support_context') for p in prompts)


def test_canonical_labels_without_native_compile_snapshot_never_qualify(tmp_path):
    def prepare(bundles):
        add_action(bundles[0], 'Label-only support', [{'type': 'temp_hp', 'flat': 7, 'applies_to': 'target'}],
                   typed={'source': 'LIFE_BASE_BORROWED_BREATH', 'sphere': 'tianxia.sphere.life'})
    combat, table, mid = fixture(tmp_path, [VESSEL, LIFE], bundle_transform=prepare)
    prompts = settle(table, mid, candidate(combat, mid, 'Label-only support', target=ALLY).candidate_id,
                     picks={CHOICE: 'increase'})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ALLY].temporary_hp == 7
    assert not receipts(engine) and ROUND not in engine.state.actors[OWNER].turn_flags
    assert not any(p['context']['reaction_source_id'] == CHOICE for p in prompts)
