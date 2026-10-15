"""General native elapsed-scene checks, shared by Beauty and Thread.

GM admission records a real task's skill, ability, subject, purpose and DC with
provenance. It never approves success. The acting controller resolves the check
through a persisted deterministic roll; source consumers supply scoped modes
before the draw and consume only after the actual receipt. Default-inert without
an admitted task. Counters and tasks survive cold load and command replay.
"""
from copy import deepcopy
from . import hook,query,run_strict
from ..journey import require,integer


@hook('compile_bundle')
def bonuses(bundle,info):
    from ..factory_compiler import _skill_bonus
    skills={'Acrobatics':'DEX','Animal Handling':'WIS','Arcana':'INT','Athletics':'STR','Deception':'CHA','History':'INT','Insight':'WIS','Intimidation':'CHA','Investigation':'INT','Medicine':'WIS','Nature':'INT','Perception':'WIS','Performance':'CHA','Persuasion':'CHA','Religion':'INT','Sleight of Hand':'DEX','Stealth':'DEX','Survival':'WIS'}
    return {**bundle,'scene_check_bonuses':{s:{'ability':a,'bonus':_skill_bonus(info['owner_sheet'],s,info['mods'].get(a,0))} for s,a in skills.items()}}


@hook('journey_persistent_fields')
def fields():return ('scene_check_tasks','scene_check_counter')


@hook('journey_admission')
def task(session,aid,kind,payload,reason):
    if kind!='scene_check_task':return None
    require(set(payload)=={'id','skill','ability','subject','purpose','dc'} and type(payload['id']) is str and payload['id'].strip(), 'Record the check task identity, skill, ability, subject, purpose and DC.')
    skill=session.state['actors'][aid]['bundle'].get('scene_check_bonuses',{}).get(payload['skill'])
    require(skill is not None and skill['ability']==payload['ability'] and integer(payload['dc']) and type(payload['purpose']) is str and bool(payload['purpose'].strip()), 'Use a real skill/ability pairing, purpose and whole-number DC.')
    subjects=set(session.state['actors'])|set(session.state.get('runtime_objects',{}))
    require(payload['subject'] in subjects,'Choose a real creature or native object as the subject of this check.')
    tasks=session.state['actors'][aid].setdefault('scene_check_tasks',{})
    require(payload['id'] not in tasks,'That task identity is already recorded.')
    tasks[payload['id']]={**deepcopy(payload),'provenance':reason,'resolved':0}
    session.emit('SCENE_CHECK_TASK_RECORDED',aid,task_id=payload['id'],reason=reason)
    return True


@hook('journey_command')
def resolve(session,aid,kind,payload):
    if kind!='scene_check':return None
    require(set(payload)=={'task'},'Choose one recorded check task.')
    actor=session.state['actors'][aid];task=actor.get('scene_check_tasks',{}).get(payload['task'])
    require(task is not None and not task['resolved'] and not actor['incapacitated'],'Choose your own unresolved task while able to act.')
    modes=set(m for m in query('journey_check_modes',session,aid,task) if m in ('ADVANTAGE','DISADVANTAGE'))
    from .ability_source import combine_modes
    from ..gate2_rolls import DeterministicRollAuthority
    roller=DeterministicRollAuthority(session.state['journey_id']+':scene_check');roller.counter=actor.get('scene_check_counter',0)
    bonus=actor['bundle']['scene_check_bonuses'][task['skill']]['bonus']
    roll=roller.d20(modifier=bonus,actor_id=aid,reason='CHECK:Scene:'+task['id'],mode=combine_modes(modes))
    actor['scene_check_counter']=roller.counter;task['resolved']=1
    session.emit('SCENE_CHECK_ROLLED',aid,task_id=task['id'],skill=task['skill'],ability=task['ability'],
        subject=task['subject'],purpose=task['purpose'],dc=task['dc'],success=int(roll.total>=task['dc']),roll=roll.model_dump(mode='json'))
    run_strict('journey_check_resolved',session,aid,task,roll)
    return True


@hook('journey_options')
def options(session,aid):
    if session.state['phase']!='travel' or session.state['actors'][aid]['incapacitated']:return None
    return [{'id':'check:'+key,'kind':'scene_check','payload':{'task':key},
        'label':f"{task['ability']} ({task['skill']}): {task['purpose']}; check against DC {task['dc']}. No Cultivation Points."}
        for key,task in session.state['actors'][aid].get('scene_check_tasks',{}).items() if not task['resolved']]
