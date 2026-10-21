"""Optional source-turn clocks for actions in a native elapsed-time scene.

A controller begins/ends its own actual scene turn. No initiative order or
elapsed number of seconds is inferred. Sources may debit Action/Bonus Action
through pay(); records use the combat engine's recognized source-marker clock
names and integer marker_turn. Unused scenes have no counters or behavior.
Consumers: source-scoped Beauty/Ink/Thread scene commands.
"""
from . import hook,run_strict
from ..journey import require


def begin(session,aid):
    actor=session.state['actors'][aid];turn=actor.setdefault('source_turn',{'started':0,'active':0,'action':0,'bonus_action':0})
    require(not turn['active'],'End this creature’s current scene turn before starting the next one.')
    turn.update(started=turn['started']+1,active=1,action=1,bonus_action=1,movement_remaining_ft=int(actor['bundle']['actor_template']['speed_ft']),movement_position=dict(actor['position']))
    session.emit('SCENE_TURN_STARTED',aid,turn=turn['started'])
    run_strict('journey_turn_boundary',session,aid,'start')


def pay(session,aid,economy):
    actor=session.state['actors'][aid]
    if 'source_turn' not in actor:begin(session,aid)
    turn=actor['source_turn']
    require(turn['active'] and turn.get(economy)==1,'This creature must begin its next scene turn before using another '+economy.replace('_',' ')+'.')
    turn[economy]=0;session.emit('SCENE_ECONOMY_SPENT',aid,economy=economy,turn=turn['started'])


def deadline(session,aid,edge):
    require(edge in ('start','end'),'Choose a start or end source-turn clock.')
    return {'source_actor_id':aid,'expires_on':'START_OF_MARKER_NEXT_TURN' if edge=='start' else 'END_OF_MARKER_NEXT_TURN',
        'marker_turn':session.state['actors'][aid].get('source_turn',{}).get('started',0)}


def live(session,row):
    if 'expires_on' not in row:return not row.get('expires_at') or row['expires_at']>session.clock()
    turn=session.state['actors'][row['source_actor_id']].get('source_turn',{'started':0,'active':0})
    if turn['started']<=row['marker_turn']:return True
    if row['expires_on']=='START_OF_MARKER_NEXT_TURN':return False
    require(row['expires_on']=='END_OF_MARKER_NEXT_TURN','Unsupported scene source clock.')
    return turn['started']==row['marker_turn']+1 and turn['active']==1


@hook('journey_persistent_fields')
def fields():return ('source_turn',)


@hook('journey_command')
def boundary(session,aid,kind,payload):
    if kind!='scene_turn':return None
    require(set(payload)=={'edge'} and payload['edge'] in ('start','end'),'Choose the actual start or end of this creature’s scene turn.')
    if payload['edge']=='start':begin(session,aid)
    else:
        turn=session.state['actors'][aid].get('source_turn')
        require(turn and turn['active'],'This creature has no active scene turn to end.')
        turn['active']=0;session.emit('SCENE_TURN_ENDED',aid,turn=turn['started'])
        run_strict('journey_turn_boundary',session,aid,'end')
    return True


@hook('journey_options')
def options(session,aid):
    turn=session.state['actors'][aid].get('source_turn')
    if not turn or session.state['phase']!='travel':return None
    edge='end' if turn['active'] else 'start'
    return [{'id':'scene_turn:'+edge,'kind':'scene_turn','payload':{'edge':edge},
        'label':edge.capitalize()+' this creature’s scene turn; source-turn effects use this actual boundary.'}]


def pay_movement(session,aid,feet):
    actor=session.state['actors'][aid]
    if 'source_turn' not in actor:begin(session,aid)
    turn=actor['source_turn']
    require(type(feet) is int and feet>=0 and turn['active'] and turn['movement_remaining_ft']>=feet,'This creature lacks the movement for that scene action.')
    turn['movement_remaining_ft']-=feet
    session.emit('SCENE_MOVEMENT_SPENT',aid,feet=feet,remaining_ft=turn['movement_remaining_ft'])


@hook('journey_state_changed')
def actual_movement(session,aid):
    from ..gate2_runtime_models import Position
    actor=session.state['actors'][aid];turn=actor.get('source_turn')
    if not turn or not turn['active'] or turn['movement_position']==actor['position']:return
    distance=session.grid.distance_ft(Position.model_validate(turn['movement_position']),Position.model_validate(actor['position']))
    pay_movement(session,aid,distance)
    turn['movement_position']=dict(actor['position'])
