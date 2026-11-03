"""Native accepted OAs meet real Factory Countermeasure through saved Table turns."""
import pytest

from combat import ext, native_reactions, typed_reactions
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN, BAI
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, ME, sheet
from tests.test_hidden_targeting import turn
from tests.test_lock2_persistence import act
from tests.test_c3ar_runtime_executability import runtime_package, adapter, bundle, runtime_engine

CM = "TAL_LIGHTNING_CHARGED_COUNTERMEASURE"
OA = "system:combat.opportunity_attack"


def fight(tmp_path, *, owned=True, two=False):
    doc = sheet([CM] if owned else [], cl=12, dc=30)
    doc['identity']['display_name'] = 'Watcher'
    bundle = compile_character(doc, actor_id=ME, reaction_plan={'ask': True})
    svc = CombatService(ROOT, tmp_path)
    positions = {ME: {'x': 4, 'y': 6}, AN: {'x': 5, 'y': 6}, BAI: {'x': 4, 'y': 7}}
    mid = svc.persistence.create_match(match_seed='LOCK13-NATIVE', typed_bundles=(bundle,),
        roster_setup={'primary_actor_ids': [ME, AN, BAI] if two else [ME, AN],
                      'team_by_actor': {ME: 'a', AN: 'b', BAI: 'b'},
                      'starting_positions': positions}).match_id
    for aid in ([ME, AN, BAI] if two else [ME, AN]):
        svc.set_controller_mode(mid, actor_id=aid, controller_mode='MANUAL')
    table = TabletopService(svc, tmp_path)
    turn(table, mid, ME)
    return svc, table, mid


def move(svc, table, mid, *, auto=False, oa_use=True, counter_use=True):
    state = table.state(mid)
    before = svc._load_session(mid).engine.state.model_dump(mode='json')
    c = next(c for c in svc._load_session(mid).engine.legal_candidates()
             if c.kind == 'MOVE' and c.destination.x == 4 and c.destination.y == 4)
    if auto:
        # A supported primary-action driver chooses a legal move; production
        # reaction policy still decides every AI reactor's answers.
        production = svc.controller
        class MoveController:
            def choose_primary_action(self, context):
                selected = next(x for x in context.legal_candidates if x.candidate_id == c.candidate_id)
                return ManualControllerAdapter(lambda _: (selected.candidate_id, ())).choose_primary_action(context)
            def __getattr__(self, name):
                return getattr(production, name)
        svc.controller = MoveController()
    answers, prompts = [], []
    for _ in range(12):
        response = (table.auto_step(mid, state['last_sequence'], answers) if auto else
                    table.act(mid, c.candidate_id, c.decision_id, c.state_version, state['last_sequence'], answers))
        if response['status'] == 'COMMITTED':
            break
        assert response['status'] == 'REACTION_REQUIRED', response
        assert svc._load_session(mid).engine.state.model_dump(mode='json') == before
        prompt = response['reaction']
        prompts.append(prompt)
        use = counter_use if prompt['reaction'] == 'Charged Countermeasure' else oa_use
        answers.append({**prompt['context'], 'selection': 'USE' if use else 'DECLINE'})
    else:
        pytest.fail('Repeated reaction prompts without commit')
    return prompts


def accepting_ai(svc):
    """Explicit test policy: accept zero-packet OAs via the production controller.

    The inherited default policy declines such OAs; changing that policy is not
    this seam's job. All other reactions retain the production policy.
    """
    production = svc.controller
    class OpportunityPolicy:
        def choose_reaction(self, context):
            if context.reaction_source_id == OA:
                policy = context.policy.model_copy(update={'reaction_rules': {
                    **context.policy.reaction_rules, OA: {'minimum_packet': 0}}})
                context = context.model_copy(update={'policy': policy})
            return production.choose_reaction(context)
        def __getattr__(self, name):
            return getattr(production, name)
    svc.controller = OpportunityPolicy()


def checked(svc, tmp_path, mid):
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state == svc._load_session(mid).engine.state
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
    return loaded.engine


@pytest.mark.parametrize('ai_reactor', [False, True])
@pytest.mark.parametrize('use', [False, True], ids=['decline', 'use'])
def test_native_manual_or_ai_reaction_countermeasure_use_decline(tmp_path, monkeypatch, ai_reactor, use):
    svc, table, mid = fight(tmp_path)
    if ai_reactor:
        svc.set_controller_mode(mid, actor_id=AN, controller_mode='LOCAL_AUTO')
        accepting_ai(svc)
    observed = []
    ext.effects()
    original = list(ext._HOOKS.get('d20_result', []))
    def observe(engine, roll, intent):
        context = engine.d20_context(roll)
        if context and context.get('source_id') == OA:
            observed.append((context, engine.state.actors[AN].reaction_available))
    monkeypatch.setitem(ext._HOOKS, 'd20_result', [*original, observe])
    prompts = move(svc, table, mid, counter_use=use)
    counter = [p for p in prompts if p['reaction'] == 'Charged Countermeasure']
    assert len(counter) == 1 and 'Opportunity Attack' in counter[0]['moment']
    assert 'An Eui' in counter[0]['moment']
    engine = checked(svc, tmp_path, mid)
    attacks = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.source_definition_id == OA]
    assert len(attacks) == 1 and attacks[0].payload['mode'] == ('DISADVANTAGE' if use else 'NORMAL')
    assert observed and all(c['economy'] == 'REACTION' and c['reaction_source_id'] == OA and not spent
                            for c, spent in observed)
    assert len([e for e in engine.events if e.event_type == 'REACTION_WINDOW_OPENED'
                and e.source_definition_id == OA and e.payload.get('checkpoint') == 'LEAVE_REACH']) == 1
    assert not engine.state.actors[AN].reaction_available
    assert engine.state.actors[ME].reaction_available is (not use)
    assert native_reactions.context(engine, AN, OA) is None
    assert typed_reactions.reaction_penalty(engine, AN, OA) is None
    # A later unrelated ordinary attack retains its old mode.
    svc.set_controller_mode(mid, actor_id=AN, controller_mode='MANUAL')
    turn(table, mid, AN)
    state = table.state(mid)
    c = next(c for c in svc._load_session(mid).engine.legal_candidates()
             if c.kind == 'MOVE' and c.destination.x == 5 and c.destination.y == 5)
    assert table.act(mid, c.candidate_id, c.decision_id, c.state_version, state['last_sequence'])['status'] == 'COMMITTED'
    assert act(table, mid, 'action:an_eui.paired_bi_shou_assault')['status'] == 'COMMITTED'
    later = checked(svc, tmp_path, mid)
    assert all(e.payload['mode'] == 'NORMAL' for e in later.events
               if e.event_type == 'ATTACK_ROLLED' and e.source_definition_id == 'action:an_eui.paired_bi_shou_assault')


def test_declined_native_opportunity_never_offers_countermeasure(tmp_path):
    svc, table, mid = fight(tmp_path)
    prompts = move(svc, table, mid, oa_use=False)
    assert not any(p['reaction'] == 'Charged Countermeasure' for p in prompts)
    engine = checked(svc, tmp_path, mid)
    assert engine.state.actors[AN].reaction_available
    assert not any(e.event_type == 'ATTACK_ROLLED' and e.source_definition_id == OA for e in engine.events)


def test_spent_countermeasure_is_not_offered_for_second_native_reaction(tmp_path):
    svc, table, mid = fight(tmp_path, two=True)
    prompts = move(svc, table, mid)
    assert len([p for p in prompts if p['reaction'] == 'Charged Countermeasure']) == 1
    engine = checked(svc, tmp_path, mid)
    assert len([e for e in engine.events if e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == OA]) == 2


def test_ai_turn_still_asks_manual_countermeasure_owner(tmp_path):
    # A native teammate moves away from the enemy; the Factory owner remains
    # Manual + Ask me while both native fighters use AI transport.
    svc = CombatService(ROOT, tmp_path)
    table = TabletopService(svc, tmp_path)
    bundle = compile_character(sheet([CM], cl=12, dc=30), actor_id=ME, reaction_plan={'ask': True})
    mid = svc.persistence.create_match(match_seed='LOCK13-AI-MOVER', typed_bundles=(bundle,),
        roster_setup={'primary_actor_ids': [ME, AN, BAI], 'team_by_actor': {ME: 'a', AN: 'b', BAI: 'a'},
            'starting_positions': {ME: {'x': 2, 'y': 6}, AN: {'x': 5, 'y': 6}, BAI: {'x': 4, 'y': 6}}}).match_id
    for aid in (ME, AN, BAI):
        svc.set_controller_mode(mid, actor_id=aid, controller_mode='MANUAL')
    turn(table, mid, BAI)
    svc.set_controller_mode(mid, actor_id=BAI, controller_mode='LOCAL_AUTO')
    svc.set_controller_mode(mid, actor_id=AN, controller_mode='LOCAL_AUTO')
    accepting_ai(svc)
    prompts = move(svc, table, mid, auto=True)
    assert any(p['reaction'] == 'Charged Countermeasure' and p['context']['reactor_id'] == ME for p in prompts)
    checked(svc, tmp_path, mid)


def test_nested_native_frames_restore_on_pause(tmp_path, monkeypatch):
    svc, _, mid = fight(tmp_path)
    engine = svc._load_session(mid).engine
    actor, target = engine.state.actors[AN], engine.state.actors[ME]
    actor.reaction_available = False
    # Observe the public dispatcher at a controlled nested pause boundary.
    calls = []
    def dispatch(e, a, kind):
        calls.append(kind)
        assert not a.reaction_available
        if len(calls) == 2:
            raise ext.ControllerPause('nested pause')
    monkeypatch.setattr(typed_reactions, 'on_creature_event', dispatch)
    with native_reactions.attack_scope(engine, actor, target, OA, 'Opportunity Attack'):
        outer = engine._typed_reaction_frames[(AN, OA)]
        outer['penalty'] = {'actor_id': AN, 'feature_id': OA}
        with pytest.raises(ext.ControllerPause):
            with native_reactions.attack_scope(engine, actor, target, OA, 'Opportunity Attack'):
                pytest.fail('pause must propagate')
        assert engine._typed_reaction_frames[(AN, OA)] is outer
        assert native_reactions.roll_mode(engine, AN, OA, 'NORMAL') == 'DISADVANTAGE'
        assert native_reactions.roll_mode(engine, AN, 'unrelated', 'NORMAL') == 'NORMAL'
    assert native_reactions.context(engine, AN, OA) is None
    assert typed_reactions.reaction_penalty(engine, AN, OA) is None
    assert not engine._d20_scopes and engine._typed_answered_reaction is None


@pytest.mark.parametrize('cancelled', [False, True])
def test_character_runtime_attack_uses_reaction_scope_then_discards_it(bundle, monkeypatch, cancelled):
    """Cover the other native resolver with a real compiled runtime bundle.

    Table tests above exercise the actual Countermeasure consumer. This focused
    resolver test supplies its resulting frame to isolate the runtime d20 path.
    """
    from combat.character_runtime_adapter import SOURCE_ACTOR_ID
    from combat.gate2_runtime_models import ActionIntent
    engine = runtime_engine(bundle)
    # The standalone runtime fixture predates d20 rewrites; the Table adapter
    # inherits this callback from its Gate2 engine when copying its fields.
    engine.roller.after_d20 = engine._rewrite_d20
    actor, target = engine.state.actors[SOURCE_ACTOR_ID], engine.state.actors['dummy:target']
    if cancelled:
        engine._apply_condition(target, 'condition:core.burning', 'test:burning', actor.entity_id, expires_on=None)
        from tests.test_lock_choices import install
        install(monkeypatch, 'before_attack', lambda *args: {'mode': 'DISADVANTAGE'})
    intent = ActionIntent(intent_id='test:runtime-oa', decision_id='test:runtime-oa',
                          candidate_id='test:runtime-oa', state_version=engine.state.state_version,
                          actor_id=actor.entity_id)
    observed = []
    ext.effects()
    original = list(ext._HOOKS.get('d20_result', []))
    def observe(e, roll, intent):
        observed.append(e.d20_context(roll))
    monkeypatch.setitem(ext._HOOKS, 'd20_result', [*original, observe])
    def strike():
        return engine._resolve_character_attack(actor, target, source_id=OA, attack_bonus=5,
            damage=None, damage_type='BLUDGEONING', fixed_damage=1, ranged=False, intent=intent,
            advantage_if_burning=cancelled)
    actor.reaction_available = False
    with native_reactions.attack_scope(engine, actor, target, OA, 'Opportunity Attack', runtime=True):
        engine._typed_reaction_frames[(actor.entity_id, OA)]['penalty'] = {
            'actor_id': actor.entity_id, 'feature_id': OA}
        strike()
    first = next(c for c in observed if c and c.get('reaction_source_id') == OA)
    assert first['economy'] == 'REACTION' and first['target_id'] == target.entity_id
    strike()  # same stable source outside the accepted scope must not inherit it
    rolls = [e.payload for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.source_definition_id == OA]
    assert [r['mode'] for r in rolls] == (['NORMAL', 'NORMAL'] if cancelled else ['DISADVANTAGE', 'NORMAL'])
    assert typed_reactions.reaction_penalty(engine, actor.entity_id, OA) is None
