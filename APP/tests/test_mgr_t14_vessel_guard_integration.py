"""Paid scoped Guard support reaches Vessel without broadening roll eligibility."""
import pytest

from tests.cw2_service_support import add_action, seal
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload, act
from tests.test_mgr_t14_spirit_vessel_parent import source_bound_owner, receipts
from tests.test_mgr_t14_spirit_vessel_value import VESSEL, LIFE, CHOICE, ROUND
from combat.ext.returning_source_guard import GUARD, CONDITION

REACTION = 'reaction:typed.' + GUARD


def guarded(tmp_path, *, concentrating=False, donors=1):
    talents = [LIFE, VESSEL]
    extra = 'actor:factory.worker2-ally3'
    def prepare(bundles):
        if donors == 2:
            bundles[3] = source_bound_owner(talents, actor_id=extra)
        add_action(bundles[2], 'Incoming pressure', [
            {'type': 'damage', 'flat': 30, 'damage_types': ['force'], 'applies_to': 'target'}])
        for name, hazards in [('Maintain rhythm', ['maintain:technique_rhythm']),
                              ('Unrelated check', [])]:
            add_action(bundles[1], name, [{'type': 'contest_against', 'applies_to': 'target',
                'actor_check': {'kind': 'check', 'ability': 'CON', 'hazards': hazards},
                'target_check': {'kind': 'dc'}, 'on_success': [], 'on_fail': []}])
            # The model-seat case must see this declared scenario action in
            # its legal set; the setup helper defaults to human-only actions.
            bundles[1]['action_catalog'][-1]['parameters']['player_only'] = False
        add_action(bundles[1], 'Maintained technique', [])
        bundles[1]['action_catalog'][-1]['target_kind'] = 'SELF'
        bundles[1]['action_catalog'][-1]['parameters']['typed']['duration'] = {
            'kind': 'minutes', 'amount': 1, 'concentration': True}
        for bundle in bundles:
            bundle['actor_template']['initiative_bonus'] = {OWNER: 1000, extra: 900, FOE: 0, ALLY: -1000}[bundle['actor_id']]
            seal(bundle)
    combat, table, mid = fixture(tmp_path, talents, owner_bundle=source_bound_owner(talents),
                                bundle_transform=prepare, named=True, seed='VESSEL-GUARD-INTEGRATION',
                                extra_allies=donors - 1)
    if concentrating:
        turn(table, mid, ALLY)
        settle(table, mid, candidate(combat, mid, 'Maintained technique', target=ALLY).candidate_id)
        turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Borrowed Breath + Greater Invigorate', target=ALLY).candidate_id,
           picks={CHOICE: None})
    if donors == 2:
        turn(table, mid, extra)
        settle(table, mid, candidate(combat, mid, 'Borrowed Breath + Greater Invigorate', target=OWNER).candidate_id,
               picks={CHOICE: None})
    turn(table, mid, FOE)
    return combat, table, mid


@pytest.mark.parametrize('scenario', ['accept', 'decline', 'automatic_provider', 'automatic_beneficiary'])
def test_paid_scoped_guard_roll_selects_one_vessel_value(tmp_path, monkeypatch, scenario):
    combat, table, mid = guarded(tmp_path)
    settle(table, mid, candidate(combat, mid, 'Incoming pressure', target=ALLY).candidate_id,
           picks={REACTION: 'first', CHOICE: None})
    engine = reload(tmp_path, mid)
    grant = next(c for c in engine.state.actors[ALLY].conditions.values() if c.condition_id == CONDITION)
    assert grant.source_actor_id == OWNER and grant.source_definition_id == GUARD
    assert not receipts(engine)
    turn(table, mid, ALLY)
    if scenario == 'automatic_provider':
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    cid = candidate(combat, mid, 'Maintain rhythm', target=FOE).candidate_id
    if scenario == 'accept':
        before = combat._load_session(mid).engine.state.model_dump(mode='json')
        for _ in range(2):
            assert act(table, mid, cid)['status'] == 'REACTION_REQUIRED'
            assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
    if scenario == 'automatic_beneficiary':
        from combat.gate4_adapters import ManualControllerAdapter
        source = candidate(combat, mid, 'Maintain rhythm', target=FOE).source_definition_id
        combat.set_controller_mode(mid, actor_id=ALLY, controller_mode='LOCAL_AUTO')
        monkeypatch.setattr(combat.controller, 'choose_primary_action',
            lambda context: ManualControllerAdapter(lambda _: (next(
                c.candidate_id for c in context.legal_candidates
                if c.source_definition_id == source and c.target_ids == (FOE,)), ()))
            .choose_primary_action(context))
    prompts = settle(table, mid, cid, picks={CHOICE: None if scenario == 'decline' else 'increase'},
                     auto=scenario == 'automatic_beneficiary')
    engine = reload(tmp_path, mid)
    found = receipts(engine)
    increased = scenario != 'decline'
    assert len(found) == int(increased)
    checks = [e for e in engine.events if e.event_type == 'CHECK_ROLLED' and e.actor_id == ALLY]
    assert checks[-1].payload['actor']['mode'] == 'ADVANTAGE'
    assert not any(c.condition_id == CONDITION for c in engine.state.actors[ALLY].conditions.values())
    assert (ROUND in engine.state.actors[OWNER].turn_flags) == increased
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.origin_spirit_support_context' for p in prompts)
    choices = [p for p in prompts if p['context']['reaction_source_id'] == CHOICE]
    assert bool(choices) == (scenario != 'automatic_provider')
    if choices:
        assert choices[-1]['context']['reactor_id'] == OWNER
        assert 'Returning Source Guard' in str(choices[-1]) and 'Tobin' in str(choices[-1])
    if increased:
        value = found[0].payload
        assert value['method'] == GUARD and value['beneficiary'] == ALLY and value['value_kind'] == 'rhythm'
        assert value['selected'] == value['original'] + 4
        assert value['final_result'] == checks[-1].payload['actor']['total']
        assert len(value['method_text_sha256']) == 64
    # The paid next-check grant is consumed independently of selecting Vessel.
    combat.set_controller_mode(mid, actor_id=ALLY, controller_mode='MANUAL')
    settle(table, mid, candidate(combat, mid, 'Maintain rhythm', target=FOE).candidate_id,
           picks={CHOICE: 'increase'})
    engine = reload(tmp_path, mid)
    assert len(receipts(engine)) == int(increased)
    check = next(e for e in reversed(engine.events) if e.event_type == 'CHECK_ROLLED' and e.actor_id == ALLY)
    assert check.payload['actor']['mode'] == 'NORMAL'


def test_two_native_donors_keep_both_vessel_choices_reachable(tmp_path):
    combat, table, mid = guarded(tmp_path, donors=2)
    # The native damage checkpoint admits one paid Guard per packet. Two
    # separate events leave the two donors' promises available on this roll.
    for _ in range(2):
        settle(table, mid, candidate(combat, mid, 'Incoming pressure', target=ALLY).candidate_id,
               picks={REACTION: 'first', CHOICE: None})
    engine = reload(tmp_path, mid)
    assert len([c for c in engine.state.actors[ALLY].conditions.values() if c.condition_id == CONDITION]) == 2
    turn(table, mid, ALLY)
    prompts = settle(table, mid, candidate(combat, mid, 'Maintain rhythm', target=FOE).candidate_id,
                     picks={CHOICE: 'increase'})
    engine = reload(tmp_path, mid)
    found = receipts(engine)
    providers = {OWNER, 'actor:factory.worker2-ally3'}
    assert len(found) == 2 and {e.actor_id for e in found} == providers
    assert {p['context']['reactor_id'] for p in prompts
            if p['context']['reaction_source_id'] == CHOICE} == providers
    assert found[1].payload['original'] == found[0].payload['selected']
    assert all(e.payload['selected'] == e.payload['original'] + 4 for e in found)
    check = next(e for e in reversed(engine.events) if e.event_type == 'CHECK_ROLLED' and e.actor_id == ALLY)
    assert check.payload['actor']['total'] == found[-1].payload['final_result']


def test_unrelated_roll_preserves_guard_and_vessel_for_actual_rhythm(tmp_path):
    combat, table, mid = guarded(tmp_path)
    settle(table, mid, candidate(combat, mid, 'Incoming pressure', target=ALLY).candidate_id,
           picks={REACTION: 'first', CHOICE: None})
    turn(table, mid, ALLY)
    prompts = settle(table, mid, candidate(combat, mid, 'Unrelated check', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    assert not receipts(engine) and ROUND not in engine.state.actors[OWNER].turn_flags
    assert any(c.condition_id == CONDITION for c in engine.state.actors[ALLY].conditions.values())
    assert not any(p['context']['reaction_source_id'] == CHOICE for p in prompts)
    settle(table, mid, candidate(combat, mid, 'Maintain rhythm', target=FOE).candidate_id,
           picks={CHOICE: 'increase'})
    assert len(receipts(reload(tmp_path, mid))) == 1


def test_paid_guard_concentration_selects_actual_native_save(tmp_path):
    combat, table, mid = guarded(tmp_path, concentrating=True)
    prompts = settle(table, mid, candidate(combat, mid, 'Incoming pressure', target=ALLY).candidate_id,
                     picks={REACTION: 'first', CHOICE: (None, 'increase')})
    engine = reload(tmp_path, mid)
    value = receipts(engine)[-1].payload
    assert len(receipts(engine)) == 1 and value['method'] == GUARD
    assert value['value_kind'] == 'concentration' and value['beneficiary'] == ALLY
    assert value['selected'] == value['original'] + 4
    save = next(e for e in reversed(engine.events) if e.event_type == 'SAVE_ROLLED'
                and e.source_definition_id == 'system:combat.concentration')
    assert save.payload['mode'] == 'ADVANTAGE' and save.payload['total'] == value['final_result']
    assert any(p['context']['reactor_id'] == OWNER and p['context']['reaction_source_id'] == CHOICE for p in prompts)
    assert not any(c.condition_id == CONDITION for c in engine.state.actors[ALLY].conditions.values())
