"""Service-level audit: actual Body Heavying and Battlefield Beheading Line.

Synthetic public sheets have extra HP to survive the one tested strike.
No engine mutations, monkeypatching, live data or browsers.
"""
import sys, pathlib, json, zipfile
APP=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from tests.test_auto_lane1 import _sheet
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.factory_compiler import compile_character
from combat.gate2_rolls import DeterministicRollAuthority

ARMOR='TAL_GRAVITY_WEIGHT_SHIFT_BASE'
LINE='tianxia.talent.sabers.battlefield_beheading_line'
PROMPTS=[]

def choose(table,mid,label,target=None,option=None,before_act=None):
    cleanup=before_act() if before_act else None
    s=table.state(mid); m=s['menu']; answers=[]
    if label=='end': cid=m['end_turn']
    else:
        g=next((g for g in m['actions'] if g['label']==label or g.get('display_name')==label),None)
        assert g is not None, (m['actor_id'],[g['label'] for g in m['actions']])
        o=next(o for o in g['options'] if target is None or target in o['target_ids']);cid=o['candidate_id']
    for _ in range(20):
        r=table.act(mid,cid,m['decision_id'],m['state_version'],s['last_sequence'],answers)
        if r['status']!='REACTION_REQUIRED':return r
        p=r['reaction']; PROMPTS.append({'after':s['last_sequence'],**p}); a={**p['context'],'selection':'USE'}
        if cleanup:cleanup();cleanup=None
        if p.get('choice'):
            options=p['choice']['options'];pick=next((o for o in options if option and option in o['id']),options[0])
            ordered=[pick]+[o for o in options if o['id']!=pick['id']]
            a['option_ids']=[o['id'] for o in ordered[:max(1,int(p['choice'].get('minimum',1)))]]
        answers.append(a)
    raise AssertionError('repeated prompts')

def run_posture(tmp_path):
    PROMPTS.clear()
    documents={}
    for pid,ability in [('guard',ARMOR),('saber',LINE),('shover',ARMOR)]:
        d=_sheet(ability,cl=20,dc=60);d['identity']['display_name']=pid.title()
        d['ability_scores_and_statistics']['hit_points']['maximum']=500
        documents[pid]=d
        p=tmp_path/'portable_characters'/pid;p.mkdir(parents=True)
        with zipfile.ZipFile(p/'current.zip','w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(d))
    svc=CombatService(APP,tmp_path);table=TabletopService(svc,tmp_path)
    modes={'actor:factory.'+p:'MANUAL' for p in documents}
    templates=[compile_character(d,actor_id='actor:factory.'+p)['actor_template'] for p,d in documents.items()]
    for n in range(1000):
        seed=f'H39-POSTURE-{n}';roller=DeterministicRollAuthority(seed)
        scores=[(roller.d20(modifier=t['initiative_bonus'],actor_id=t['entity_id'],reason='INITIATIVE').total,
                 t['initiative_bonus'],t['dexterity_score'],t['entity_id']) for t in templates]
        if [r[3] for r in sorted(scores,key=lambda r:(-r[0],-r[1],-r[2],r[3]))]==list(modes):break
    else:raise AssertionError('seed not found')
    arena=svc.tabletop_maps.save({'display_name':'H39 Posture','width_squares':12,'height_squares':10,'walls':[],
        'starts':{'team1':[[3,3]],'team2':[[8,3],[4,3]]}})
    mid=svc.create_factory_match(project_ids=['guard'],opponent_actor_ids=['actor:factory.saber','actor:factory.shover'],control_modes=modes,
        arena_id='battlefield:map.'+arena['map_id'],match_seed=seed)['match_id']
    if table.state(mid)['menu']['actor_id']!='actor:factory.guard':choose(table,mid,'end')
    # Use exact service catalog names without guessing presentation keys.
    s=table.state(mid)
    choose(table,mid,'Weight Shift: Body Heavying')
    choose(table,mid,'end')
    guard=svc._load_session(mid).engine.state.actors['actor:factory.guard']
    held=next(c for c in guard.conditions.values() if (c.data or {}).get('rule',{}).get('save_against'))
    def add_identical_effect():
        original=svc._load_session; seeded=None; duplicate_id=None
        def load(match_id):
            nonlocal seeded,duplicate_id
            if seeded is not None:return seeded
            session=original(match_id)
            actor=session.engine.state.actors['actor:factory.guard']
            duplicate=held.model_copy(deep=True)
            duplicate.instance_id=held.instance_id+':duplicate'
            duplicate_id=duplicate.instance_id
            actor.conditions[duplicate.instance_id]=duplicate
            seeded=session
            return seeded
        svc._load_session=load
        def cleanup():
            seeded.engine.state.actors['actor:factory.guard'].conditions.pop(duplicate_id,None)
        return cleanup
    choose(table,mid,'Battlefield Beheading Line','actor:factory.guard',held.instance_id,before_act=add_identical_effect)
    choose(table,mid,'end')
    choose(table,mid,'Shove: Prone','actor:factory.guard')
    fresh=CombatService(APP,tmp_path)._load_session(mid);guard=fresh.engine.state.actors['actor:factory.guard']
    evidence={'match_id':mid,'seed':seed,
        'events':[e.model_dump(mode='json') for e in fresh.engine.events],'prompts':list(PROMPTS),
        'verify':fresh.verify()['status'],'replay':fresh.mechanical.replay()['status']}

    return evidence

def test_posture_removal_choices_are_distinguishable(tmp_path):
    evidence=run_posture(tmp_path)
    prompts=[p for p in evidence['prompts'] if p.get('reaction')=='Battlefield Beheading Line']
    assert len(prompts)==1
    labels=[o['label'] for o in prompts[0]['choice']['options']]
    assert len(labels)==2, 'The table scenario must contain two eligible effects with identical descriptions'
    assert len(labels)==len(set(labels)), 'Different effect instances need distinct player-facing choice labels'
    assert any('(copy 1 of 2)' in label for label in labels) and any('(copy 2 of 2)' in label for label in labels), labels
    assert all('Advantage on saving throws' in label for label in labels), labels
    assert all("suppressed until the end of Guard's next turn" in label for label in labels), labels
    assert evidence['verify']=='PASS' and evidence['replay']=='PASS'
