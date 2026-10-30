"""A second source exercises the general native journey declaration contract.

These behavioral tests run from any source snapshot: provenance collection
stays in tests/soul_contract_evidence_support.py for queued lane evidence and
must not be bound to the fixtures here, because a public snapshot has no
private historical commit to diff against.
"""
import pytest
from combat import ext
from combat.fact_consent_admission import read
from combat.gate5_service import CombatService
from tests.h1_support import ROOT,sheet

SOURCE='tianxia.subpath.qi.tea_sage_cultivator.feature.grandmaster_infusion'
HOST='actor:factory.host';GUEST='actor:factory.guest'


@ext.hook('fact_admission_schema')
def hospitality_schema(session,source,subject,kind):
    if source!=SOURCE or kind!='hospitality':return None
    if not any(a.get('parameters',{}).get('typed',{}).get('source')==SOURCE
        for actor in session.state['actors'].values() for a in actor['bundle']['action_catalog']):return None
    return {'value_type':'flag','maximum_seconds':60,'description':'Accept this exact hospitality offer.'}


def session_game(tmp_path,monkeypatch,owner=True):
    monkeypatch.setattr(CombatService,'_factory_owner_sheet',lambda self,pid:sheet([SOURCE] if pid=='host' and owner else [],cl=18,name=pid))
    arena={'stable_id':'battlefield:hospitality','display_name':'Tea garden','width_squares':8,'height_squares':8,'square_size_ft':5,'terrain_regions':[],'starting_positions':{}}
    monkeypatch.setattr(CombatService,'factory_arenas',lambda self:{'garden':arena})
    service=CombatService(ROOT,tmp_path)
    state=service.create_journey(project_ids=['host','guest'],arena_id='garden',positions={HOST:{'x':2,'y':2},GUEST:{'x':3,'y':2}},base_paces={HOST:5,GUEST:5})
    jid=state['journey_id']
    def cold():return CombatService(ROOT,tmp_path)
    def act(payload,*,actor=GUEST):
        before=cold().journey_state(jid)
        return cold().journey_act(jid,before['revision'],actor,'declare_fact',payload)
    payload={'source':SOURCE,'subject':GUEST,'kind':'hospitality','scope':'tea-service-offer-one','value':1,'expires_at':60,'readers':[HOST]}
    return cold,jid,act,payload


def test_second_source_native_consent_privacy_expiry_and_refusal(tmp_path,monkeypatch):
    cold,jid,act,payload=session_game(tmp_path,monkeypatch)
    after=act(payload)
    assert cold().journey_state(jid)==after
    session=cold().journeys.load(jid)
    assert read(session,SOURCE,GUEST,'hospitality',payload['scope'],HOST)['value']==1
    after=act({**payload,'value':0,'readers':[]})
    session=cold().journeys.load(jid)
    assert read(session,SOURCE,GUEST,'hospitality',payload['scope'],HOST) is None
    assert read(session,SOURCE,GUEST,'hospitality',payload['scope'],GUEST)['value']==0
    event=after['events'][-1]
    assert event['kind']=='FACT_DECLARED' and 'value' not in event and 'readers' not in event
    cold().journey_act(jid,after['revision'],GUEST,'wait',{'seconds':60})
    assert read(cold().journeys.load(jid),SOURCE,GUEST,'hospitality',payload['scope'],GUEST) is None


@pytest.mark.parametrize('guard',['wrong_owner','unknown_source','wrong_subject','expiry','value_type','spoof_authority'])
def test_general_native_admission_guards_are_default_inert(tmp_path,monkeypatch,guard):
    cold,jid,act,payload=session_game(tmp_path,monkeypatch,owner=guard!='wrong_owner')
    actor=GUEST
    if guard=='unknown_source':payload['source']='unknown-source'
    if guard=='wrong_subject':actor=HOST
    if guard=='expiry':payload['expires_at']=61
    if guard=='value_type':payload['value']='yes'
    if guard=='spoof_authority':payload['authority']='gm'
    before=cold().journey_state(jid)
    with pytest.raises(ValueError):act(payload,actor=actor)
    assert cold().journey_state(jid)==before


@ext.hook('fact_admission_schema')
def hospitality_world_schema(session,source,subject,kind):
    if kind!='ambient_qi':return None
    if hospitality_schema(session,source,subject,'hospitality') is None:return None
    return {'value_type':'flag','maximum_seconds':60,'authority':'table_owner',
            'description':'The native world owner records whether ambient Qi is present.'}


def test_world_input_is_separate_from_party_consent_and_survives_reload(tmp_path,monkeypatch):
    cold,jid,act,payload=session_game(tmp_path,monkeypatch)
    world={**payload,'kind':'ambient_qi'}
    before=cold().journey_state(jid)
    with pytest.raises(ValueError,match='table-owner'):act(world)
    assert cold().journey_state(jid)==before
    after=cold().journey_world_fact(jid,before['revision'],world)
    assert cold().journey_state(jid)==after
    record=read(cold().journeys.load(jid),SOURCE,GUEST,'ambient_qi',payload['scope'],HOST)
    assert record['authority']=='table_owner' and record['value']==1
    assert after['events'][-1]['kind']=='WORLD_FACT_DECLARED' and 'value' not in after['events'][-1]
    with pytest.raises(ValueError,match='private consent'):
        cold().journey_world_fact(jid,after['revision'],payload)
    assert cold().journey_state(jid)==after
    with pytest.raises(ValueError,match='changed'):
        cold().journey_world_fact(jid,before['revision'],world)
    assert cold().journey_state(jid)==after


def test_second_production_consumer_native_scene_end_without_contract_owner(tmp_path,monkeypatch):
    cold,jid,act,payload=session_game(tmp_path,monkeypatch,owner=False)
    before=cold().journey_state(jid)
    after=cold().journey_end_scene(jid,before['revision'],'The tea-house meeting ends and the guests leave.')
    assert cold().journey_state(jid)==after
    record=after['fact_consent_admission'][-1]
    assert record['source']=='system:journey.scene' and record['kind']=='scene_end'
    assert record['authority']=='table_owner'
    assert after['events'][-1]['declaration_receipt']==record['receipt_id']
    assert after['scene_number']==1
    assert after['actors'][GUEST]['resources']==before['actors'][GUEST]['resources']
    ordinary={k:v for k,v in record.items() if k in payload}
    ordinary['expires_at']=1
    with pytest.raises(ValueError,match='table-owner'):act(ordinary,actor=record['subject'])


def test_behavioral_consent_tests_need_no_private_repository_history():
    """A public snapshot has no private ancestor to diff: importing the history
    checkpoint fixture here would abort every behavioral test above."""
    import tests.test_fact_consent_admission as module
    assert not hasattr(module,'source_checkpoint')
