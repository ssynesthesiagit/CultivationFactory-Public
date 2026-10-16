"""Review regressions through native declarations, table commits and cold journeys."""
import json
import pytest
from tests.test_mgr_t14_clinical_native import (
    A,B,C,game,anatomy,exposure,start,engine,use,turn,act,next_round,
    final_native_mechanical_replay,
)


def conditions(state,aid):
    return [json.loads(v) for v in state['actors'][aid]['encounter_snapshot']['conditions'].values()]


def test_replaced_protocol_withdraws_reader_and_old_price_in_combat(tmp_path,monkeypatch):
    cold,table,jid,command,world=game(tmp_path,monkeypatch,spheres=(),ally=True)
    group=exposure(world,'poison','poisoned',readers=[A,C])
    value={'method':'Medicine','ability':'WIS','skill':'medicine','seconds':6,
           'costs':{'resource:core.qi':1},'operation':'treat','source_instance':group}
    old=world('clinical_protocol',value,scope='medicine',readers=[A,C])['fact_consent_admission'][-1]
    latest=world('clinical_protocol',{**value,'costs':{'resource:core.qi':3}},scope='medicine',readers=[C])['fact_consent_admission'][-1]
    assert not [c for c in conditions(cold().journey_state(jid),A) if c['condition_id']=='condition:typed.clinical_protocol']
    mid=start(cold,jid)
    e=engine(cold,mid)
    assert not any(old['receipt_id'] in key for key in e.action_catalog)
    assert not any(g['label']=='Begin Medicine treatment' for g in turn(cold,table,mid,A)['menu']['actions'])
    before=e.state.actors[C].resources['resource:core.qi']
    use(cold,table,mid,'Begin Medicine treatment',aid=C)
    e=engine(cold,mid)
    assert e.state.actors[C].resources['resource:core.qi']==before-3
    assert not any((c.data.get('clinical') or {}).get('source_instance')==group for c in e.state.actors[B].conditions.values())
    assert any(latest['receipt_id'] in key for key in e.action_catalog)


def test_actual_resource_price_is_readable_in_travel_and_combat(tmp_path,monkeypatch):
    cold,table,jid,command,world=game(tmp_path,monkeypatch,spheres=())
    group=exposure(world,'poison','poisoned')
    world('clinical_protocol',{'method':'Medicine','ability':'WIS','skill':'medicine','seconds':6,
        'costs':{'resource:core.qi':3},'operation':'treat','source_instance':group},scope='medicine')
    from combat.ext.clinical_treatment import clinical_options
    options=clinical_options(cold().journeys.load(jid),A)
    label=next(o['label'] for o in options if o['kind']=='clinical_treat')
    assert '3 Qi' in label and 'resource:' not in label
    mid=start(cold,jid)
    descriptions=[a.parameters['description'] for a in engine(cold,mid).action_catalog.values()
                  if a.parameters.get('clinical_stage')=='begin']
    assert descriptions and all('3 Qi' in text and 'recorded resources' not in text for text in descriptions)


def test_shared_protocol_actions_survive_cold_reload_for_every_reader(tmp_path,monkeypatch):
    cold,table,jid,command,world=game(tmp_path,monkeypatch,spheres=(),ally=True)
    group=exposure(world,'poison','poisoned',readers=[A,C])
    world('clinical_protocol',{'method':'Medicine','ability':'WIS','skill':'medicine','seconds':12,
        'costs':{'resource:core.qi':1},'operation':'treat','source_instance':group},scope='medicine',readers=[A,C])
    mid=start(cold,jid)
    e=engine(cold,mid)
    actions=[a for a in e.action_catalog.values() if a.parameters.get('clinical_stage')=='begin']
    assert {a.owner_id for a in actions}=={A,C}
    assert len({a.source_definition_id for a in actions})==2
    for reader in (A,C):
        use(cold,table,mid,'Begin Medicine treatment',aid=reader)
        e=engine(cold,mid)
        assert e.state.actors[reader].resources['resource:core.qi']==29
        assert any(c.condition_id=='condition:typed.clinical_procedure' for c in e.state.actors[reader].conditions.values())


@pytest.mark.parametrize('key_score',[14,30],ids=['source-outlasts-suppression','source-expires-during-suppression'])
def test_native_timed_source_retains_own_deadline_across_journey_reload(tmp_path,monkeypatch,key_score):
    cold,table,jid,command,world=game(tmp_path,monkeypatch,spheres=('life',),
        enemy=('the_piercing_needle',),enemy_talents=('TAL_FENCING_FEINT','TAL_FENCING_FACE_STRIKE'),
        enemy_weapon=True,weapon=True,enemy_dc=50,enemy_hp=1,key_score=key_score)
    anatomy(world);mid=start(cold,jid)
    # Native weapon attack + acquired Exploit produces the timed obstruction.
    def strike(aid,target,choose=None):
        state=turn(cold,table,mid,aid)
        candidate=next(o for g in state['menu']['actions'] if g['label'].startswith('Jian')
                       for o in g['options'] if target in o.get('target_ids',[]))
        return act(cold,table,mid,state,candidate['candidate_id'],choose)
    for _ in range(12):
        state=turn(cold,table,mid,B)
        feint=next(g['label'] for g in state['menu']['actions'] if g['label'].startswith('Feint'))
        use(cold,table,mid,feint,target=A,aid=B)
        strike(B,A,lambda p,ids:[v for v in ids if 'face_strike' in v.lower()] or ids[:1])
        e=engine(cold,mid)
        blind=next((c for c in e.state.actors[A].conditions.values() if c.condition_id=='condition:typed.blinded'),None)
        if blind is not None:break
        state=turn(cold,table,mid,B);act(cold,table,mid,state,state['menu']['end_turn'],lambda p,ids:[])
    assert blind is not None
    assert 'external_expiry' not in blind.data
    control=next(c for c in e.state.actors[A].conditions.values() if blind.instance_id in (c.data.get('linked') or []))
    # GM classifies an actual source; this creates no condition or clock.
    payload={'source':'clinical_source','subject':A,'kind':'clinical_annotation','scope':'face-obstruction',
        'value':{'condition_instances':[blind.instance_id,control.instance_id],'label':'Dust obstructing the eyes',
                 'category':'physical_impairment','ongoing':1,'excluded':[]},'expires_at':10000,'readers':[A]}
    before=e.state.model_dump(mode='json')
    with pytest.raises(ValueError,match='actual harmful condition'):
        cold().world_fact(mid,e.state.state_version,{**payload,'value':{**payload['value'],'condition_instances':[control.instance_id]}})
    assert engine(cold,mid).state.model_dump(mode='json')==before
    cold().world_fact(mid,e.state.state_version,payload)
    state=turn(cold,table,mid,A)
    purify=next(g['label'] for g in state['menu']['actions'] if g['label'].startswith('Purify the Pulse: Remove Blinded')
                and any(A in o.get('target_ids',[]) for o in g['options']))
    use(cold,table,mid,purify,target=A)
    assert any(c.data.get('clinical_retained_source') for c in engine(cold,mid).state.actors[A].conditions.values())
    for _ in range(10):
        next_round(cold,table,mid)
        strike(A,B)
        if engine(cold,mid).state.terminal_result is not None:break
    assert engine(cold,mid).state.terminal_result is not None
    state=cold().journey_state(jid)
    resumed=cold().journey_resume(jid,state['revision'])
    retained=next(c for c in conditions(resumed,A) if c['data'].get('clinical_retained_source')
                  and c['data']['model']['instance_id']==blind.instance_id)
    source_end=retained['data']['clinical_source_expires_at']
    suppression_end=retained['data']['clinical_suppressed_until']
    assert source_end>resumed['seconds']
    if key_score==30:
        assert source_end<suppression_end
        expired=command('wait',{'seconds':source_end-resumed['seconds']})
        assert not any(c['data'].get('clinical_retained_source') for c in conditions(expired,A))
        final=command('wait',{'seconds':suppression_end-expired['seconds']})
    else:
        assert suppression_end<source_end
        restored=command('wait',{'seconds':suppression_end-resumed['seconds']})
        original=next(c for c in conditions(restored,A) if c['instance_id']==blind.instance_id)
        assert original['data']['external_expiry']==source_end
        final=command('wait',{'seconds':source_end-restored['seconds']})
    assert not any(c['instance_id']==blind.instance_id or c['data'].get('clinical_retained_source') for c in conditions(final,A))
