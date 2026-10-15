"""Warleader printed contracts through accepted table intents and cold replay."""
import pytest
from combat.canonical import canonical_sha256
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload
from tests.test_r9i_karma_persistence import act
from combat.ext import warleader as wl
from combat.ext.warleader_second_pass import BEARER, VOICE, GAP, GRANT, CAPTAIN
BASE=['WARLEADER_BASE_SET_THE_STANDARD','WARLEADER_BASE_MOMENTUM_MARKS']
OTHER='actor:factory.worker2-ally3'

def setup_actions(bundles):
    for b in bundles:
        for name,effects in [('Fund',[{'type':'gain_resource','resource_id':wl.MOMENTUM,'flat':4,'formula':'none','applies_to':'self'}]),
                             ('Deafen',[{'type':'condition','condition':'deafened','applies_to':'self','duration':'one_minute'}]),
                             ('Blind',[{'type':'condition','condition':'blinded','applies_to':'self','duration':'one_minute'}]),
                             ('Invisible',[{'type':'condition','condition':'invisible','applies_to':'self','duration':'one_minute'}]),
                             ('Sense',[{'type':'gain_sense','sense':'blindsight','range_ft':30,'applies_to':'self'}]),
                             ('Disengage',[{'type':'movement','distance_ft':0,'no_opportunity_attacks':True,'applies_to':'self'}]),
                             ('Free Move',[{'type':'movement','distance_ft':5,'no_opportunity_attacks':True,'applies_to':'self'}])]:
            sid='action:test.warleader.'+b['actor_id'].rsplit('.',1)[-1]+'.'+name
            b['action_catalog'].append({'source_definition_id':sid,'display_name':name,'owner_id':b['actor_id'],
                'economy':'NONE','resolution_kind':'TYPED','target_kind':'SELF','costs':[],
                'parameters':{'player_only':True,'typed':{'effects':effects,'numbers':{'pb':4},'riders':[]}}})
            b['actor_template']['action_ids'].append(sid)
        sid='action:test.warleader.'+b['actor_id'].rsplit('.',1)[-1]+'.Ignore'
        b['action_catalog'].append({'source_definition_id':sid,'display_name':'Ignore','owner_id':b['actor_id'],
            'economy':'NONE','resolution_kind':'TYPED','target_kind':'HOSTILE_ENTITY','range_ft':5,'costs':[],
            'parameters':{'player_only':True,'typed':{'effects':[{'type':'ignore_oa_from_target','applies_to':'target'}],
                'numbers':{'pb':4},'riders':[]}}})
        b['actor_template']['action_ids'].append(sid)
        sid='action:test.warleader.'+b['actor_id'].rsplit('.',1)[-1]+'.Critical'
        b['action_catalog'].append({'source_definition_id':sid,'display_name':'Critical','owner_id':b['actor_id'],
            'economy':'NONE','resolution_kind':'TYPED','target_kind':'HOSTILE_ENTITY','range_ft':60,'costs':[],
            'parameters':{'player_only':True,'typed':{'effects':[{'type':'attack','attack_kind':'cultivation_ranged','count':1,
                'on_hit':[{'type':'damage','dice':'1d6','damage_types':['force'],'applies_to':'target'}],'on_miss':[]}],
                'numbers':{'pb':4,'attack_bonus':100},'riders':[]}}})
        b['actor_template']['action_ids'].append(sid)
        sid='action:test.warleader.'+b['actor_id'].rsplit('.',1)[-1]+'.Spent'
        b['action_catalog'].append({'source_definition_id':sid,'display_name':'Spend Reaction','owner_id':b['actor_id'],
            'economy':'NONE','resolution_kind':'TYPED','target_kind':'SELF','costs':[],
            'parameters':{'player_only':True,'typed':{'effects':[{'type':'reaction_denied','applies_to':'self','duration':'until_start_of_next_turn'}],'riders':[]}}})
        b['actor_template']['action_ids'].append(sid)
        b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)

def make(tmp_path,talents,**kw):return fixture(tmp_path,[*BASE,*talents],bundle_transform=setup_actions,**kw)
def use(c,t,m,name,picks=None,**kw):return settle(t,m,candidate(c,m,name,**kw).candidate_id,picks=picks)
def held(e,aid,cid):return [x for x in e.state.actors[aid].conditions.values() if x.condition_id.startswith(cid)]

@pytest.mark.parametrize('choice',[ALLY,OTHER,None])
def test_bearer_chosen_ally_and_decline_survive_reload(tmp_path,choice):
    c,t,m=make(tmp_path,[BEARER],extra_allies=1)
    prompts=use(c,t,m,'Set the Standard',{'choice:warleader.warleader_standard_bearer':choice})
    e=reload(tmp_path,m);assert prompts;assert e.state.actors[FOE].temporary_hp==0
    for aid in [OWNER,ALLY,OTHER]:
        assert e.state.actors[aid].temporary_hp==(4 if aid==choice else 0)
        assert bool(held(e,aid,GRANT))==(aid==choice)

def test_bearer_fulfillment_obeys_momentum_cap(tmp_path):
    c,t,m=make(tmp_path,[BEARER],positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':4,'y':7}})
    use(c,t,m,'Set the Standard',{'choice:warleader.warleader_standard_bearer':ALLY})
    turn(t,m,ALLY);use(c,t,m,'Unarmed Strike',target=FOE)
    e=reload(tmp_path,m);assert not held(e,ALLY,GRANT)
    assert e.state.actors[OWNER].resources[wl.MOMENTUM]==1

def test_bearer_expires_at_source_next_turn(tmp_path):
    c,t,m=make(tmp_path,[BEARER]);use(c,t,m,'Set the Standard',{'choice:warleader.warleader_standard_bearer':ALLY})
    settle(t,m,t.state(m)['menu']['end_turn']);turn(t,m,OWNER)
    e=reload(tmp_path,m);assert not held(e,ALLY,GRANT);assert e.state.actors[OWNER].resources[wl.MOMENTUM]==0

@pytest.mark.parametrize('selected',[ALLY,OTHER,None])
def test_voice_one_visible_deaf_ally_and_radius(tmp_path,selected):
    c,t,m=make(tmp_path,[VOICE],extra_allies=1,positions={OWNER:{'x':3,'y':6},ALLY:{'x':7,'y':6},OTHER:{'x':6,'y':7},FOE:{'x':5,'y':6}})
    for aid in [ALLY,OTHER,FOE]:turn(t,m,aid);use(c,t,m,'Deafen')
    turn(t,m,OWNER);prompts=use(c,t,m,'Fierce Shout',{'choice:warleader.warleader_voice':selected})
    e=reload(tmp_path,m);assert prompts;assert held(e,OWNER,wl.FIERCE);assert not held(e,FOE,wl.FIERCE)
    assert any('20-foot Emanation' in str(x.payload.get('log','')) for x in e.events if x.event_type=='PASSIVE_TRIGGERED')
    for aid in [ALLY,OTHER]:assert bool(held(e,aid,wl.FIERCE))==(aid==selected)

def test_voice_ai_uses_shout_with_both_sides_in_range(tmp_path):
    modes={OWNER:'MANUAL',ALLY:'MANUAL',FOE:'MANUAL',OTHER:'MANUAL'}
    c,t,m=make(tmp_path,[VOICE],extra_allies=1,modes=modes,positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},OTHER:{'x':4,'y':7},FOE:{'x':5,'y':6}})
    for aid in [ALLY,OTHER,FOE]:turn(t,m,aid);use(c,t,m,'Deafen')
    turn(t,m,OWNER)
    c.set_controller_mode(m,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    from combat.gate4_adapters import ManualControllerAdapter
    real=c.controller
    class Controller:
        def choose_primary_action(self,context):
            chosen=next(x for x in context.legal_candidates if x.display_name=='Fierce Shout')
            return ManualControllerAdapter(lambda _: (chosen.candidate_id, ())).choose_primary_action(context)
        def __getattr__(self,name):return getattr(real,name)
    c.controller=Controller()
    settle(t,m,None,auto=True);e=reload(tmp_path,m)
    assert held(e,OWNER,wl.FIERCE)
    assert sum(bool(held(e,aid,wl.FIERCE)) for aid in [ALLY,OTHER])==1
    assert not held(e,FOE,wl.FIERCE)

def test_voice_blind_deaf_ally_cannot_receive_exception(tmp_path):
    c,t,m=make(tmp_path,[VOICE]);turn(t,m,ALLY);use(c,t,m,'Deafen');use(c,t,m,'Blind');turn(t,m,OWNER)
    use(c,t,m,'Fierce Shout');e=reload(tmp_path,m);assert not held(e,ALLY,wl.FIERCE)

@pytest.mark.parametrize('revealing_sense,blinded,expected',[(False,False,False),(True,False,True),(True,True,True)])
def test_voice_deaf_ally_needs_shared_perception_of_invisible_leader(tmp_path,revealing_sense,blinded,expected):
    c,t,m=make(tmp_path,[VOICE],positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':7,'y':6}})
    turn(t,m,ALLY);use(c,t,m,'Deafen')
    if revealing_sense:use(c,t,m,'Sense')
    if blinded:use(c,t,m,'Blind')
    turn(t,m,OWNER);use(c,t,m,'Invisible');use(c,t,m,'Fierce Shout')
    e=reload(tmp_path,m)
    assert bool(held(e,ALLY,wl.FIERCE)) is expected

@pytest.mark.parametrize('funded,two,spent',[(True,True,False),(True,True,True),(False,True,False),(True,False,False)])
def test_gap_attack_payment_and_no_reaction_cost(tmp_path,funded,two,spent):
    c,t,m=make(tmp_path,[GAP],positions={OWNER:{'x':3,'y':6},ALLY:{'x':5,'y':6} if two else {'x':8,'y':6},FOE:{'x':4,'y':7}},ask=False)
    if funded:use(c,t,m,'Fund')
    if spent:use(c,t,m,'Spend Reaction')
    use(c,t,m,'Set the Standard');turn(t,m,FOE)
    e=c._load_session(m).engine;before=len(e.events)
    moves=[x for x in e.legal_candidates() if getattr(x.kind,'value',x.kind)=='MOVE' and x.destination.x==4 and x.destination.y==6]
    assert moves;settle(t,m,moves[0].candidate_id);e=reload(tmp_path,m);events=e.events[before:]
    gap=[x for x in events if x.source_definition_id==GAP and x.event_type=='PASSIVE_TRIGGERED']
    assert bool(gap)==(funded and two)
    assert e.state.actors[OWNER].reaction_available == (not spent);assert e.state.actors[ALLY].reaction_available
    if funded and two:
        assert any(x.event_type=='ATTACK_ROLLED' for x in events)
        assert any(x.event_type=='RESOURCE_SPENT' and x.source_definition_id==GAP and x.payload['amount']==1 for x in events)
        assert not any(x.event_type=='REACTION_USED' for x in events)
        assert e.state.actors[FOE].turn_flags.get('typed_round_wl_gap_provoked')
        before=len(e.events)
        moves=[x for x in e.legal_candidates() if getattr(x.kind,'value',x.kind)=='MOVE' and x.destination.x==4 and x.destination.y==7]
        assert moves;settle(t,m,moves[0].candidate_id);e=reload(tmp_path,m)
        assert not any(x.source_definition_id==GAP and x.event_type=='PASSIVE_TRIGGERED' for x in e.events[before:])

def test_gap_uses_long_grip_reach_and_loses_it_when_weapon_is_dropped(tmp_path):
    """Long Grip's real weapon-bound bonus admits Gap and ends when the weapon is dropped."""
    from combat.typed_reactions import physical_melee_reach
    from tests.test_auto21_weapons import GRIP_TALENT, VERSATILE, kit as weapons_kit, to_turn as weapons_to_turn
    c,t,m=make(tmp_path,[GAP],ally_talents=[GRIP_TALENT],ally_kit=weapons_kit(VERSATILE),ask=False,
               positions={OWNER:{'x':3,'y':6},ALLY:{'x':6,'y':6},FOE:{'x':4,'y':7}})
    weapons_to_turn(t,m,ALLY,choice='long')
    engine=c._load_session(m).engine
    assert physical_melee_reach(engine,engine.state.actors[ALLY])==10
    turn(t,m,OWNER);use(c,t,m,'Fund');use(c,t,m,'Set the Standard')
    engine=c._load_session(m).engine
    assert physical_melee_reach(engine,engine.state.actors[ALLY])==10
    turn(t,m,FOE)
    before=len(c._load_session(m).engine.events)
    moves=[x for x in c._load_session(m).engine.legal_candidates()
           if getattr(x.kind,'value',x.kind)=='MOVE' and x.destination.x==4 and x.destination.y==6]
    assert moves;settle(t,m,moves[0].candidate_id)
    e=reload(tmp_path,m);events=e.events[before:]
    assert any(x.source_definition_id==GAP and x.event_type=='PASSIVE_TRIGGERED' for x in events)
    assert any(x.event_type=='ATTACK_ROLLED' for x in events)
    assert e.state.actors[ALLY].reaction_available
    assert not any(x.event_type=='REACTION_USED' and x.actor_id==ALLY for x in events)
    turn(t,m,ALLY);use(c,t,m,'Drop jian');e=reload(tmp_path,m)
    assert physical_melee_reach(e,e.state.actors[ALLY])==5

@pytest.mark.parametrize('exemption',['disengaged','free','owner_only','ally_only'])
def test_gap_respects_each_current_step_opportunity_exemption(tmp_path,exemption):
    c,t,m=make(tmp_path,[GAP],ask=False,positions={OWNER:{'x':3,'y':6},ALLY:{'x':5,'y':6},FOE:{'x':4,'y':7}})
    use(c,t,m,'Fund');use(c,t,m,'Set the Standard');turn(t,m,FOE)
    if exemption=='disengaged':use(c,t,m,'Disengage')
    elif exemption=='free':use(c,t,m,'Free Move')
    elif exemption=='owner_only':use(c,t,m,'Ignore',target=OWNER)
    elif exemption=='ally_only':use(c,t,m,'Ignore',target=ALLY)
    before=len(c._load_session(m).engine.events)
    moves=[x for x in c._load_session(m).engine.legal_candidates()
           if getattr(x.kind,'value',x.kind)=='MOVE' and x.destination.x==4 and x.destination.y==6]
    assert moves;settle(t,m,moves[0].candidate_id);e=reload(tmp_path,m);events=e.events[before:]
    attacks=[x for x in events if x.event_type=='ATTACK_ROLLED']
    paid=exemption in ('owner_only','ally_only')
    assert bool(attacks) is paid
    if paid:
        exempt=OWNER if exemption=='owner_only' else ALLY
        assert all(x.actor_id!=exempt for x in attacks)
        assert any(x.event_type=='RESOURCE_SPENT' and x.source_definition_id==GAP for x in events)
    else:
        assert not any(x.source_definition_id==GAP and x.event_type=='RESOURCE_SPENT' for x in events)
        assert not any(x.source_definition_id==GAP and x.event_type=='PASSIVE_TRIGGERED' for x in events)

@pytest.mark.parametrize('mover_ai',[False,True])
@pytest.mark.parametrize('accept',[False,True])
def test_gap_asks_manual_attacker_even_when_free_and_reaction_is_spent(tmp_path,mover_ai,accept):
    c,t,m=make(tmp_path,[GAP],ask=True,positions={OWNER:{'x':3,'y':6},ALLY:{'x':5,'y':6},FOE:{'x':4,'y':7}})
    turn(t,m,ALLY);use(c,t,m,'Spend Reaction')
    turn(t,m,OWNER);use(c,t,m,'Fund');use(c,t,m,'Set the Standard');turn(t,m,FOE)
    e=c._load_session(m).engine
    momentum_before=e.state.actors[OWNER].resources[wl.MOMENTUM]
    event_start=len(e.events)
    if mover_ai:
        c.set_controller_mode(m,actor_id=FOE,controller_mode='LOCAL_AUTO')
        from combat.gate4_adapters import ManualControllerAdapter
        real=c.controller
        class Controller:
            def choose_primary_action(self,context):
                chosen=next(x for x in context.legal_candidates if getattr(x.kind,'value',x.kind)=='MOVE'
                            and x.destination.x==4 and x.destination.y==6)
                return ManualControllerAdapter(lambda _: (chosen.candidate_id,())).choose_primary_action(context)
            def __getattr__(self,name):return getattr(real,name)
        c.controller=Controller()
        cid=None
    else:
        moves=[x for x in e.legal_candidates() if getattr(x.kind,'value',x.kind)=='MOVE'
               and x.destination.x==4 and x.destination.y==6]
        assert moves;cid=moves[0].candidate_id
    answers=[];prompts=[]
    for _ in range(20):
        result=t.auto_step(m,0,answers) if mover_ai else act(t,m,cid,answers)
        if result['status']!='REACTION_REQUIRED':
            assert result['status']=='COMMITTED',result
            break
        p=result['reaction'];prompts.append(p);rid=p['context']['reaction_source_id']
        if rid.startswith('choice:'):
            selection='USE'
        elif rid=='reaction:typed.opportunity_attack':
            selection='USE' if accept else 'DECLINE'
        else:
            selection='DECLINE'
        answer={**p['context'],'selection':selection}
        if selection=='USE' and p.get('choice'):
            options=[option['id'] for option in p['choice']['options']]
            answer['option_ids']=[ALLY if ALLY in options else options[0]]
        answers.append(answer)
    else:pytest.fail('too many reaction prompts')
    assert any(p['context']['reaction_source_id']=='reaction:typed.opportunity_attack' for p in prompts)
    gap_prompt=next(p for p in prompts if p['context']['reaction_source_id']=='reaction:typed.opportunity_attack')
    assert gap_prompt['reaction']=='Command the Gap'
    assert 'moved within the reaches' in gap_prompt['trigger']
    assert e.state.actors[ALLY].display_name in gap_prompt['trigger']
    assert e.state.actors[FOE].display_name in gap_prompt['trigger']
    assert 'you do not spend a Reaction' in gap_prompt['summary']
    assert 'No Reaction cost' in gap_prompt['cost']
    assert gap_prompt['title']!='Reaction'
    e=reload(tmp_path,m)
    movement_events=e.events[event_start:]
    gap=[x for x in movement_events if x.source_definition_id==GAP and x.event_type=='PASSIVE_TRIGGERED']
    assert bool(gap) is accept
    assert bool([x for x in movement_events if x.event_type=='ATTACK_ROLLED' and x.actor_id==ALLY]) is accept
    spends=[x for x in movement_events if x.event_type=='RESOURCE_SPENT' and x.source_definition_id==GAP]
    assert len(spends)==int(accept)
    gains=sum(x.payload.get('gained',0) for x in movement_events if x.event_type=='RESOURCE_GAINED'
              and x.actor_id==OWNER and x.payload.get('resource_id')==wl.MOMENTUM)
    assert e.state.actors[OWNER].resources[wl.MOMENTUM]==momentum_before-int(accept)+gains
    assert bool(e.state.actors[FOE].turn_flags.get('typed_round_wl_gap_provoked')) is accept
    assert e.state.actors[ALLY].reaction_available is False


def fixed_attacks(monkeypatch,natural):
    from combat.gate2_rolls import DeterministicRollAuthority
    original=DeterministicRollAuthority.raw_d20
    def raw(self,**kw):
        row=original(self,**kw)
        if kw['reason'].startswith('ATTACK:'):
            row=row.model_copy(update={'dice':(natural,), 'natural_result':natural,'discarded':(), 'mode':'NORMAL','total':natural+kw['modifier']})
        return row
    monkeypatch.setattr(DeterministicRollAuthority,'raw_d20',raw)

@pytest.mark.parametrize('owned,funded,natural,accept,supported',[(True,True,20,True,True),(False,True,20,True,True),
    (True,False,20,True,True),(True,True,15,True,True),(True,True,20,False,True),(True,True,20,True,False)])
def test_captain_paid_critical_conversion_and_scene_limit(tmp_path,monkeypatch,owned,funded,natural,accept,supported):
    fixed_attacks(monkeypatch,natural)
    c,t,m=make(tmp_path,[CAPTAIN] if owned else [],positions={OWNER:{'x':3,'y':6},ALLY:{'x':4 if supported else 8,'y':6},FOE:{'x':6,'y':7}},ask=True)
    if funded:use(c,t,m,'Fund')
    use(c,t,m,'Set the Standard');turn(t,m,FOE)
    before=c._load_session(m).engine.state.actors[OWNER].resources[wl.MOMENTUM]
    use(c,t,m,'Critical',{'choice:warleader.iron_captain':'protect' if accept else None},target=ALLY)
    e=reload(tmp_path,m);protected=owned and funded and natural==20 and accept and supported
    assert e.state.actors[OWNER].resources[wl.MOMENTUM]==before-int(protected)
    rolls=[x for x in e.events if x.event_type=='DAMAGE_ROLLED' and x.source_definition_id.endswith('.Critical')]
    assert len(rolls[-1].payload['dice'])==(1 if protected or natural<20 else 2)
    assert e.state.actors[OWNER].reaction_available
    if protected:
        use(c,t,m,'Critical',target=ALLY);e=reload(tmp_path,m)
        rolls=[x for x in e.events if x.event_type=='DAMAGE_ROLLED' and x.source_definition_id.endswith('.Critical')]
        assert len(rolls[-1].payload['dice'])==2
        assert e.state.actors[OWNER].resources[wl.MOMENTUM]==before-1


def test_bearer_ai_selects_only_commanded_allies_with_enemy_in_range(tmp_path):
    from combat.gate4_adapters import ManualControllerAdapter
    c,t,m=make(tmp_path,[BEARER],extra_allies=1)
    real=c.controller
    class Controller:
        def choose_primary_action(self,context):
            chosen=next(x for x in context.legal_candidates if x.display_name=='Set the Standard')
            return ManualControllerAdapter(lambda _: (chosen.candidate_id, ())).choose_primary_action(context)
        def __getattr__(self,name):return getattr(real,name)
    c.controller=Controller();c.set_controller_mode(m,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    settle(t,m,None,auto=True);e=reload(tmp_path,m)
    assert e.state.actors[FOE].temporary_hp==0 and not held(e,FOE,GRANT)
    assert sum(bool(held(e,aid,GRANT)) for aid in [OWNER,ALLY,OTHER])==1
