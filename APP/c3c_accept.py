from pathlib import Path
from fastapi.testclient import TestClient
from app.api import create_app
from app.core import Settings
import tempfile, hashlib, json, zipfile
ROOT=Path('.').resolve(); data=Path(tempfile.mkdtemp(prefix='c3c-'))/'UserData'
def fp(p):
 return {str(x.relative_to(p)):hashlib.sha256(x.read_bytes()).hexdigest() for x in sorted(p.rglob('*')) if x.is_file()} if p.exists() else {}
with TestClient(create_app(Settings.from_env(ROOT,data))) as c:
 token=c.get('/api/session').json()['token']; h={'x-foundry-token':token}
 cat=c.get('/api/combat/catalog').json(); bf=cat['battlefields'][0]; pos=bf['starting_positions']; parts=[]
 for row in cat['projections']:
  if not row.get('primary_combatant'): continue
  parts.append({'actor_id':row['runtime_entity_id'],'team_id':row['team_id'],'qi_current':0,'stamina_current':0,'resonance_current':0,'controller_mode':'LOCAL_AUTO','token_asset_id':row['character_sheet_identity'],'footprint_width':1,'footprint_height':1,'placement':pos[row['runtime_entity_id']]})
 payload={'encounter_id':cat['encounters'][0]['stable_id'],'display_name':'C3C P1 Golden Round','match_seed':'C3C-P1-GOLDEN-ROUND-0001','maximum_rounds':20,'battlefield_id':bf['stable_id'],'initiative_method':'DETERMINISTIC_ACCEPTED','grid_calibration':{'mode':'AUTHORITATIVE_GATE2_GRID','width':bf['width_squares'],'height':bf['height_squares'],'square_size_ft':bf['square_size_ft'],'centered_tokens':True},'participants':parts}
 before=fp(data/'Combat')
 p1=c.post('/api/combat/new-fight/preflight',headers=h,json=payload); assert p1.status_code==200,p1.text
 p2=c.post('/api/combat/new-fight/preflight',headers=h,json=payload); assert p2.status_code==200,p2.text
 assert p1.json()==p2.json() and fp(data/'Combat')==before and p1.json()['ready']
 create={**payload,'preflight_commitment':p1.json()['preflight_commitment'],'idempotency_key':'c3c-p1-golden-create','owner_confirmed':True}
 r=c.post('/api/combat/new-fight/create',headers=h,json=create); assert r.status_code==200,r.text
 mid=r.json()['match_id']; rr=c.post('/api/combat/new-fight/create',headers=h,json=create); assert rr.status_code==200,rr.text; assert rr.json()['match_id']==mid
 reactions=0; steps=0
 while True:
  state=c.get(f'/api/combat/matches/{mid}').json()['state']
  if state['round_number']>=2: break
  out=c.post(f'/api/combat/matches/{mid}/local-step',headers=h,json={}); assert out.status_code==200,out.text
  body=out.json(); assert body['status']=='COMMITTED',body
  steps+=1
  rec=body.get('record',{})
  reactions += len(rec.get('reaction_decisions') or [])
  if steps>120: raise RuntimeError('round did not complete')
 paused=c.post(f'/api/combat/matches/{mid}/pause',headers=h,json={}); assert paused.json()['metadata']['paused']
 snap=c.post(f'/api/combat/matches/{mid}/snapshot',headers=h,json={}); assert snap.status_code==200,snap.text
 ver=c.post(f'/api/combat/matches/{mid}/verify',headers=h,json={}); assert ver.status_code==200 and ver.json()['status']=='PASS',ver.text
 rep=c.get(f'/api/combat/matches/{mid}/replay'); assert rep.status_code==200,rep.text
 exp=c.get(f'/api/combat/matches/{mid}/export'); assert exp.status_code==200,exp.text
 z=Path(tempfile.mkdtemp())/'combat.zip'; z.write_bytes(exp.content)
 with zipfile.ZipFile(z) as za: assert za.testzip() is None
 print(json.dumps({'data_root':str(data),'match_id':mid,'steps':steps,'round':c.get(f'/api/combat/matches/{mid}').json()['state']['round_number'],'reactions_in_records':reactions,'verify':ver.json(),'snapshot':snap.json(),'export_bytes':len(exp.content),'preflight_no_write':True,'idempotent_retry':True},indent=2))
