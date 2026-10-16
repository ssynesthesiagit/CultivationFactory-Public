"""Native scene menus and controller priority; source eligibility is opt-in."""
from copy import deepcopy
from . import hook,query
from ..journey import require


def actions(session,aid,native):
    ids={key for rows in query('journey_native_actions',session,aid,native) for key in (rows or ())}
    return [a for key,a in native.action_catalog.items() if key in ids and a.owner_id==aid]


@hook('journey_options')
def options(session,aid):
    if session.state['phase']!='travel' or session.state['actors'][aid]['incapacitated']:return None
    pending=session.state.get('scene_pending')
    if pending:
        request=pending['request']
        if request['reactor_id']!=aid:return []
        # Multi-select choices are represented by their full native spec, never
        # expanded/truncated to one selected option. The controller submits the
        # complete option_ids array through the same journey command endpoint.
        spec=request.get('extension_choice') or {}
        trigger=request.get('choice_trigger') or {}
        labels=trigger.get('labels') or {}
        rows=[]
        for oid in spec.get('option_ids',[]):
            rows.append({'id':'scene_choice:'+oid,'kind':'scene_choice',
                'payload':{'selection':'USE','option_ids':[oid],'spend':0},
                'label':trigger['prompt']+' '+labels.get(oid,oid),
                'choice':deepcopy(spec),'auto_select':0})
        if not spec:
            for spend in request.get('spend_options') or [0]:
                rows.append({'id':'scene_choice:use:'+str(spend),'kind':'scene_choice',
                    'payload':{'selection':'USE','option_ids':[],'spend':spend},
                    'label':trigger['prompt']+' Use this response.','auto_select':0})
        if not spec or spec.get('allow_decline'):
            rows.append({'id':'scene_choice:pass','kind':'scene_choice',
                'payload':{'selection':'DECLINE','option_ids':[],'spend':0},
                'label':trigger['prompt']+' Pass.','auto_select':0})
        return rows
    from ..scene_resolution import engine_for,candidates
    if not any(query('journey_native_enabled',session,aid)):return None
    native=engine_for(session)
    turn=session.state['actors'][aid].get('source_turn')
    rows=[]
    for action in actions(session,aid,native):
        economy={'ACTION':'action','BONUS_ACTION':'bonus_action'}.get(action.economy.value)
        if turn and (not turn['active'] or (economy and not turn[economy])):continue
        for candidate in candidates(native,aid,action):
            names=[native.state.actors[t].display_name if t in native.state.actors
                else str(native.state.objects[t].component.get('name') or native.state.objects[t].object_kind)
                for t in candidate.target_ids if t in native.state.actors or t in native.state.objects]
            rows.append({'id':'scene_native:'+candidate.candidate_id,'kind':'scene_native_action',
                'payload':{'action':action.source_definition_id,'candidate':candidate.candidate_id},
                'label':action.display_name+(' — '+', '.join(names) if names else '')+'. '+str(action.parameters.get('description','Choose the native target and choices; normal action and CP costs apply.'))})
    return rows


@hook('journey_command')
def command(session,aid,kind,payload):
    if kind!='scene_native_action':return None
    require(set(payload)=={'action','candidate'},'Choose one offered native scene action.')
    from ..scene_resolution import engine_for,candidates,commit
    native=engine_for(session)
    action=next((a for a in actions(session,aid,native) if a.source_definition_id==payload['action']),None)
    require(action is not None,'This creature does not own that scene action.')
    offered=next((c for c in candidates(native,aid,action) if c.candidate_id==payload['candidate']),None)
    require(offered is not None,'Refresh the native scene target options.')
    return commit(session,native,aid,action,offered,{})


@hook('journey_auto_blocked')
def waiting(session,aid):
    return True if session.state.get('scene_pending') else None


@hook('journey_view')
def private_pending(state,viewer_id):
    if 'scene_pending' not in state:return None
    out=deepcopy(state);pending=out.pop('scene_pending')
    if pending['request']['reactor_id']==viewer_id:
        out['scene_pending']={'request':pending['request']}
    out.pop('replay_base',None);out.pop('command_journal',None)
    return out
