"""Clinical lifecycle seams through committed tables, cold journeys and replay.

The synthetic source is an explicit imported typed test packet (not a claimed
printed ability). It produces a real condition and modifier in one activation.
Life ownership, Purify, protocol admission, treatment and continuation use the
normal imported acquisition and native service paths.
"""
import json
import pytest
from combat.canonical import canonical_sha256
from tests.test_mgr_t14_clinical_native import (
    A,B,C,game,anatomy,exposure,start,engine,use,turn,act,
    final_native_mechanical_replay,
)
from tests.test_mgr_t14_clinical_review_f4 import conditions


def test_main_observer_transport_keeps_authorized_clinical_readings(tmp_path,monkeypatch):
    cold,table,jid,command,world=game(tmp_path,monkeypatch)
    exposure(world,'poison','poisoned',label='An examined poison')
    mid=start(cold,jid)
    e=engine(cold,mid)
    from combat.senses import perception
    known=perception(e,e.state.actors[A]).get('information',[])
    assert any(row.get('details',{}).get('diagnosis')=='An examined poison' for row in known)
    unknown=perception(e,e.state.actors[B]).get('information',[])
    assert not any(row.get('details',{}).get('diagnosis')=='An examined poison' for row in unknown)


def scenario(tmp_path,monkeypatch,*,source_round=100):
    from combat import factory_compiler
    compile_character=factory_compiler.compile_character
    def compile_packet(doc,**kwargs):
        # Both real Life practitioners have a one-round Purify suppression.
        for ability in doc['ability_scores_and_statistics']['abilities']:
            ability.update(score=12,modifier=1)
        bundle=compile_character(doc,**kwargs)
        aid=bundle['actor_id']
        for name,effects,clinical in (
            ('Clinical source packet',[
                {'type':'condition','condition':'poisoned','applies_to':'target',
                 'expires_on':f'START_OF_SLOT_AT:{source_round}:2'},
                {'type':'speed','flat':-5,'applies_to':'target',
                 'expires_on':f'START_OF_SLOT_AT:{source_round}:2'},
            ],{'category':'poison','ongoing':1}),
            ('Finish encounter',[{'type':'damage','flat':10000,'damage_types':['force'],'applies_to':'target'}],None),
        ):
            source='action:test.clinical.'+aid+'.'+name.lower().replace(' ','_')
            row={'source_definition_id':source,'owner_id':aid,'display_name':name,
                 'economy':'NONE','resolution_kind':'TYPED','target_kind':'ANY_CREATURE','range_ft':60,
                 'parameters':{'typed':{'source':source,'numbers':{'save_dc':12,'pb':4,'key_mod':1},
                     'duration':{'kind':'rounds','amount':source_round},'effects':effects,'riders':[],
                     **({'clinical':clinical} if clinical else {})}}}
            bundle['action_catalog'].append(row)
            bundle['actor_template']['action_ids'].append(source)
        bundle.pop('bundle_sha256',None)
        bundle['bundle_sha256']=canonical_sha256(bundle)
        return bundle
    monkeypatch.setattr(factory_compiler,'compile_character',compile_packet)
    cold,table,jid,command,world=game(tmp_path,monkeypatch,spheres=('life',),
        ally=True,third_spheres=('life',),key_score=12)
    anatomy(world)
    world('clinical_anatomy',{'living':1,'meaningful_circulation':1,'meaningful_biology':1},target=C)
    # A rule-qualified procedure is a method declaration, never an exposure.
    for aid in (A,C):
        source='action:test.clinical.'+aid+'.clinical_source_packet'
        world('clinical_protocol',{'method':'Medicine','ability':'WIS','skill':'medicine','seconds':6,
            'costs':{'resource:core.qi':1},'operation':'treat','source_instance':'rule:'+source},
            target=aid,scope='medicine-'+aid,readers=[aid])
    mid=start(cold,jid)
    e=engine(cold,mid)
    order=list(e.state.initiative_order)
    # An earlier practitioner receives the source and finishes the encounter
    # before the later practitioner's suppression slot in the following round.
    patient,healer=sorted((A,C),key=order.index)
    use(cold,table,mid,'Clinical source packet',aid=patient,target=patient)
    e=engine(cold,mid)
    modifier=next(m for m in e.state.actors[patient].modifiers.values() if m.target_field=='speed_ft' and m.value==-5)
    group=next(c.data['clinical']['source_instance'] for c in e.state.actors[patient].conditions.values()
               if c.condition_id=='condition:typed.poisoned')
    use(cold,table,mid,'Purify the Pulse: Remove Poisoned (any living creature)',aid=healer,target=patient)
    e=engine(cold,mid)
    retained=[c for c in e.state.actors[patient].conditions.values() if c.data.get('kind')=='modifier']
    assert len(retained)==1
    assert retained[0].data.get('clinical_retained_source',{}).get('source_instance')==group
    assert modifier.modifier_id not in e.state.actors[patient].modifiers
    return cold,table,jid,command,mid,patient,healer,modifier.modifier_id,group


def finish(cold,table,jid,mid,patient,target=B):
    use(cold,table,mid,'Finish encounter',aid=patient,target=target)
    e=engine(cold,mid)
    assert e.state.terminal_result is not None
    before=e.state.model_dump(mode='json')
    state=cold().journey_state(jid)
    resumed=cold().journey_resume(jid,state['revision'])
    assert engine(cold,mid).state.model_dump(mode='json')==before
    assert cold().journey_state(jid)==resumed
    return resumed


def test_treatment_discards_suppressed_modifier_before_its_deadline(tmp_path,monkeypatch):
    cold,table,jid,command,mid,patient,healer,mid_id,group=scenario(tmp_path,monkeypatch)
    use(cold,table,mid,'Begin Medicine treatment',aid=patient,target=patient)
    e=engine(cold,mid)
    assert not any((c.data.get('clinical') or c.data.get('clinical_retained_source') or {}).get('source_instance')==group
                   for c in e.state.actors[patient].conditions.values())
    # A full round passes after the cure, crossing the original suppression
    # boundary through normal table turns before the encounter ends.
    state=turn(cold,table,mid,patient)
    act(cold,table,mid,state,state['menu']['end_turn'],lambda p,ids:[])
    turn(cold,table,mid,patient)
    assert mid_id not in engine(cold,mid).state.actors[patient].modifiers
    resumed=finish(cold,table,jid,mid,patient)
    later=command('wait',{'seconds':18},actor=patient)
    assert not any(c['data'].get('clinical_retained_source') for c in conditions(later,patient))
    assert later['seconds']>resumed['seconds']


@pytest.mark.parametrize('source_round',[2,100],ids=['original-later-in-terminal-round','suppression-later-in-terminal-round'])
def test_retained_components_keep_later_slot_clocks_through_continuation(tmp_path,monkeypatch,source_round):
    cold,table,jid,command,mid,patient,healer,mid_id,group=scenario(tmp_path,monkeypatch,source_round=source_round)
    resumed=finish(cold,table,jid,mid,patient)
    terminal=engine(cold,mid).state
    assert terminal.round_number==2 and terminal.current_slot_index<2
    rows=conditions(resumed,patient)
    retained=[c for c in rows if c['data'].get('clinical_retained_source')]
    assert {c['data']['kind'] for c in retained}=={'condition','modifier'}
    for c in retained:
        assert c['data']['clinical_suppressed_until']==resumed['seconds']+6
        assert c['data']['clinical_source_expires_at']>resumed['seconds']
    if source_round==2:
        assert all(c['data']['clinical_source_expires_at']==resumed['seconds']+6 for c in retained)
    after=command('wait',{'seconds':6},actor=patient)
    rows=conditions(after,patient)
    assert not any(c['data'].get('clinical_retained_source') for c in rows)
    if source_round==2:
        assert not any(c['data'].get('clinical_stored_modifier') or c['condition_id']=='condition:typed.poisoned' for c in rows)
    else:
        restored=next(c for c in rows if c['data'].get('clinical_stored_modifier'))
        source_end=restored['data']['external_expiry']
        # Re-entry restores the real modifier and cold mechanical replay.
        # The first enemy remains dead: a new encounter needs a living opposing
        # side, not a fabricated resurrection or an already-terminal roster.
        next_mid=start(cold,jid,teams={patient:'team:a',healer:'team:b',B:'team:a'})
        assert mid_id in engine(cold,next_mid).state.actors[patient].modifiers
        use(cold,table,next_mid,'Purify the Pulse: Remove Poisoned (any living creature)',aid=healer,target=patient)
        final_native=finish(cold,table,jid,next_mid,patient,target=healer)
        assert final_native['seconds']<source_end
        retained_again=[c for c in conditions(final_native,patient) if c['data'].get('clinical_retained_source')]
        assert {c['data']['kind'] for c in retained_again}=={'condition','modifier'}
        assert all(c['data']['clinical_source_expires_at']==source_end for c in retained_again)
        ended=command('wait',{'seconds':source_end-final_native['seconds']},actor=patient)
        assert not any(c['data'].get('clinical_stored_modifier') or c['data'].get('clinical_retained_source') for c in conditions(ended,patient))
