"""Real Blood talents use owned atomic HP substitution at the saved table."""
import json
import zipfile

import pytest

from combat import ext, stances
from combat.alternative_payments import PaymentAlternative, options
from combat.ext.blood_riders import SACRIFICE, VEINS
from combat.gate2_runtime_models import ActionIntent
from combat.gate5_service import CombatService, CombatServiceError
from combat.tabletop_service import TabletopService
from combat.typed_executor import mark_condition_id
from tests.h1_support import ROOT, sheet
from tests.test_hidden_targeting import turn
from tests.test_lock_choices import install
from tests.test_lock2_persistence import act
from tests.r10_fixup_support import cast_sender, commit, answer

OWNER, ALLY, FOE = ('actor:factory.' + pid for pid in ('aaaaaaaa', 'bbbbbbbb', 'ffffffff'))
MENDING = 'tianxia.talent.blood.blood_mending'


def fight(monkeypatch, tmp_path, *, current=0, primary='Qi', discount=None, hp=60, setting=99):
    for pid in ('aaaaaaaa', 'bbbbbbbb', 'ffffffff'):
        doc = sheet([MENDING] if pid == 'aaaaaaaa' else [], cl=10, primary=primary)
        doc['identity']['display_name'] = {'aaaaaaaa': 'Owner', 'bbbbbbbb': 'Ally', 'ffffffff': 'Foe'}[pid]
        folder = tmp_path / 'portable_characters' / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
    pool = 'resource:core.' + primary.lower()
    def prepare(engine, kind, kwargs):
        if kind != 'HOLD_POSITION_COMMITTED' or kwargs['actor_id'] != OWNER:
            return
        owner = engine.state.actors[OWNER]
        engine._spend_resource(owner, pool, owner.resources[pool] - current, 'test:pool')
        for who in (OWNER, ALLY):
            engine._apply_condition(engine.state.actors[who], mark_condition_id('Blood Thread', OWNER),
                'test:thread', OWNER, expires_on='UNTIL_REMOVED', data={'mark': 'Blood Thread'})
        engine._commit_damage(engine.state.actors[ALLY], 20, 'UNTYPED', 'test:wound', FOE, None, reaction_depth=0)
        if hp < owner.current_hp:
            engine._commit_damage(owner, owner.current_hp - hp, 'UNTYPED', 'test:hp', FOE, None, reaction_depth=0)
        if discount:
            engine._apply_condition(owner, VEINS if discount == 'veins' else stances.PREFIX + 'blood_emperor_incarnation',
                'test:active-discount', OWNER, expires_on='END_OF_SELF_TURN')
    install(monkeypatch, 'event', prepare)
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({'display_name': 'Blood yard', 'width_squares': 12, 'height_squares': 8,
        'walls': [], 'starts': {'team1': [[3, 4], [3, 5]], 'team2': [[8, 4]]}})
    mid = combat.create_factory_match(project_ids=['aaaaaaaa', 'bbbbbbbb'], opponent_actor_ids=[FOE],
        control_modes={OWNER: 'MANUAL', ALLY: 'MANUAL', FOE: 'MANUAL'},
        arena_id='battlefield:map.blood-yard', match_seed='LOCK7-CRIMSON')['match_id']
    table = TabletopService(combat, tmp_path)
    turn(table, mid, OWNER)
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    if setting is not None:
        e = combat._load_session(mid).engine
        source = next(c.source_definition_id for c in e.legal_candidates()
                      if c.source_definition_id.endswith('.crimson_sacrifice.' + str(setting)))
        assert act(table, mid, source)['status'] == 'COMMITTED'
    return combat, table, mid, pool


def reload_checked(tmp_path, mid):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'
    return session.engine


@pytest.mark.parametrize('primary', ['Qi', 'Stamina', 'Resonance'])
@pytest.mark.parametrize('current,setting,replaced', [(0, 99, 3), (1, 99, 3), (1, 2, 2), (10, 2, 2)])
def test_missing_and_affordable_costs_are_asked_paid_once_and_reloaded(monkeypatch, tmp_path, primary, current, setting, replaced):
    combat, table, mid, pool = fight(monkeypatch, tmp_path, current=current, primary=primary, setting=setting)
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    send = cast_sender(combat, table, mid, 'Blood Mending', target=ALLY)
    first = send()
    assert first['status'] == 'REACTION_REQUIRED'
    assert 'Blood Mending' in first['reaction']['moment'] and 'Owner' in first['reaction']['moment']
    label = first['reaction']['choice']['options'][0]['label']
    assert f'{replaced * 5} HP' in label and 'Crimson Sacrifice' in label and primary in label
    assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
    assert send([answer(first['reaction'])])['status'] == 'COMMITTED'
    e = reload_checked(tmp_path, mid)
    actor = e.state.actors[OWNER]
    assert actor.current_hp == before['actors'][OWNER]['current_hp'] - replaced * 5
    assert actor.resources[pool] == current - (3 - replaced)
    assert actor.turn_flags['crimson_sacrifice_used'] and actor.turn_flags['crimson_sacrifice_cp'] == replaced
    receipts = [ev for ev in e.events if ev.event_type == 'ALTERNATIVE_PAYMENT_COMMITTED']
    assert len(receipts) == 1 and receipts[0].payload['covered'] == {pool: replaced}
    assert not any(ev.event_type in ('RESOURCE_GAINED', 'DAMAGE_COMMITTED')
                   and ev.source_definition_id.endswith('.crimson_sacrifice.' + str(setting)) for ev in e.events)
    if actor.resources[pool] == 0:
        assert not any(g['label'].startswith('Coagulate') for g in table.state(mid)['menu']['actions'])


@pytest.mark.parametrize('setting,hp', [(None, 60), (0, 60), (1, 60), (99, 15)])
def test_ineligible_missing_cost_stays_unavailable(monkeypatch, tmp_path, setting, hp):
    combat, table, mid, pool = fight(monkeypatch, tmp_path, setting=setting, hp=hp)
    assert not any(g['label'] == 'Blood Mending' for g in table.state(mid)['menu']['actions'])
    e = reload_checked(tmp_path, mid)
    assert e.state.actors[OWNER].current_hp == hp and e.state.actors[OWNER].resources[pool] == 0


@pytest.mark.parametrize('discount,rate', [(None, 5), ('veins', 4), ('emperor', 4)])
def test_hp_floor_discount_and_owning_turn_limits(monkeypatch, tmp_path, discount, rate):
    combat, table, mid, pool = fight(monkeypatch, tmp_path, discount=discount, hp=3 * rate + 1)
    commit(cast_sender(combat, table, mid, 'Blood Mending', target=ALLY), lambda p: (None, True))
    e = reload_checked(tmp_path, mid)
    assert e.state.actors[OWNER].current_hp == 1
    assert e.state.actors[OWNER].turn_flags['crimson_sacrifice_cp'] == 3
    assert not any(g['label'].startswith('Coagulate') for g in table.state(mid)['menu']['actions'])


def test_open_veins_multiple_payments_share_cap_and_persist(monkeypatch, tmp_path):
    combat, table, mid, pool = fight(monkeypatch, tmp_path, discount='veins')
    commit(cast_sender(combat, table, mid, 'Blood Mending', target=ALLY), lambda p: (None, True))
    combat = CombatService(ROOT, tmp_path); table = TabletopService(combat, tmp_path)
    commit(cast_sender(combat, table, mid, 'Coagulate', target=ALLY), lambda p: (None, True))
    e = reload_checked(tmp_path, mid); actor = e.state.actors[OWNER]
    assert actor.current_hp == 44 and actor.turn_flags['crimson_sacrifice_cp'] == 4
    source = next(a.source_definition_id for a in e.action_catalog.values()
                  if a.owner_id == OWNER and a.display_name == 'Blood Mending')
    # The reloaded aggregate permits four more CP, not a fresh twice-PB allowance.
    assert options(e, actor, source, ((pool, 4),))
    assert not options(e, actor, source, ((pool, 5),))


def test_decline_cancels_without_spending_even_when_cp_is_affordable(monkeypatch, tmp_path):
    combat, table, mid, _ = fight(monkeypatch, tmp_path, current=10, setting=2)
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    send = cast_sender(combat, table, mid, 'Blood Mending', target=ALLY)
    first = send()
    with pytest.raises(CombatServiceError, match='canceled'):
        send([answer(first['reaction'], use=False)])
    assert combat._load_session(mid).engine.state.model_dump(mode='json') == before


@pytest.mark.parametrize('failure', [RuntimeError, ext.ControllerPause])
def test_exception_after_hp_payment_restores_entire_native_transaction(monkeypatch, tmp_path, failure):
    combat, table, mid, _ = fight(monkeypatch, tmp_path)
    first = cast_sender(combat, table, mid, 'Blood Mending', target=ALLY)()
    engine = combat._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates() if c.display_name == 'Blood Mending' and c.target_ids == (ALLY,))
    intent = ActionIntent(intent_id='test:payment-rollback', decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=OWNER,
        target_ids=candidate.target_ids, reaction_decisions=(answer(first['reaction']),))
    def fail(*args):
        raise failure('interrupted after payment')
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, 'payment_shortfall_paid', [*ext._HOOKS['payment_shortfall_paid'], fail])
    before = engine.state.model_dump(mode='json'), list(engine.events), list(engine.rolls), engine.roller.counter
    with pytest.raises(failure):
        engine.execute_intent(intent)
    assert (engine.state.model_dump(mode='json'), engine.events, engine.rolls, engine.roller.counter) == before


def test_ai_owner_uses_real_payment_plan_without_player_prompt(monkeypatch, tmp_path):
    from combat.gate4_context import build_decision_context
    combat, table, mid, _ = fight(monkeypatch, tmp_path)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    session = combat._load_session(mid)
    policy, _ = combat.policies.for_actor(OWNER)
    context = build_decision_context(session.engine, policy, for_ai=True)
    choices = tuple(c for c in context.legal_candidates if c.display_name == 'Blood Mending' and c.target_ids == (ALLY,))
    assert choices
    choice = combat.controller.choose_primary_action(context.model_copy(update={'legal_candidates': choices}))
    session.execute_controller_choice(choice, controller=combat.controller, policy_library=combat.policies)
    assert reload_checked(tmp_path, mid).state.actors[OWNER].current_hp == 45


def test_no_setting_and_nonblood_costs_keep_native_payment(monkeypatch, tmp_path):
    combat, table, mid, pool = fight(monkeypatch, tmp_path, current=10, setting=None)
    assert not commit(cast_sender(combat, table, mid, 'Blood Mending', target=ALLY))
    e = reload_checked(tmp_path, mid)
    assert e.state.actors[OWNER].current_hp == 60 and e.state.actors[OWNER].resources[pool] == 7
    assert not any(ev.event_type == 'ALTERNATIVE_PAYMENT_COMMITTED' for ev in e.events)


@pytest.mark.parametrize('coverage', [(), (('resource:core.qi', 4),), (('resource:core.qi', 0),)])
def test_substitution_never_overpays_or_covers_an_empty_cost(monkeypatch, tmp_path, coverage):
    combat, table, mid, pool = fight(monkeypatch, tmp_path, current=10)
    e = combat._load_session(mid).engine; actor = e.state.actors[OWNER]
    source = next(a.source_definition_id for a in e.action_catalog.values()
                  if a.owner_id == OWNER and a.display_name == 'Blood Mending')
    setting = next(c for c in actor.conditions.values() if c.condition_id == SACRIFICE)
    install(monkeypatch, 'payment_substitution', lambda *a:
        PaymentAlternative(setting.source_definition_id, 'Bad quote', coverage, hp_cost=5))
    with pytest.raises(ValueError, match='payment_substitution'):
        options(e, actor, source, ((pool, 3),))


def test_final_cost_floor_is_paid_and_usage_resets_only_next_turn(monkeypatch, tmp_path):
    combat, table, mid, pool = fight(monkeypatch, tmp_path)
    install(monkeypatch, 'technique_cost_floor', lambda e, a, source, *rest:
        {pool: 5} if source in e.action_catalog and e.action_catalog[source].display_name == 'Blood Mending' else None)
    commit(cast_sender(combat, table, mid, 'Blood Mending', target=ALLY), lambda p: (None, True))
    e = reload_checked(tmp_path, mid)
    assert e.state.actors[OWNER].current_hp == 35 and e.state.actors[OWNER].turn_flags['crimson_sacrifice_cp'] == 5
    assert not any(g['label'].startswith('Coagulate') for g in table.state(mid)['menu']['actions'])
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    turn(table, mid, OWNER)
    commit(cast_sender(combat, table, mid, 'Coagulate', target=ALLY), lambda p: (None, True))
    e = reload_checked(tmp_path, mid)
    assert e.state.actors[OWNER].current_hp == 30 and e.state.actors[OWNER].turn_flags['crimson_sacrifice_cp'] == 1


def test_refund_never_manufactures_the_voluntarily_replaced_cp(monkeypatch, tmp_path):
    from combat.technique_costs import refund
    combat, table, mid, pool = fight(monkeypatch, tmp_path, current=10, setting=2)
    def discount(engine, actor, source, plan, intent):
        assert refund(engine, actor, source, ((pool, 3),), pool, 3, 'test:refund') == 1
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, 'payment_shortfall_paid', [*ext._HOOKS['payment_shortfall_paid'], discount])
    commit(cast_sender(combat, table, mid, 'Blood Mending', target=ALLY), lambda p: (None, True))
    e = reload_checked(tmp_path, mid)
    assert e.state.actors[OWNER].current_hp == 50 and e.state.actors[OWNER].resources[pool] == 10


def test_setting_cannot_substitute_nonblood_actions_or_another_owner(monkeypatch, tmp_path):
    combat, table, mid, pool = fight(monkeypatch, tmp_path)
    e = combat._load_session(mid).engine
    from combat.ext.blood_riders import crimson_sacrifice
    assert crimson_sacrifice(e, e.state.actors[OWNER], 'system:combat.dodge', {pool: 3}, {pool: 3}) is None
    source = next(a.source_definition_id for a in e.action_catalog.values()
                  if a.owner_id == OWNER and a.display_name == 'Blood Mending')
    assert crimson_sacrifice(e, e.state.actors[ALLY], source, {pool: 3}, {pool: 3}) is None
