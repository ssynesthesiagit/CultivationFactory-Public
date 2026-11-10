"""Printed Karma Insight service/table commits, cold reload and replay.

Synthetic preparation actions are sealed before creation; no live engine mutation.
Every behavioral assertion reads a new CombatService session after execute_intent.
"""
import json
import zipfile
from pathlib import Path

import pytest

from combat.factory_compiler import compile_character, TYPED_AUTHORITY
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.ext import karma_insights as ki
from combat.ext.karma_imprints import held, RECORD
from combat.typed_executor import mark_condition_id
from tests.cw2_service_support import add_action, seal
from tests.h1_support import ROOT, sheet
from tests.worker2_support import OWNER, ALLY, FOE, candidate, settle, turn, reload, sealed_native_attack

FOE2 = 'actor:factory.karma-foe2'
CP = 'resource:core.qi'


def fight(tmp_path, insights, *, owner_ai=False, pb=4, ally_attack_bonus=-100, foe_ac=None,
          owner_x=3, owner_y=6, ally_x=4, ally_y=6, foe_x=6, foe_y=6,
          ally_features=(), ally_pools=None, ally_primary='Qi', save_dc=1000, save_ability='wis'):
    ids = [OWNER, ALLY, FOE, FOE2]
    docs = [sheet([RECORD], cl=10), sheet(list(ally_features), cl=10, primary=ally_primary), sheet([], cl=10), sheet([], cl=10)]
    docs[0]['spheres_and_talents']['cultivation_insight_record_ids'] = list(insights)
    docs[0]['identity']['proficiency_bonus'] = pb
    if foe_ac is not None:
        docs[2]['ability_scores_and_statistics']['armor_class']['base_value'] = foe_ac
    bundles = []
    for aid, doc in zip(ids, docs):
        folder = tmp_path / 'portable_characters' / aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        doc['ability_scores_and_statistics']['primary_resource']['maximum'] = 100
        doc['ability_scores_and_statistics']['hit_points']['maximum'] = 300
        with zipfile.ZipFile(folder / 'current.zip', 'w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
        bundles.append(compile_character(doc, actor_id=aid, reaction_plan={'ask': True}))
    for bundle, init in zip(bundles, [100, -100, 0, -200]):
        bundle['actor_template']['initiative_bonus'] = init
        seal(bundle)
    owner, ally, foe, foe2 = bundles
    for resource, amount in (ally_pools or {}).items():
        pool = next(r for r in ally['actor_template']['resources'] if r['resource_id'] == resource)
        # Synthetic pools are sealed like the fixture's 100 CP pool. Keep the
        # declared capacity valid when a test supplies a larger initial reserve.
        pool['maximum'] = max(pool['maximum'], amount)
        pool['initial'] = amount
    for kind in ('Debt', 'Grace'):
        add_action(owner, 'Seed ' + kind, [{'type': 'condition', 'condition': mark_condition_id(kind + ' Imprint', OWNER).removeprefix('condition:typed.'),
                                          'applies_to': 'target', 'duration': 'until_removed',
                                          'condition_data': {'cause': 'Prepared deed'}}])
    add_action(owner, 'Spend CP', [{'type': 'resource', 'resource': 'cp', 'amount': -20, 'applies_to': 'self'}], target='SELF')
    # Use a sealed actual CP cost rather than depending on a preparation effect.
    owner['action_catalog'][-1]['costs'] = [[CP, 20]]
    owner['action_catalog'][-1]['parameters']['typed']['effects'] = []
    add_action(owner, 'Finish debtor', [{'type': 'damage', 'flat': 500, 'damage_types': ['force'], 'applies_to': 'target'}])
    add_action(owner, 'Blind owner', [{'type': 'condition', 'condition': 'blinded', 'applies_to': 'self', 'duration': 'until_removed'}], target='SELF')
    add_action(foe, 'Harm', [{'type': 'damage', 'flat': 2, 'damage_types': ['force'], 'applies_to': 'target'}], target='HOSTILE_ENTITY')
    add_action(ally, 'Ally harm', [{'type': 'damage', 'flat': 2, 'damage_types': ['force'], 'applies_to': 'target'}], target='HOSTILE_ENTITY')
    add_action(foe, 'Fear', [{'type': 'condition', 'condition': 'frightened', 'applies_to': 'target', 'duration': 'until_removed'}], target='HOSTILE_ENTITY')
    add_action(foe, 'Demand save', [{'type': 'save', 'ability': save_ability, 'dc': save_dc,
                                  'on_fail': [{'type': 'damage', 'flat': 1, 'damage_types': ['force'], 'applies_to': 'target'}]}], target='HOSTILE_ENTITY')
    sealed_native_attack(ally, 'Ally miss', attack_bonus=ally_attack_bonus, modifier=1)
    # Known failed check with a real native ability-check context.
    add_action(ally, 'Hard check', [{'type': 'contest_against', 'actor_check': {'kind': 'check', 'ability': 'STR'},
                                    'target_check': {'kind': 'dc', 'dc': 1000}, 'on_success': [], 'on_fail': []}], target='HOSTILE_ENTITY')
    for bundle in bundles:
        seal(bundle)
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    modes = {aid: 'MANUAL' for aid in ids}
    mid = combat._finish_factory_match(bundles, ids,
        {OWNER: 'team:a', ALLY: 'team:a', FOE: 'team:b', FOE2: 'team:b'},
        {OWNER: {'x': owner_x, 'y': owner_y}, ALLY: {'x': ally_x, 'y': ally_y}, FOE: {'x': foe_x, 'y': foe_y}, FOE2: {'x': foe_x, 'y': foe_y + 1}},
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],
        [OWNER, ALLY], [FOE, FOE2], control_modes=modes, match_seed='A2KARMASEC',
        display_name='Karma second pass', maximum_rounds=15)['match_id']
    turn(table, mid, OWNER)
    return combat, table, mid


def use(combat, table, mid, name, target=None, picks=None):
    return settle(table, mid, candidate(combat, mid, name, target=target).candidate_id, picks)


def seed(combat, table, mid, target, kind='Debt', count=1):
    for _ in range(count):
        use(combat, table, mid, 'Seed ' + kind, target)


def test_reviewed_insights_are_owned_and_report_actual_coverage(tmp_path):
    c, t, mid = fight(tmp_path, [ki.COLLECT, ki.TRANSFER, ki.BORROW])
    engine = reload(tmp_path, mid)
    m = json.loads(Path(TYPED_AUTHORITY).read_text())['mechanics']
    bundle = next(b for b in engine.typed_bundle_documents if b['actor_id'] == OWNER)
    boundaries = bundle['diagnostics']['insights']
    assert all(r['status'] == ('partial' if r['id'] == ki.BORROW else 'automated') for r in boundaries)
    assert all(r['table_applies'] and r['table_applies'][0] != r['name'] for r in boundaries)
    for feature in (ki.COLLECT, ki.TRANSFER, ki.BORROW):
        assert ki.owned(engine, engine.state.actors[OWNER], feature)
        assert m[feature]['coverage'] == ('CORE_WITH_RIDERS' if feature == ki.BORROW else 'FULL')
        assert bool(m[feature]['riders']) == (feature == ki.BORROW)


@pytest.mark.parametrize('debts,insights,expected', [(3, [ki.COLLECT], 4), (2, [ki.COLLECT], 0), (3, [], 0)])
def test_debt_collector_drop_recovers_pb_only_with_owned_insight_and_three_debts(tmp_path, debts, insights, expected):
    c, t, mid = fight(tmp_path, insights)
    seed(c, t, mid, FOE, count=debts)
    use(c, t, mid, 'Spend CP', OWNER)
    before_engine = reload(tmp_path, mid)
    assert len(held(before_engine.state.actors[FOE], OWNER, 'debt')) == debts
    before = before_engine.state.actors[OWNER].resources[CP]
    use(c, t, mid, 'Finish debtor', FOE)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[CP] == before + expected
    assert engine.state.actors[FOE].current_hp == 0
    if expected:
        seed(c, t, mid, FOE2, count=3)
        use(c, t, mid, 'Finish debtor', FOE2)
        assert reload(tmp_path, mid).state.actors[OWNER].resources[CP] == before + expected


def test_debt_collector_does_not_reward_damage_to_already_down_debtor(tmp_path):
    c, t, mid = fight(tmp_path, [ki.COLLECT], owner_y=12, ally_y=11, foe_x=17, foe_y=12)
    seed(c, t, mid, FOE, count=3)
    use(c, t, mid, 'Spend CP', OWNER)
    # The debtor begins 70 feet away, outside Collector range.
    use(c, t, mid, 'Finish debtor', FOE)
    down = reload(tmp_path, mid)
    assert down.state.actors[FOE].current_hp == 0
    assert down.state.actors[OWNER].resources[CP] == 80
    # Move to 60 feet through the committed tabletop movement service.
    from combat.movement_routes import explicit_candidate, parse_waypoints
    path = [{'x': 3, 'y': 12}, {'x': 4, 'y': 12}, {'x': 5, 'y': 12}]
    route = explicit_candidate(c._load_session(mid).engine, OWNER, parse_waypoints(path))
    menu = t.state(mid)['menu']
    moved = t.act(mid, route.candidate_id, menu['decision_id'], menu['state_version'],
                  t.state(mid)['last_sequence'], movement_path=path, actor_id=OWNER)
    assert moved['status'] == 'COMMITTED'
    use(c, t, mid, 'Finish debtor', FOE)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[CP] == 80
    assert not any(c.condition_id == ki.COLLECT_USED for c in engine.state.actors[OWNER].conditions.values())


def test_borrowed_merit_manual_choices_do_not_depend_on_ledger_owner_sight(tmp_path):
    c, t, mid = fight(tmp_path, [ki.BORROW])
    seed(c, t, mid, FOE, 'Grace')
    seed(c, t, mid, ALLY, 'Grace')
    use(c, t, mid, 'Blind owner', OWNER)
    turn(t, mid, FOE)
    prompts = use(c, t, mid, 'Demand save', ALLY,
                  {'reaction:typed.' + ki.BORROW: 'use', 'choice:needle.karma_borrow_accept': 'accept'})
    engine = reload(tmp_path, mid)
    assert not held(engine.state.actors[FOE], OWNER, 'grace')
    assert len(held(engine.state.actors[ALLY], OWNER, 'grace')) == 1
    assert len([r for r in engine.rolls if r.reason == 'BORROWED_MERIT']) == 1
    assert any(p['context']['reactor_id'] == FOE for p in prompts)
    assert any(p['context']['reactor_id'] == ALLY for p in prompts)


@pytest.mark.parametrize('ability', ['Harm', 'Fear'])
@pytest.mark.parametrize('ai', [False, True])
def test_accountant_transfers_enemy_debt_with_both_sides_in_range_and_reload_limit(tmp_path, ability, ai):
    c, t, mid = fight(tmp_path, [ki.TRANSFER], owner_ai=ai)
    seed(c, t, mid, FOE)
    seed(c, t, mid, FOE2, count=2)
    seed(c, t, mid, ALLY)  # Never an automatic donor, despite carrying a Debt.
    before = reload(tmp_path, mid)
    first_donor = FOE2 if ai else ALLY
    original = held(before.state.actors[first_donor], OWNER, 'debt')[0][1]
    turn(t, mid, FOE)
    if ai:
        c.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    prompts = use(c, t, mid, ability, ALLY, { 'choice:needle.karma_accountant': FOE2 if ai else ALLY })
    engine = reload(tmp_path, mid)
    assert len(held(engine.state.actors[FOE], OWNER, 'debt')) == 2 + int(ai)
    assert len(held(engine.state.actors[FOE2], OWNER, 'debt')) == 2 - int(ai)
    assert len(held(engine.state.actors[ALLY], OWNER, 'debt')) == int(ai)
    moved = next(c for _, c in held(engine.state.actors[FOE], OWNER, 'debt')
                 if c.source_definition_id == original.source_definition_id)
    assert moved.data == original.data
    assert moved.source_definition_id == original.source_definition_id
    assert moved.expires_on == original.expires_on
    if not ai:
        p = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.karma_accountant')
        assert ALLY in [o['id'] for o in p['choice']['options']]
        assert p['action'] == ability
        assert ability in p['moment'] and 'caused harm' in p['moment']
    # New service reads a saved allowance, not a process-local transfer cache.
    c = CombatService(ROOT, tmp_path); t = TabletopService(c, tmp_path)
    use(c, t, mid, 'Harm', ALLY)
    assert len(held(reload(tmp_path, mid).state.actors[FOE], OWNER, 'debt')) == 2 + int(ai)
    if ai:
        c.set_controller_mode(mid, actor_id=OWNER, controller_mode='MANUAL')
    turn(t, mid, OWNER); turn(t, mid, FOE)
    if ai:
        c.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    use(c, t, mid, 'Harm', ALLY, {'choice:needle.karma_accountant': FOE2})
    assert len(held(reload(tmp_path, mid).state.actors[FOE], OWNER, 'debt')) == 3 + int(ai)


def test_accountant_can_decline_and_never_exceeds_capacity(tmp_path):
    c, t, mid = fight(tmp_path, [ki.TRANSFER], pb=2)
    seed(c, t, mid, FOE); seed(c, t, mid, FOE2)
    turn(t, mid, FOE)
    use(c, t, mid, 'Harm', ALLY, {'choice:needle.karma_accountant': None})
    assert len(held(reload(tmp_path, mid).state.actors[FOE], OWNER, 'debt')) == 1
    use(c, t, mid, 'Harm', ALLY, {'choice:needle.karma_accountant': FOE2})
    assert len(held(reload(tmp_path, mid).state.actors[FOE], OWNER, 'debt')) == 2


def test_accountant_automatic_owner_keeps_enemy_only_cause_policy(tmp_path):
    c, t, mid = fight(tmp_path, [ki.TRANSFER])
    seed(c, t, mid, ALLY)
    seed(c, t, mid, FOE2)
    turn(t, mid, ALLY)
    c.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    use(c, t, mid, 'Ally harm', FOE)
    engine = reload(tmp_path, mid)
    assert len(held(engine.state.actors[ALLY], OWNER, 'debt')) == 1
    assert len(held(engine.state.actors[FOE2], OWNER, 'debt')) == 1
    assert not any(e.event_type == 'CONDITION_REMOVED' and e.payload.get('reason') == 'IMPRINT_TRANSFERRED'
                   for e in engine.events)


@pytest.mark.parametrize('ai', [False, True])
def test_borrowed_merit_save_preserves_natural_and_spends_only_donor_grace(tmp_path, ai):
    c, t, mid = fight(tmp_path, [ki.BORROW], owner_ai=ai)
    for target in (OWNER, ALLY):
        seed(c, t, mid, target, 'Grace')
    turn(t, mid, FOE)
    if ai:
        c.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    prompts = use(c, t, mid, 'Demand save', ALLY, {'reaction:typed.' + ki.BORROW: 'use'})
    engine = reload(tmp_path, mid)
    donor_roll = next(r for r in engine.rolls if r.reason == 'BORROWED_MERIT')
    rewritten = [e for e in engine.events if e.event_type == 'D20_REWRITTEN' and e.source_definition_id == ki.BORROW]
    assert len(rewritten) == 1
    payload = rewritten[0].payload
    assert payload['result']['natural_result'] == payload['original']['natural_result']
    assert payload['result']['total'] == payload['original']['total'] + donor_roll.total
    assert not held(engine.state.actors[OWNER], OWNER, 'grace')
    assert len(held(engine.state.actors[ALLY], OWNER, 'grace')) == 1
    assert not held(engine.state.actors[FOE], OWNER, 'grace')
    assert engine.state.actors[OWNER].turn_flags[ki.BORROW_USED] == engine.state.round_number
    assert any(p['context']['reactor_id'] == ALLY and p['context']['reaction_source_id'] == 'choice:needle.karma_borrow_accept' for p in prompts)
    consent = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.karma_borrow_accept')
    assert consent['action'] == 'Demand save'
    assert 'Demand save' in consent['moment'] and 'saving throw' in consent['moment']
    assert 'spends that Grace Imprint' in consent['moment']
    use(c, t, mid, 'Demand save', ALLY, {'reaction:typed.' + ki.BORROW: 'use'})
    assert len([r for r in reload(tmp_path, mid).rolls if r.reason == 'BORROWED_MERIT']) == 1


@pytest.mark.parametrize('decline', ['donor', 'roller'])
def test_borrowed_merit_decline_preserves_grace_and_round_allowance(tmp_path, decline):
    c, t, mid = fight(tmp_path, [ki.BORROW])
    seed(c, t, mid, OWNER, 'Grace'); seed(c, t, mid, ALLY, 'Grace')
    turn(t, mid, FOE)
    picks = {'reaction:typed.' + ki.BORROW: None if decline == 'donor' else 'use',
             'choice:needle.karma_borrow_accept': None if decline == 'roller' else 'accept'}
    use(c, t, mid, 'Demand save', ALLY, picks)
    engine = reload(tmp_path, mid)
    assert len(held(engine.state.actors[OWNER], OWNER, 'grace')) == 1
    assert ki.BORROW_USED not in engine.state.actors[OWNER].turn_flags


def test_borrowed_merit_manual_enemy_donor_is_legal_with_both_consents_and_reload(tmp_path):
    c, t, mid = fight(tmp_path, [ki.BORROW])
    seed(c, t, mid, ALLY, 'Grace')
    seed(c, t, mid, FOE, 'Grace')
    turn(t, mid, FOE)
    prompts = use(c, t, mid, 'Demand save', ALLY,
                  {'reaction:typed.' + ki.BORROW: 'use', 'choice:needle.karma_borrow_accept': 'accept'})
    engine = reload(tmp_path, mid)
    assert not held(engine.state.actors[FOE], OWNER, 'grace')
    assert len(held(engine.state.actors[ALLY], OWNER, 'grace')) == 1
    assert len([r for r in engine.rolls if r.reason == 'BORROWED_MERIT']) == 1
    donor = next(p for p in prompts if p['context']['reaction_source_id'] == 'reaction:typed.' + ki.BORROW)
    roller = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.karma_borrow_accept')
    assert donor['context']['reactor_id'] == FOE
    assert roller['action'] == 'Demand save'


def test_borrowed_merit_attack_bonus_turns_near_miss_into_hit_after_reload(tmp_path, monkeypatch):
    from combat.gate2_rolls import DeterministicRollAuthority
    raw_d20 = DeterministicRollAuthority.raw_d20

    def natural_nine(self, *, modifier, actor_id, reason, mode='NORMAL'):
        roll = raw_d20(self, modifier=modifier, actor_id=actor_id, reason=reason, mode=mode)
        if actor_id == ALLY and reason.startswith('ATTACK:'):
            return roll.model_copy(update={'dice': (9,), 'natural_result': 9, 'total': 9 + modifier})
        return roll

    monkeypatch.setattr(DeterministicRollAuthority, 'raw_d20', natural_nine)
    c, t, mid = fight(tmp_path, [ki.BORROW], ally_attack_bonus=0, foe_ac=10)
    seed(c, t, mid, OWNER, 'Grace'); seed(c, t, mid, ALLY, 'Grace')
    turn(t, mid, ALLY)
    prompts = use(c, t, mid, 'Ally miss', FOE, {'reaction:typed.' + ki.BORROW: 'use'})
    engine = reload(tmp_path, mid)
    donated = next(r for r in engine.rolls if r.reason == 'BORROWED_MERIT')
    attacks = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == ALLY]
    rewritten = next(e for e in engine.events if e.event_type == 'D20_REWRITTEN' and e.source_definition_id == ki.BORROW)
    assert rewritten.payload['original']['natural_result'] == attacks[-1].payload['natural_result'] == 9
    assert rewritten.payload['result']['natural_result'] == 9
    assert rewritten.payload['original']['total'] == 9
    assert attacks and attacks[-1].payload['total'] == 9 + donated.total
    assert attacks[-1].payload['provisional_hit'] is True
    assert engine.state.actors[FOE].current_hp < 300
    consent = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.karma_borrow_accept')
    assert consent['action'] == 'Ally miss'
    assert 'Ally miss' in consent['moment'] and 'attack' in consent['moment']


def test_borrowed_merit_attack_natural_one_stays_miss_despite_high_total(tmp_path, monkeypatch):
    from combat.gate2_rolls import DeterministicRollAuthority
    raw_d20 = DeterministicRollAuthority.raw_d20

    def natural_one(self, *, modifier, actor_id, reason, mode='NORMAL'):
        roll = raw_d20(self, modifier=modifier, actor_id=actor_id, reason=reason, mode=mode)
        if actor_id == ALLY and reason.startswith('ATTACK:'):
            return roll.model_copy(update={'dice': (1,), 'natural_result': 1, 'total': 1 + modifier})
        return roll

    monkeypatch.setattr(DeterministicRollAuthority, 'raw_d20', natural_one)
    c, t, mid = fight(tmp_path, [ki.BORROW], ally_attack_bonus=100, foe_ac=10)
    seed(c, t, mid, OWNER, 'Grace'); seed(c, t, mid, ALLY, 'Grace')
    turn(t, mid, ALLY)
    use(c, t, mid, 'Ally miss', FOE, {'reaction:typed.' + ki.BORROW: 'use'})
    engine = reload(tmp_path, mid)
    rewrite = next(e for e in engine.events if e.event_type == 'D20_REWRITTEN' and e.source_definition_id == ki.BORROW)
    attack = next(e for e in reversed(engine.events) if e.event_type == 'ATTACK_ROLLED' and e.actor_id == ALLY)
    assert rewrite.payload['original']['natural_result'] == rewrite.payload['result']['natural_result'] == 1
    assert rewrite.payload['result']['total'] > engine.state.actors[FOE].armor_class
    assert attack.payload['natural_result'] == 1
    assert attack.payload['provisional_hit'] is False
    assert engine.state.actors[FOE].current_hp == 300


def test_borrowed_merit_adds_exact_d4_to_a_failed_ability_check(tmp_path):
    c, t, mid = fight(tmp_path, [ki.BORROW])
    seed(c, t, mid, OWNER, 'Grace'); seed(c, t, mid, ALLY, 'Grace')
    turn(t, mid, ALLY)
    prompts = use(c, t, mid, 'Hard check', FOE, {'reaction:typed.' + ki.BORROW: 'use'})
    engine = reload(tmp_path, mid)
    donated = next(r for r in engine.rolls if r.reason == 'BORROWED_MERIT')
    checks = [e for e in engine.events if e.event_type == 'CHECK_ROLLED' and e.actor_id == ALLY]
    assert checks
    result = checks[-1].payload['actor']
    assert result['total'] == result['natural_result'] + 2 + donated.total
    assert not held(engine.state.actors[OWNER], OWNER, 'grace')
    consent = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.karma_borrow_accept')
    assert consent['action'] == 'Hard check'
    assert 'Hard check' in consent['moment'] and 'ability check' in consent['moment']


WHEEL = 'tianxia.subpath.qi.samsara_wheel_cultivator.feature.wheel_turns_once'


@pytest.mark.parametrize('ai', [False, True], ids=['manual-donor', 'automatic-donor'])
@pytest.mark.parametrize('force_success', [True, False], ids=['forced-success', 'failed-save-control'])
def test_borrowed_merit_respects_crown_explicit_success_after_reload(tmp_path, monkeypatch, ai, force_success):
    from combat.ext.inner_soul_gate import CROWN, OPENING, RESONANCE
    from combat.gate2_rolls import DeterministicRollAuthority

    c, t, mid = fight(tmp_path, [ki.BORROW], ally_features=[CROWN],
                      ally_pools={RESONANCE: 30}, ally_primary='Resonance')
    seed(c, t, mid, OWNER, 'Grace', count=2)
    seed(c, t, mid, ALLY, 'Grace')
    turn(t, mid, ALLY)
    use(c, t, mid, 'Crown Opening', ALLY)
    turn(t, mid, FOE)
    if ai:
        c.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    before = reload(tmp_path, mid)
    assert any(cond.condition_id == OPENING and cond.data['gate'] == 'crown'
               for cond in before.state.actors[ALLY].conditions.values())
    # Execute with an active Opening loaded from disk, not transient preparation.
    c = CombatService(ROOT, tmp_path); t = TabletopService(c, tmp_path)
    raw_d20 = DeterministicRollAuthority.raw_d20

    def failed_save(self, *, modifier, actor_id, reason, mode='NORMAL'):
        roll = raw_d20(self, modifier=modifier, actor_id=actor_id, reason=reason, mode=mode)
        if actor_id == ALLY and reason.startswith('SAVE:'):
            return roll.model_copy(update={'dice': (5,), 'natural_result': 5, 'total': 5 + modifier})
        return roll

    monkeypatch.setattr(DeterministicRollAuthority, 'raw_d20', failed_save)
    picks = {'reaction:typed.' + CROWN: 'use' if force_success else None,
             'reaction:typed.' + ki.BORROW: 'use', 'choice:needle.karma_borrow_accept': 'accept'}
    prompts = use(c, t, mid, 'Demand save', ALLY, picks)
    engine = reload(tmp_path, mid)  # cold service load and mechanical journal replay
    rewrites = [e for e in engine.events if e.event_type == 'D20_REWRITTEN']
    crowns = [e for e in rewrites if e.source_definition_id == CROWN]
    donations = [e for e in rewrites if e.source_definition_id == ki.BORROW]
    assert len(crowns) == int(force_success)
    if force_success:
        assert crowns[0].payload['original']['natural_result'] == crowns[0].payload['result']['natural_result'] == 5
        assert crowns[0].payload['result']['total'] < 1000  # numeric failure, effective success
        assert engine.state.actors[ALLY].current_hp == before.state.actors[ALLY].current_hp
        assert not donations, 'an explicitly successful save must not spend donated Grace'
        assert not any(r.reason == 'BORROWED_MERIT' for r in engine.rolls)
        assert len(held(engine.state.actors[OWNER], OWNER, 'grace')) == 2
        assert ki.BORROW_USED not in engine.state.actors[OWNER].turn_flags
        assert not any(p['context']['reaction_source_id'] in
                       ('reaction:typed.' + ki.BORROW, 'choice:needle.karma_borrow_accept') for p in prompts)
        assert engine.state.actors[ALLY].resources[RESONANCE] == before.state.actors[ALLY].resources[RESONANCE] - 2
    else:
        assert len(donations) == 1
        assert len([r for r in engine.rolls if r.reason == 'BORROWED_MERIT']) == 1
        assert len(held(engine.state.actors[OWNER], OWNER, 'grace')) == 1
        assert engine.state.actors[OWNER].turn_flags[ki.BORROW_USED] == engine.state.round_number
        assert engine.state.actors[ALLY].current_hp == before.state.actors[ALLY].current_hp - 1
        assert any(p['context']['reaction_source_id'] == 'choice:needle.karma_borrow_accept' for p in prompts)
        assert engine.state.actors[ALLY].resources[RESONANCE] == before.state.actors[ALLY].resources[RESONANCE]
    assert len(held(engine.state.actors[ALLY], OWNER, 'grace')) == 1
    # A subsequent genuine failure in the same round can use the preserved
    # allowance after Crown's success; a previously spent allowance stays spent.
    c = CombatService(ROOT, tmp_path); t = TabletopService(c, tmp_path)
    use(c, t, mid, 'Demand save', ALLY, picks)
    again = reload(tmp_path, mid)
    assert len([e for e in again.events if e.event_type == 'D20_REWRITTEN' and e.source_definition_id == CROWN]) == int(force_success)
    assert len([r for r in again.rolls if r.reason == 'BORROWED_MERIT']) == 1
    assert len(held(again.state.actors[OWNER], OWNER, 'grace')) == 1
    assert again.state.actors[OWNER].turn_flags[ki.BORROW_USED] == again.state.round_number
    assert again.state.actors[ALLY].current_hp == before.state.actors[ALLY].current_hp - (1 if force_success else 2)


@pytest.mark.parametrize('donor', [OWNER, FOE2], ids=['reroll-sorts-first', 'donor-sorts-first'])
@pytest.mark.parametrize('reroll_total', [15, 16], ids=['failed-reroll-rescued', 'successful-reroll-no-donation'])
def test_borrowed_merit_combines_with_wheel_reroll_and_cold_reload(tmp_path, monkeypatch, donor, reroll_total):
    from combat.gate2_rolls import DeterministicRollAuthority
    raw_d20 = DeterministicRollAuthority.raw_d20
    c, t, mid = fight(tmp_path, [ki.BORROW], ally_features=[WHEEL], save_dc=16)
    seed(c, t, mid, donor, 'Grace', count=2)
    seed(c, t, mid, ALLY, 'Grace')
    turn(t, mid, FOE)
    first_counters = {reload(tmp_path, mid).state.roll_counter}

    def failed_then_reroll(self, *, modifier, actor_id, reason, mode='NORMAL'):
        roll = raw_d20(self, modifier=modifier, actor_id=actor_id, reason=reason, mode=mode)
        if actor_id == ALLY and reason.startswith('SAVE:'):
            total = 5 if roll.counter_start in first_counters else reroll_total
            natural = total - modifier
            assert 1 <= natural <= 20
            return roll.model_copy(update={'dice': (natural,), 'natural_result': natural, 'total': total})
        return roll

    monkeypatch.setattr(DeterministicRollAuthority, 'raw_d20', failed_then_reroll)
    picks = {'reaction:typed.' + WHEEL: 'use', 'reaction:typed.' + ki.BORROW: 'use',
             'choice:needle.karma_borrow_accept': 'accept'}
    prompts = use(c, t, mid, 'Demand save', ALLY, picks)
    engine = reload(tmp_path, mid)
    rewrites = [e for e in engine.events if e.event_type == 'D20_REWRITTEN']
    wheels = [e for e in rewrites if e.source_definition_id == WHEEL]
    donations = [e for e in rewrites if e.source_definition_id == ki.BORROW]
    assert len(wheels) == 1, 'one actual reroll must still be offered even when the donor sorts first'
    assert wheels[0].payload['operation'] == 'reroll'
    assert wheels[0].payload['original']['total'] == 5
    assert wheels[0].payload['result']['total'] == reroll_total
    assert engine.state.actors[ALLY].resources[CP] == 97
    assert not any(e.event_type == 'DAMAGE_COMMITTED' and ALLY in e.target_ids for e in engine.events)
    donated = int(reroll_total < 16)
    assert len(donations) == donated
    assert len(held(engine.state.actors[donor], OWNER, 'grace')) == 2 - donated
    assert len(held(engine.state.actors[ALLY], OWNER, 'grace')) == 1
    if donated:
        payload = donations[0].payload
        assert payload['operation'] == 'bonus'
        assert payload['original'] == wheels[0].payload['result']
        assert payload['result']['natural_result'] == payload['original']['natural_result']
        assert 1 <= payload['bonus'] <= 4
        assert payload['result']['total'] == 15 + payload['bonus'] >= 16
        assert wheels[0].sequence < donations[0].sequence
        donor_prompt = next(p for p in prompts if p['context']['reaction_source_id'] == 'reaction:typed.' + ki.BORROW)
        assert donor_prompt['context']['reactor_id'] == donor
        assert 'D20_ROLL_BONUS' in donor_prompt['context']['checkpoint']
        assert 'saving throw' in donor_prompt['moment']
        assert donor_prompt['action'] == 'Demand save'
        assert any(p['context']['reactor_id'] == ALLY and
                   p['context']['reaction_source_id'] == 'choice:needle.karma_borrow_accept' for p in prompts)
        assert engine.state.actors[OWNER].turn_flags[ki.BORROW_USED] == engine.state.round_number
    else:
        assert not any(p['context']['reaction_source_id'] in
                       ('reaction:typed.' + ki.BORROW, 'choice:needle.karma_borrow_accept') for p in prompts)
        assert ki.BORROW_USED not in engine.state.actors[OWNER].turn_flags
    # A new service must retain the ledger allowance and the wheel's round limit.
    c = CombatService(ROOT, tmp_path); t = TabletopService(c, tmp_path)
    first_counters.add(engine.state.roll_counter)
    use(c, t, mid, 'Demand save', ALLY, picks)
    engine = reload(tmp_path, mid)
    assert len([e for e in engine.events if e.event_type == 'D20_REWRITTEN' and e.source_definition_id == WHEEL]) == 1
    assert len([r for r in engine.rolls if r.reason == 'BORROWED_MERIT']) == 1
    assert len(held(engine.state.actors[donor], OWNER, 'grace')) == 1


COUNTERFLOW = 'tianxia.subpath.qi.devil_heart_second_furnace.feature.heart_devil_counterflow'


@pytest.mark.parametrize('donor', [OWNER, FOE2], ids=['reroll-sorts-first', 'donor-sorts-first'])
@pytest.mark.parametrize('rescued', [True, False], ids=['donation-rescues', 'still-failed-control'])
def test_borrowed_merit_finalizes_counterflow_after_all_bonuses(tmp_path, monkeypatch, donor, rescued):
    from combat.gate2_rolls import DeterministicRollAuthority
    c, t, mid = fight(tmp_path, [ki.BORROW], ally_features=[COUNTERFLOW],
                      ally_pools={'resource:named.devil_qi': 30}, save_dc=16)
    seed(c, t, mid, donor, 'Grace', count=2)
    seed(c, t, mid, ALLY, 'Grace')
    turn(t, mid, FOE)
    before = reload(tmp_path, mid)
    first_counter = before.state.roll_counter
    original_die = DeterministicRollAuthority._die

    def scripted_die(self, sides):
        value, counter = original_die(self, sides)
        if sides == 20:
            value = 3 if counter == first_counter else (9 if rescued else 8)
        elif sides == 4:
            value = 1
        elif sides == 8:
            value = 5
        return value, counter

    monkeypatch.setattr(DeterministicRollAuthority, '_die', scripted_die)
    picks = {'reaction:typed.' + COUNTERFLOW: 'use', 'reaction:typed.' + ki.BORROW: 'use',
             'choice:needle.karma_borrow_accept': 'accept'}
    prompts = use(c, t, mid, 'Demand save', ALLY, picks)
    engine = reload(tmp_path, mid)  # fresh CombatService plus mechanical journal replay
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == ALLY]
    assert saves[-1].payload['total'] == (16 if rescued else 15)
    assert saves[-1].payload['success'] is rescued
    rewrites = [e for e in engine.events if e.event_type == 'D20_REWRITTEN']
    reroll = next(e for e in rewrites if e.source_definition_id == COUNTERFLOW)
    donation = next(e for e in rewrites if e.source_definition_id == ki.BORROW)
    assert reroll.payload['result']['total'] == (15 if rescued else 14)
    assert donation.payload['bonus'] == 1
    assert reroll.sequence < donation.sequence < saves[-1].sequence
    assert len(rewrites) == 2
    assert engine.state.actors[ALLY].resources['resource:named.devil_qi'] == 28
    assert not engine.state.actors[ALLY].reaction_available
    assert len(held(engine.state.actors[donor], OWNER, 'grace')) == 1
    assert len(held(engine.state.actors[ALLY], OWNER, 'grace')) == 1
    assert any(p['context']['reactor_id'] == donor for p in prompts)
    assert any(p['context']['reactor_id'] == ALLY and
               p['context']['reaction_source_id'] == 'choice:needle.karma_borrow_accept' for p in prompts)
    source = engine.state.actors[FOE]
    assert source.current_hp == before.state.actors[FOE].current_hp - (15 if rescued else 0)
    assert any('reaction' in cond.condition_id for cond in source.conditions.values()) is rescued
    from combat.typed_reactions import _can_react
    assert _can_react(engine, source) is not rescued
    assert engine.state.actors[ALLY].current_hp == before.state.actors[ALLY].current_hp - (0 if rescued else 1)
    lines = [e for e in engine.events if e.event_type == 'PASSIVE_TRIGGERED' and
             e.source_definition_id == COUNTERFLOW and 'uses Heart-Devil Counterflow:' in e.payload.get('log', '')]
    assert len(lines) == 1
    assert ('and succeeds.' if rescued else 'and fails.') in lines[0].payload['log']
    assert f'adds 4 (final save total {16 if rescued else 15} against DC 16)' in lines[0].payload['log']
    assert lines[0].sequence > donation.sequence
    # Cold service executes another save: neither payment nor rider may recur this round.
    c = CombatService(ROOT, tmp_path); t = TabletopService(c, tmp_path)
    use(c, t, mid, 'Demand save', ALLY, picks)
    again = reload(tmp_path, mid)
    assert len([e for e in again.events if e.event_type == 'D20_REWRITTEN']) == 2
    assert again.state.actors[ALLY].resources['resource:named.devil_qi'] == 28
    assert len(held(again.state.actors[donor], OWNER, 'grace')) == 1
    assert again.state.actors[FOE].current_hp == source.current_hp
    assert not getattr(again, '_d20_rewrite_finalizers', None)


@pytest.mark.parametrize('move', [True, False], ids=['player-moves', 'player-declines'])
def test_borrowed_merit_rescues_gourd_and_preserves_player_movement_choice(tmp_path, monkeypatch, move):
    from combat.gate2_rolls import DeterministicRollAuthority
    gourd = 'TAL_DRUNKEN_STYLE_BROKEN_GOURD_RECOVERY'
    c, t, mid = fight(tmp_path, [ki.BORROW], ally_features=[gourd], save_dc=16, save_ability='dex')
    seed(c, t, mid, OWNER, 'Grace')
    seed(c, t, mid, ALLY, 'Grace')
    turn(t, mid, FOE)
    before = reload(tmp_path, mid)
    first_counter = before.state.roll_counter
    raw_d20 = DeterministicRollAuthority.raw_d20
    original_die = DeterministicRollAuthority._die

    def failed_then_reroll(self, *, modifier, actor_id, reason, mode='NORMAL'):
        result = raw_d20(self, modifier=modifier, actor_id=actor_id, reason=reason, mode=mode)
        if actor_id == ALLY and reason.startswith('SAVE:'):
            natural = (5 if result.counter_start == first_counter else 15) - modifier
            assert 1 <= natural <= 20
            result = result.model_copy(update={'dice': (natural,), 'natural_result': natural, 'total': natural + modifier})
        return result

    def one_d4(self, sides):
        value, counter = original_die(self, sides)
        return (1 if sides == 4 else value), counter

    monkeypatch.setattr(DeterministicRollAuthority, 'raw_d20', failed_then_reroll)
    monkeypatch.setattr(DeterministicRollAuthority, '_die', one_d4)
    key = 'choice:needle.broken_gourd_step'
    # Cell immediately north of the ally is clear. The player selects it or declines.
    from combat.ext.needle import cell_id
    destination = before.state.actors[ALLY].position.model_copy(update={'y': 5})
    picks = {'reaction:typed.' + gourd: 'use', 'reaction:typed.' + ki.BORROW: 'use',
             'choice:needle.karma_borrow_accept': 'accept', key: cell_id(destination) if move else None}
    prompts = use(c, t, mid, 'Demand save', ALLY, picks)
    engine = reload(tmp_path, mid)
    choices = [p for p in prompts if p['context']['reaction_source_id'] == key]
    assert len(choices) == 1, 'a success rescued by donation still owes the player a movement choice'
    assert choices[0]['context']['reactor_id'] == ALLY
    assert 'Broken Gourd Recovery' in choices[0]['moment']
    assert engine.state.actors[ALLY].position == (destination if move else before.state.actors[ALLY].position)
    assert engine.state.actors[ALLY].current_hp == before.state.actors[ALLY].current_hp
    assert engine.state.actors[ALLY].resources['resource:core.martial_focus'] == 0
    assert not held(engine.state.actors[OWNER], OWNER, 'grace')
    assert len([e for e in engine.events if e.event_type == 'D20_REWRITTEN']) == 2
    assert not getattr(engine, '_d20_rewrite_finalizers', None)
