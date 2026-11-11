"""F5 boundary regressions: native acquisition, committed table IO and cold replay."""
import json
import pytest
from combat import ext
from combat.tabletop_service import TabletopService
from tests.test_journey_activities_native import (
    A, B, PIDS, ARENA, ROOT, LEARN, DUTY, RECOVER, MERIT, BASE_REQUESTS,
    EFFECTS, game, inst, work, ledger, catalog, controlling_source_base,
)
from tests.test_journey_activities_review import complete_encounter
from tests.test_shield_fix_r1 import table_action
from tests.test_shield_fix_r2 import advance, finish


def fixture_action(monkeypatch, name, effects, duration):
    """Explicit test-only action producer; never changes ability ownership."""
    from combat.gate2_runtime_models import ActionDefinition, EconomyKind
    ext.effects()
    def actions(info):
        if info['actor_id'] != B:
            return None
        return [ActionDefinition(source_definition_id='action:test.journey-f5',
            display_name=name, owner_id=B, economy=EconomyKind.NONE,
            resolution_kind='TYPED', target_kind='SELF', parameters={'typed':{
                'source':'test:journey-f5','effects':effects,'numbers':{},
                'duration':duration,'riders':[]}})]
    monkeypatch.setitem(ext._HOOKS, 'compile_actions', [*ext._HOOKS.get('compile_actions',()), actions])


def test_party_supplies_have_distinct_identity_through_combat_and_continuation(tmp_path,monkeypatch,catalog):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog,party_size=7)
    inst(world)
    world(LEARN,'duty_plan','roster',{'obligation':'Deliver the roster','institution':'hall',
        'steps':[{'task':'deliver roster','seconds':1}]})
    state=act('sect_duty',{'scope':'roster'})
    instance=ledger(state)['duty']['instance_id']
    work(act,DUTY,{'step':0},1)
    rows=json.loads((ROOT/'authority/Tianxia_Mundane_Equipment_Catalog_R1.json').read_text())['items']
    ration=next(r for r in rows if r['category']=='gear' and 'ration' in r['name'].lower())
    package={'description':'Ordinary travel rations','items':[{'item_id':ration['item_id'],'quantity':1}],
        'entitlements':['basic_supplies']}
    world(LEARN,'duty_verification',instance,{'witness':'Hall clerk','record':'signed roster',
        'approved_rewards':['supplies'],'detail':'The clerk supplied the party','supplies':package})
    others=[aid for aid in state['actors'] if aid!=A]
    recipients=[A,*others[:5]]
    state=act('sect_reward',{'reward':'supplies','companions':others[:5]})
    keys={aid:ledger(state,aid)['granted_items'][0]['key'] for aid in recipients}
    assert len(set(keys.values()))==6
    assert all(ledger(state,aid)['granted_items'][0]['grant_receipt']==instance for aid in recipients)
    teams={aid:'team:a' if aid==A else 'team:b' for aid in state['actors']}
    for encounter in range(2):
        state=cold().journey_state(jid)
        mid=cold().journey_start_combat(jid,state['revision'],teams,maximum_rounds=1)['match_id']
        engine=cold()._load_session(mid).engine
        from combat.carry import carrying_of
        for aid,key in keys.items():
            assert any(r['key']==key for r in carrying_of(engine,aid)['items']) == (encounter==0 or aid!=A)
        assert cold().verify(mid)['status']=='PASS' and cold().replay(mid)['status']=='PASS'
        if encounter==0:
            table=TabletopService(cold(),tmp_path)
            advance(table,mid,A)
            assert table_action(table,mid,'Drop '+ration['name'])['status']=='COMMITTED'
        complete_encounter(cold,mid,tmp_path)
        state=cold().journey_state(jid)
        state=cold().journey_resume(jid,state['revision'])
        assert cold().journey_state(jid)==state
        assert not ledger(state,A)['granted_items']
        for aid in recipients[1:]:
            assert ledger(state,aid)['granted_items'][0]['key']==keys[aid]
        assert 'granted_items' not in state['actors'][others[-1]].get('source_states',{}).get('sect_stewardship:journey',{})
        act('wait',{'seconds':1})


@pytest.mark.parametrize('resolved',[False,True])
def test_timed_fear_resolution_does_not_restore_permanent_fear(tmp_path,monkeypatch,catalog,resolved):
    fixture_action(monkeypatch,'Timed fear fixture',[{'type':'condition','condition':'frightened',
        'applies_to':'self','condition_data':{'origin_save':{'ability':'WIS','dc':20}}}],
        {'kind':'minutes','amount':10})
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog,sphere='dreams')
    state=cold().journey_state(jid)
    teams={A:'team:a',B:'team:b'}
    mid=cold().journey_start_combat(jid,state['revision'],teams,maximum_rounds=1)['match_id']
    table=TabletopService(cold(),tmp_path)
    advance(table,mid,B)
    assert table_action(table,mid,'Timed fear fixture')['status']=='COMMITTED'
    complete_encounter(cold,mid,tmp_path)
    creature=cold()._load_session(mid).engine.state.actors[B]
    fear=next(c for c in creature.conditions.values() if c.condition_id=='condition:typed.frightened')
    assert fear.expires_on not in (None,'UNTIL_REMOVED') and fear.data['origin_save']['dc']==20
    state=cold().journey_state(jid)
    before=state
    if not resolved:
        with pytest.raises(ValueError,match='timed or unsupported condition'):
            cold().journey_resume(jid,state['revision'])
        assert cold().journey_state(jid)==before
    state=cold().journey_resume(jid,state['revision'],effect_resolutions={B:'The ten-minute fear has ended'})
    assert cold().journey_state(jid)==state
    assert not state['actors'][B]['encounter_snapshot']['conditions']
    assert not state['actors'][B].get('source_states',{}).get(EFFECTS,{})
    act('wait',{'seconds':1})
    state=cold().journey_state(jid)
    second=cold().journey_start_combat(jid,state['revision'],teams,maximum_rounds=1)['match_id']
    assert not any(c.condition_id=='condition:typed.frightened'
        for c in cold()._load_session(second).engine.state.actors[B].conditions.values())
    complete_encounter(cold,second,tmp_path)


@pytest.mark.parametrize('boundary',['scene','new_journey'])
@pytest.mark.parametrize('present,good,expected',[(1,1,4),(0,0,1),(1,0,0)])
def test_merit_work_survives_boundaries_but_rechecks_actual_facts(tmp_path,monkeypatch,catalog,boundary,present,good,expected):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog)
    inst(world)
    for _ in range(4):
        act('sect_petition',{'institution':'hall','request':BASE_REQUESTS[0].text})
    inst(world,present=present,good=1 if present else good)
    work(act,RECOVER,{'institution':'hall','activity':'maintain the ledger'},600)
    # A later loss of good standing still defeats recovery; the scene itself cannot.
    if present and not good:
        inst(world,present=present,good=good)
    if boundary=='scene':
        state=cold().journey_state(jid)
        cold().journey_end_scene(jid,state['revision'],'The ledger scene ends')
    else:
        act('finish')
        state=cold().create_journey(project_ids=PIDS,arena_id=ARENA,
            positions={A:{'x':2,'y':2},B:{'x':2,'y':3}},base_paces={A:1800,B:1800})
        jid=state['journey_id']
        # Facts belong to the journey's own world clock and are deliberately
        # not inherited as permanent truths. Admit the still-current facts in
        # the new journey; the completed work itself must remain durable.
        def current_world(source,kind,scope,value,aid=A):
            current=cold().journey_state(jid)
            result=cold().journey_world_fact(jid,current['revision'],{
                'source':source,'subject':aid,'kind':kind,'scope':scope,'value':value,
                'expires_at':current['seconds']+31536000,'readers':[aid]})
            assert cold().journey_state(jid)==result
            assert cold().journey_verify(jid)['status']=='PASS'
            return result
        inst(current_world,present=present,good=good)
    state=cold().journey_state(jid)
    assert ledger(state)['recovery_work']['rest']==state['actors'][A]['long_rests']
    state=cold().journey_act(jid,state['revision'],A,'long_rest',{})
    assert cold().journey_state(jid)==state and state['actors'][A]['resources'][MERIT]==expected
    assert 'recovery_work' not in ledger(state)
    assert cold().journey_verify(jid)['status']=='PASS'
    # A new rest cannot reuse the completed activity receipt.
    state=cold().journey_act(jid,state['revision'],A,'long_rest',{})
    assert state['actors'][A]['resources'][MERIT]==expected
    assert len([e for e in state['events'] if e['kind']=='MERIT_RECOVERED'])==int(expected>0)
    assert cold().journey_verify(jid)['status']=='PASS'


@pytest.mark.parametrize('ready',[False,True])
def test_unseen_attacker_reaches_owned_active_defense_awareness_declaration(tmp_path,monkeypatch,catalog,ready):
    fixture_action(monkeypatch,'Invisible fixture',[{'type':'condition','condition':'invisible',
        'applies_to':'self','expires_on':'UNTIL_REMOVED'}],{'kind':'instant'})
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog,sphere='shield')
    state=cold().journey_state(jid)
    mid=cold().journey_start_combat(jid,state['revision'],{A:'team:a',B:'team:b'},maximum_rounds=2)['match_id']
    table=TabletopService(cold(),tmp_path)
    advance(table,mid,B)
    assert table_action(table,mid,'Invisible fixture')['status']=='COMMITTED'
    from combat.target_knowledge import can_see
    engine=cold()._load_session(mid).engine
    assert not can_see(engine,engine.state.actors[A],engine.state.actors[B])
    def choose(prompt):
        source=prompt['context']['reaction_source_id']
        if 'fact_admission.shield_readiness' in source:
            return ['ready' if ready else 'unaware']
        if 'active_defense_payment' in source or source=='reaction:typed.SHIELD_BASE_ACTIVE_DEFENSE':
            return ['reaction']
        return None
    prompts=finish(table,mid,'Bi Shou (Dagger) attack',choose,target=A)
    assert any('fact_admission.shield_readiness' in p['context']['reaction_source_id'] for p in prompts)
    engine=cold()._load_session(mid).engine
    assert engine.state.actors[A].reaction_available is (not ready)
    assert any(e.event_type=='REACTION_RESOLVED' and e.payload.get('checkpoint')=='AFTER_ATTACK_ROLL_DEFENSES'
        for e in engine.events) is ready
    assert cold().verify(mid)['status']=='PASS' and cold().replay(mid)['status']=='PASS'
