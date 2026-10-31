"""Native non-combat checks with typed GM requests and controller-owned spending.

The GM supplies purpose/DC/ability/skill, never dice, success or completion.
Bonuses use journey_check_profile; journey_check_finished consumes source uses.
"""
from copy import deepcopy
from . import hook, query, run_strict
from ..journey import require, integer
from ..fact_consent_admission import read
from ..gate2_rolls import DeterministicRollAuthority
from .journey_rolls import roll
from ..journey_decisions import autonomous

SOURCE = 'journey:noncombat_check'
KEY = 'journey:check'


@hook('compile_bundle')
def seal_tools(bundle, info):
    """Seal native tool training once, independent of any particular sphere."""
    import json
    tools = (info['owner_sheet'].get('ability_scores_and_statistics') or {}).get('tool_proficiencies',[])
    if isinstance(tools,str): tools = json.loads(tools)
    names = sorted({name for name in tools if type(name) is str and name.strip()})
    if not names: return None
    bundle = deepcopy(bundle)
    bundle['journey_tool_proficiencies'] = names
    return bundle


@hook('fact_admission_schema')
def schema(session, source, subject, kind):
    if source == SOURCE and kind == 'request':
        return {'value_type': 'document', 'authority': 'table_owner', 'maximum_seconds': 31536000,
                'description': 'Noncombat check purpose, DC, ability, skill and explicit institutional/recovery context.'}


@hook('journey_command')
def command(session, aid, kind, payload):
    if kind not in ('check_start', 'check_settle'): return None
    actor = session.state['actors'][aid]
    require(not actor['incapacitated'], 'An incapacitated creature cannot attempt this check.')
    states = actor.setdefault('source_states', {})
    if kind == 'check_start':
        require(set(payload) == {'scope', 'merit'} and payload['merit'] in (0, 1)
                and type(payload['merit']) is int and KEY not in states, 'Choose a new requested check and whether to spend Merit before rolling.')
        receipt = read(session, SOURCE, aid, 'request', payload['scope'], aid)
        require(receipt is not None, 'The GM must request this non-combat check.')
        spec = {**receipt['value'], 'check_kind':receipt['value'].get('check_kind','ability'),
                'person':receipt['value'].get('person',''),'problem':receipt['value'].get('problem','')}
        require(set(spec) == {'purpose', 'ability', 'skill', 'dc', 'sect_context', 'role', 'duty', 'institution', 'recovery','check_kind','person','problem'}
                and all(type(spec[k]) is str for k in ('purpose', 'ability', 'skill', 'role', 'duty', 'institution', 'recovery','check_kind','person','problem'))
                and bool(spec['purpose'].strip()) and spec['ability'] in ('STR','DEX','CON','INT','WIS','CHA')
                and spec['check_kind'] in ('ability','sect') and integer(spec['dc']) and type(spec['sect_context']) is int and spec['sect_context'] in (0,1)
                and spec['recovery'] in ('', 'ordinary_exhaustion', 'stress', 'mental_fatigue'), 'Supply a typed check request, with source-qualified context.')
        used = states.setdefault('journey:used_checks', [])
        require(receipt['receipt_id'] not in used, 'This requested check has already been rolled.')
        profiles = [r for r in run_strict('journey_check_profile', session, aid, spec) if r]
        bonus = sum(r.get('bonus', 0) for r in profiles)
        merit = any(r.get('merit') for r in profiles)
        mode = 'ADVANTAGE' if any(r.get('advantage') for r in profiles) else 'NORMAL'
        template = actor['bundle']['actor_template']
        # Compiled ability saves include proficiency; ordinary checks use sealed
        # ability modifiers, carried in the native owned bundle numbers below.
        modifier = actor['check_mods'][spec['ability']]
        skills = actor['bundle'].get('skills', template.get('skills', {}))
        if spec['skill'] in skills:
            modifier = skills[spec['skill']]
        elif spec['skill'] in actor['bundle'].get('journey_tool_proficiencies',()):
            modifier += template['proficiency_bonus']
        if spec['check_kind']=='sect':
            from .sect_stewardship import SECT_KEY
            choice=actor['resources'].get(SECT_KEY,0)
            require(1<=choice<=3 and spec['sect_context']==1 and not spec['skill'], 'A Sect Check needs its acquired key-ability choice and explicit sect purpose.')
            modifier=actor['bundle']['actor_template']['proficiency_bonus']+actor['check_mods'][('INT','WIS','CHA')[choice-1]]
        pending = {'scope': payload['scope'], 'spec': deepcopy(spec), 'merit_allowed': int(merit), 'merit_spent': 0,
                   'merit_roll': 0, 'mode': mode, 'receipt': receipt['receipt_id']}
        if payload['merit']:
            spend(session, aid, pending)
        roller = DeterministicRollAuthority(session.state['journey_id'], session.state.get('roll_counter', 0))
        result = roller.d20(modifier=modifier + bonus - 2*actor['exhaustion'], actor_id=aid, reason=SOURCE + ':' + payload['scope'], mode=mode)
        session.state['roll_counter'] = roller.counter
        pending['total'] = result.total
        pending['natural'] = result.natural_result
        used.append(receipt['receipt_id'])
        states[KEY] = pending
        session.emit('JOURNEY_CHECK_ROLLED', aid, scope=payload['scope'], roll=result.model_dump(mode='json'))
        run_strict('journey_check_rolled', session, aid, spec)
    else:
        require(set(payload) == {'merit'} and type(payload['merit']) is int and payload['merit'] in (0,1) and KEY in states,
                'Settle the pending check before its result is declared.')
        pending = states[KEY]
        if payload['merit']: spend(session, aid, pending)
        total = pending['total'] + pending['merit_roll']
        session.emit('JOURNEY_CHECK_RESOLVED', aid, scope=pending['scope'], total=total,
                     success=int(total >= pending['spec']['dc']), merit=pending['merit_roll'])
        run_strict('journey_check_finished', session, aid, pending['spec'])
        del states[KEY]
    return True


def spend(session, aid, pending):
    from .sect_stewardship import MERIT, MERIT_SIZE
    actor = session.state['actors'][aid]
    require(pending['merit_allowed'] and not pending['merit_spent'] and actor['resources'].get(MERIT,0) > 0,
            'Only one available Merit Die may advance the current role or Duty check.')
    session.spend_resource(aid,MERIT,1,SOURCE)
    pending['merit_roll'] = roll(session, aid, actor['resources'].get(MERIT_SIZE,4), SOURCE)
    pending['merit_spent'] = 1


@hook('journey_options')
def choices(session, aid):
    pending = session.state['actors'][aid].get('source_states', {}).get(KEY)
    if not pending or session.state['phase'] != 'travel': return None
    rows = [{'id':'check:finish', 'kind':'check_settle','auto_select':0,'payload':{'merit':0},
             'label':'Declare the check result without spending a Merit Die'}]
    from .sect_stewardship import MERIT
    if pending['merit_allowed'] and not pending['merit_spent'] and session.state['actors'][aid]['resources'].get(MERIT,0):
        rows.append({'id':'check:merit','kind':'check_settle','auto_select':0,'payload':{'merit':1},
                     'label':'Spend one Merit Die after seeing the d20, before the result'})
    for row in rows: row['auto_select'] = int(autonomous(session,aid))
    return rows


@hook('journey_auto_blocked')
def block_auto(session, aid):
    if not autonomous(session,aid) and session.state['actors'][aid].get('source_states',{}).get(KEY): return True


@hook('journey_before_command')
def pending_decision(session, aid, kind, payload):
    ids = session.state['actors'] if kind in ('enter_combat','finish') else (aid,)
    for target in ids:
        if session.state['actors'][target].get('source_states', {}).get(KEY):
            require(target == aid and kind == 'check_settle', 'Resolve this pending check before beginning another activity.')


@hook('journey_auto_priority')
def auto_priority(session,aid,option):
    if option['kind'] == 'check_settle':
        pending = session.state['actors'][aid]['source_states'][KEY]
        # The requester and the rolled result are this actor's own information.
        needs_merit = pending['total'] < pending['spec']['dc']
        return -100 if bool(option['payload']['merit']) == needs_merit else -99
    if option['kind'] == 'check_start': return -30


@hook('journey_properties')
def pending_display(session,aid):
    pending=session.state['actors'][aid].get('source_states',{}).get(KEY)
    if pending is None:return None
    return {'pending_check':{'purpose':pending['spec']['purpose'],'natural':pending['natural'],
        'total':pending['total']+pending['merit_roll'],'merit_already_spent':pending['merit_spent']}}


@hook('journey_options')
def requested_checks(session,aid):
    actor=session.state['actors'][aid]
    if session.state['phase']!='travel' or actor['incapacitated'] or actor.get('source_states',{}).get(KEY):return None
    from ..fact_consent_admission import visible_records
    used=actor.get('source_states',{}).get('journey:used_checks',())
    return [{'id':'check:start:'+r['receipt_id'],'kind':'check_start','auto_select':int(autonomous(session,aid)),
        'payload':{'scope':r['scope'],'merit':0},
        'label':'Attempt '+r['value'].get('purpose','the requested non-combat check')+'; roll the d20, then choose whether to spend an eligible Merit Die before declaring the result'}
        for r in visible_records(session,SOURCE,aid,'request',aid) if r['receipt_id'] not in used]
