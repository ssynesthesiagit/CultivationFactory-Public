"""Round 17 integration: real service pauses, decline and table reloads."""
from types import SimpleNamespace

import pytest

from combat.canonical import canonical_sha256
from combat.gate2_runtime_models import ActionIntent, ReactionDecision
from combat.gate5_service import CombatService, _ReactionRequired
from combat.tabletop_service import TabletopService
from tests import test_riders_lane3 as L


@pytest.mark.parametrize('mode', ['MANUAL', 'SUGGESTED'])
@pytest.mark.parametrize('kind', ['cleave', 'red_line', 'pull', 'mandate'])
def test_rider_choice_service_pause_can_decline_single_candidate(tmp_path, mode, kind):
    if kind == 'cleave':
        engine, other = L._two_foes(['TAL_AXES_CLEAVING_ARC'])
        name, target, choice = L.STRIKE + 'Bite + Cleaving Arc', L.H.FOE, 'second_attack'
    elif kind == 'red_line':
        engine, other = L._with_ally(['TAL_AXES_HEADSMAN_S_RED_LINE'], dc=L.FAIL)
        name, target, choice = L.STRIKE + "Bite + Headsman's Red Line", L.H.FOE, 'red_line_ally'
    elif kind == 'pull':
        engine = L.H._engine(L._axes(['TAL_AXES_LODGED_AXE_PULL'], dc=L.FAIL), foe_at=(8,6))
        target, other, choice = L.H.AN, L.ME, 'lodge_pull'
        L._grow(engine, actor_id=target, cells=3)
        engine._apply_condition(engine.state.actors[target], L.typed_executor.mark_condition_id('Bite', L.ME),
                               'test:bite', L.ME, expires_on='UNTIL_REMOVED')
        name = 'Lodged Axe Pull'
    else:
        engine = L._three_foes(['TAL_AXES_HEADSMAN_S_MANDATE'], [(3,6),(4,6),(4,9),(19,6)], dc=L.FAIL)
        engine.state.actors[L.F1].current_hp = 5
        name, target, other, choice = L.MANDATE, L.F1, L.F2, 'hostiles_within'
    candidate = next(c for c in engine.legal_candidates() if c.display_name == name and target in c.target_ids)
    intent = ActionIntent(intent_id='r3i-choice', actor_id=candidate.actor_id, decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id, state_version=candidate.state_version,
        target_ids=candidate.target_ids, destination=candidate.destination)
    service = CombatService(L.H.ROOT, tmp_path)
    session = SimpleNamespace(engine=engine, match_id=engine.state.match_id)
    metadata = {'participant_control_modes': {a: mode if a == L.ME else 'LOCAL_AUTO' for a in engine.state.actors}}
    before = canonical_sha256(engine.state.model_dump(mode='json'))
    with pytest.raises(_ReactionRequired) as paused:
        service._run_preview(session, metadata, intent, ())
    context = paused.value.context
    assert context.reactor_id == L.ME and context.reaction_source_id == 'choice:needle.' + choice
    prompt = context.choice_trigger['prompt']
    assert name in prompt and engine.state.actors[target].display_name in prompt
    assert context.choice_trigger['allow_decline']
    answer = ReactionDecision(checkpoint=context.checkpoint, reactor_id=L.ME,
        reaction_source_id=context.reaction_source_id, selection='DECLINE', option_ids=())
    result = service._run_preview(session, metadata, intent, (answer,))
    if kind == 'cleave':
        assert len([e for e in result['events'] if e['event_type'] == 'ATTACK_ROLLED']) == 1
    elif kind == 'red_line':
        assert not any(e['event_type'] == 'CONDITION_APPLIED' and 'no_approach' in e['payload']['condition_id'] for e in result['events'])
    elif kind == 'pull':
        assert not any(e['event_type'] == 'MOVEMENT_COMMITTED' and e['actor_id'] == L.ME for e in result['events'])
    else:
        assert not any(e['event_type'] == 'CONDITION_APPLIED' and other in e['target_ids'] and 'frightened' in e['payload']['condition_id'] for e in result['events'])
    assert canonical_sha256(engine.state.model_dump(mode='json')) == before


@pytest.mark.parametrize('auto_turn', [False, True])
@pytest.mark.parametrize('include', [False, True])
def test_cauldron_owner_choice_at_turn_start_table_commit_reload(tmp_path, auto_turn, include):
    """A manual owner must choose even when an AI END_TURN advances to the owner."""
    from combat.factory_compiler import compile_character
    from combat.gate4_adapters import ManualControllerAdapter

    owner, ally, foe = L.ME, 'actor:factory.r3i-ally', L.H.FOE
    ids = [owner, ally, foe]
    sheets = [L.H._sheet('tianxia.sphere.alchemy', [L.CAULDRON], L.H.AXE_KIT, dc=L.FAIL, cl=15),
              L.H._sheet(None, [], L.H.AXE_KIT), L.H._sheet(None, [], L.H.AXE_KIT)]
    for document, display in zip(sheets, ['Cauldron Owner', 'Cauldron Ally', 'Cauldron Foe']):
        document['identity']['display_name'] = display
    bundles = [compile_character(s, actor_id=a, reaction_plan={'ask': True}) for s,a in zip(sheets,ids)]
    combat = CombatService(L.H.ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(bundles, ids,
        {owner:'team:a', ally:'team:a', foe:'team:b'},
        {owner:{'x':3,'y':6}, ally:{'x':3,'y':5}, foe:{'x':4,'y':6}},
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'], [owner,ally], [foe],
        control_modes={a:'MANUAL' for a in ids}, match_seed='R3I-COURT',
        display_name='R3i Court choices', maximum_rounds=5)['match_id']

    def act(cid, answers=()):
        menu = table.state(mid)['menu']
        return table.act(mid, cid, menu['decision_id'], menu['state_version'], 0, list(answers))

    for _ in range(3):
        menu = table.state(mid)['menu']
        if menu['actor_id'] == owner:
            break
        assert act(menu['end_turn'])['status'] == 'COMMITTED'
    menu = table.state(mid)['menu']
    group = next(g for g in menu['actions'] if 'Court of the Three-Legged Cauldron' in g['label'])
    assert act(group['options'][0]['candidate_id'])['status'] == 'COMMITTED'
    real = combat.controller

    class EndTurnController:
        def choose_primary_action(self, context):
            end = next(c for c in context.legal_candidates if c.kind.value == 'END_TURN')
            return ManualControllerAdapter(lambda _: (end.candidate_id, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(real, name)

    combat.controller = EndTurnController()
    for a in (ally,foe):
        if auto_turn:
            combat.set_controller_mode(mid, actor_id=a, controller_mode='LOCAL_AUTO')
    for _ in range(6):
        menu = table.state(mid)['menu']
        current = menu['actor_id']
        cid = next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates() if c.kind.value == 'END_TURN')
        send = (lambda answers=(): table.auto_step(mid, 0, list(answers))) if auto_turn and current != owner else (
            lambda answers=(): act(cid, answers))
        before = combat._load_session(mid).engine.state.model_dump(mode='json')
        result = send()
        if result['status'] == 'REACTION_REQUIRED':
            prompt = result['reaction']
            assert prompt['context']['reaction_source_id'] == 'choice:needle.furnace_target'
            assert prompt['context']['reactor_id'] == owner
            answer = {**prompt['context'], 'selection':'USE', 'option_ids':['include' if include else 'exclude']}
            if current != owner and 'Cauldron Owner' in prompt['moment']:
                assert 'Court of the Three-Legged Cauldron' in prompt['moment']
                assert send()['reaction'] == prompt
                assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
                assert send([answer])['status'] == 'COMMITTED'
                loaded = CombatService(L.H.ROOT, tmp_path)._load_session(mid)
                assert loaded.engine.state.actors[owner].temporary_hp == (4 if include else 0)
                assert loaded.engine._active_intent is None
                assert not getattr(loaded.engine, '_active_turn_advancing', False)
                assert loaded.mechanical.replay()['status'] == 'PASS'
                return
            assert send([answer])['status'] == 'COMMITTED'
        else:
            assert result['status'] == 'COMMITTED'
    pytest.fail('No off-turn owner beneficiary checkpoint reached')


@pytest.mark.parametrize('auto_turn', [False, True])
@pytest.mark.parametrize('decline', [False, True])
def test_poise_off_turn_step_table_keeps_both_movement_budgets(tmp_path, auto_turn, decline):
    from combat.factory_compiler import compile_character
    from combat.gate4_adapters import ManualControllerAdapter

    owner, foe = L.ME, L.H.FOE
    documents = [L.H._sheet('tianxia.sphere.beauty', ['tianxia.talent.beauty.unapproachable_poise'],
                           L.H.AXE_KIT, dc=L.FAIL), L.H._sheet(None, [], L.H.AXE_KIT)]
    documents[0]['identity']['display_name'] = 'Poise Owner'
    documents[1]['identity']['display_name'] = 'Poise Attacker'
    bundles = [compile_character(d, actor_id=a, reaction_plan={'ask':True}) for d,a in zip(documents,(owner,foe))]
    combat = CombatService(L.H.ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(bundles, [owner,foe], {owner:'team:a',foe:'team:b'},
        {owner:{'x':3,'y':6},foe:{'x':4,'y':6}}, combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],
        [owner],[foe], control_modes={owner:'MANUAL',foe:'MANUAL'}, match_seed='R3I-POISE',
        display_name='R3i Poise', maximum_rounds=4)['match_id']

    def act(cid, answers=()):
        menu = table.state(mid)['menu']
        return table.act(mid,cid,menu['decision_id'],menu['state_version'],0,list(answers))

    for _ in range(2):
        menu = table.state(mid)['menu']
        if menu['actor_id'] == owner:
            break
        assert act(menu['end_turn'])['status'] == 'COMMITTED'
    engine = combat._load_session(mid).engine
    c = next(c for c in engine.legal_candidates() if c.display_name == 'Catch the Eye' and foe in c.target_ids)
    assert act(c.candidate_id)['status'] == 'COMMITTED'
    assert act(table.state(mid)['menu']['end_turn'])['status'] == 'COMMITTED'
    engine = combat._load_session(mid).engine
    c = next(c for c in engine.legal_candidates() if c.display_name == 'Fu (Short Axe) attack' and owner in c.target_ids)
    real = combat.controller

    class AttackController:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _: (c.candidate_id, ())).choose_primary_action(context)

        def __getattr__(self,name):
            return getattr(real,name)

    combat.controller = AttackController()
    if auto_turn:
        combat.set_controller_mode(mid,actor_id=foe,controller_mode='LOCAL_AUTO')
    send = (lambda answers=(): table.auto_step(mid,0,list(answers))) if auto_turn else (lambda answers=():act(c.candidate_id,answers))
    answers = []
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    for _ in range(5):
        result = send(answers)
        assert result['status'] == 'REACTION_REQUIRED'
        prompt = result['reaction']
        if prompt['context']['reaction_source_id'] == 'choice:needle.rider_step':
            break
        answer = {**prompt['context'],'selection':'USE','option_ids':[]}
        if prompt.get('choice'):
            answer['option_ids'] = [prompt['choice']['options'][0]['id']]
        answers.append(answer)
    assert prompt['context']['reaction_source_id'] == 'choice:needle.rider_step'
    assert prompt['context']['reactor_id'] == owner
    assert 'Poise Attacker' in prompt['moment'] and 'Turn the Blade Aside' in prompt['moment']
    assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
    answer = {**prompt['context'],'selection':'DECLINE' if decline else 'USE',
              'option_ids':[] if decline else ['cell:3,3']}
    assert send([*answers,answer])['status'] == 'COMMITTED'
    loaded = CombatService(L.H.ROOT,tmp_path)._load_session(mid)
    for a in (owner,foe):
        assert loaded.engine.state.actors[a].movement_remaining_ft == before['actors'][a]['movement_remaining_ft']
    assert loaded.engine.state.actors[owner].position.model_dump(mode='json') == ({'x':3,'y':6} if decline else {'x':3,'y':3})
    assert loaded.mechanical.replay()['status'] == 'PASS'
