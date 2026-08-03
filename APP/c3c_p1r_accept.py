from pathlib import Path
from fastapi.testclient import TestClient
from app.api import create_app
from app.core import Settings
from combat.gate2_engine import Gate2Engine
import tempfile, hashlib, json, zipfile

ROOT=Path('.').resolve(); base=Path(tempfile.mkdtemp(prefix='c3c-p1r-')); data=base/'UserData'
def tree_hash(p):
 return {str(x.relative_to(p)):hashlib.sha256(x.read_bytes()).hexdigest() for x in sorted(p.rglob('*')) if x.is_file()} if p.exists() else {}
def sanitize(intent):
 return {key:intent.get(key) for key in ("decision_id","state_version","candidate_id","actor_id","target_ids","destination","option_ids")}
def suggest_commit(c,h,mid):
 suggestion=c.post(f'/api/combat/matches/{mid}/suggest',headers=h,json={}); assert suggestion.status_code==200,suggestion.text
 payload=sanitize(suggestion.json()['intent']); reactions=[]
 for _ in range(8):
  preview=c.post(f'/api/combat/matches/{mid}/preview',headers=h,json={'intent':payload,'reaction_decisions':reactions}); assert preview.status_code==200,preview.text
  body=preview.json()
  if body['status']=='REACTION_REQUIRED': reactions.append(body['local_suggestion']['decision']); continue
  commit=c.post(f'/api/combat/matches/{mid}/intent',headers=h,json={'intent':payload,'reaction_decisions':reactions,'preview_id':body['preview_id']}); assert commit.status_code==200,commit.text
  return commit.json(),reactions
 raise AssertionError('reaction loop exceeded')

seed='C3C-P1-GOLDEN-ROUND-0001'
probe=Gate2Engine(ROOT,match_seed=seed,maximum_rounds=20)
order=list(probe.state.initiative_order)
primary=[x for x in order if probe.state.actors[x].primary_combatant]
modes={x:'LOCAL_AUTO' for x in primary}; modes[primary[0]]='MANUAL'; modes[primary[1]]='SUGGESTED'
print('START CLIENT1', flush=True)
with TestClient(create_app(Settings.from_env(ROOT,data))) as c:
 h={'x-foundry-token':c.get('/api/session').json()['token']}
 cat=c.get('/api/combat/catalog').json(); bf=cat['battlefields'][0]; auth=cat['c3c_p1_setup_authority']; parts=[]
 custom={actor_id:row['placement'] for actor_id,row in auth.items()}
 for row in cat['projections']:
  if not row.get('primary_combatant'): continue
  a=auth[row['runtime_entity_id']]; r=a['resources']
  parts.append({'actor_id':row['runtime_entity_id'],'team_id':row['team_id'],'qi_current':r.get('qi',{}).get('current',0),'stamina_current':r.get('stamina',{}).get('current',0),'resonance_current':r.get('resonance',{}).get('current',0),'controller_mode':modes[row['runtime_entity_id']],'token_asset_id':a['token_asset_id'],'footprint_width':a['footprint']['width'],'footprint_height':a['footprint']['height'],'placement':custom[row['runtime_entity_id']]})
 payload={'encounter_id':cat['encounters'][0]['stable_id'],'display_name':'C3C P1R Golden Round','match_seed':seed,'maximum_rounds':20,'battlefield_id':bf['stable_id'],'initiative_method':'DETERMINISTIC_ACCEPTED','grid_calibration':{'mode':'AUTHORITATIVE_GATE2_GRID','width':bf['width_squares'],'height':bf['height_squares'],'square_size_ft':bf['square_size_ft'],'centered_tokens':True},'participants':parts}
 before=tree_hash(data/'Combat')
 print('PREFLIGHT', flush=True)
 p1=c.post('/api/combat/new-fight/preflight',headers=h,json=payload); p2=c.post('/api/combat/new-fight/preflight',headers=h,json=payload)
 assert p1.status_code==200 and p1.json()==p2.json() and p1.json()['ready'] and tree_hash(data/'Combat')==before
 # no-write negatives
 unconfirmed=c.post('/api/combat/new-fight/create',headers=h,json={**payload,'preflight_commitment':p1.json()['preflight_commitment'],'idempotency_key':'unconfirmed-key','owner_confirmed':False}); assert unconfirmed.status_code==409 and tree_hash(data/'Combat')==before
 stale=c.post('/api/combat/new-fight/create',headers=h,json={**payload,'preflight_commitment':'0'*64,'idempotency_key':'stale-key','owner_confirmed':True}); assert stale.status_code==409 and tree_hash(data/'Combat')==before
 create={**payload,'preflight_commitment':p1.json()['preflight_commitment'],'idempotency_key':'c3c-p1r-golden-create','owner_confirmed':True}
 print('CREATE', flush=True)
 r=c.post('/api/combat/new-fight/create',headers=h,json=create); assert r.status_code==200,r.text; mid=r.json()['match_id']
 rr=c.post('/api/combat/new-fight/create',headers=h,json=create); assert rr.status_code==200 and rr.json()['match_id']==mid
 actors={a['entity_id']:a for a in r.json()['state']['actors']}
 for row in p1.json()['participants']:
  assert actors[row['actor_id']]['position']==row['placement']
  for rid,val in row['actual_resources'].items(): assert actors[row['actor_id']]['resources'][rid]==val
 conflict_payload=json.loads(json.dumps(payload)); conflict_payload['participants'][0]['placement']={'x':2,'y':2}
 cp=c.post('/api/combat/new-fight/preflight',headers=h,json=conflict_payload); assert cp.status_code==200 and cp.json()['ready']
 conflict=c.post('/api/combat/new-fight/create',headers=h,json={**conflict_payload,'preflight_commitment':cp.json()['preflight_commitment'],'idempotency_key':'c3c-p1r-golden-create','owner_confirmed':True}); assert conflict.status_code==409
 # manual and suggested-with-approval
 print('MANUAL', flush=True)
 _,rx1=suggest_commit(c,h,mid)
 print('SUGGESTED', flush=True)
 _,rx2=suggest_commit(c,h,mid)
 for actor_id in primary:
  sw=c.post(f'/api/combat/matches/{mid}/controller-mode',headers=h,json={'actor_id':actor_id,'controller_mode':'LOCAL_AUTO'}); assert sw.status_code==200,sw.text
 steps=2; reaction_count=len(rx1)+len(rx2)
 print('AUTO', flush=True)
 while c.get(f'/api/combat/matches/{mid}').json()['state']['round_number']<2:
  out=c.post(f'/api/combat/matches/{mid}/local-step',headers=h,json={}); assert out.status_code==200,out.text
  reaction_count += len(out.json().get('record',{}).get('reaction_decisions') or []); steps+=1
  if steps>120: raise AssertionError('round did not complete')
 print('PAUSE', steps, flush=True)
 paused=c.post(f'/api/combat/matches/{mid}/pause',headers=h,json={}); assert paused.status_code==200 and paused.json()['metadata']['paused']
# actual service restart
print('RESTART', flush=True)
with TestClient(create_app(Settings.from_env(ROOT,data))) as c:
 h={'x-foundry-token':c.get('/api/session').json()['token']}
 reopened=c.get(f'/api/combat/matches/{mid}'); assert reopened.status_code==200 and reopened.json()['metadata']['paused']
 resumed=c.post(f'/api/combat/matches/{mid}/resume',headers=h,json={}); assert resumed.status_code==200 and not resumed.json()['metadata']['paused']
 print('SNAP', flush=True)
 snap=c.post(f'/api/combat/matches/{mid}/snapshot',headers=h,json={}); assert snap.status_code==200
 ver=c.post(f'/api/combat/matches/{mid}/verify',headers=h,json={}); assert ver.status_code==200 and ver.json()['status']=='PASS',ver.text
 rep=c.get(f'/api/combat/matches/{mid}/replay'); assert rep.status_code==200,rep.text
 print('AUDIT', flush=True)
 audit=c.get(f'/api/combat/matches/{mid}/dao-iching-audit'); assert audit.status_code==200 and len(audit.json()['combatants'])==4,audit.text
 print('EXPORT', flush=True)
 exp=c.get(f'/api/combat/matches/{mid}/export'); assert exp.status_code==200
 z=base/'combat.zip'; z.write_bytes(exp.content)
 with zipfile.ZipFile(z) as za: assert za.testzip() is None
 final=c.get(f'/api/combat/matches/{mid}').json()
 report={'schema':'Tianxia.C3CP1RAcceptance.v1','status':'PASS','match_id':mid,'round':final['state']['round_number'],'steps':steps,'reaction_decisions':reaction_count,'manual_actor':primary[0],'suggested_actor':primary[1],'preflight_no_write':True,'genesis_matches_commitment':True,'idempotent_retry':True,'conflicting_reuse_rejected':True,'restart_reopen_resume':True,'snapshot':snap.json(),'verification':ver.json(),'replay':rep.json(),'audit':audit.json(),'export_bytes':len(exp.content),'isolated_userdata':str(data)}
 Path('CHECKPOINTS/C3C_P1R_COMPLETE').mkdir(parents=True,exist_ok=True)
 Path('CHECKPOINTS/C3C_P1R_COMPLETE/C3C_P1R_ACCEPTANCE_REPORT.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
 print(json.dumps(report,indent=2)[:6000])
