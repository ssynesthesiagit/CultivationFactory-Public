"""Karate's Body Stamina consumer of the existing elapsed-time Journey API.

The JourneyStore owns admission, integer clocks, optimistic revisions, atomic
persistence, actor continuity and combat handoff. This family consumer restores
only its source-owned Stamina and tracks its two printed rest-recovery limits.
Other Body families retain their existing owners and behavior.
"""
from . import hook
from .karate import PREFIX

STAMINA = 'resource:core.stamina'
SHORT = 'tianxia.path.body_refining.short_recoveries'
CULTIVATION = 'tianxia.path.body_refining.cultivation_used'
SHORT_COMMAND = 'karate_stamina_short_rest'
CULTIVATION_COMMAND = 'karate_stamina_cultivation'


def owns(session, actor_id):
    actor = session.state['actors'][actor_id]
    return any(str(row.get('feature_id') or '').startswith(PREFIX)
               for row in actor['bundle'].get('typed_passives') or [])


def maximum(actor):
    return next((int(pool['maximum']) for pool in actor['bundle']['actor_template']['resources']
                 if pool['resource_id'] == STAMINA), 0)


def restore(session, actor_id, amount, procedure):
    actor = session.state['actors'][actor_id]
    before = actor['resources'].get(STAMINA, 0)
    actor['resources'][STAMINA] = min(maximum(actor), before + amount)
    session.emit('STAMINA_RECOVERED', actor_id, source='tianxia.path.body_refining.stamina',
                 procedure=procedure, amount=actor['resources'][STAMINA]-before,
                 remaining=actor['resources'][STAMINA], maximum=maximum(actor))


@hook('journey_options')
def stamina_options(session, actor_id):
    actor = session.state['actors'][actor_id]
    if not owns(session, actor_id) or session.state['phase'] != 'travel' or actor['incapacitated']:
        return None
    uses = actor['travel_uses']
    missing = maximum(actor)-actor['resources'].get(STAMINA, 0)
    options = []
    if int(uses.get(SHORT, 0)) < 2:
        amount = min(missing, maximum(actor)//2)
        options.append({'id': SHORT_COMMAND, 'kind': SHORT_COMMAND, 'payload': {},
            'auto_select': int(missing > 0),
            'label': f"{actor['name']}: recover {amount} Stamina during a one-hour Short Rest "
                     f"(use {int(uses.get(SHORT, 0))+1} of 2 before the next Long Rest)."})
    if not uses.get(CULTIVATION):
        options.append({'id': CULTIVATION_COMMAND, 'kind': CULTIVATION_COMMAND, 'payload': {},
            'auto_select': int(missing > 0),
            'label': f"{actor['name']}: complete two uninterrupted hours of cultivation to recover "
                     f"{missing} Stamina (once before the next Long Rest)."})
    return options


@hook('journey_command')
def stamina_recovery(session, actor_id, kind, payload):
    if kind not in {SHORT_COMMAND, CULTIVATION_COMMAND}:
        return None
    from ..journey import require
    actor = session.state['actors'][actor_id]
    require(owns(session, actor_id) and not actor['incapacitated'],
            'This creature cannot use the Karate Body Stamina recovery procedure.')
    require(not payload, 'This recovery has no instant or variable-duration shortcut.')
    uses = actor['travel_uses']
    if kind == SHORT_COMMAND:
        require(int(uses.get(SHORT, 0)) < 2, 'Both Short Rest Stamina recoveries are spent until a Long Rest.')
        session.tick(3600)
        uses[SHORT] = int(uses.get(SHORT, 0))+1
        restore(session, actor_id, maximum(actor)//2, 'short_rest')
    else:
        require(not uses.get(CULTIVATION), 'The full cultivation restoration is spent until a Long Rest.')
        session.tick(7200)
        uses[CULTIVATION] = 1
        restore(session, actor_id, maximum(actor), 'cultivation_session')
    return True


@hook('journey_rest')
def stamina_long_rest(session, actor_id):
    if not owns(session, actor_id):
        return None
    actor = session.state['actors'][actor_id]
    actor['travel_uses'][SHORT] = 0
    actor['travel_uses'][CULTIVATION] = 0
    restore(session, actor_id, maximum(actor), 'long_rest')


SCENE = 'tianxia.subpath.body.karate.scene'


def seal_scene(actor, state):
    """Pass native continuation into the family's existing compiled profile."""
    for row in actor['bundle'].get('typed_passives') or []:
        if row.get('block') == 'karate_profile':
            row['scene_id'] = state['scene_id']
            row['scene_prior_initiative'] = state['initiative_seen']


@hook('journey_initialized')
def karate_scene_initialize(session):
    # The shared owner imports every participant's persisted source state before
    # this hook. A new participant joining this family's retained conflict must
    # not obtain another initial-scene restoration.
    actors=session.state['actors']
    retained=[actor.get('source_states',{}).get(SCENE) for actor in actors.values()]
    retained=[state for state in retained if state is not None]
    scene=next((state['scene_id'] for state in retained),session.state.get('scene_id',session.state['journey_id']))
    events=session.state['events']
    boundary=max((index for index,event in enumerate(events) if event['kind']=='SCENE_ENDED'),default=-1)
    native_seen=any(event['kind']=='ENTER_COMBAT' for event in events[boundary+1:])
    seen=int(native_seen or any(state['initiative_seen'] for state in retained))
    for actor_id,actor in actors.items():
        if not owns(session,actor_id):
            continue
        state=actor.setdefault('source_states',{}).setdefault(SCENE,{'scene_id':scene,'initiative_seen':seen})
        from ..journey import require
        require(set(state)=={'scene_id','initiative_seen'} and type(state['scene_id']) is str
                and type(state['initiative_seen']) is int and state['initiative_seen'] in (0,1),
                'The retained Karate scene state is invalid.')
        seal_scene(actor,state)


@hook('journey_encounter_settled')
def karate_scene_settled(session,actor_id,engine,creature):
    if not owns(session,actor_id):
        return
    # Initiative is a real native event; an empty/inactive roster entry does
    # not manufacture it. Journey resume imports the actual scene-use pools.
    if any(event.event_type=='INITIATIVE_ROLLED' and event.actor_id==actor_id for event in engine.events):
        state=session.state['actors'][actor_id]['source_states'][SCENE]
        state['initiative_seen']=1
        seal_scene(session.state['actors'][actor_id],state)


@hook('journey_scene_end')
def karate_scene_end(session,previous,current):
    for actor_id,actor in session.state['actors'].items():
        if not owns(session,actor_id):
            continue
        state={'scene_id':current,'initiative_seen':0}
        actor.setdefault('source_states',{})[SCENE]=state
        seal_scene(actor,state)
        # Only the original owned Isshun Action identifies its native limit.
        # Restore that printed use; no Stamina or other source's pool changes.
        limits={resource for action in actor['bundle']['action_catalog']
            if (action.get('parameters',{}).get('typed') or {}).get('source')==PREFIX+'isshun_sengeki'
            for resource,cost in action.get('costs') or [] if resource.startswith('resource:uses.')}
        for pool in actor['bundle']['actor_template']['resources']:
            if pool['resource_id'] in limits:
                actor['resources'][pool['resource_id']]=pool['maximum']
