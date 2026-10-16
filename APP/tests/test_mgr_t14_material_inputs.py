"""Typed owner/GM source input and physical ordinary threadwork, without sockets."""
import json
import httpx
import pytest
from app.api import create_app
from app.core import Settings
from tests.async_support import run_asgi
from tests.h1_support import ROOT
from tests.test_mgr_t14_stock_materials import game,supply,A,B
THREAD='THREAD_BASE_SPOOL_AND_STRAND'


@pytest.mark.parametrize('operation',['prepare','draw','control','conceal','sew','bind','stitch','tie_knot','mend_cloth','mark_path','set_cord','hide_spool','finework'])
def test_mundane_threadwork_uses_actual_tools_without_check_or_cost(tmp_path,monkeypatch,operation):
    cold,jid,act,admit=game(tmp_path,monkeypatch,features=[THREAD])
    tool=supply(admit,act,'silk-spool','thread_tool',1,material='silk')
    target=supply(admit,act,'cloth-workpiece','raw_material',1,material='cloth')
    admit('thread_task',{'id':'mending','operation':operation,'target':target,'difficulty':'ordinary','dc':0,'ability':'DEX'})
    before=cold().journey_state(jid,viewer_id=A)
    menu=cold().journey_menu(jid,A)
    option=next(o for o in menu['options'] if o['kind']=='thread_handle')
    result=act(option['kind'],option['payload'])
    assert result['seconds']==before['seconds']
    assert result['actors'][A]['resources']==before['actors'][A]['resources']
    assert result['actors'][A]['material_holdings'][target]['threadwork']['tool_id']==tool
    assert result['actors'][A]['thread_tasks']['mending']['completed']==1
    assert not any(e['kind']=='THREADWORK_CHECK' for e in result['events'])
    assert cold().journeys.replay(jid)['status']=='PASS'
    assert 'thread_tasks' not in cold().journey_state(jid,viewer_id=B)['actors'][A]


def test_difficult_threadwork_rolls_actual_stat_and_failure_changes_no_workpiece(tmp_path,monkeypatch):
    cold,jid,act,admit=game(tmp_path,monkeypatch,features=[THREAD])
    tool=supply(admit,act,'wire','thread_tool',1,material='wire')
    target=supply(admit,act,'cloth','raw_material',1,material='cloth')
    admit('thread_task',{'id':'storm-knot','operation':'tie_knot','target':target,'difficulty':'difficult','dc':100,'ability':'DEX'})
    result=act('thread_handle',{'task':'storm-knot','tool':tool})
    assert 'threadwork' not in result['actors'][A]['material_holdings'][target]
    event=next(e for e in result['events'] if e['kind']=='THREADWORK_CHECK')
    assert event['roll']['modifier']==2 and event['roll']['reason']=='CHECK:Threadwork'
    assert cold().journeys.replay(jid)['status']=='PASS'
    with pytest.raises(ValueError):act('thread_handle',{'task':'storm-knot','tool':tool},B)


def test_native_http_facts_require_session_gm_and_complete_source_then_cold_reload(tmp_path,monkeypatch):
    cold,jid,act,admit=game(tmp_path,monkeypatch)
    settings=Settings.from_env(ROOT,tmp_path)
    app=create_app(settings)
    app.state.agent_seats.background=False
    source={'id':'field-receipt','name':'Named paid common reagents','kind':'common_reagents','context':'market',
            'material':'common reagents','unit':'gp','quantity':20,'known_to':[A],'exclusive_to':A}
    request={'revision':0,'actor_id':A,'kind':'material_source','payload':source,'gm':True,
             'reason':'The GM records this named purchase from the scene market.'}
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1:8000') as client:
            url=f'/api/combat/journeys/{jid}/facts'
            assert (await client.post(url,json=request)).status_code==403
            token=(await client.get('/api/session')).json()['token']; headers={'x-foundry-token':token}
            assert (await client.post(url,headers=headers,json={**request,'gm':False})).status_code==400
            assert (await client.post(url,headers=headers,json={**request,'payload':{**source,'quantity':True}})).status_code==400
            accepted=await client.post(url,headers=headers,json=request)
            assert accepted.status_code==200,accepted.text
            assert (await client.post(url,headers=headers,json=request)).status_code==400
            assert 'material_sources' not in (await client.get(f'/api/combat/journeys/{jid}')).json()
            collect={'revision':1,'actor_id':A,'kind':'collect_material','payload':{'source':'field-receipt','quantity':20}}
            accepted=await client.post(f'/api/combat/journeys/{jid}/act',headers=headers,json=collect)
            assert accepted.status_code==200,accepted.text
            owned=await client.get(f'/api/combat/journeys/{jid}',params={'viewer_id':A})
            assert owned.json()['actors'][A]['material_holdings']['field-receipt:20']['quantity']==20
    run_asgi(exercise())
    assert cold().journeys.replay(jid)['status']=='PASS'
