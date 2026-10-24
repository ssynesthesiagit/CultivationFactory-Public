"""Deterministic replay of native Journey command segments.

Genesis captures actual acquired bundles and restored balances. Every successful
actor/world/scene transaction carries its revision and mechanical state hash.
Failed requests never enter this ledger. Combat binding remains a separately
verified native match; callers verify the journey segment before that boundary.
"""
from copy import deepcopy
import hashlib
import json
from .journey import JourneySession, require
from .ext import run_strict

KEY = 'command_replay'


def body(state): return {k:v for k,v in state.items() if k!=KEY}


def digest(state):
    return hashlib.sha256(json.dumps(body(state),sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def initialize(session, *, completed_match=None):
    prior=session.state.get(KEY)
    history=deepcopy(prior.get('previous_segments',[])) if prior else []
    if prior and completed_match:
        history.append({'genesis':deepcopy(prior['genesis']),'commands':deepcopy(prior['commands']),
                        'match_id':completed_match})
    session.state[KEY] = {'genesis':deepcopy(body(session.state)), 'commands':[],
                         **({'previous_segments':history} if history else {})}


def append(session, operation, parameters):
    if KEY not in session.state: return  # older journeys keep their original format
    session.state[KEY]['commands'].append({'operation':operation,'parameters':deepcopy(parameters),
        'revision':session.state['revision'],'state_sha256':digest(session.state)})


def world(session, payload):
    from .fact_consent_admission import declare_world, KEY as FACTS
    receipt_id=declare_world(session,payload)
    receipt=next(r for r in session.state[FACTS] if r['receipt_id']==receipt_id)
    run_strict('journey_world_fact_committed',session,receipt)


def scene(session,reason):
    previous=session.state.get('scene_id',session.state['journey_id'])
    from .fact_consent_admission import declare_world
    subject=next(iter(session.state['actors']))
    receipt=declare_world(session,{'source':'system:journey.scene','subject':subject,'kind':'scene_end',
        'scope':previous+':'+str(session.state['revision']),'value':reason.strip(),'expires_at':int(session.clock())+1,
        'readers':list(session.state['actors'])})
    number=int(session.state.get('scene_number',0))+1
    current=session.state['journey_id']+':scene:'+str(number)
    session.state['scene_id']=current;session.state['scene_number']=number
    run_strict('journey_scene_end',session,previous,current)
    session.emit('SCENE_ENDED',subject,authority='table_owner',
        previous_scene=previous,next_scene=current,reason=reason.strip(),declaration_receipt=receipt)


def verify(state):
    ledger=state.get(KEY)
    require(ledger is not None,'This older journey has no native command replay ledger.')
    for previous in ledger.get('previous_segments',()):execute(previous)
    working=execute(ledger)
    require(digest(working.state)==digest(state), 'The journey crossed an external combat boundary; verify its native match separately.')
    return {'status':'PASS','commands':len(ledger['commands']),'state_sha256':digest(working.state),
            'previous_segments':len(ledger.get('previous_segments',())),
            'bound_matches':[row['match_id'] for row in ledger.get('previous_segments',())]}


def execute(ledger):
    working=JourneySession(deepcopy(ledger['genesis']))
    for row in ledger['commands']:
        parameters=row['parameters']
        if row['operation']=='actor':
            working.command(parameters['actor_id'],parameters['kind'],deepcopy(parameters['payload']))
        elif row['operation']=='world': world(working,deepcopy(parameters))
        elif row['operation']=='scene': scene(working,parameters['reason'])
        else: raise ValueError('Unknown journey replay operation.')
        working.state['revision']+=1
        require(working.state['revision']==row['revision'] and digest(working.state)==row['state_sha256'],
                'The journey command replay differs from its committed mechanical checkpoint.')
    return working
