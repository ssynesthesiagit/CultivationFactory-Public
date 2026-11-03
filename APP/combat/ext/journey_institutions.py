"""Source consumers for Sect Stewardship's learning, place, petition and duty.

World declarations describe institutional judgments; activities and check dice
come from committed clocks and deterministic rolls, never a completion flag.
"""
from copy import deepcopy
from . import hook
from ..journey import require, integer
from ..fact_consent_admission import read
from ..journey_decisions import autonomous
from .journey_rolls import roll
from .sect_stewardship import MERIT, MERIT_SIZE, SECT_KEY, SECT_ABILITIES, BASE_REQUESTS, petition_band, petition_groups, merit_result

BASE = 'SECT_STEWARDSHIP_BASE_'
LEARN = BASE + 'LEARNING_SECT_STEWARDSHIP'
PLACE = BASE + 'TAKING_A_PLACE'
PETITION = BASE + 'PETITIONING_THE_HALL'
DUTY = BASE + 'ACCEPTING_A_DUTY'
RECOVER = BASE + 'MERIT_DICE'
KEY = 'sect_stewardship:journey'
SKILLS = ('History', 'Insight', 'Investigation', 'Persuasion', 'Religion')
TOOLS = ("Calligrapher’s Supplies", "Cook’s Utensils", 'Herbalism Kit')
ROLES = ('Field Hand', 'Kitchen Worker', 'Messenger', 'Dormitory Senior', 'Archive Runner',
         'Medicine Hall Assistant', 'Mission Board Reader', 'Patrol Clerk', 'Guest Attendant',
         'Stable Hand', 'Furnace Cleaner', 'Spirit Field Steward', 'Lecture Scribe',
         'Dispute Witness', 'Storehouse Aide', 'Outer Gate Watcher', 'Junior Instructor')
REWARDS = ('merit', 'standing', 'favor', 'rumor', 'supplies', 'sect_check')


@hook('compile_passives')
def seal(rows, info):
    ids = set(info['owned_ids'])
    own = sorted(ids.intersection((LEARN, PLACE, PETITION, DUTY, RECOVER)))
    if not own:
        return None
    return [*rows, {'block': 'institution_journey', 'feature_id': LEARN,
                    'owned': own, 'numbers': deepcopy(info['numbers']),
                    'petition_groups':[{'requests':[{'text':r.text,'kinds':list(r.kinds)} for r in group.requests],
                         'one_becomes':int(group.one_becomes or 0),'twice':int(group.twice)} for group in petition_groups(frozenset(ids))]}]


def contract(session, aid):
    return next((r for r in session.state['actors'][aid]['bundle'].get('typed_passives', ())
                 if r.get('block') == 'institution_journey'), None)


def owns(session, aid, source):
    return source in (contract(session, aid) or {}).get('owned', ())


def ledger(session, aid):
    return session.state['actors'][aid].setdefault('source_states', {}).setdefault(KEY, {})


def fact(session, aid, kind, scope):
    r = read(session, LEARN, aid, kind, scope, aid)
    require(r is not None, 'This institutional fact needs a current table-owner declaration.')
    return r['value']


@hook('fact_admission_schema')
def schema(session, source, subject, kind):
    if source != LEARN or not contract(session, subject):
        return None
    if kind in ('institution', 'duty_plan', 'duty_verification', 'check', 'tool_approval', 'support_terms', 'recovery_context'):
        return {'value_type': 'document', 'maximum_seconds': 31536000,
                'authority': 'table_owner', 'description': 'Source-qualified institutional judgment; never a mechanical completion receipt.'}


def text(value, label):
    require(type(value) is str and 0 < len(value.strip()) <= 1000, 'Supply ' + label + '.')
    return value.strip()


def institution(session, aid, scope):
    row = fact(session, aid, 'institution', scope)
    require(set(row) == {'name', 'authority', 'standing', 'good_standing', 'present', 'ordinary_support'}
            and integer(row['standing']) and row['standing'] <= 4
            and all(type(row[k]) is int and row[k] in (0, 1) for k in ('good_standing', 'present'))
            and isinstance(row['ordinary_support'], list)
            and all(type(s) is str and s.strip() and len(s)<=180 for s in row['ordinary_support']),
            'Declare the named institution, appropriate authority, Standing 0–4, good-standing/presence facts and plausible ordinary requests.')
    text(row['name'], 'institution name'); text(row['authority'], 'appropriate authority')
    result=deepcopy(row)
    reward=ledger_view(session,aid).get('standing_reward')
    if reward and reward['institution']==scope and reward['scene']==session.state.get('scene_id',session.state['journey_id']):
        result['standing']=reward['standing_grade']
    return result


@hook('journey_command')
def command(session, aid, kind, payload):
    if kind not in ('sect_learn', 'sect_role', 'sect_duty', 'sect_reward', 'sect_petition'):
        return None
    source = {'sect_learn': LEARN, 'sect_role': PLACE, 'sect_duty': DUTY, 'sect_reward': DUTY, 'sect_petition': PETITION}[kind]
    require(owns(session, aid, source), 'This creature has not learned this Sect Stewardship ability.')
    actor, data = session.state['actors'][aid], ledger(session, aid)
    require(not actor['incapacitated'], 'This creature cannot perform institutional activities while incapacitated.')
    if kind == 'sect_learn':
        require(set(payload) == {'ability', 'proficiency', 'approval'} and 'training' not in data,
                'Record the learning choice once: key ability, proficiency and optional custom-tool approval scope.')
        ability, skill = payload['ability'], text(payload['proficiency'], 'skill or tool')
        require(ability in ('INT', 'WIS', 'CHA'), 'Choose Intelligence, Wisdom or Charisma.')
        if skill not in (*SKILLS, *TOOLS):
            approved = fact(session, aid, 'tool_approval', payload['approval'])
            require(approved == {'tool': skill, 'duty': text(approved.get('duty'), 'appropriate sect duty')}, 'This tool needs GM approval for the sect duty.')
        # The compiled native template supplies actual previous proficiency.
        # skill proficiency ranks are sealed separately below at compile_bundle.
        duplicate = skill in actor['bundle'].get('institution_proficiencies', [])
        data['training'] = {'ability': ability, 'proficiency': skill, 'duplicate': int(duplicate)}
        actor['resources'][SECT_KEY] = ('INT', 'WIS', 'CHA').index(ability) + 1
        session.emit('SECT_LEARNED', aid, source=source, training=deepcopy(data['training']))
    elif kind == 'sect_role':
        require(set(payload) == {'role', 'duty'} and actor['long_rests'] > 0
                and data.get('role_rest', -1) != actor['long_rests'], 'Choose one current Sect Role after a completed Long Rest.')
        data['role'] = text(payload['role'], 'current role')
        data['role_duty'] = text(payload['duty'], 'current duty reflected by this role')
        data['role_rest'] = actor['long_rests']
        session.emit('SECT_ROLE_CHOSEN', aid, source=source, role=data['role'], duty=data['role_duty'])
    elif kind == 'sect_duty':
        require(set(payload) == {'scope'} and data.get('declared_rest', -1) != actor['long_rests'], 'Declare a Duty only once per Long Rest.')
        plan = fact(session, aid, 'duty_plan', payload['scope'])
        require({'obligation','institution','steps'} <= set(plan) <= {'obligation','institution','steps','person','problem'} and isinstance(plan['steps'], list) and plan['steps'], 'A Duty needs a clear non-combat obligation and work steps.')
        text(plan['obligation'], 'non-combat obligation'); institution(session, aid, plan['institution'])
        for step in plan['steps']:
            require(isinstance(step, dict) and set(step) == {'task', 'seconds'} and integer(step['seconds'], 1), 'Each work step needs a task and a sourced positive duration.')
            text(step['task'], 'work task')
        instance=session.state['journey_id']+':duty:'+aid+':'+str(actor['long_rests'])+':'+str(len(session.state['events'])+1)
        data['duty'] = {'scope': payload['scope'], 'instance_id':instance, 'plan': deepcopy(plan), 'completed': [], 'rewarded': 0}
        data['declared_rest'] = actor['long_rests']
        session.emit('DUTY_DECLARED', aid, source=source, scope=payload['scope'], instance_id=instance, obligation=plan['obligation'])
    elif kind == 'sect_reward':
        require(set(payload) == {'reward', 'companions'} and payload['reward'] in REWARDS, 'Choose one printed Duty reward.')
        duty = data.get('duty', {})
        require(duty and not duty['rewarded'] and len(duty['completed']) == len(duty['plan']['steps']), 'Finish the actual Duty work before choosing its one reward.')
        verification_receipt=read(session,LEARN,aid,'duty_verification',duty['instance_id'],aid)
        require(verification_receipt is not None and verification_receipt['created_at']>=duty['completed'][-1]['finished_at'],
                'This exact completed Duty needs a current witness/record and reward approval after its actual work.')
        verification=verification_receipt['value']
        require({'witness', 'record', 'approved_rewards', 'detail'} <= set(verification) <= {'witness','record','approved_rewards','detail','standing_grade','supplies'}
                and isinstance(verification['approved_rewards'], list)
                and payload['reward'] in verification['approved_rewards'], 'GM verification and approval of this particular reward are required.')
        for field in ('witness', 'record', 'detail'): text(verification[field], field)
        companions = payload['companions']
        require(isinstance(companions, list) and len(companions) <= 5 and len(set(companions)) == len(companions)
                and set(companions) <= set(session.state['actors']) - {aid}, 'Choose up to five distinct companions.')
        require(payload['reward'] == 'supplies' or not companions, 'Only the supplies reward has companion recipients.')
        reward = payload['reward']; duty['rewarded'] = 1
        receipt = {'reward': reward, 'scope': duty['scope'], 'instance_id':duty['instance_id'], 'institution': duty['plan']['institution'],
                   'witness': verification['witness'], 'record': verification['record'], 'detail': verification['detail'],
                   'scene': session.state.get('scene_id', session.state['journey_id']), 'companions': companions,
                   'person':duty['plan'].get('person',''),'problem':duty['plan'].get('problem','')}
        if reward == 'merit':
            actor['resources'][MERIT] = min(maximum(session, aid), actor['resources'][MERIT] + 1)
        elif reward == 'sect_check':
            data.setdefault('check_rewards', []).append(receipt)
        elif reward == 'standing':
            current=institution(session,aid,duty['plan']['institution'])['standing']
            grade=verification.get('standing_grade')
            require(integer(grade, current+1) and grade<=4, 'The GM must state the actual improved ordinary Standing grade for this scene.')
            receipt['standing_grade']=grade
            data['standing_reward'] = receipt
        else:
            receipt['source_actor']=aid
            data.setdefault('support', []).append(deepcopy(receipt))
            if reward=='supplies':
                package=verification.get('supplies')
                validate_package(package)
                receipt_id=duty['instance_id']
                data['support'][-1]['fulfillment']=deepcopy(package)
                grant_goods(session,aid,package['items'],receipt_id)
                for companion in companions:
                    ledger(session,companion).setdefault('support',[]).append({**deepcopy(receipt),'fulfillment':deepcopy(package)})
                    grant_goods(session,companion,package['items'],receipt_id,producer=aid)
        session.emit('DUTY_REWARDED', aid, source=source, receipt=deepcopy(receipt))
    else:
        require(set(payload) == {'institution', 'request'}, 'Name the appropriate institution and one ordinary petition.')
        inst = institution(session, aid, payload['institution'])
        require(inst['present'] and payload['request'] in inst['ordinary_support'], 'The appropriate institution must plausibly grant this ordinary request; forbidden or exceptional petitions are unavailable.')
        terms=support_terms(session,aid,payload['institution'],payload['request'],inst['standing'])
        require(actor['resources'].get(MERIT, 0) >= 1, 'Petitioning costs one Merit Die.')
        session.spend_resource(aid,MERIT,1,PETITION)
        kinds=next((set(r.kinds) for r in BASE_REQUESTS if r.text==payload['request']),set())
        groups=contract(session,aid).get('petition_groups',[])
        for group in groups:
            for request in group['requests']:
                if request['text']==payload['request']:kinds.update(request['kinds'])
        relevant=[g for g in groups if any(kinds.intersection(r['kinds']) for r in g['requests'])]
        replacement=next((g['one_becomes'] for g in relevant if g['one_becomes']),None)
        sides=max(4,min(10,actor['resources'].get(MERIT_SIZE,4)))
        dice=[roll(session,aid,sides,PETITION) for _ in range(2 if any(g['twice'] for g in relevant) else 1)]
        number=merit_result(dice,one_becomes=replacement)
        receipt = {'institution': payload['institution'], 'authority': inst['authority'], 'request': payload['request'],
                   'standing': inst['standing'], 'die': number, 'band': petition_band(number), 'scene': session.state.get('scene_id', session.state['journey_id'])}
        package=terms['minimum' if number<=2 else 'useful' if number<=4 else 'exceptional']
        receipt['fulfillment']=deepcopy(package)
        receipt['receipt_id']=session.state['journey_id']+':petition:'+str(len(session.state['events']))
        grant_goods(session,aid,package['items'],receipt['receipt_id'])
        data.setdefault('support', []).append(receipt)
        session.emit('PETITION_GRANTED', aid, source=source, economy='NONCOMBAT_ACTION', receipt=deepcopy(receipt))
    return True


def maximum(session, aid):
    return max(1, int(contract(session, aid)['numbers']['pb']))



@hook('activity_spec')
def activity(session, aid, source, parameters):
    if source not in (DUTY, RECOVER): return None
    require(owns(session, aid, source), 'Learn this ability before performing its activity.')
    if source == DUTY:
        duty = ledger(session, aid).get('duty', {})
        require(set(parameters) == {'step'} and duty and not duty['rewarded'], 'Choose a declared Duty step.')
        step = parameters['step']
        require(integer(step) and step == len(duty['completed']) and step < len(duty['plan']['steps']), 'Work the next unfinished Duty step.')
        task = duty['plan']['steps'][step]
        return {'seconds': task['seconds'], 'label': task['task']}
    require({'institution','activity'} <= set(parameters) <= {'institution','activity','seconds','context'}, 'Name the institution (or away scope) and role-honoring work.')
    text(parameters['activity'], 'role-honoring activity')
    inst = institution(session, aid, parameters['institution'])
    context=fact(session,aid,'recovery_context',parameters.get('context','travel'))
    require(set(context)=={'away_from_all_institutions','evidence'} and type(context['away_from_all_institutions']) is int
            and context['away_from_all_institutions'] in (0,1), 'Recovery needs actual global institutional presence or travel facts.')
    text(context['evidence'],'the source of the current institutional/travel context')
    require((context['away_from_all_institutions']==1 and inst['present']==0) or
            (context['away_from_all_institutions']==0 and inst['good_standing']==1),
            'Recovery requires actual good standing with an institution, or consistent actual absence from all institutions.')
    seconds=parameters.get('seconds',600)
    require(integer(seconds,1 if context['away_from_all_institutions'] else 600), 'Role work at an institution requires at least ten minutes; away work must have a real positive elapsed duration.')
    return {'seconds': seconds, 'label': parameters['activity']}


@hook('activity_interrupted')
def interrupted(session, aid, row):
    # Interrupted Duty steps are not completed or rewarded, but their real
    # elapsed work still counts toward the separate Merit recovery rule.
    if row['source'] == DUTY and row.get('worked_seconds', 0) > 0:
        ledger(session, aid).setdefault('duty_work', []).append({
            'rest': session.state['actors'][aid]['long_rests'],
            'worked_seconds': row['worked_seconds'],
        })


@hook('activity_finished')
def completed(session, aid, row):
    if row['source'] == DUTY:
        ledger(session, aid)['duty']['completed'].append({'step': row['parameters']['step'], 'worked_seconds': row['worked_seconds'],
            'finished_at': int(session.clock()), 'rest': session.state['actors'][aid]['long_rests']})
    elif row['source'] == RECOVER:
        context=fact(session,aid,'recovery_context',row['parameters'].get('context','travel'))
        ledger(session, aid)['recovery_work'] = {'institution': row['parameters']['institution'], 'rest': session.state['actors'][aid]['long_rests'],
            'context':row['parameters'].get('context','travel'),
            'worked_seconds':row['worked_seconds'],
            'recovery_mode':'away' if context['away_from_all_institutions'] else 'institution'}


@hook('journey_rest')
def recovery(session, aid):
    if not owns(session, aid, RECOVER): return
    actor, data = session.state['actors'][aid], ledger(session, aid)
    work = data.pop('recovery_work', None)
    candidates = [work] if work else []
    duty = data.get('duty')
    if duty:
        # Actual Duty work also honors the role. Count only completed work in
        # this rest generation, independently of the optional Duty reward.
        seconds = sum(step['worked_seconds'] for step in duty['completed']
                      if step.get('rest') == actor['long_rests'] - 1)
        seconds += sum(step['worked_seconds'] for step in data.get('duty_work', ())
                       if step.get('rest') == actor['long_rests'] - 1)
        if seconds >= 1:
            candidates.append({'institution': duty['plan']['institution'], 'context': 'travel',
                'rest': actor['long_rests'] - 1, 'worked_seconds': seconds, 'recovery_mode': 'institution'})
    before=actor['resources'].get(MERIT,0)
    balances = []
    for work in candidates:
        if work['rest'] != actor['long_rests'] - 1: continue
        if work.get('recovery_mode') not in ('away','institution') or work.get('worked_seconds',0)<1:continue
        context=read(session,LEARN,aid,'recovery_context',work['context'],aid)
        inst_record=read(session,LEARN,aid,'institution',work['institution'],aid)
        if context is None or inst_record is None:continue
        context=context['value'];inst=inst_record['value']
        if context.get('away_from_all_institutions')==1 and inst.get('present')==0:
            balances.append(min(maximum(session,aid),before+1))
        elif (context.get('away_from_all_institutions')==0 and inst.get('good_standing')==1
              and work['worked_seconds']>=600):
            balances.append(maximum(session,aid))
    if not balances:return
    # Multiple qualifying receipts grant the same rest benefit once.
    actor['resources'][MERIT]=max(balances)
    data['duty_work'] = [step for step in data.get('duty_work', ())
                         if step.get('rest') != actor['long_rests'] - 1]
    session.emit('MERIT_RECOVERED',aid,source=RECOVER,balance=actor['resources'][MERIT],gained=actor['resources'][MERIT]-before)



@hook('journey_scene_end')
def scene_end(session, old, new):
    for aid, actor in session.state['actors'].items():
        data = actor.get('source_states', {}).get(KEY)
        if data:
            data.pop('standing_reward', None)


@hook('compile_bundle')
def compile_proficiencies(bundle, info):
    if not any(r.get('block') == 'institution_journey' for r in bundle.get('typed_passives', ())): return None
    rows = (info['owner_sheet'].get('ability_scores_and_statistics') or {}).get('skills', [])
    if isinstance(rows, str):
        import json
        rows = json.loads(rows)
    bundle = deepcopy(bundle)
    from ..ability_checks import skill_proficiency_ranks
    bundle['institution_gear_profile'] = {'identity':deepcopy(info['owner_sheet'].get('identity',{})),
        'ability_scores_and_statistics':{'abilities':deepcopy((info['owner_sheet'].get('ability_scores_and_statistics') or {}).get('abilities',[]))}}
    bundle['institution_training_applied'] = int(bool(info['owner_sheet'].get('sect_stewardship_training')))
    removed={a['source_definition_id'] for a in bundle['action_catalog'] if a.get('parameters',{}).get('sect_key_choice') or a.get('parameters',{}).get('typed',{}).get('source')==PETITION}
    bundle['action_catalog']=[a for a in bundle['action_catalog'] if a['source_definition_id'] not in removed]
    bundle['actor_template']['action_ids']=[key for key in bundle['actor_template']['action_ids'] if key not in removed]
    tools=(info['owner_sheet'].get('ability_scores_and_statistics') or {}).get('tool_proficiencies',[])
    if isinstance(tools,str):
        import json
        tools=json.loads(tools)
    bundle['institution_proficiencies'] = [name for name, rank in skill_proficiency_ranks(rows).items() if rank > 0]+[name for name in tools if type(name) is str]
    return bundle


@hook('journey_options')
def options(session, aid):
    if not contract(session, aid) or session.state['phase'] != 'travel' or session.state['actors'][aid]['incapacitated']: return None
    data = ledger_view(session, aid)
    rows = []
    if 'training' not in data and owns(session,aid,LEARN):
        for ability, label in SECT_ABILITIES:
            for skill in (*SKILLS, *TOOLS):
                rows.append({'id': 'sect:learn:' + ability + ':' + skill, 'kind': 'sect_learn', 'auto_select': 0,
                             'payload': {'ability': ability, 'proficiency': skill, 'approval': ''},
                             'label': 'Learning Sect Stewardship: record '+label+' as your fixed key ability and gain proficiency in '+skill+'; if already proficient, gain +2 on directly sect-related checks. No action or Merit Die cost.'})
    actor = session.state['actors'][aid]
    if owns(session,aid,PLACE) and actor['long_rests'] > 0 and data.get('role_rest', -1) != actor['long_rests']:
        for role in ROLES:
            rows.append({'id': 'sect:role:' + role, 'kind': 'sect_role', 'auto_select': 0,
                         'payload': {'role': role, 'duty': role}, 'label': 'Taking a Place: choose '+role+' as your current duty after this Long Rest; related non-combat checks may add one spent Merit Die. Choosing costs no action or resource.'})
    for row in rows: row['auto_select'] = int(autonomous(session,aid))
    return rows


def ledger_view(session, aid):
    return session.state['actors'][aid].get('source_states', {}).get(KEY, {})


@hook('journey_auto_priority')
def auto_priority(session,aid,option):
    if not contract(session,aid): return None
    kind = option['kind']
    if kind == 'sect_learn':
        return -60 - session.state['actors'][aid]['check_mods'][option['payload']['ability']]
    if kind == 'sect_role': return -50
    if kind == 'sect_reward': return -40
    if kind == 'sect_duty': return -20
    if kind == 'activity_start' and option['payload']['source']==DUTY: return -15
    if kind == 'sect_petition': return -5


@hook('journey_check_profile')
def check_profile(session, aid, spec):
    if not contract(session, aid): return None
    data = ledger_view(session, aid)
    training = data.get('training', {})
    bonus = 0
    if spec['skill'] == training.get('proficiency'):
        if training['duplicate']:
            bonus = 2 if spec['sect_context'] else 0
        else:
            bonus = 0 if session.state['actors'][aid]['bundle'].get('institution_training_applied') else maximum(session, aid)
    duty = data.get('duty', {})
    related_duty = bool(duty and spec['duty'] == duty.get('instance_id') and not duty['rewarded']
                        and len(duty['completed'])<len(duty['plan']['steps']))
    related_role = bool(data.get('role') and spec['role'] == data['role'] and data.get('role_rest')==session.state['actors'][aid]['long_rests'])
    rewards = data.get('check_rewards', [])
    advantage = any(spec.get('check_kind')=='sect' and related_reward(r,spec) for r in rewards)
    return {'bonus': bonus, 'merit': int(related_duty or related_role or spec.get('check_kind')=='sect'), 'advantage': int(advantage)}


@hook('journey_check_rolled')
def consume_check_reward(session, aid, spec):
    if not contract(session, aid): return
    data = ledger_view(session, aid)
    for r in list(data.get('check_rewards', [])):
        if spec.get('check_kind')=='sect' and related_reward(r,spec):
            data['check_rewards'].remove(r)
            break


@hook('journey_properties')
def properties(session,aid):
    data=ledger_view(session,aid)
    if not data:return None
    result={}
    if data.get('training'):result['sect_training']=deepcopy(data['training'])
    if data.get('role') and data.get('role_rest')==session.state['actors'][aid]['long_rests']:
        result['sect_role']={'role':data['role'],'duty':data['role_duty']}
    elif session.state['actors'][aid]['long_rests']>0:result['sect_role_choice_pending']=1
    if data.get('support'):result['institutional_support']=deepcopy(data['support'])
    if data.get('standing_reward',{}).get('scene')==session.state.get('scene_id',session.state['journey_id']):
        result['scene_standing']=deepcopy(data['standing_reward'])
    return result or None


@hook('journey_combat_bundle')
def export_institution(bundle,session,aid):
    data=ledger_view(session,aid)
    if not data:return None
    bundle=deepcopy(bundle)
    bundle['institution_journey_setup']=deepcopy(data)
    install_goods(bundle,data.get('granted_items',[]))
    return bundle


@hook('d20_bonus')
def native_training(engine,roll,intent):
    context=engine.d20_context(roll) or {}
    if context.get('kind')!='check':return None
    bundle=next((b for b in engine.typed_bundle_documents if b['actor_id']==roll.actor_id),{})
    data=bundle.get('institution_journey_setup',{})
    training=data.get('training',{})
    if not training or context.get('skill')!=training['proficiency']:return None
    if training['duplicate']:
        # Native request producers must explicitly describe their sect context;
        # a combat check, role label or damage name alone supplies no such fact.
        if context.get('sect_context')!=1:return None
        return {'bonus':2,'source_id':LEARN}
    if bundle.get('institution_training_applied'):return None
    actor=engine.state.actors[roll.actor_id]
    return {'bonus':actor.proficiency_bonus,'source_id':LEARN}



def support_terms(session,aid,scope,request,standing):
    terms=fact(session,aid,'support_terms',scope+':'+request)
    require(set(terms)=={'request','standing','ordinary','minimum','useful','exceptional'} and type(terms['ordinary']) is int and terms['ordinary']==1 and terms['request']==request
            and terms['standing']==standing, 'The GM must specify actual support at each die band for this Standing and request.')
    for key in ('minimum','useful','exceptional'):
        package=terms[key]
        validate_package(package)
    return terms


def validate_package(package):
    require(isinstance(package,dict) and set(package)=={'description','items','entitlements'}
            and isinstance(package['items'],list) and isinstance(package['entitlements'],list)
            and all(type(v) is str and v.strip() for v in package['entitlements']),
            'Describe the actual ordinary goods and institutional entitlements supplied.')
    text(package['description'],'actual support delivered')
    for item in package['items']:
        require(isinstance(item,dict) and set(item)=={'item_id','quantity'} and integer(item['quantity'],1),
                'Ordinary goods require native catalogue identity and positive quantity.')
        catalogue=mundane_catalogue()
        require(item['item_id'] in catalogue and catalogue[item['item_id']]['category'] in ('gear','tool'),
                'Only ordinary native mundane gear or tools can be supplied by this petition.')


def mundane_catalogue():
    import json
    from pathlib import Path
    return {r['item_id']:r for r in json.loads((Path(__file__).resolve().parents[2]/'authority/Tianxia_Mundane_Equipment_Catalog_R1.json').read_text())['items']}


def grant_goods(session,aid,items,receipt_id,producer=None):
    if not items:return
    from ..factory_compiler import equipment_list
    producer=producer or aid
    profile=deepcopy(session.state['actors'][producer]['bundle']['institution_gear_profile'])
    catalogue=mundane_catalogue()
    profile['equipment']=[{'starting_kit':{'items':[{**item,'name':catalogue[item['item_id']]['name']} for item in items]}}]
    generated=equipment_list(profile)['items']
    def plain(value):
        if type(value) is bool:return int(value)
        if type(value) is float:return int(value) if value.is_integer() else str(value)
        if isinstance(value,dict):return {k:plain(v) for k,v in value.items()}
        if isinstance(value,list):return [plain(v) for v in value]
        return value
    for index,row in enumerate(generated):
        row=plain(row)
        # One reward receipt can supply six creatures. Each receives a distinct
        # physical item whose identity stays unchanged if it later changes hands.
        row['key']='institution:'+receipt_id+':'+aid+':'+str(index)
        row['grant_receipt']=receipt_id
        ledger(session,aid).setdefault('granted_items',[]).append(row)
    session.emit('INSTITUTIONAL_GOODS_DELIVERED',aid,receipt_id=receipt_id,items=deepcopy(items))


def install_goods(bundle,items):
    if not items:return
    from decimal import Decimal
    from ..gate2_runtime_models import ActionDefinition,EconomyKind
    carrying=bundle.get('carrying')
    if carrying is None:return
    existing={r['key'] for r in carrying.get('items',[])}
    total=Decimal(str(carrying.get('weight_lb',0)))
    for row in items:
        if row['key'] in existing:continue
        carrying.setdefault('items',[]).append(deepcopy(row))
        total+=Decimal(str(row.get('weight_lb',0)))
        for verb,economy in (('drop',EconomyKind.NONE),('pickup',EconomyKind.NONE)):
            action=ActionDefinition(source_definition_id='action:'+verb+':'+row['key'],display_name=('Drop ' if verb=='drop' else 'Pick up ')+row['name'],
                owner_id=bundle['actor_id'],economy=economy,resolution_kind='TYPED',target_kind='SELF',parameters={
                    'typed':{'effects':[{'type':'drop_item' if verb=='drop' else 'pickup_item','item':row['key']}],
                             'numbers':{},'duration':{'kind':'instant'},'riders':[]},
                    'item_action':'drop' if verb=='drop' else 'pickup','item_key':row['key'],'free_primary':True})
            bundle['action_catalog'].append(action.model_dump(mode='json'))
            bundle['actor_template']['action_ids'].append(action.source_definition_id)
    carrying['weight_lb']=str(total)


@hook('journey_encounter_settled')
def settled_goods(session,aid,engine,creature):
    # Reconcile only this producer's actual builder-generated goods. Native
    # carrying records retain the original owner and explicit current holder;
    # a delivered receipt never fabricates possession after Drop or transfer.
    from ..carry import owned_item_location,remaining_quantity
    kept={}
    for bundle in engine.typed_bundle_documents:
        owner=engine.state.actors.get(bundle['actor_id'])
        if owner is None:continue
        for row in bundle.get('institution_journey_setup',{}).get('granted_items',()):
            holder=owner.entity_id
            if owned_item_location(owner,row['key']) is None:
                for condition in owner.conditions.values():
                    location=condition.data or {}
                    if location.get('item_key')!=row['key']:continue
                    if location.get('held_by'):holder=location['held_by']
                    elif location.get('dropped_at'):holder=None
            if holder!=aid:continue
            count=remaining_quantity(engine,creature,row)
            if count>0:kept[row['key']]={**deepcopy(row),'quantity':count}
    prior=ledger_view(session,aid)
    if kept or prior.get('granted_items'):
        ledger(session,aid)['granted_items']=list(kept.values())


@hook('match_initialize')
def initialize_goods(engine):
    from ..carry import refresh
    for bundle in engine.typed_bundle_documents:
        actor=engine.state.actors.get(bundle['actor_id'])
        if actor is not None and bundle.get('institution_journey_setup',{}).get('granted_items'):
            refresh(engine,actor,PETITION)



def related_reward(reward,spec):
    return (bool(spec['institution']) and reward['institution']==spec['institution']
            or bool(spec.get('person')) and reward.get('person')==spec['person']
            or bool(spec.get('problem')) and reward.get('problem')==spec['problem'])


@hook('character_source_projection_needed')
def learning_projection_needed(sheet):
    import json
    known=sheet.get('spheres_and_talents') or {}
    if isinstance(known,str):known=json.loads(known)
    sphere_ids=known.get('sphere_record_ids',[])
    if isinstance(sphere_ids,str):sphere_ids=json.loads(sphere_ids)
    return True if 'tianxia.sphere.sect_stewardship' in sphere_ids else None


@hook('character_source_projection')
def learning_projection(sheet,actor_record):
    if not learning_projection_needed(sheet):return None
    training=actor_record.get('source_states',{}).get(KEY,{}).get('training')
    if not training:return None
    from ..journey import ability_modifiers
    import json
    sheet=deepcopy(sheet)
    sheet['sect_stewardship_training']=deepcopy(training)
    stats=sheet['ability_scores_and_statistics']
    skill=training['proficiency']
    if not training['duplicate'] and skill in SKILLS:
        rows=stats.get('skills',[])
        if isinstance(rows,str):rows=json.loads(rows)
        rows=deepcopy(rows)
        ability={'History':'INT','Insight':'WIS','Investigation':'INT','Persuasion':'CHA','Religion':'WIS'}[skill]
        mods=ability_modifiers(sheet)
        row=next((r for r in rows if r.get('skill')==skill),None)
        if row is None:row={'skill':skill,'bonus':mods[ability]};rows.append(row)
        from ..ability_checks import proficiency_rank
        if row.get('granted_by')!=LEARN and (proficiency_rank(row) or 0)<1:
            row['bonus']+=int(sheet.get('identity',{}).get('proficiency_bonus',2))
            row['granted_by']=LEARN
            row['proficiency']='Proficient';row['proficiency_multiplier']=1
        stats['skills']=rows
    elif not training['duplicate']:
        tools=stats.get('tool_proficiencies',[])
        if isinstance(tools,str):tools=json.loads(tools)
        stats['tool_proficiencies']=list(dict.fromkeys([*tools,skill]))
    return sheet


@hook('compile_resource_definitions')
def learned_key(resources,info):
    training=info['owner_sheet'].get('sect_stewardship_training')
    if not training or LEARN not in info['owned_ids']:return None
    value=('INT','WIS','CHA').index(training['ability'])+1
    return [r.model_copy(update={'initial':value}) if r.resource_id==SECT_KEY else r for r in resources]


@hook('journey_options')
def institutional_intents(session,aid):
    """Offer concrete admitted activities; arbitrary choices remain typed intents."""
    from ..fact_consent_admission import visible_records
    from .journey_activities import current
    actor=session.state['actors'][aid]
    if not contract(session,aid) or session.state['phase']!='travel' or actor['incapacitated']:return None
    data=ledger_view(session,aid);rows=[]
    if 'training' not in data and owns(session,aid,LEARN):
        for approval in visible_records(session,LEARN,aid,'tool_approval',aid):
            tool=approval['value'].get('tool')
            if type(tool) is not str:continue
            for ability,label in SECT_ABILITIES:
                rows.append({'id':'sect:custom:'+ability+':'+approval['receipt_id'],'kind':'sect_learn','auto_select':0,
                    'payload':{'ability':ability,'proficiency':tool,'approval':approval['scope']},
                    'label':'Learn Sect Stewardship with '+label+' and the GM-approved duty tool '+tool+'; no action or Merit cost'})
    if owns(session,aid,PETITION) and actor['resources'].get(MERIT,0)>0:
        for record in visible_records(session,LEARN,aid,'institution',aid):
            try:inst=institution(session,aid,record['scope'])
            except ValueError:continue
            if not inst['present']:continue
            for request in inst['ordinary_support']:
                try:support_terms(session,aid,record['scope'],request,inst['standing'])
                except ValueError:continue
                rows.append({'id':'sect:petition:'+record['receipt_id']+':'+request,'kind':'sect_petition','auto_select':0,
                    'payload':{'institution':record['scope'],'request':request},
                    'label':'Petition '+inst['authority']+' at '+inst['name']+' for '+request+'; one non-combat Action and one Merit Die, with support determined by the roll'})
    if owns(session,aid,DUTY):
        if data.get('declared_rest',-1)!=actor['long_rests']:
            for record in visible_records(session,LEARN,aid,'duty_plan',aid):
                obligation=record['value'].get('obligation')
                if type(obligation) is str:
                    rows.append({'id':'sect:duty:'+record['receipt_id'],'kind':'sect_duty','auto_select':0,
                        'payload':{'scope':record['scope']},'label':'Declare Duty: '+obligation+'; once per Long Rest, actual work still required'})
        duty=data.get('duty')
        if duty and not duty['rewarded']:
            step=len(duty['completed'])
            if step<len(duty['plan']['steps']) and not current(session,aid):
                task=duty['plan']['steps'][step]
                rows.append({'id':'sect:work:'+str(step),'kind':'activity_start','auto_select':0,
                    'payload':{'source':DUTY,'parameters':{'step':step}},
                    'label':'Pursue Duty: '+task['task']+'; requires '+str(task['seconds'])+' seconds of actual work'})
            elif step==len(duty['plan']['steps']):
                record=read(session,LEARN,aid,'duty_verification',duty['instance_id'],aid)
                if record and record['created_at']>=duty['completed'][-1]['finished_at']:
                    labels={'merit':'regain one spent Merit Die','standing':'improve Standing for this scene',
                        'favor':'gain a minor favor','rumor':'learn a useful rumor','supplies':'secure food, shelter or basic supplies for yourself; you may choose up to five companions to share this reward',
                        'sect_check':'gain Advantage on one later Sect Check concerning the same hall, person or problem'}
                    for reward in record['value'].get('approved_rewards',()):
                        if reward in labels:rows.append({'id':'sect:reward:'+reward,'kind':'sect_reward','auto_select':0,
                            'payload':{'reward':reward,'companions':[]},
                            'label':'Completed Duty — '+labels[reward]+'; consumes your one GM-approved reward'})
    for row in rows: row['auto_select'] = int(autonomous(session,aid))
    return rows
