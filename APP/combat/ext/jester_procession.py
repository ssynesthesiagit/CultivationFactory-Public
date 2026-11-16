"""Procession's continuous ally benefits and once-round Flustered steps.

Enemy entry/start saves and post-save choices use ordinary typed zone rows.
The existing source-owned zone choice transport serves every delayed save.
"""
from . import hook
SOURCE='tianxia.talent.jester.ten_thousand_masks_procession'
ALLY_RULE='jester_masks_allies'


@hook('zone_recipient_allowed')
def recipients(engine, zone, creature, row):
    if zone.source_definition_id.startswith('action:') and (zone.trigger_profile.get('profile') or {}).get('jester_masks'):
        if row.get('id')==ALLY_RULE and creature.entity_id==zone.owner_id:return False
    return None


@hook('speed')
def ally_speed(engine, actor):
    from ..zones import current_inside_grants
    return 10 if any(row.get('id')==ALLY_RULE for zone,row in current_inside_grants(engine,actor).values()
        if (zone.trigger_profile.get('profile') or {}).get('jester_masks')) else 0


@hook('event',nested=True)
def flustered_steps(engine,event_type,kwargs):
    if event_type!='CONDITION_APPLIED' or (kwargs.get('payload') or {}).get('condition_id')!='condition:typed.flustered':return
    from .. import zones
    from ..typed_executor import Context
    from .rider_step import step
    from ..relations import ALLY, ENEMY, relation
    for enemy_id in kwargs.get('target_ids') or ():
        enemy=engine.state.actors.get(enemy_id)
        if enemy is None:continue
        for zone in list(zones.typed_zones(engine)):
            if not (zone.trigger_profile.get('profile') or {}).get('jester_masks') or not zones._inside(engine,enemy,zone):continue
            owner=engine.state.actors.get(zone.owner_id)
            action=engine.action_catalog.get(zone.source_definition_id)
            if owner is None or action is None or relation(engine,owner,enemy)!=ENEMY:continue
            for ally in list(engine.state.actors.values()):
                if ally is owner or not ally.active or relation(engine,owner,ally)!=ALLY or not zones._inside(engine,ally,zone):continue
                from . import ai_controlled
                from ..target_knowledge import located
                if ai_controlled(engine,ally) and not located(engine,ally,enemy):continue
                flag='_round_masks_step:'+zone.zone_id
                if ally.turn_flags.get(flag)==engine.state.round_number:continue
                typed={'source':SOURCE,'effects':[],'numbers':dict(zone.trigger_profile.get('numbers') or {}),'riders':[]}
                ctx=Context(engine,ally,action,getattr(engine,'_active_intent',None),typed,[enemy],enemy,{})
                step(ctx,{'distance_ft':5,'no_oa':True,'label':'Ten-Thousand Masks Procession','trigger':'an enemy became Flustered'})
                ally.turn_flags[flag]=engine.state.round_number
