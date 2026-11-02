"""HUNT125 K1/K2/K5: controller inputs must not follow hidden truth.

Fixtures reproduce H125-04's unknown summoned foe, H125-05's westward
unseen attacker, and H125-02's private payment/initiative events. No GUI.
"""
from types import SimpleNamespace

import pytest

from combat import knowledge_policy, target_knowledge
from combat.ext import ai_restraint, mount_guard, steel_forms
from combat.gate2_runtime_models import CandidateKind, Position, ReactionDecision
from combat.gate4_context import build_decision_context
from combat.gate4_policy import PolicyLibrary
from combat.gate5_service import CombatService
from tests.test_ai_restraint import _summon_turn, _menu, STAY
from tests.test_hidden_targeting import table_fight, turn, LEFT, RIGHT, ROOT
from tests.test_mounts import actors, fight, rider_bundle, take
from tests.test_h2_mount_guard import _my_turn


def stamp(engine, value=1):
    next(e for e in engine.events if e.event_type == 'MATCH_CREATED').payload[knowledge_policy.KEY] = value


def hide_unknown(engine, viewer, foe):
    engine.state.observations.clear()
    engine._apply_condition(foe, 'condition:typed.invisible', 'test:concealed', foe.entity_id,
                            expires_on='UNTIL_REMOVED', data={})
    assert target_knowledge.knowledge(engine, viewer, foe) is None


def test_k1_unknown_enemy_does_not_force_pursuit_or_dash():
    engine, (servant, *_), foe = _summon_turn()
    stamp(engine)
    hide_unknown(engine, servant, foe)
    ai = _menu(engine, servant)
    assert STAY <= {c.kind for c in ai}
    assert any(c.source_definition_id == 'system:combat.dodge' for c in ai)
    end = next(c for c in engine.legal_candidates() if c.kind == CandidateKind.END_TURN)
    assert ai_restraint._close_in(engine, servant, end) is None
    assert not ai_restraint._enemy_in_reach(engine, servant)


def test_k1_remembered_distance_does_not_follow_live_hidden_enemy():
    engine, (servant, *_), foe = _summon_turn()
    stamp(engine)
    remembered = Position(x=12, y=6)
    hide_unknown(engine, servant, foe)
    engine.state.observations[servant.team_id] = {foe.entity_id: remembered}
    expected = engine._distance_actor_to_actor(servant, foe.model_copy(update={'position': remembered}))
    foe.position = Position(x=1, y=6)
    assert ai_restraint._nearest_ft(engine, servant, (foe.entity_id,)) == expected
    assert not ai_restraint._enemy_in_reach(engine, servant)


def test_k1_dash_queries_observed_occupancy(monkeypatch):
    engine, (servant, *_), foe = _summon_turn()
    stamp(engine)
    walk = ai_restraint._Walk((foe.entity_id,), 95, 5, None, False)
    original = engine._occupied_cells_except
    calls = []
    def occupied(actor_id, *, observed=False):
        calls.append(observed)
        return original(actor_id, observed=observed)
    monkeypatch.setattr(engine, '_occupied_cells_except', occupied)
    ai_restraint._dash_opens_a_step(engine, servant, walk)
    assert calls == [True]
    # Execution/collision's ordinary query still uses the real roster.
    assert original(servant.entity_id) == engine._occupied_cells_except(servant.entity_id)


@pytest.mark.parametrize('remembered,edge', [(None, 'N'), (Position(x=2, y=6), 'W')])
def test_k2_meat_shield_uses_known_edge(remembered, edge):
    engine = fight(rider_bundle(['TAL_BEASTMASTERY_MEAT_SHIELD']), foe_at=(2, 6))
    rider, mount, foe = actors(engine)
    stamp(engine)
    _my_turn(engine)
    hide_unknown(engine, rider, foe)
    if remembered is not None:
        engine.state.observations[rider.team_id] = {foe.entity_id: remembered}
        foe.position = Position(x=10, y=6)
    requests = []
    def answer(request):
        requests.append(request)
        return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=rider.entity_id,
            reaction_source_id=request['reaction_source_id'], selection='USE', option_ids=(edge,)), None
    engine.set_reaction_provider(answer)
    take(engine, 'Meat Shield')
    assert requests[-1]['extension_choice']['preferred_option_ids'] == [edge]
    assert mount_guard.edge_of(engine, rider) == edge


def test_k2_no_known_attacker_keeps_existing_edge(monkeypatch):
    engine = fight(rider_bundle(['TAL_BEASTMASTERY_MEAT_SHIELD']), foe_at=(2, 6))
    rider, mount, foe = actors(engine)
    stamp(engine)
    hide_unknown(engine, rider, foe)
    mount_guard.activate_cover(engine, rider, mount, 'E', 'test')
    seen = []
    def ask(*args, **kwargs):
        seen.append(kwargs['preferred'])
        return kwargs['preferred']
    monkeypatch.setattr(mount_guard, 'ask', ask)
    mount_guard._bonus_action(SimpleNamespace(engine=engine, actor=rider, intent=None), {})
    assert seen == [['E']]


def test_k2_reactive_cover_uses_known_facing_and_only_owned_hp(monkeypatch):
    engine = fight(rider_bundle(['TAL_BEASTMASTERY_MEAT_SHIELD']), foe_at=(2, 6))
    rider, mount, foe = actors(engine)
    stamp(engine)
    _my_turn(engine)
    hide_unknown(engine, rider, foe)
    rider.current_hp, mount.current_hp = 5, 10
    decisions = []
    def decline(*args, **kwargs):
        decisions.append((kwargs['preferred'], kwargs['automatic']))
        return []
    monkeypatch.setattr(mount_guard, 'ask', decline)
    for hp in (1, foe.maximum_hp):
        foe.current_hp = hp
        mount_guard.meat_shield(engine, foe, rider, None, {'action_name': 'Sword attack'})
    assert decisions == [(['N'], True), (['N'], True)]
    mount.current_hp = 1
    mount_guard.meat_shield(engine, foe, rider, None, {'action_name': 'Sword attack'})
    assert decisions[-1] == (['N'], False)


@pytest.mark.parametrize('visible', [False, True])
def test_k5_service_context_redacts_opponent_events_after_reload(tmp_path, monkeypatch, visible):
    if not visible:
        from combat.tabletop import TabletopMapStore
        save = TabletopMapStore.save
        def walled(store, document):
            document = {**document, 'walls': [{'shape': 'rect', 'points': [[20, 0], [21, 25]],
                                               'blocks': 'sight_and_movement'}]}
            return save(store, document)
        monkeypatch.setattr(TabletopMapStore, 'save', walled)
    combat, table, mid = table_fight(tmp_path, right_at=(15, 11) if visible else (24, 24))
    turn(table, mid, LEFT)
    session = combat._load_session(mid)
    engine = session.engine
    viewer, foe = engine.state.actors[LEFT], engine.state.actors[RIGHT]
    # The wall prevents perception; neither opponent has a creation observation.
    assert (target_knowledge.knowledge(engine, viewer, foe) is not None) == visible
    policy, _ = PolicyLibrary(ROOT).for_actor(LEFT)
    context = build_decision_context(engine, policy, for_ai=True)
    raw = [e.model_dump(mode='json') for e in engine.events]
    opposing = [e for e in context.recent_events if e['actor_id'] == RIGHT]
    if not visible:
        assert opposing == []
    else:
        initiative = [e for e in opposing if e['event_type'] == 'INITIATIVE_ROLLED']
        assert initiative and initiative[0]['payload'] == {}
    # Table commit and a fresh service reload retain the stamped policy.
    from tests.test_lock2_persistence import act
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    reloaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert knowledge_policy.enabled(reloaded.engine)
    assert [e.model_dump(mode='json') for e in reloaded.engine.events[:len(raw)]] == raw
    assert reloaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('payment_type', ['RESOURCE_SPENT', 'RESOURCE_GAINED', 'RESOURCE_EXPIRED'])
def test_k5_visible_payments_and_nested_expiry_are_private(payment_type):
    engine, (viewer, *_), foe = _summon_turn(at=(18, 6))
    stamp(engine)
    payment = engine._append_event(payment_type, 'test:qi', actor_id=foe.entity_id,
                                  payload={'amount': 2, 'remaining': 19, 'current': 19, 'gained': 2,
                                           'log': 'Spent 2 Qi; 19 remain'})
    applied = engine._append_event('CONDITION_APPLIED', 'test:armor', actor_id=foe.entity_id,
        payload={'condition_id': 'test:armor', 'expires_on': 'TURN_START',
                 'nested': {'modifier': 4, 'counter_start': 7, 'roll_counter_after': 8, 'amount_spent': 2}})
    before = [e.model_dump(mode='json') for e in (payment, applied)]
    projected = target_knowledge.recent_events(engine, viewer, (payment, applied))
    assert projected[0]['payload'] == {}
    assert projected[1]['payload'] == {'condition_id': 'test:armor', 'nested': {}}
    assert [e.model_dump(mode='json') for e in (payment, applied)] == before
    own = payment.model_copy(update={'actor_id': viewer.entity_id})
    assert target_knowledge.recent_events(engine, viewer, (own,))[0]['payload'] == own.payload


@pytest.mark.parametrize('amount', [1, 3])
@pytest.mark.parametrize('restricted', [True, False])
def test_k5_production_soak_payment_in_contexts_survives_table_reload(
        tmp_path, monkeypatch, amount, restricted):
    from combat import ext, typed_reactions
    from combat.gate4_context import build_reaction_context
    from tests.test_tabletop_hunt6 import table_fight as soak_fight, on_hold, LEFT as defender, RIGHT as observer, HOLD
    from tests.test_lock2_persistence import act

    guard = 'tianxia.path.body_refining.feature.stamina_guard'
    if not restricted:
        def unstamped(engine):
            for event in engine.events:
                event.payload.pop(knowledge_policy.KEY, None)
        monkeypatch.setitem(ext._HOOKS, 'match_start', [*ext._HOOKS['match_start'], unstamped])
    combat, table, mid = soak_fight(tmp_path, [guard], ask=True, ally_talents=[], primary='Stamina')
    turn(table, mid, observer)
    policy, _ = PolicyLibrary(ROOT).for_actor(observer)
    captured = []

    def contexts(engine):
        return (build_decision_context(engine, policy, for_ai=True),
                build_reaction_context(engine, policy, {
                    'checkpoint': 'BEFORE_ATTACK_ROLL', 'reactor_id': observer,
                    'reaction_source_id': 'system:combat.opportunity_attack',
                    'attacking_actor_id': defender, 'protected_target_id': observer}))

    def damage(engine):
        target = engine.state.actors[defender]
        pending = typed_reactions.on_damage(engine, target, 16, 0, HOLD, observer)
        # Capture both production context builders while the accepted action
        # is still executing, then again from the committed journal below.
        captured.append(contexts(engine))
        engine._commit_damage(target, pending, 'FORCE', HOLD, observer, None, reaction_depth=0)

    on_hold(monkeypatch, damage)
    state = table.state(mid)
    menu = state['menu']
    cid = next(g['options'][0]['candidate_id'] for g in menu['actions'] if g['source_definition_id'] == HOLD)
    first = table.act(mid, cid, menu['decision_id'], menu['state_version'], state['last_sequence'], [])
    assert first['status'] == 'REACTION_REQUIRED'
    assert first['reaction']['reaction'] == 'Stamina Guard'
    answer = {**first['reaction']['context'], 'selection': 'USE', 'option_ids': [str(amount)]}
    assert table.act(mid, cid, menu['decision_id'], menu['state_version'], state['last_sequence'], [answer])['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    engine = loaded.engine
    assert knowledge_policy.enabled(engine) == restricted
    assert target_knowledge.located(engine, engine.state.actors[observer], engine.state.actors[defender])
    resolved = next(e for e in engine.events if e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == guard)
    raw = resolved.model_dump(mode='json')
    assert raw['payload']['spend'] == amount
    assert raw['payload']['pending_before'] == 16
    assert engine.state.actors[defender].resources['resource:core.stamina'] == 30 - amount
    public = {k: v for k, v in raw['payload'].items() if not k.startswith('gate3_')}
    assert captured
    for pair in [*captured, contexts(engine)]:
        for context in pair:
            projected = next(e for e in context.recent_events if e['event_type'] == 'REACTION_RESOLVED' and e['source_definition_id'] == guard)
            expected = {k: v for k, v in public.items() if k != 'spend'} if restricted else public
            assert projected['payload'] == expected
    # Own payments remain available; projection cannot change replay evidence.
    own_policy, _ = PolicyLibrary(ROOT).for_actor(defender)
    own = build_reaction_context(engine, own_policy, {
        'checkpoint': 'DAMAGE_APPLICATION', 'reactor_id': defender, 'reaction_source_id': guard})
    assert next(e for e in own.recent_events if e['event_type'] == 'REACTION_RESOLVED' and e['source_definition_id'] == guard)['payload'] == public
    assert resolved.model_dump(mode='json') == raw
    assert loaded.mechanical.replay()['status'] == 'PASS'


def test_unstamped_fight_keeps_legacy_decisions_and_journal():
    engine, (servant, *_), foe = _summon_turn()
    for e in engine.events:
        e.payload.pop(knowledge_policy.KEY, None)
    hide_unknown(engine, servant, foe)
    assert not knowledge_policy.enabled(engine)
    assert not STAY.intersection(c.kind for c in _menu(engine, servant))
    event = engine._append_event('RESOURCE_SPENT', 'test:qi', actor_id=foe.entity_id,
                                payload={'remaining': 19})
    # Legacy invisibility suppression is retained too.
    assert target_knowledge.recent_events(engine, servant, (event,)) == ()


def test_unstamped_genesis_keeps_zero_policy_after_commit_and_cold_reload(tmp_path, monkeypatch):
    from combat import ext
    from combat.gate4_persistence import Gate4Persistence
    from tests.persistence_support import inventory, end_turn
    def unstamped(engine):
        for event in engine.events:
            event.payload.pop(knowledge_policy.KEY, None)
    # An absent optional setting is data, not a source-version check. Construct
    # it through the real save path; constructor defaults must not replace it.
    with monkeypatch.context() as before:
        before.setitem(ext._HOOKS, 'match_start', [*ext._HOOKS['match_start'], unstamped])
        old = Gate4Persistence(ROOT, tmp_path).create_match(match_seed='unstamped-knowledge')
    end_turn(old)
    original = inventory(old.store.match_dir)
    reloaded = Gate4Persistence(ROOT, tmp_path).load_match(old.match_id)
    assert not knowledge_policy.enabled(reloaded.engine)
    assert inventory(old.store.match_dir) == original
    assert reloaded.mechanical.replay()['status'] == 'PASS'


def test_tempering_forms_names_damage_saves_and_duration(monkeypatch):
    from tests.test_riders_c7 import bundle, fight as steel_fight, ME
    engine = steel_fight(bundle(['tianxia.subpath.body.thousand_fold_steel_body.feature.body_forged_in_three_forms'], cl=10))
    stamp(engine)
    captured = []
    from combat.ext import needle
    def ask(*args, **kwargs):
        captured.append(kwargs)
        return ['edge']
    monkeypatch.setattr(needle, 'ask', ask)
    steel_forms.choose_forms(engine, engine.state.actors[ME])
    choice = captured[-1]
    assert '+4 damage (Slashing or Force)' in choice['labels']['edge']
    assert 'Slashing damage' in choice['labels']['edge']
    assert 'Advantage on saving throws against being knocked Prone' in choice['labels']['spine']
    assert 'until the start of your next turn' in choice['prompt']
