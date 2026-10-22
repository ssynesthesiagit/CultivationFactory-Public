"""Native Path consequences shared by outside-combat procedures.

Public add_exhaustion is used by Stamina depletion and Dream Refinement. Both
retain the same canonical snapshot, level cap, death condition and replay event.
"""
from . import hook


@hook('journey_resource_spent')
def stamina_to_zero(session,aid,resource,before,after,source):
    if resource!='resource:core.stamina' or before<=0 or after!=0:return
    add_exhaustion(session, aid, 1, source, event='STAMINA_ZERO_EXHAUSTION')


def add_exhaustion(session, aid, levels, source, *, event='JOURNEY_EXHAUSTION'):
    from ..journey import require, integer
    from .forged_exhaustion import MAX_LEVEL
    import json
    require(integer(levels, 1) and type(source) is str and bool(source), 'Exhaustion needs actual positive levels and a source.')
    actor=session.state['actors'][aid]
    actor['exhaustion']=min(MAX_LEVEL,actor['exhaustion']+levels)
    session.emit(event,aid,source=source,level=actor['exhaustion'])
    if actor['exhaustion']>=MAX_LEVEL:
        # Six actual levels are lethal, never a fresh healthy combat actor.
        from ..gate2_runtime_models import ConditionInstance
        from .life_state import DEAD
        template=actor['bundle']['actor_template']
        snapshot=actor.setdefault('encounter_snapshot',{'current_hp':template['maximum_hp'],
            'maximum_hp':template['maximum_hp'],'temporary_hp':0,'active':1,'life_state':'',
            'conditions':{},'death_saves':{'ok':0,'bad':0}})
        if any(json.loads(c)['condition_id'] == DEAD for c in snapshot['conditions'].values()):
            return
        snapshot['current_hp']=0;snapshot['active']=0;snapshot['life_state']=''
        key='journey:exhaustion_death'
        condition=ConditionInstance(instance_id=key,condition_id=DEAD,source_definition_id=source,
            source_actor_id=aid,target_id=aid,applied_sequence=len(session.state['events']),expires_on='UNTIL_REMOVED',
            data={'label':'Death from six levels of Exhaustion'})
        snapshot['conditions'][key]=condition.model_dump_json()
        actor['incapacitated']=1
        session.emit('JOURNEY_DEATH',aid,source=source,cause='six_exhaustion_levels')
