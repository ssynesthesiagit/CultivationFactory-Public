from pathlib import Path
from fastapi.testclient import TestClient
from app.api import create_app
from app.core import Settings
from combat.gate2_engine import Gate2Engine
import tempfile,json,zipfile,hashlib,copy
ROOT=Path('.').resolve(); base=Path(tempfile.mkdtemp(prefix='c3c-p3-')); data=base/'UserData'
def matchdir(mid):
 for d in (data/'Combat'/'Matches').glob('*'):
  q=d/'MatchLock.json'
  if q.is_file() and json.loads(q.read_text()).get('match_id')==mid: return d
 raise FileNotFoundError(mid)

def setup(cat, ids, seed, max_rounds=1, teams=None):
 bf=cat['battlefields'][0]; auth=cat['c3c_p1_setup_authority']; teams=teams or {ids[0]:'team:1',ids[1]:'team:2'}; parts=[]
 for a in ids:
  au=auth[a]; r=au['resources']; parts.append({'actor_id':a,'team_id':teams[a],'qi_current':r.get('qi',{}).get('current',0),'stamina_current':r.get('stamina',{}).get('current',0),'resonance_current':r.get('resonance',{}).get('current',0),'controller_mode':'MANUAL','token_asset_id':au['token_asset_id'],'footprint_width':au['footprint']['width'],'footprint_height':au['footprint']['height'],'placement':au['placement']})
 return {'encounter_id':cat['encounters'][0]['stable_id'],'display_name':'C3C P3 Complete Lifecycle','match_seed':seed,'maximum_rounds':max_rounds,'battlefield_id':bf['stable_id'],'initiative_method':'DETERMINISTIC_ACCEPTED','grid_calibration':{'mode':'AUTHORITATIVE_GATE2_GRID','width':bf['width_squares'],'height':bf['height_squares'],'square_size_ft':bf['square_size_ft'],'centered_tokens':True},'participants':parts,'team_names':{'team:1':'Crimson','team:2':'Jade'}}

def intent_payload(row):
 return {k:row.get(k) for k in ('decision_id','state_version','candidate_id','actor_id','target_ids','destination','option_ids')}

def commit_candidate(c,h,mid,payload):
 reactions=[]
 for _ in range(12):
  pr=c.post(f'/api/combat/matches/{mid}/preview',headers=h,json={'intent':payload,'reaction_decisions':reactions}); assert pr.status_code==200,pr.text
  b=pr.json()
  if b['status']=='REACTION_REQUIRED':
   sug=b.get('local_suggestion') or {}; dec=sug.get('decision')
   assert dec, b; reactions.append(dec); continue
  cm=c.post(f'/api/combat/matches/{mid}/intent',headers=h,json={'intent':payload,'reaction_decisions':reactions,'preview_id':b['preview_id']}); assert cm.status_code==200,cm.text
  return cm.json(),reactions
 raise AssertionError('reaction loop')

def manual_step(c,h,mid):
 d=c.get(f'/api/combat/matches/{mid}/decision',headers=h); assert d.status_code==200,d.text
 ctx=d.json()['context']; cand=ctx['legal_candidates'][0]
 p={'decision_id':ctx['decision_id'],'state_version':ctx['state_version'],'candidate_id':cand['candidate_id'],'actor_id':cand['actor_id'],'target_ids':list(cand.get('target_ids') or []),'destination':cand.get('destination'),'option_ids':list(cand.get('default_option_ids') or [])}
 return commit_candidate(c,h,mid,p),cand['actor_id']

def suggested_step(c,h,mid):
 sg=c.post(f'/api/combat/matches/{mid}/suggest',headers=h,json={}); assert sg.status_code==200,sg.text
 return commit_candidate(c,h,mid,intent_payload(sg.json()['intent'])),sg.json()['intent']['actor_id']

with TestClient(create_app(Settings.from_env(ROOT,data))) as c:
 h={'x-foundry-token':c.get('/api/session').json()['token']}; cat=c.get('/api/combat/catalog').json(); by={r['display_name']:r['runtime_entity_id'] for r in cat['projections'] if r.get('primary_combatant')}; an,lee,bai=by['An Eui'],by['Lee Jia'],by['Bai Meizhen']
 p=setup(cat,[an,lee],'C3C-P3-DURATION-1',1); pf=c.post('/api/combat/new-fight/preflight',headers=h,json=p); assert pf.status_code==200 and pf.json()['ready'],pf.text
 cr=c.post('/api/combat/new-fight/create',headers=h,json={**p,'preflight_commitment':pf.json()['preflight_commitment'],'idempotency_key':'c3c-p3-a','owner_confirmed':True}); assert cr.status_code==200,cr.text; mid=cr.json()['match_id']
 # Manual first
 _,manual_actor=manual_step(c,h,mid)
 c.post(f'/api/combat/matches/{mid}/controller-mode',headers=h,json={'actor_id':manual_actor,'controller_mode':'LOCAL_AUTO'}).raise_for_status()
 # ensure another owner-approved Suggested decision
 steps=0; suggested_actor=None; reaction_seen=False
 while not suggested_actor:
  m=c.get(f'/api/combat/matches/{mid}').json(); assert not m['state']['terminal_result']
  active=m['state']['current_actor_id']
  if active!=manual_actor and next(a for a in m['state']['actors'] if a['entity_id']==active)['primary_combatant']:
   c.post(f'/api/combat/matches/{mid}/controller-mode',headers=h,json={'actor_id':active,'controller_mode':'SUGGESTED'}).raise_for_status()
   _,suggested_actor=suggested_step(c,h,mid)
   c.post(f'/api/combat/matches/{mid}/controller-mode',headers=h,json={'actor_id':active,'controller_mode':'LOCAL_AUTO'}).raise_for_status()
   break
  r=c.post(f'/api/combat/matches/{mid}/local-step',headers=h,json={}); assert r.status_code==200,r.text; steps+=1; assert steps<40
 # finish by local auto
 while True:
  m=c.get(f'/api/combat/matches/{mid}').json()
  if m['state']['terminal_result']: break
  active=m['state']['current_actor_id']; actor=next(a for a in m['state']['actors'] if a['entity_id']==active)
  owner=actor.get('owner_id') or active
  if actor['primary_combatant']:
   c.post(f'/api/combat/matches/{mid}/controller-mode',headers=h,json={'actor_id':owner,'controller_mode':'LOCAL_AUTO'}).raise_for_status()
  r=c.post(f'/api/combat/matches/{mid}/local-step',headers=h,json={}); assert r.status_code==200,r.text; steps+=1; assert steps<100
 term=m['state']['terminal_result']; assert term['kind']=='DRAW_DURATION',term
 summary1=c.get(f'/api/combat/matches/{mid}/final-summary'); assert summary1.status_code==200,summary1.text; summary1=summary1.json()
 # negative terminal operations
 assert c.get(f'/api/combat/matches/{mid}/decision').status_code==409
 assert c.post(f'/api/combat/matches/{mid}/local-step',headers=h,json={}).status_code==409
 assert c.post(f'/api/combat/matches/{mid}/resume',headers=h,json={}).status_code==409
 assert c.post(f'/api/combat/matches/{mid}/controller-mode',headers=h,json={'actor_id':an,'controller_mode':'MANUAL'}).status_code==409
 snap=c.post(f'/api/combat/matches/{mid}/snapshot',headers=h,json={}); assert snap.status_code==200
 ver1=c.post(f'/api/combat/matches/{mid}/verify',headers=h,json={}); assert ver1.status_code==200 and ver1.json()['status']=='PASS',ver1.text
 rep1=c.get(f'/api/combat/matches/{mid}/replay'); assert rep1.status_code==200 and rep1.json()['canonical_state_sha256']==summary1['final_state_sha256'],rep1.text
 exp=c.get(f'/api/combat/matches/{mid}/export'); assert exp.status_code==200; ep=base/'final.zip'; ep.write_bytes(exp.content); assert zipfile.ZipFile(ep).testzip() is None; assert 'FinalSummary.json' in zipfile.ZipFile(ep).namelist()
 journal_before=(matchdir(mid)/'Journal.ndjson').read_bytes()
 summary_bytes=(matchdir(mid)/'FinalSummary.json').read_bytes()
# restart/reopen read-only
with TestClient(create_app(Settings.from_env(ROOT,data))) as c:
 h={'x-foundry-token':c.get('/api/session').json()['token']}; reopened=c.get(f'/api/combat/matches/{mid}'); assert reopened.status_code==200 and reopened.json()['state']['terminal_result']; assert reopened.json()['final_summary']==summary1
 assert c.get(f'/api/combat/matches/{mid}/final-summary').json()==summary1
 assert c.post(f'/api/combat/matches/{mid}/verify',headers=h,json={}).json()['status']=='PASS'
 assert c.get(f'/api/combat/matches/{mid}/replay').json()['canonical_state_sha256']==summary1['final_state_sha256']
 assert (matchdir(mid)/'Journal.ndjson').read_bytes()==journal_before
 assert (matchdir(mid)/'FinalSummary.json').read_bytes()==summary_bytes
 # Case B Bai/Cui duration terminal persistence proves companion ownership preserved; focused engine primary semantics below
 cat=c.get('/api/combat/catalog').json(); p2=setup(cat,[bai,an],'C3C-P3-CUI',1); pf2=c.post('/api/combat/new-fight/preflight',headers=h,json=p2); assert pf2.json()['ready']; cb=c.post('/api/combat/new-fight/create',headers=h,json={**p2,'preflight_commitment':pf2.json()['preflight_commitment'],'idempotency_key':'c3c-p3-b','owner_confirmed':True}); assert cb.status_code==200; midb=cb.json()['match_id']
 for aid in [bai,an]: c.post(f'/api/combat/matches/{midb}/controller-mode',headers=h,json={'actor_id':aid,'controller_mode':'LOCAL_AUTO'}).raise_for_status()
 for i in range(100):
  mm=c.get(f'/api/combat/matches/{midb}').json()
  if mm['state']['terminal_result']: break
  rr=c.post(f'/api/combat/matches/{midb}/local-step',headers=h,json={}); assert rr.status_code==200,rr.text
 else: raise AssertionError('case b did not terminate')
 sb=c.get(f'/api/combat/matches/{midb}/final-summary').json(); cui=next(x for x in sb['companion_ownership'] if x['entity_id']=='bai_cui'); assert cui['owner_id']==bai and cui['team_id']==next(x for x in sb['actors'] if x['entity_id']==bai)['team_id']
 assert c.post(f'/api/combat/matches/{midb}/verify',headers=h,json={}).json()['status']=='PASS'
# focused engine companion victory authority
eng=Gate2Engine(ROOT,match_seed='C3C-P3-COMPANION-PRIMARY',maximum_rounds=20)
# Make all primaries on Bai's team inactive while preserving Cui active, then invoke existing terminal authority.
bai_actor=eng.state.actors[bai]; team=bai_actor.team_id
for a in eng.state.actors.values():
 if a.primary_combatant and a.team_id==team: a.active=False; a.current_hp=0
assert eng.state.actors['bai_cui'].active
eng._check_victory(); assert eng.state.terminal_result is not None and eng.state.terminal_result.winning_team_id!=team
report={'schema':'Tianxia.C3CP3Acceptance.v1','status':'PASS','match_id':mid,'terminal_result':term,'manual_actor':manual_actor,'suggested_actor':suggested_actor,'local_auto_steps':steps,'summary_sha256':hashlib.sha256(summary_bytes).hexdigest(),'verification':ver1.json(),'replay_state_sha256':rep1.json()['canonical_state_sha256'],'restart_reopen':'PASS','final_export_sha256':hashlib.sha256(ep.read_bytes()).hexdigest(),'companion_case_match_id':midb,'companion_primary_semantics':'PASS','isolated_userdata':str(data)}
out=Path('CHECKPOINTS/C3C_P3_COMPLETE'); out.mkdir(parents=True,exist_ok=True); (out/'C3C_P3_ACCEPTANCE_REPORT.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n'); print(json.dumps(report,indent=2))
