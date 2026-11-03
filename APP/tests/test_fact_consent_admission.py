"""A second source exercises the general native journey declaration contract."""
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


@ext.hook('fact_admission_schema')
def validated_schema(session, source, subject, kind):
    if kind != 'validated_hospitality' or hospitality_schema(session, source, subject, 'hospitality') is None:
        return None
    return {'value_type': 'flag', 'maximum_seconds': 60, 'description': 'A source with an additional validation contract.',
            'validate': lambda native_session, payload: payload['value'] == 1}


def test_source_validator_rejects_before_committing_native_declaration(tmp_path, monkeypatch):
    cold, jid, act, payload = session_game(tmp_path, monkeypatch)
    payload = {**payload, 'kind': 'validated_hospitality'}
    before = cold().journey_state(jid)
    with pytest.raises(ValueError, match='native validation'):
        act({**payload, 'value': 0})
    assert cold().journey_state(jid) == before
    after = act(payload)
    assert cold().journey_state(jid, GUEST) == after
    assert read(cold().journeys.load(jid), SOURCE, GUEST, payload['kind'], payload['scope'], GUEST)['value'] == 1
    assert cold().journey_replay(jid)['status'] == 'PASS'


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
    assert cold().journey_state(jid,GUEST)==after
    assert 'fact_consent_admission' not in cold().journey_state(jid)
    assert cold().journey_state(jid,HOST)['fact_consent_admission'][0]['value']==1
    session=cold().journeys.load(jid)
    assert read(session,SOURCE,GUEST,'hospitality',payload['scope'],HOST)['value']==1
    after=act({**payload,'value':0,'readers':[]})
    session=cold().journeys.load(jid)
    assert read(session,SOURCE,GUEST,'hospitality',payload['scope'],HOST) is None
    assert read(session,SOURCE,GUEST,'hospitality',payload['scope'],GUEST)['value']==0
    assert 'fact_consent_admission' not in cold().journey_state(jid,HOST)
    assert cold().journey_state(jid,GUEST)['fact_consent_admission'][0]['value']==0
    assert cold().journey_replay(jid)['status']=='PASS'
    event=after['events'][-1]
    assert event['kind']=='FACT_DECLARED' and 'value' not in event and 'readers' not in event
    cold().journey_act(jid,after['revision'],GUEST,'wait',{'seconds':60})
    assert read(cold().journeys.load(jid),SOURCE,GUEST,'hospitality',payload['scope'],GUEST) is None
    assert 'fact_consent_admission' not in cold().journey_state(jid,GUEST)
    assert cold().journey_replay(jid)['status']=='PASS'


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
    return {'value_type':'flag','maximum_seconds':60,'authority':'table_owner','subject_access':False,
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
    assert cold().journey_state(jid,HOST)['fact_consent_admission'][0]['value']==1
    assert 'fact_consent_admission' not in cold().journey_state(jid,GUEST)
    assert 'fact_consent_admission' not in after
    assert cold().journey_replay(jid)['status']=='PASS'
    assert after['events'][-1]['kind']=='WORLD_FACT_DECLARED' and 'value' not in after['events'][-1]
    with pytest.raises(ValueError,match='private consent'):
        cold().journey_world_fact(jid,after['revision'],payload)
    assert cold().journey_state(jid)==after
    with pytest.raises(ValueError,match='changed'):
        cold().journey_world_fact(jid,before['revision'],world)
    assert cold().journey_state(jid)==after

    # The published HTTP owner boundary must use the same revisioned store.
    import asyncio
    import httpx
    from app.api import create_app
    from app.core import Settings
    app=create_app(Settings.from_env(ROOT,tmp_path))
    app.state.agent_seats.background=False
    async def post_world():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as client:
            token=(await client.get('/api/session')).json()['token']
            return await client.post(f'/api/combat/journeys/{jid}/world-facts',
                headers={'x-foundry-token':token},json={'revision':after['revision'],'payload':{**world,'value':0}})
    response=asyncio.run(post_world())
    assert response.status_code==200, response.text
    assert cold().journey_state(jid)==response.json()
    assert read(cold().journeys.load(jid),SOURCE,GUEST,'ambient_qi',payload['scope'],HOST)['value']==0
    assert cold().journey_replay(jid)['status']=='PASS'
