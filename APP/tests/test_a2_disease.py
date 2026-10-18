"""Disease second pass: table intents, committed state and cold mechanical replay."""
import pytest
from combat.ext import disease
from tests.auto_worker1_support import LEFT, RIGHT, fight, reload, turn, settle, action_sender
WOUND='tianxia.talent.disease.contaminated_wound'
SOW=disease.SOW
CHOICE='choice:needle.contaminated_wound'

def send(combat,table,mid,source,choose=None):
    return settle(action_sender(combat,table,mid,source,target_id=RIGHT),choose=choose)

def wounds(engine):
    return [e for e in engine.events if e.event_type=='RESOURCE_SPENT' and e.source_definition_id==WOUND]

def choose_wound(prompt):
    return ['WOUND'] if prompt['context']['reaction_source_id']==CHOICE else [o['id'] for o in prompt.get('choice',{}).get('options',[])][:1]

@pytest.mark.parametrize('source',['weapon.bi_shou',SOW])
@pytest.mark.parametrize('cl,count',[(5,1),(10,2),(15,3)])
@pytest.mark.parametrize('dc,token',[(100,1),(1,0)])
def test_contaminated_damage_payment_tiers_and_save(tmp_path,source,cl,count,dc,token):
    combat,table,mid=fight(tmp_path,[WOUND,SOW],cl=cl,left_save_dc=dc,left_attack_bonus=100,left_score=30)
    before=reload(combat,mid); balance=dict(before.state.actors[LEFT].resources)
    _,prompts=send(combat,table,mid,source,choose_wound)
    engine=reload(combat,mid)
    assert len([p for p in prompts if p['context']['reaction_source_id']==CHOICE])==1
    assert len(wounds(engine))==1
    assert engine.state.actors[LEFT].resources['resource:core.qi']==balance['resource:core.qi']-1
    assert disease.tokens(engine,engine.state.actors[LEFT],engine.state.actors[RIGHT])==token+(1 if source==SOW else 0)
    damage=[e for e in engine.events if e.event_type=='DAMAGE_COMMITTED' and e.payload.get('display_source_id')==WOUND]
    assert damage,[(e.source_definition_id,e.payload) for e in engine.events if e.event_type=='DAMAGE_COMMITTED']
    rolls=[r for r in engine.rolls if 'DAMAGE' in r.reason]
    assert rolls and len(rolls[-1].dice)==count,[r.model_dump() for r in engine.rolls]
    assert any(m.target_field=='healing_reduction' and m.value=='minus:4' for m in engine.state.actors[RIGHT].modifiers.values())
    assert not any(e.event_type=='GM_RIDER' and 'Contaminated Wound' in str(e.payload) for e in engine.events)
    turn(table,mid,RIGHT);turn(table,mid,LEFT)
    engine=reload(combat,mid)
    assert not any(m.target_field=='healing_reduction' for m in engine.state.actors[RIGHT].modifiers.values())

@pytest.mark.parametrize('owned,accept',[(False,True),(True,False)])
def test_contaminated_nonowner_and_decline(tmp_path,owned,accept):
    combat,table,mid=fight(tmp_path,[WOUND] if owned else [],left_attack_bonus=100,left_score=30)
    _,prompts=send(combat,table,mid,'weapon.bi_shou',lambda p:['WOUND'] if accept and p['context']['reaction_source_id']==CHOICE else [])
    engine=reload(combat,mid)
    assert bool([p for p in prompts if p['context']['reaction_source_id']==CHOICE])==owned
    assert not wounds(engine)
    assert disease.tokens(engine,engine.state.actors[LEFT],engine.state.actors[RIGHT])==0

@pytest.mark.parametrize('mid_id,label,symptom',[
 ('tianxia.talent.disease.weakening_sickness','Weakening Sickness','Contagion Token each turn'),
 ('tianxia.talent.disease.symptom_cascade','Symptom Cascade','Parasite')])
@pytest.mark.parametrize('dc,success',[(100,False),(1,True)])
def test_token_symptom_recurrence_cold_reload_and_expiry(tmp_path,mid_id,label,symptom,dc,success):
    combat,table,mid=fight(tmp_path,[mid_id],left_save_dc=dc)
    def choose(prompt):
        options=prompt.get('choice',{}).get('options',[])
        selected=[o['id'] for o in options if symptom in o['label'] or symptom==o['id']]
        if selected:
            minimum=prompt['choice'].get('minimum',1)
            return selected+[o['id'] for o in options if o['id'] not in selected][:max(0,minimum-len(selected))]
        return [o['id'] for o in options][:1]
    settle(action_sender(combat,table,mid,"Choose "+label+": "+symptom))
    _,prompts=send(combat,table,mid,label,choose)
    engine=reload(combat,mid)
    holders=[c for c in engine.state.actors[RIGHT].conditions.values() if c.condition_id=='condition:typed.affliction']
    assert holders and symptom in holders[0].data['picks'],(prompts,[c.data for c in holders])
    assert disease.tokens(engine,engine.state.actors[LEFT],engine.state.actors[RIGHT])==0
    turn(table,mid,RIGHT);engine=reload(combat,mid)
    assert disease.tokens(engine,engine.state.actors[LEFT],engine.state.actors[RIGHT])==1
    turn(table,mid,LEFT);turn(table,mid,RIGHT);engine=reload(combat,mid)
    assert disease.tokens(engine,engine.state.actors[LEFT],engine.state.actors[RIGHT])==(1 if success else 2)
    assert not any(e.event_type=='GM_RIDER' and ('GM adds' in str(e.payload) or 'GM-only' in str(e.payload)) for e in engine.events)


def test_contaminated_decline_then_shared_frequency_across_deliveries(tmp_path):
    # Only action economy is relaxed in this fixture, to admit independent native
    # weapon/Sow packets in one holder turn. Their delivery and numbers are real.
    def edit(bundle):
        if bundle['actor_id']==LEFT:
            for action in bundle['action_catalog']:
                if action['source_definition_id'].endswith(('weapon.bi_shou',SOW)):
                    action['economy']='NONE'
    combat,table,mid=fight(tmp_path,[WOUND,SOW],left_score=30,left_attack_bonus=100,bundle_edit=edit)
    send(combat,table,mid,'weapon.bi_shou',lambda p:[])
    assert not wounds(reload(combat,mid))
    send(combat,table,mid,SOW,choose_wound)
    assert len(wounds(reload(combat,mid)))==1
    _,prompts=send(combat,table,mid,'weapon.bi_shou',choose_wound)
    assert not any(p['context']['reaction_source_id']==CHOICE for p in prompts)
    assert len(wounds(reload(combat,mid)))==1
    turn(table,mid,RIGHT);turn(table,mid,LEFT)
    send(combat,table,mid,'weapon.bi_shou',choose_wound)
    assert len(wounds(reload(combat,mid)))==2


@pytest.mark.parametrize('reason',['miss','unrelated','empty_pool','retained'])
def test_contaminated_inert_without_admissible_paid_damage(tmp_path,reason):
    def edit(bundle):
        if bundle['actor_id']==LEFT:
            if reason=='empty_pool':
                for pool in bundle['actor_template']['resources']:
                    if pool['resource_id']=='resource:core.qi':pool['initial']=0
            if reason=='retained':
                bundle['typed_passives']=[r for r in bundle.get('typed_passives',[]) if r.get('block')!='disease_wound']
    combat,table,mid=fight(tmp_path,[WOUND],left_score=2 if reason=='miss' else 30,
        prepare=[{'type':'damage','applies_to':'target','flat':5,'damage_types':['force']}],bundle_edit=edit)
    _,prompts=send(combat,table,mid,'Prepare' if reason=='unrelated' else 'weapon.bi_shou',choose_wound)
    engine=reload(combat,mid)
    assert not wounds(engine)
    assert not any(p['context']['reaction_source_id']==CHOICE for p in prompts)
    if reason=='miss':assert not any(e.event_type=='DAMAGE_COMMITTED' for e in engine.events)


@pytest.mark.parametrize('feature,label,symptom',[
 ('tianxia.talent.disease.weakening_sickness','Weakening Sickness','Contagion Token each turn'),
 ('tianxia.talent.disease.symptom_cascade','Symptom Cascade','Parasite')])
def test_selected_token_symptom_ends_with_concentration(tmp_path,feature,label,symptom):
    combat,table,mid=fight(tmp_path,[feature],left_save_dc=100,
        cause=[{'type':'condition','applies_to':'target','condition':'stunned'}])
    settle(action_sender(combat,table,mid,'Choose '+label+': '+symptom))
    send(combat,table,mid,label)
    turn(table,mid,RIGHT)
    engine=reload(combat,mid)
    assert disease.tokens(engine,engine.state.actors[LEFT],engine.state.actors[RIGHT])==1
    assert any(c.condition_id=='condition:typed.affliction' for c in engine.state.actors[RIGHT].conditions.values())
    # Native Stunned ends the caster's current and held concentration. It works
    # in the owner's default unlimited mode as well as the legacy capped mode.
    settle(action_sender(combat,table,mid,'Cause',target_id=LEFT))
    engine=reload(combat,mid)
    assert any(e.event_type=='CONCENTRATION_ENDED' and e.payload.get('reason')=='INCAPACITATED' for e in engine.events)
    assert not any(c.condition_id=='condition:typed.affliction' for c in engine.state.actors[RIGHT].conditions.values())
    settle(action_sender(combat,table,mid,'end'))
    turn(table,mid,RIGHT);engine=reload(combat,mid)
    assert disease.tokens(engine,engine.state.actors[LEFT],engine.state.actors[RIGHT])==1


@pytest.mark.parametrize('feature,label,symptom',[
 ('tianxia.talent.disease.weakening_sickness','Weakening Sickness','Contagion Token each turn'),
 ('tianxia.talent.disease.symptom_cascade','Symptom Cascade','Parasite')])
def test_token_symptom_repeat_save_ends_future_tokens(tmp_path,feature,label,symptom):
    combat,table,mid=fight(tmp_path,[feature],left_save_dc=15,maximum_rounds=20)
    settle(action_sender(combat,table,mid,'Choose '+label+': '+symptom))
    send(combat,table,mid,label)
    initial=reload(combat,mid)
    assert any(c.data.get('repeat_save',{}).get('dc')==15 for c in initial.state.actors[RIGHT].conditions.values())
    for _ in range(9):
        turn(table,mid,RIGHT);turn(table,mid,LEFT)
        engine=reload(combat,mid)
        if not any(c.condition_id=='condition:typed.affliction' for c in engine.state.actors[RIGHT].conditions.values()):break
    else:raise AssertionError('seeded target never succeeded on its repeat save')
    assert any(e.event_type=='CONDITION_REMOVED' and e.payload.get('repeat_save') for e in engine.events)
    count=disease.tokens(engine,engine.state.actors[LEFT],engine.state.actors[RIGHT])
    turn(table,mid,RIGHT);engine=reload(combat,mid)
    assert disease.tokens(engine,engine.state.actors[LEFT],engine.state.actors[RIGHT])==count


@pytest.mark.parametrize('dc',[1,100])
def test_contaminated_healing_is_reduced_then_restored(tmp_path,dc):
    combat,table,mid=fight(tmp_path,[WOUND],left_score=30,left_save_dc=dc,
        prepare=[{'type':'damage','applies_to':'target','flat':100,'damage_types':['force']}],
        cause=[{'type':'healing','applies_to':'self','flat':20}])
    send(combat,table,mid,'Prepare')
    send(combat,table,mid,'weapon.bi_shou',choose_wound)
    turn(table,mid,RIGHT)
    before=reload(combat,mid).state.actors[RIGHT].current_hp
    settle(action_sender(combat,table,mid,'Cause'))
    assert reload(combat,mid).state.actors[RIGHT].current_hp-before==16
    turn(table,mid,LEFT);turn(table,mid,RIGHT)
    before=reload(combat,mid).state.actors[RIGHT].current_hp
    settle(action_sender(combat,table,mid,'Cause'))
    assert reload(combat,mid).state.actors[RIGHT].current_hp-before==20
