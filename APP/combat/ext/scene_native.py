"""Native scene menus and controller priority; source eligibility is opt-in."""
from copy import deepcopy
from . import hook,query
from ..journey import require


@hook('journey_persistent_fields')
def persistent_fields():return ('scene_turn_flags','scene_reaction_available',)


@hook('journey_resolution_settled')
def turn_settled(session,aid,native,actor):
    from ..scene_resolution import choice_document
    row=session.state['actors'][aid]
    row['scene_turn_flags']=choice_document(actor.turn_flags)
    row['scene_reaction_available']=int(bool(actor.reaction_available))


@hook('journey_turn_boundary')
def turn_boundary(session,aid,edge):
    # Native turn flags, including remaining attacks, never cross a scene turn.
    # Reaction budget refreshes only at this actor's actual next turn start.
    row=session.state['actors'][aid]
    row.pop('scene_turn_flags',None)
    if edge=='start':row['scene_reaction_available']=1


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
        if spec.get('maximum_selections',0)>1:
            preferred=spec.get('preferred_option_ids') or spec['option_ids']
            rows.append({'id':'scene_choice:select','kind':'scene_choice',
                'payload':{'selection':'USE','option_ids':preferred[:spec['minimum_selections']],'spend':0},
                'label':trigger['prompt'],'choice':deepcopy(spec),'auto_select':0,
                'inputs':{'option_ids':{'type':'choices','choices':list(spec['option_ids']),
                    'labels':deepcopy(labels),'minimum':spec['minimum_selections'],
                    'maximum':spec['maximum_selections']}}})
        for oid in spec.get('option_ids',[]):
            if spec.get('minimum_selections',1)>1:continue
            rows.append({'id':'scene_choice:'+oid,'kind':'scene_choice',
                'payload':{'selection':'USE','option_ids':[oid],'spend':0},
                'label':trigger['prompt']+' '+labels.get(oid,oid),
                'choice':deepcopy(spec),'auto_select':0})
        if not spec:
            for spend in request.get('spend_options') or [0]:
                for selected in ([[o] for o in request.get('legal_option_ids',[])] or [[]]):
                    rows.append({'id':'scene_choice:use:'+str(spend)+':'+','.join(selected),'kind':'scene_choice',
                        'payload':{'selection':'USE','option_ids':selected,'spend':spend},
                        'label':trigger['prompt']+' Use this response'+(' ('+', '.join(s.replace('_',' ').title() for s in selected)+')' if selected else '')+f'; spend {spend} from the response’s resource pool.',
                        'auto_select':0})
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
    require(not session.state['actors'][aid]['incapacitated'],
            'An incapacitated creature cannot take a native scene action or response.')
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
    if 'scene_pending' not in state and not any('scene_turn_flags' in a for a in state['actors'].values()):return None
    out=deepcopy(state);pending=out.pop('scene_pending',None)
    if pending and pending['request']['reactor_id']==viewer_id:
        out['scene_pending']={'request':pending['request']}
    # Flags are an internal continuation format. Menus expose legal remaining
    # attacks, never opaque actor bookkeeping or another creature's decisions.
    for actor in out['actors'].values():actor.pop('scene_turn_flags',None)
    out.pop('replay_base',None);out.pop('command_journal',None)
    return out
