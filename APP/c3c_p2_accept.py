from pathlib import Path
from fastapi.testclient import TestClient
from app.api import create_app
from app.core import Settings
import tempfile, json, zipfile, hashlib
ROOT=Path('.').resolve(); base=Path(tempfile.mkdtemp(prefix='c3c-p2-')); data=base/'UserData'
def tree(p): return {str(x.relative_to(p)):hashlib.sha256(x.read_bytes()).hexdigest() for x in p.rglob('*') if x.is_file()} if p.exists() else {}
def setup(cat, ids, seed, teams=None):
 bf=cat['battlefields'][0]; auth=cat['c3c_p1_setup_authority']; parts=[]; teams=teams or {ids[0]:'team:1',ids[1]:'team:2'}
 for a in ids:
  au=auth[a]; r=au['resources']; parts.append({'actor_id':a,'team_id':teams[a],'qi_current':r.get('qi',{}).get('current',0),'stamina_current':r.get('stamina',{}).get('current',0),'resonance_current':r.get('resonance',{}).get('current',0),'controller_mode':'MANUAL','token_asset_id':au['token_asset_id'],'footprint_width':au['footprint']['width'],'footprint_height':au['footprint']['height'],'placement':au['placement']})
 return {'encounter_id':cat['encounters'][0]['stable_id'],'display_name':'C3C P2 Dynamic','match_seed':seed,'maximum_rounds':20,'battlefield_id':bf['stable_id'],'initiative_method':'DETERMINISTIC_ACCEPTED','grid_calibration':{'mode':'AUTHORITATIVE_GATE2_GRID','width':bf['width_squares'],'height':bf['height_squares'],'square_size_ft':bf['square_size_ft'],'centered_tokens':True},'participants':parts,'team_names':{'team:1':'Crimson','team:2':'Jade'}}
with TestClient(create_app(Settings.from_env(ROOT,data))) as c:
 h={'x-foundry-token':c.get('/api/session').json()['token']}; cat=c.get('/api/combat/catalog').json(); prim=[r for r in cat['projections'] if r.get('primary_combatant')]
 by={r['display_name']:r['runtime_entity_id'] for r in prim}; an,lee,ling,bai=by['An Eui'],by['Lee Jia'],by['Ling Qi'],by['Bai Meizhen']
 # Case A 1v1
 p=setup(cat,[an,lee],'C3C-P2-1V1'); before=tree(data/'Combat'); a=c.post('/api/combat/new-fight/preflight',headers=h,json=p); b=c.post('/api/combat/new-fight/preflight',headers=h,json=p); assert a.status_code==200 and a.json()==b.json() and a.json()['ready'] and tree(data/'Combat')==before
 cr=c.post('/api/combat/new-fight/create',headers=h,json={**p,'preflight_commitment':a.json()['preflight_commitment'],'idempotency_key':'c3c-p2-case-a','owner_confirmed':True}); assert cr.status_code==200,cr.text; mid=cr.json()['match_id']; assert set(x['entity_id'] for x in cr.json()['state']['actors'])=={an,lee}
 retry=c.post('/api/combat/new-fight/create',headers=h,json={**p,'preflight_commitment':a.json()['preflight_commitment'],'idempotency_key':'c3c-p2-case-a','owner_confirmed':True}); assert retry.json()['match_id']==mid
 steps=0
 for actor in [an,lee]: c.post(f'/api/combat/matches/{mid}/controller-mode',headers=h,json={'actor_id':actor,'controller_mode':'LOCAL_AUTO'}).raise_for_status()
 while c.get(f'/api/combat/matches/{mid}').json()['state']['round_number']<2:
  r=c.post(f'/api/combat/matches/{mid}/local-step',headers=h,json={}); assert r.status_code==200,r.text; steps+=1; assert steps<80
 c.post(f'/api/combat/matches/{mid}/pause',headers=h,json={}).raise_for_status()
with TestClient(create_app(Settings.from_env(ROOT,data))) as c:
 h={'x-foundry-token':c.get('/api/session').json()['token']}; assert c.get(f'/api/combat/matches/{mid}').json()['metadata']['paused']; c.post(f'/api/combat/matches/{mid}/resume',headers=h,json={}).raise_for_status(); c.post(f'/api/combat/matches/{mid}/snapshot',headers=h,json={}).raise_for_status(); ver=c.post(f'/api/combat/matches/{mid}/verify',headers=h,json={}); assert ver.json()['status']=='PASS',ver.text; rep=c.get(f'/api/combat/matches/{mid}/replay'); assert rep.status_code==200; exp=c.get(f'/api/combat/matches/{mid}/export'); assert exp.status_code==200; z=base/'a.zip'; z.write_bytes(exp.content); assert zipfile.ZipFile(z).testzip() is None
 # Case B asymmetric with companion
 cat=c.get('/api/combat/catalog').json(); p2=setup(cat,[bai,an,ling],'C3C-P2-COMP',{bai:'team:1',an:'team:2',ling:'team:2'}); pf=c.post('/api/combat/new-fight/preflight',headers=h,json=p2); assert pf.status_code==200 and pf.json()['ready'],pf.text; assert pf.json()['included_companion_ids']==['bai_cui']; cb=c.post('/api/combat/new-fight/create',headers=h,json={**p2,'preflight_commitment':pf.json()['preflight_commitment'],'idempotency_key':'c3c-p2-case-b','owner_confirmed':True}); assert cb.status_code==200,cb.text; actors={x['entity_id']:x for x in cb.json()['state']['actors']}; assert set(actors)=={bai,an,ling,'bai_cui'} and actors['bai_cui']['team_id']==actors[bai]['team_id']
 # negatives
 bad=json.loads(json.dumps(p)); bad['participants'].append(dict(bad['participants'][0])); assert not c.post('/api/combat/new-fight/preflight',headers=h,json=bad).json()['ready']
 bad=setup(cat,[an,lee],'empty'); bad['participants'][1]['team_id']='team:1'; assert not c.post('/api/combat/new-fight/preflight',headers=h,json=bad).json()['ready']
 bad=setup(cat,[an,lee],'overlap'); bad['participants'][1]['placement']=bad['participants'][0]['placement']; assert not c.post('/api/combat/new-fight/preflight',headers=h,json=bad).json()['ready']
 bad=setup(cat,[an,lee],'unknown'); bad['participants'][1]['actor_id']='unknown'; assert not c.post('/api/combat/new-fight/preflight',headers=h,json=bad).json()['ready']
 bad=setup(cat,[an,lee],'comp'); bad['participants'][1]['actor_id']='bai_cui'; assert not c.post('/api/combat/new-fight/preflight',headers=h,json=bad).json()['ready']
 # golden regression
 pg=setup(cat,[an,lee,ling,bai],'golden',{an:'team:1',lee:'team:1',ling:'team:2',bai:'team:2'}); g=c.post('/api/combat/new-fight/preflight',headers=h,json=pg); assert g.status_code==200 and g.json()['ready'],g.text
 report={'schema':'Tianxia.C3CP2Acceptance.v1','status':'PASS','case_a':{'match_id':mid,'actors':[an,lee],'round':2,'steps':steps,'verification':ver.json()},'case_b':{'match_id':cb.json()['match_id'],'actors':sorted(actors),'companion_team':actors['bai_cui']['team_id']},'negative_cases':'PASS','golden_regression':'PASS','isolated_userdata':str(data)}
Path('CHECKPOINTS/C3C_P2_COMPLETE').mkdir(parents=True,exist_ok=True); Path('CHECKPOINTS/C3C_P2_COMPLETE/C3C_P2_ACCEPTANCE_REPORT.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n'); print(json.dumps(report,indent=2))
