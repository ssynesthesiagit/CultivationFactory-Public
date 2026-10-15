"""Native controller consent, cap, and replacement boundaries from review."""
from tests.mason_native_support import *


def build_payload(source,form,x,y,**dimensions):
    from combat.ext.needle import cell_id
    from combat.gate2_runtime_models import Position
    d=journey_wall_payload()
    d.update(source=BASE+source,form=form)
    d['sections'][0].update(form=form,position={'x':x,'y':y},
        material_source='terrain:'+cell_id(Position(x=x,y=y)),**dimensions)
    if source=='raise_the_imperial_bastion':
        d.update(form='Raise Sections',chosen_allies=[s.OWNER,s.SECOND])
    return d


def test_elevated_covered_advance_requires_own_consent_and_moves_on_deck(tmp_path):
    combat,j=journey_fixture(tmp_path);jid=j['journey_id']
    state=combat.journey_act(jid,j['revision'],s.OWNER,'mason_build',build_payload(
        'raise_barrier','Platform',4,4,length_ft=10,width_ft=10,height_ft=10))
    state=combat.journey_act(jid,state['revision'],s.SECOND,'move',{'path':[
        {'x':5,'y':5,'z':1},{'x':5,'y':5,'z':2}]})
    state=combat.journey_act(jid,state['revision'],s.OWNER,'mason_build',build_payload(
        'raise_the_imperial_bastion','Low Wall',7,8))
    state=combat.journey_act(jid,state['revision'],s.OWNER,'wait',{'seconds':6})
    path=[{'x':4,'y':5,'z':2}]
    command={'command':'Covered Advance','ally_id':s.SECOND,'path':path}
    with pytest.raises(ValueError):combat.journey_act(jid,state['revision'],s.OWNER,'mason_command',command)
    from combat.fact_consent_admission import canonical
    group=next(o['component']['asset_anchor_runtime']['group'] for o in state['runtime_objects'].values()
        if o['component']['mason']['feature']==BASE+'raise_the_imperial_bastion')
    declaration={'source':BASE+'raise_the_imperial_bastion','subject':s.SECOND,'kind':'covered_advance',
        'scope':canonical({'group':group,'ally':s.SECOND,'path':path}),'value':1,
        'expires_at':int(state['seconds'])+6,'readers':[s.OWNER]}
    with pytest.raises(ValueError):combat.journey_act(jid,state['revision'],s.OWNER,'declare_fact',declaration)
    state=combat.journey_act(jid,state['revision'],s.SECOND,'declare_fact',declaration)
    state=combat.journey_act(jid,state['revision'],s.OWNER,'mason_command',command)
    assert state['actors'][s.SECOND]['position']==path[-1]
    assert state['events'][-2]['kind']=='GRANTED_MOVEMENT'
    assert CombatService(ROOT,tmp_path).journey_state(jid)==state


def test_ordinary_and_temporary_caps_are_independent_and_temporary_expires(tmp_path):
    combat,j=journey_fixture(tmp_path);jid=j['journey_id'];state=j
    for x in (1,3,5,7):
        state=combat.journey_act(jid,state['revision'],s.OWNER,'mason_build',build_payload('raise_barrier','Low Wall',x,8))
    ordinary=set(state['runtime_objects'])
    state=combat.journey_act(jid,state['revision'],s.OWNER,'mason_build',build_payload('raise_the_imperial_bastion','Low Wall',6,10))
    temporary=[]
    from combat.ext.needle import cell_id
    from combat.gate2_runtime_models import Position
    for x in (6,8,10,12,14):
        state=combat.journey_act(jid,state['revision'],s.OWNER,'wait',{'seconds':6})
        before=set(state['runtime_objects'])
        state=combat.journey_act(jid,state['revision'],s.OWNER,'mason_command',{'command':'Raise New Work',
            'section':{'position':{'x':x,'y':12},'rotation':0,'material_source':'terrain:'+cell_id(Position(x=x,y=12))}})
        temporary.extend(set(state['runtime_objects'])-before)
    assert all(not state['runtime_objects'][oid]['destroyed'] for oid in ordinary)
    assert state['runtime_objects'][temporary[0]]['destroyed']
    assert all(not state['runtime_objects'][oid]['destroyed'] for oid in temporary[1:])
    state=combat.journey_act(jid,state['revision'],s.OWNER,'mason_build',build_payload('raise_barrier','Low Wall',9,8))
    assert sum(not state['runtime_objects'][oid]['destroyed'] for oid in ordinary)==3
    ended=combat.journey_end_scene(jid,state['revision'],'The siege situation ended after the defense.')
    assert all(ended['runtime_objects'][oid]['destroyed'] for oid in temporary)
    assert sum(not ended['runtime_objects'][oid]['destroyed'] for oid in ordinary)==3
    assert CombatService(ROOT,tmp_path).journey_state(jid)==ended
