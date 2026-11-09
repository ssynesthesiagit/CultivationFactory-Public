"""Native paid Guard receipt -> actual Concentration d20 -> cold replay."""
import pytest
from combat.canonical import canonical_sha256
try:
    from combat.ext.returning_source_guard import CONDITION, allowance
except ModuleNotFoundError as missing:
    # The exact integrated baseline has no Guard allowance plugin. Keeping
    # the regression importable there permits native fail-before evidence.
    if (missing.name != 'combat.ext.returning_source_guard'
            and not str(missing).startswith('combat.ext.returning_source_guard is absent from Git tree ')):
        raise
    CONDITION = 'condition:typed.returning_source_guard'
    def allowance(subject):
        return next((c for c in subject.conditions.values() if c.condition_id == CONDITION), None)
from tests.test_mgr_t14_ling_guard_sum import (GUARD, REACTION, DEW, owner_bundle,
                                             add_action, resolved, assert_guard_paid_before_new_dew,
                                             VESSEL_CHOICE)
from tests.worker2_support import ALLY, FOE, OWNER, fixture, candidate, settle, turn, reload


def setup(tmp_path, *, target=ALLY, concentrating=True, friendly=False, initial=1, owned=True):
    def delivery(bundles):
        add_action(bundles[2], 'Hostile strike', [
            {'type': 'damage', 'flat': 8, 'damage_types': ['force'], 'applies_to': 'target'}],
            target_kind='ANY_CREATURE')
        add_action(bundles[2], 'Unrelated save', [{'type': 'save', 'ability': 'CON',
                   'dc': 10, 'on_fail': [], 'on_success': [], 'applies_to': 'target'}])
        recipient = bundles[1] if target == ALLY else bundles[0]
        add_action(recipient, 'Maintained technique', [], target_kind='SELF')
        recipient['action_catalog'][-1]['parameters']['typed']['duration'] = {
            'kind': 'minutes', 'amount': 1, 'concentration': True}
        recipient.pop('bundle_sha256', None)
        recipient['bundle_sha256'] = canonical_sha256(recipient)
    combat, table, mid = fixture(tmp_path, [], seed='GUARD-PARENT',
        owner_bundle=owner_bundle(2, 8, initial) if owned else None, bundle_transform=delivery,
        team_overrides={FOE: 'team:factory'} if friendly else None)
    if concentrating:
        turn(table, mid, target)
        settle(table, mid, candidate(combat, mid, 'Maintained technique', target=target).candidate_id)
    return combat, table, mid


def test_unowned_guard_is_inert_through_native_damage_and_save(tmp_path):
    combat, table, mid = setup(tmp_path, owned=False)
    engine, prompts = hit(tmp_path, combat, table, mid)
    assert not [p for p in prompts if p['context']['reaction_source_id'] == REACTION]
    assert not [e for e in engine.events if e.event_type == 'REACTION_RESOLVED'
                and e.source_definition_id == GUARD]
    assert allowance(engine.state.actors[ALLY]) is None
    roll = next(e for e in engine.events if e.event_type == 'SAVE_ROLLED'
                and e.source_definition_id == 'system:combat.concentration')
    assert roll.payload['mode'] == 'NORMAL'


def hit(tmp_path, combat, table, mid, target=ALLY, use=True):
    turn(table, mid, FOE)
    cid = candidate(combat, mid, 'Hostile strike', target=target).candidate_id
    prompts = settle(table, mid, cid, picks={REACTION: 'first' if use else None, VESSEL_CHOICE: None})
    return reload(tmp_path, mid), prompts


@pytest.mark.parametrize('target,use,initial,mode', [
    (ALLY, True, 1, 'ADVANTAGE'), (OWNER, True, 1, 'NORMAL'),
    (ALLY, False, 1, 'NORMAL'), (ALLY, True, 0, 'NORMAL')])
def test_paid_guard_actual_concentration_once(tmp_path, target, use, initial, mode):
    combat, table, mid = setup(tmp_path, target=target, initial=initial)
    engine, prompts = hit(tmp_path, combat, table, mid, target, use)
    rolls = [e for e in engine.events if e.event_type == 'SAVE_ROLLED'
             and e.source_definition_id == 'system:combat.concentration'
             and e.actor_id == target]
    assert len(rolls) == 1
    assert rolls[0].payload['mode'] == mode
    assert allowance(engine.state.actors[target]) is None
    if use and initial and target == ALLY:
        assert_guard_paid_before_new_dew(engine)
    else:
        assert engine.state.actors[OWNER].resources[DEW] == (0 if use and initial else initial)
    if use and initial:
        assert resolved(engine).payload['reduction'] == 1
    reload(tmp_path, mid)


def test_friendly_damage_does_not_admit_guard(tmp_path):
    combat, table, mid = setup(tmp_path, concentrating=False, friendly=True)
    engine, prompts = hit(tmp_path, combat, table, mid)
    assert not prompts
    assert not [e for e in engine.events if e.event_type == 'REACTION_RESOLVED'
                and e.source_definition_id == GUARD]
    assert engine.state.actors[OWNER].resources[DEW] == 1


def test_guard_boon_persists_until_owner_next_start(tmp_path):
    combat, table, mid = setup(tmp_path, concentrating=False)
    engine, _ = hit(tmp_path, combat, table, mid)
    assert allowance(engine.state.actors[ALLY]) is not None
    assert allowance(engine.state.actors[OWNER]) is None
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert allowance(engine.state.actors[ALLY]) is None


def test_unrelated_constitution_save_preserves_the_allowance(tmp_path):
    def delivery(bundles):
        add_action(bundles[2], 'Strike then unrelated save', [
            {'type': 'damage', 'flat': 8, 'damage_types': ['force'], 'applies_to': 'target'},
            {'type': 'save', 'ability': 'CON', 'dc': 'technique_save_dc',
             'on_fail': [], 'on_success': [], 'applies_to': 'target'}])
    combat, table, mid = fixture(tmp_path, [], owner_bundle=owner_bundle(2, 8),
                               bundle_transform=delivery, seed='GUARD-UNRELATED')
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Strike then unrelated save', target=ALLY).candidate_id,
           picks={REACTION: 'first'})
    engine = reload(tmp_path, mid)
    roll = next(e for e in reversed(engine.events) if e.event_type == 'SAVE_ROLLED')
    assert roll.payload['mode'] == 'NORMAL'
    assert allowance(engine.state.actors[ALLY]) is not None


@pytest.mark.parametrize('purpose', ['concentration', 'technique_rhythm',
                                    'manifestation', 'formation', 'spiritual_control'])
def test_explicit_native_maintenance_check_consumes_once(tmp_path, purpose):
    """The supported-caller contract; production caller provenance is separate."""
    def delivery(bundles):
        add_action(bundles[2], 'Strike then maintain', [
            {'type': 'damage', 'flat': 8, 'damage_types': ['force'], 'applies_to': 'target'},
            {'type': 'contest_against', 'applies_to': 'target',
             'actor_check': {'kind': 'cultivation'},
             'target_check': {'kind': 'cultivation', 'hazards': ['maintain:' + purpose]},
             'on_success': [], 'on_fail': []},
            {'type': 'contest_against', 'applies_to': 'target',
             'actor_check': {'kind': 'cultivation'},
             'target_check': {'kind': 'cultivation', 'hazards': ['maintain:' + purpose]},
             'on_success': [], 'on_fail': []}])
    combat, table, mid = fixture(tmp_path, [], owner_bundle=owner_bundle(2, 8),
                               bundle_transform=delivery, seed='GUARD-CHECK')
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Strike then maintain', target=ALLY).candidate_id,
           picks={REACTION: 'first'})
    engine = reload(tmp_path, mid)
    checks = [e for e in engine.events if e.event_type == 'CHECK_ROLLED']
    assert len(checks) == 2
    assert [e.payload['target']['mode'] for e in checks] == ['ADVANTAGE', 'NORMAL']
    assert allowance(engine.state.actors[ALLY]) is None


@pytest.mark.parametrize('category,ability,mode', [('drain', 'CON', 'ADVANTAGE'),
    ('backlash', 'CON', 'ADVANTAGE'), ('unknown', 'CON', 'NORMAL'),
    ('drain', 'CHA', 'NORMAL')])
def test_source_bound_pressure_roll(tmp_path, category, ability, mode):
    """Actual typed packet/save transaction, including unknown facts left unknown."""
    def delivery(bundles):
        add_action(bundles[2], 'Repeated pressure', [
            {'type': 'damage', 'flat': 8, 'pressure_kind': category,
             'damage_types': ['force'], 'applies_to': 'target'},
            {'type': 'save', 'ability': ability, 'dc': 'technique_save_dc',
             'on_fail': [{'type': 'damage', 'flat': 1, 'pressure_kind': category,
                          'damage_types': ['force'], 'applies_to': 'target'}],
             'on_success': [], 'applies_to': 'target'}])
    combat, table, mid = fixture(tmp_path, [], owner_bundle=owner_bundle(2, 8),
                               bundle_transform=delivery, seed='GUARD-PRESSURE')
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Repeated pressure', target=ALLY).candidate_id,
           picks={REACTION: 'first'})
    engine = reload(tmp_path, mid)
    roll = next(e for e in reversed(engine.events) if e.event_type == 'SAVE_ROLLED')
    assert roll.payload['mode'] == mode
    held = allowance(engine.state.actors[ALLY])
    assert (held is None) == (mode == 'ADVANTAGE')
    if held:
        assert held.data['pressure_kind'] == category


def test_automatic_owner_takes_guard_without_a_human_prompt(tmp_path):
    combat, table, mid = setup(tmp_path)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    engine, prompts = hit(tmp_path, combat, table, mid)
    assert not [p for p in prompts if p['context']['reactor_id'] == OWNER]
    # An automatic full-Foundation owner also uses Vessel's available PB 2.
    # Preserve the signed base assertion so the original arithmetic bug still
    # fails even though the final paid reduction legitimately includes Vessel.
    value = next(e.payload for e in engine.events
                 if e.payload.get('receipt_kind') == 'origin_spirit_support_value')
    assert value['method'] == GUARD and value['original'] == 1 and value['selected'] == 3
    assert resolved(engine).payload['reduction'] == 3
    roll = next(e for e in engine.events if e.event_type == 'SAVE_ROLLED'
                and e.source_definition_id == 'system:combat.concentration')
    assert roll.payload['mode'] == 'ADVANTAGE'


def test_human_guard_choice_on_automatic_enemy_turn(tmp_path, monkeypatch):
    from combat.gate4_adapters import ManualControllerAdapter
    combat, table, mid = setup(tmp_path)
    turn(table, mid, FOE)
    row = candidate(combat, mid, 'Hostile strike', target=ALLY)
    cid = row.candidate_id
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode='LOCAL_AUTO')
    monkeypatch.setattr(combat.controller, 'choose_primary_action',
        lambda context: ManualControllerAdapter(lambda _: (next(c.candidate_id for c in context.legal_candidates
            if c.source_definition_id == row.source_definition_id and c.target_ids == (ALLY,)), ())).choose_primary_action(context))
    prompts = settle(table, mid, cid, picks={REACTION: 'first', VESSEL_CHOICE: None}, auto=True)
    assert any(p['context']['reactor_id'] == OWNER for p in prompts)
    assert 'Returning Source Guard' in str(prompts)
    engine = reload(tmp_path, mid)
    assert resolved(engine).payload['reduction'] == 1
    assert_guard_paid_before_new_dew(engine)


def test_repeated_preview_and_decline_are_pure(tmp_path):
    from combat.gate3_storage import canonical_state_sha256
    from tests.worker2_support import act
    combat, table, mid = setup(tmp_path, concentrating=False)
    turn(table, mid, FOE)
    cid = candidate(combat, mid, 'Hostile strike', target=ALLY).candidate_id
    before = canonical_state_sha256(reload(tmp_path, mid).state)
    for _ in range(2):
        prompt = act(table, mid, cid, [])
        assert prompt['status'] == 'REACTION_REQUIRED'
        assert canonical_state_sha256(reload(tmp_path, mid).state) == before
    settle(table, mid, cid, picks={REACTION: None})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[DEW] == 1
    assert engine.state.actors[OWNER].reaction_available
    assert allowance(engine.state.actors[ALLY]) is None


@pytest.mark.parametrize('invisible', [False, True])
def test_guard_geometry_and_visible_ally_admission(tmp_path, invisible):
    def delivery(bundles):
        add_action(bundles[2], 'Hostile strike', [
            {'type': 'damage', 'flat': 8, 'damage_types': ['force'], 'applies_to': 'target'}])
        add_action(bundles[0], 'Lose sight', [{'type': 'condition', 'condition': 'blinded',
            'applies_to': 'self', 'duration': {'kind': 'minutes', 'amount': 1}}], target_kind='SELF')
    combat, table, mid = fixture(tmp_path, [], owner_bundle=owner_bundle(2, 8),
        ally_position={'x': 11, 'y': 5} if not invisible else None,
        foe_position={'x': 10, 'y': 5} if not invisible else None,
        bundle_transform=delivery, seed='GUARD-GEOMETRY')
    if invisible:
        settle(table, mid, candidate(combat, mid, 'Lose sight', target=OWNER).candidate_id)
    engine, prompts = hit(tmp_path, combat, table, mid)
    assert not [p for p in prompts if p['context']['reactor_id'] == OWNER]
    assert engine.state.actors[OWNER].resources[DEW] == 1
    assert allowance(engine.state.actors[ALLY]) is None


def test_nonhostile_damage_threatening_a_maintained_ally_grants_only_the_roll(tmp_path):
    combat, table, mid = setup(tmp_path, friendly=True)
    engine, _ = hit(tmp_path, combat, table, mid)
    assert resolved(engine).payload['reduction'] == 0
    assert engine.state.actors[ALLY].current_hp == 52
    roll = next(e for e in engine.events if e.event_type == 'SAVE_ROLLED'
                and e.source_definition_id == 'system:combat.concentration')
    assert roll.payload['mode'] == 'ADVANTAGE'
    assert engine.state.actors[OWNER].resources[DEW] == 0


def test_prior_native_support_event_generates_dew_before_guard(tmp_path):
    def delivery(bundles):
        add_action(bundles[0], 'Earlier support', [
            {'type': 'temp_hp', 'flat': 1, 'applies_to': 'target'}], target_kind='ALLY_OR_SELF')
        add_action(bundles[2], 'Hostile strike', [
            {'type': 'damage', 'flat': 8, 'damage_types': ['force'], 'applies_to': 'target'}])
    combat, table, mid = fixture(tmp_path, [], owner_bundle=owner_bundle(2, 8, initial=0),
        bundle_transform=delivery, seed='GUARD-PRIOR-EVENT')
    settle(table, mid, candidate(combat, mid, 'Earlier support', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[DEW] == 1
    engine, _ = hit(tmp_path, combat, table, mid)
    assert resolved(engine).payload['reduction'] == 1
    assert engine.state.actors[OWNER].resources[DEW] == 0


def test_different_pressure_source_preserves_allowance(tmp_path):
    def delivery(bundles):
        add_action(bundles[2], 'Hostile strike', [
            {'type': 'damage', 'flat': 8, 'damage_types': ['force'], 'applies_to': 'target'}])
        add_action(bundles[2], 'Different drain source', [
            {'type': 'save', 'ability': 'CON', 'dc': 'technique_save_dc', 'on_success': [],
             'on_fail': [{'type': 'damage', 'flat': 1, 'pressure_kind': 'drain',
                          'damage_types': ['necrotic'], 'applies_to': 'target'}]}],
            economy='BONUS_ACTION')
    combat, table, mid = fixture(tmp_path, [], owner_bundle=owner_bundle(2, 8),
        bundle_transform=delivery, seed='GUARD-DIFFERENT-SOURCE')
    engine, _ = hit(tmp_path, combat, table, mid)
    assert allowance(engine.state.actors[ALLY]) is not None
    settle(table, mid, candidate(combat, mid, 'Different drain source', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    roll = next(e for e in reversed(engine.events) if e.event_type == 'SAVE_ROLLED')
    assert roll.payload['mode'] == 'NORMAL'
    assert allowance(engine.state.actors[ALLY]) is not None


def test_two_paid_donors_keep_independent_source_promises(tmp_path):
    from combat.ext.returning_source_guard import allowances
    extra = 'actor:factory.worker2-ally3'
    def delivery(bundles):
        bundles[3] = owner_bundle(2, 8, actor_id=extra)
        add_action(bundles[2], 'First pressure', [{'type': 'damage', 'flat': 2,
            'pressure_kind': 'drain', 'damage_types': ['force'], 'applies_to': 'target'}])
        add_action(bundles[2], 'Second pressure', [
            {'type': 'damage', 'flat': 2, 'pressure_kind': 'drain',
             'damage_types': ['force'], 'applies_to': 'target'},
            {'type': 'save', 'ability': 'CON', 'dc': 'technique_save_dc', 'on_success': [],
             'on_fail': [{'type': 'damage', 'flat': 1, 'pressure_kind': 'drain',
                          'damage_types': ['force'], 'applies_to': 'target'}]}], economy='BONUS_ACTION')
    combat, table, mid = fixture(tmp_path, [], owner_bundle=owner_bundle(2, 8),
        extra_allies=1, bundle_transform=delivery, seed='GUARD-TWO-DONORS')
    turn(table, mid, FOE)
    first = candidate(combat, mid, 'First pressure', target=ALLY)
    settle(table, mid, first.candidate_id, picks={REACTION: 'first'})
    settle(table, mid, candidate(combat, mid, 'Second pressure', target=ALLY).candidate_id,
           picks={REACTION: 'first'})
    engine = reload(tmp_path, mid)
    promises = allowances(engine.state.actors[ALLY])
    assert len(promises) == 1
    assert promises[0].data['pressure_source_id'] == first.source_definition_id
    roll = next(e for e in reversed(engine.events) if e.event_type == 'SAVE_ROLLED')
    assert roll.payload['mode'] == 'ADVANTAGE'
    assert_guard_paid_before_new_dew(engine)
    assert_guard_paid_before_new_dew(engine, extra)
