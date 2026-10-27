"""r8 findings: real service intents, committed OA outcomes and cold reload."""
import pytest
from tests.test_a2_athletics_second_pass import (
    SOURCE, POOL, seal_actions, add_action, commit, finish, momentum,
)
from tests.auto8f1_table_support import fixture, candidate_id, OWNER, FOE, SECOND

FIELD = 'tianxia.talent.pressure_points.meridian_stillness_field'
HERD = 'tianxia.talent.warleader.deadly_herdsman'


def option(g, label, target):
    return next(o['candidate_id'] for group in g['menu']()['actions'] for o in group['options']
                if label in o['label'] and target in o.get('target_ids', ()))


def helper_game(tmp_path, prohibition):
    def prepare(bs):
        seal_actions(bs)
        owner = next(b for b in bs if b['actor_id'] == OWNER)
        if prohibition in ('global', 'against_owner', 'against_other'):
            add_action(owner, 'Restrict helper OA', [{'type': 'hammer_rebuke_no_oa',
                       'against_you': prohibition != 'global'}])
            owner['action_catalog'][-1]['target_kind'] = 'ANY_CREATURE'
            owner['action_catalog'][-1]['range_ft'] = 60
            if prohibition == 'against_other':
                # A different creature is the protected subject.
                caster = next(b for b in bs if b['actor_id'] == SECOND)
                add_action(caster, 'Restrict helper against caster',
                           [{'type': 'hammer_rebuke_no_oa', 'against_you': True}])
                caster['action_catalog'][-1]['target_kind'] = 'ANY_CREATURE'
                caster['action_catalog'][-1]['range_ft'] = 60
        if prohibition == 'field':
            caster = next(b for b in bs if b['actor_id'] == SECOND)
            add_action(caster, 'Mark helper Pressure Point', [{'type': 'mark', 'mark': 'Pressure Point',
                       'applies_to': 'target', 'duration': {'kind': 'until_removed'}}])
            caster['action_catalog'][-1]['target_kind'] = 'ANY_CREATURE'
            caster['action_catalog'][-1]['range_ft'] = 60
    g = fixture(tmp_path, [SOURCE], seed='ATH-R9-HELPER-'+prohibition,
                bundle_transform=prepare, allies=(FOE,),
                talents_by_actor={SECOND: [FIELD]} if prohibition == 'field' else None,
                places={OWNER: {'x': 3, 'y': 6}, FOE: {'x': 4, 'y': 6}, SECOND: {'x': 7, 'y': 6}})
    if prohibition in ('global', 'against_owner'):
        g['commit'](option(g, 'Restrict helper OA', FOE))
    elif prohibition == 'against_other':
        g['turn_of'](SECOND)
        g['commit'](option(g, 'Restrict helper against caster', FOE))
        g['turn_of'](OWNER)
    elif prohibition == 'field':
        g['turn_of'](SECOND)
        g['commit'](option(g, 'Mark helper Pressure Point', FOE))
        commit(g, 'Meridian Stillness Field at 4,6')
        g['turn_of'](OWNER)
        from combat.ext.pressure_points import field_no_opportunity
        engine = g['stored_engine']()
        assert field_no_opportunity(engine, engine.state.actors[FOE], engine.state.actors[OWNER]) is False
    finish(g)
    return g


@pytest.mark.parametrize('prohibition,allowed', [
    ('global', False), ('against_owner', False), ('field', False),
    ('against_other', True), ('none', True),
])
def test_assistance_honors_oa_specific_admission_and_reload(tmp_path, prohibition, allowed):
    g = helper_game(tmp_path, prohibition)
    offered = [o for group in g['menu']()['actions'] for o in group['options']
               if 'ask an ally to assist' in o['label'] and FOE in o.get('target_ids', ())]
    assert bool(offered) is allowed
    before = len(g['stored_engine']().events)
    if allowed:
        g['commit'](offered[0]['candidate_id'])
    else:
        # A real, harmless intent commits while the forbidden assistance stays absent.
        commit(g, 'Hold position')
    engine = g['stored_engine']()
    events = engine.events[before:]
    assert engine.state.actors[FOE].reaction_available is (not allowed)
    assert bool([e for e in events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == FOE]) is allowed
    assert bool(momentum(g)) is allowed
    if not allowed:
        assert not [e for e in events if e.event_type in ('REACTION_USED', 'REACTION_WINDOW_OPENED')
                    and (e.actor_id == FOE or FOE in e.target_ids)]
        assert g['reload_owner']().bonus_action_available
    finish(g)


@pytest.mark.parametrize('hit', [True, False])
def test_herdsman_forced_shove_oa_does_not_grant_momentum(tmp_path, hit):
    def prepare(bs):
        seal_actions(bs)
        owner = next(b for b in bs if b['actor_id'] == OWNER)
        owner['actor_template']['armor_class'] = 1
        owner['actor_template']['saving_throws'] = {'STR': -100, 'DEX': -100}
        # Deterministic triggering hit; the watcher OA separately hits/misses.
        watcher = next(b for b in bs if b['actor_id'] == FOE)
        for row in watcher['action_catalog']:
            if row['source_definition_id'] in [r.get('action_id') for r in watcher['typed_reactions']
                                                if r.get('block') == 'opportunity']:
                row['parameters']['typed']['numbers']['attack_bonus'] = 100 if hit else -100
    g = fixture(tmp_path, [SOURCE], seed='ATH-R9-HERD-'+str(hit), bundle_transform=prepare,
                talents_by_actor={FOE: [HERD]}, places={OWNER: {'x': 3, 'y': 7},
                FOE: {'x': 4, 'y': 6}, SECOND: {'x': 4, 'y': 7}})
    g['turn_of'](FOE)
    commit(g, 'Deadly Herdsman')
    finish(g)
    g['turn_of'](SECOND)
    before = len(g['stored_engine']().events)
    prompts = []
    def choose(p, c):
        prompts.append(p)
        for wanted in ('push', 'horizontal'):
            if any(o['id'] == wanted for o in c['options']):
                return [wanted]
        return c.get('preferred') or [c['options'][0]['id']]
    g['commit'](option(g, 'Unarmed Strike', OWNER), choose)
    engine = g['stored_engine']()
    events = engine.events[before:]
    assert engine.state.actors[OWNER].position.x == 2
    assert any(e.event_type == 'REACTION_WINDOW_OPENED' and e.source_definition_id == HERD for e in events)
    oa = [e for e in events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == FOE]
    assert len(oa) == 1
    assert bool(oa[0].payload['provisional_hit']) is hit
    assert not engine.state.actors[FOE].reaction_available
    assert not engine.state.actors[SECOND].bonus_action_available
    assert not momentum(g)
    assert not [p for p in prompts if p['context']['reaction_source_id'].split(':', 2)[:2] == ['choice', 'needle.athletics.momentum']]
    assert engine.state.actors[OWNER].bonus_action_available
    finish(g)


@pytest.mark.parametrize('blocker', ['condition', 'hook'])
def test_assistance_revalidates_after_consent_before_reaction_payment(tmp_path, monkeypatch, blocker):
    from combat import ext
    from combat.ext import athletics_momentum as am
    g = helper_game(tmp_path, 'none')
    consent = am.ask
    veto_condition = 'condition:typed.no_opportunity_attacks' if blocker == 'condition' else 'condition:test.oa_hook_veto'
    if blocker == 'hook':
        def veto(engine, reactor, target):
            return False if any(c.condition_id == veto_condition for c in reactor.conditions.values()) else None
        monkeypatch.setitem(ext._HOOKS, 'opportunity_allowed', [*ext.subscribers('opportunity_allowed'), veto])
    def changed_during_consent(engine, intent, checkpoint, actor, choice_id, options, **kwargs):
        chosen = consent(engine, intent, checkpoint, actor, choice_id, options, **kwargs)
        if choice_id == 'choice:needle.athletics.momentum_assist' and chosen:
            engine._apply_condition(actor, veto_condition, 'test:consent_revalidation', OWNER,
                                    expires_on='UNTIL_REMOVED', data={'label': 'Opportunity Attacks forbidden'})
        return chosen
    monkeypatch.setattr(am, 'ask', changed_during_consent)
    before = len(g['stored_engine']().events)
    commit(g, 'ask an ally to assist')
    engine = g['stored_engine']()
    events = engine.events[before:]
    assert any(c.condition_id == veto_condition for c in engine.state.actors[FOE].conditions.values())
    assert engine.state.actors[FOE].reaction_available
    assert not any(e.event_type == 'ATTACK_ROLLED' and e.actor_id == FOE for e in events)
    assert not any(e.event_type in ('REACTION_USED', 'REACTION_WINDOW_OPENED')
                   and (e.actor_id == FOE or FOE in e.target_ids) for e in events)
    assert not momentum(g)
    assert g['reload_owner']().bonus_action_available
    finish(g)


def test_native_movement_oa_keeps_boost_provenance_after_scope_unwinds(tmp_path, monkeypatch):
    from combat.gate2_runtime_content import AN
    from combat import attack_completion
    seen = []
    deliver = attack_completion._deliver
    def observe(engine, notice, intent):
        if notice.attacker_id == AN:
            seen.append((notice, engine))
        return deliver(engine, notice, intent)
    monkeypatch.setattr(attack_completion, '_deliver', observe)
    g = fixture(tmp_path, [SOURCE], seed='ATH-R9-NATIVE-MOVE', bundle_transform=seal_actions,
                places={OWNER: {'x': 3, 'y': 6}, FOE: {'x': 7, 'y': 6}, SECOND: {'x': 8, 'y': 8}},
                legacy_foes={AN: {'x': 4, 'y': 6}})
    menu = g['menu']()
    path = [{'x': 3, 'y': 6}, {'x': 3, 'y': 7}, {'x': 3, 'y': 8}]
    table, mid = g['table'], g['match_id']
    quote = table.preview_move_path(mid, menu['decision_id'], menu['state_version'], OWNER, path)
    answers = []
    for _ in range(30):
        seen.clear()
        response = table.commit_move_path(mid, quote['candidate']['candidate_id'], menu['decision_id'],
                                          menu['state_version'], OWNER, path, reactions=answers)
        if response['status'] == 'COMMITTED':
            break
        assert response['status'] == 'REACTION_REQUIRED'
        prompt = response['reaction']
        answer = {**prompt['context'], 'selection': 'USE'}
        choice = prompt.get('choice')
        if choice:
            answer['option_ids'] = list(choice.get('preferred') or [choice['options'][0]['id']])
        answers.append(answer)
    else:
        raise AssertionError('native movement never committed')
    # The service executes a preview and the committed intent. Observe every
    # receipt, then count attacks and grants in the persisted journal only.
    assert seen
    for notice, completed_engine in seen:
        assert (notice.attacker_id, notice.target_id) == (AN, OWNER)
        assert notice.opportunity and notice.opportunity_trigger == 'movement'
        assert getattr(completed_engine, '_opportunity_attack_provenance', None) is None
    assert len(momentum(g)) == 1
    engine = g['stored_engine']()
    assert len([e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == AN]) == 1
    assert not engine.state.actors[AN].reaction_available
    finish(g)


def test_patrol_movement_oa_remains_a_movement_trigger(tmp_path):
    patrol = 'GUARDIAN_BASE_PATROL_PRACTICE'
    g = fixture(tmp_path, [SOURCE], seed='ATH-R9-PATROL-MOVE', bundle_transform=seal_actions,
                talents_by_actor={FOE: [patrol]}, places={OWNER: {'x': 3, 'y': 6},
                FOE: {'x': 4, 'y': 6}, SECOND: {'x': 8, 'y': 8}})
    g['turn_of'](FOE)
    commit(g, 'Patrol')
    finish(g)
    g['turn_of'](OWNER)
    from tests.auto8f1_table_support import move_candidate_id
    before = len(g['stored_engine']().events)
    # This step stays in melee reach; only Patrol answers the movement.
    g['commit'](move_candidate_id(g['menu'](), 3, 7))
    engine = g['stored_engine']()
    events = engine.events[before:]
    assert any(e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == patrol for e in events)
    assert len([e for e in events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == FOE]) == 1
    assert momentum(g)
    finish(g)
