"""Travel interruptions and honest quotes through native committed service paths."""
import pytest
from tests.test_mgr_t14_clinical_native import (
    A, B, C, ROOT, game, exposure, start, engine, use,
    final_native_mechanical_replay,
)
from tests.test_mgr_t14_clinical_review_f4 import conditions
from tests.test_mgr_t14_clinical_review_f5 import finish, scenario
from combat.ext.clinical_procedures import PROGRESS


def test_clinical_acquisition_supplies_sealed_authority_in_isolated_test_root(tmp_path,monkeypatch):
    from character_creation.constructed_arts import forging_authority as fa
    # Exercise the exact absent-resource condition in the admitted snapshot.
    monkeypatch.setattr(fa,'forging_authority_path',lambda root: tmp_path/'absent.json')
    cold,table,jid,command,world=game(tmp_path,monkeypatch,spheres=('life',))
    authority=fa.load_forging_authority(ROOT)
    assert authority['seal_sha256']
    assert fa.forging_authority_path(ROOT).is_relative_to(tmp_path)
    assert not (tmp_path/'absent.json').exists()
    assert cold().journey_state(jid)['actors'][A]['bundle']['action_catalog']


@pytest.mark.parametrize('interruption',['practitioner-moves','patient-moves','incapacitated'])
def test_paid_work_interrupted_in_travel_cannot_be_revived(tmp_path,monkeypatch,interruption):
    from combat import factory_compiler
    from combat.canonical import canonical_sha256
    compile_character=factory_compiler.compile_character
    def with_finisher(doc,**kwargs):
        bundle=compile_character(doc,**kwargs)
        source='action:test.clinical.finish.'+bundle['actor_id']
        bundle['action_catalog'].append({'source_definition_id':source,'owner_id':bundle['actor_id'],
            'display_name':'Finish encounter','economy':'BONUS_ACTION','resolution_kind':'TYPED',
            'target_kind':'ANY_CREATURE','range_ft':60,'parameters':{'typed':{'source':source,
                'numbers':{},'duration':{'kind':'instant'},'riders':[],
                'effects':[{'type':'damage','flat':10000,'damage_types':['force'],'applies_to':'target'}]}}})
        bundle['actor_template']['action_ids'].append(source)
        bundle.pop('bundle_sha256',None);bundle['bundle_sha256']=canonical_sha256(bundle)
        return bundle
    monkeypatch.setattr(factory_compiler,'compile_character',with_finisher)
    cold,table,jid,command,world=game(tmp_path,monkeypatch,spheres=(),ally=True)
    group=exposure(lambda *a,**kw: world(*a,target=C,**kw),'poison','poisoned')
    world('clinical_protocol',{'method':'Medicine','ability':'WIS','skill':'medicine','seconds':18,
        'costs':{'resource:core.qi':1},'operation':'treat','source_instance':group},
        target=C,scope='medicine',readers=[A])
    mid=start(cold,jid)
    before=engine(cold,mid).state.actors[A].resources['resource:core.qi']
    use(cold,table,mid,'Begin Medicine treatment',target=C)
    assert any(c.condition_id==PROGRESS for c in engine(cold,mid).state.actors[A].conditions.values())
    resumed=finish(cold,table,jid,mid,A)
    assert any(c['condition_id']==PROGRESS for c in conditions(resumed,A))
    if interruption=='incapacitated':
        interrupted=command('incapacitated',{'value':True})
        returned=command('incapacitated',{'value':False})
    elif interruption=='patient-moves':
        interrupted=command('move',{'path':[{'x':3,'y':4}]},actor=C)
        returned=command('move',{'path':[{'x':3,'y':5}]},actor=C)
    else:
        interrupted=command('move',{'path':[{'x':2,'y':6},{'x':1,'y':6}]})
        returned=command('move',{'path':[{'x':2,'y':6},{'x':3,'y':6}]})
    assert not any(c['condition_id']==PROGRESS for c in conditions(interrupted,A))
    assert not any(c['condition_id']==PROGRESS for c in conditions(returned,A))
    assert returned['actors'][A]['resources']['resource:core.qi']==before-1
    assert any(e['kind']=='CLINICAL_PROCEDURE_INTERRUPTED' for e in returned['events'])
    option=next(o for o in cold().journey_menu(jid,A)['options'] if o['kind']=='clinical_treat')
    assert '18 seconds' in option['label'] and '1 Qi' in option['label']
    command('declare_fact',{'source':'clinical_source','subject':C,'kind':'clinical_consent',
        'scope':'medicine:'+group+':'+A,'value':1,
        'expires_at':int(returned['seconds'])+3600,'readers':[A]},actor=C)
    clock=cold().journey_state(jid)['seconds']
    done=command('clinical_treat',option['payload'])
    assert done['seconds']==clock+18
    assert done['actors'][A]['resources']['resource:core.qi']==before-2
    assert not any((c['data'].get('clinical') or {}).get('source_instance')==group for c in conditions(done,C))


def test_carried_work_quote_matches_remaining_execution(tmp_path,monkeypatch):
    cold,table,jid,command,mid,patient,healer,_,group=scenario(tmp_path,monkeypatch,treatment_seconds=18)
    before=engine(cold,mid).state.actors[patient].resources['resource:core.qi']
    use(cold,table,mid,'Begin Medicine treatment',aid=patient,target=patient)
    resumed=finish(cold,table,jid,mid,patient)
    option=next(o for o in cold().journey_menu(jid,patient)['options'] if o['kind']=='clinical_treat')
    assert 'continue to treat' in option['label']
    assert '12 seconds' in option['label'] and 'no resource cost' in option['label']
    assert '18 seconds' not in option['label'] and '1 Qi' not in option['label']
    done=command('clinical_treat',option['payload'],actor=patient)
    assert done['seconds']==resumed['seconds']+12
    assert done['actors'][patient]['resources']['resource:core.qi']==before-1
    assert not any(c['condition_id']==PROGRESS for c in conditions(done,patient))
    assert not any((c['data'].get('clinical') or c['data'].get('clinical_retained_source') or {}).get('source_instance')==group
                   for c in conditions(done,patient))
