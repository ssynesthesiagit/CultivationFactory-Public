"""Mantra of Silence: bounded exceptions, start-turn relief and sound paths.

The ordinary zone condition provides Deafened and Silenced only while inside.
Exempt creatures and a creature succeeding on its start-turn Charisma save lose
that zone grant; a source-owned holder-next-start marker records relief. Sound
still cannot cross the boundary, even for exempt/relieved creatures. Thunder
packets are unchanged. Automatic exemptions are perceived allies.
"""
from . import effect, hook, placed

TAG='mantra_silence'
RELIEF='condition:typed.mantra_silence_relief'


def _relieved(actor, zone):
    return any(c.condition_id==RELIEF and c.data.get('zone_id')==zone.zone_id for c in actor.conditions.values())


@effect('mantra_silence', harmful=True)
def silence(ctx, row):
    from .. import stealth
    from .needle import ask,checkpoint_id
    creatures=[a for a in ctx.engine.state.actors.values() if a.active and (a is ctx.actor or stealth.sees(ctx.engine,ctx.actor,a))]
    friends=[a.entity_id for a in creatures if a.team_id==ctx.actor.team_id]
    exempt=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'mantra_silence_exempt',ctx.source),ctx.actor,
               'choice:needle.mantra_silence_exempt',[a.entity_id for a in creatures],labels={a.entity_id:a.display_name for a in creatures},
               minimum=0,maximum=int(ctx.numbers.get('pb') or 2),preferred=friends,automatic_options=friends,
               default_count=min(len(friends),int(ctx.numbers.get('pb') or 2)),
               prompt='Mantra of Silence: choose up to your Proficiency Bonus in creatures, including yourself, to leave unaffected. You are also affected unless you choose to leave yourself unaffected.')
    center=getattr(ctx.intent,'destination',None) or ctx.actor.position
    placed.place(ctx.engine,ctx.actor,source=ctx.source,tag=TAG,cells=(center,*placed.area(ctx.engine,center,'sphere',30)),
                 name='Mantra of Silence',placed={'exempt':exempt},numbers=ctx.numbers,duration_rounds=10,
                 concentration=True,concentration_scope=True,radial_volume=True,shape='sphere',size_ft=30,color='#a1b1ce',
                 extra={'sound_suppression':1},
                 inside=[{'id':'silence','name':'Mantra of Silence: Deafened, cannot use audible techniques',
                          'rule':{'cant_hear':True,'silenced':True}}])


@hook('zone_subject_allowed')
def silence_subject(engine,zone,actor):
    if placed.data(zone).get('tag')==TAG:
        return actor.entity_id not in placed.data(zone).get('exempt',[]) and not _relieved(actor,zone)


@hook('turn_start_choice')
def silence_save(engine,actor):
    from .. import zones,typed_executor
    from .needle import ask,checkpoint_id
    for zone in placed.of(engine,TAG):
        if not zones.actor_inside_zone(engine,actor,zone) or actor.entity_id in placed.data(zone).get('exempt',[]):
            continue
        owner=engine.state.actors.get(zone.owner_id)
        if owner is None:continue
        use=ask(engine,engine._active_intent,checkpoint_id(engine,'mantra_silence_save',zone.zone_id,actor.entity_id),actor,
                'choice:needle.mantra_silence_save',['save'],minimum=0,maximum=1,allow_decline=True,
                preferred=['save'],labels={'save':'Make a Charisma save to hear and use audible techniques this turn'},
                prompt=f'{actor.display_name} starts a turn inside Mantra of Silence. Make a Charisma save to speak, hear and use audible techniques until the start of your next turn? No action or Qi cost; sound still cannot cross the boundary.')
        if not use:continue
        from .activation_requirements import effective_numbers
        ctx=placed.context(engine,owner,zone.source_definition_id,effective_numbers(owner,zone.trigger_profile['numbers'],engine=engine),[actor])
        typed_executor.run_effects(ctx,[{'type':'save','applies_to':'target','ability':'cha','on_fail':[],
                                        'on_success':[{'type':'mantra_silence_relief','zone_id':zone.zone_id}]}])


@effect('mantra_silence_relief')
def relief(ctx,row):
    if ctx.target:
        # The save occurs on the affected creature's turn. Name that creature's
        # next start through the shared turn-counter expiry helper; the legacy
        # native token also expires on the caster's next turn.
        from ..typed_executor import effect_expiry
        expires=effect_expiry(ctx,{'expires_on':'START_OF_TARGET_NEXT_TURN'},ctx.target,condition=True)
        ctx.engine._apply_condition(ctx.target,RELIEF,ctx.source,ctx.actor.entity_id,expires_on=expires,
                                    data={'zone_id':row['zone_id'],'label':'Mantra of Silence: can hear and speak until next turn'})
        from .. import zones
        zones.sync_inside(ctx.engine,ctx.source)


@hook('sound_path_allowed')
def sound_path(engine,speaker,listener,source):
    from .. import zones
    from ..space import ray
    for zone in placed.of(engine,TAG):
        # Successful relief restores speech/hearing inside, not transmission.
        a,b=zones.actor_inside_zone(engine,speaker,zone),zones.actor_inside_zone(engine,listener,zone)
        if a != b:return False
        if a:
            exempt=placed.data(zone).get('exempt',[])
            if not (speaker.entity_id in exempt or _relieved(speaker,zone)):return False
            if not (listener.entity_id in exempt or _relieved(listener,zone)):return False
        else:
            from ..typed_executor import in_area
            from ..gate2_runtime_models import Position
            if any(in_area(engine,zone.center,zone.center,Position(x=x,y=y,z=z),{'shape':'sphere','size_ft':30}) for x,y,z in ray(speaker.position,listener.position)[1:-1]):return False


@hook('sound_boundaries')
def physical_sound_boundaries(engine,speaker,recipient,origin,endpoint):
    """Public physical-source transport, including items/Formation points.

    Hearing is deliberately separate: an affected Deafened recipient can still
    receive physical vibration from an exempt speaker inside the same sphere.
    Every boundary crossing remains blocked, including exempt/relieved speakers.
    """
    from ..spatial_areas import positions_inside_zone
    from ..space import ray
    from ..gate2_runtime_models import Position
    from ..typed_executor import in_area
    result=[]
    for zone in placed.of(engine,TAG):
        inside=lambda p:positions_inside_zone(engine,[(p.x,p.y,p.z)],zone)
        a,b=inside(origin),inside(endpoint)
        crosses = a != b or (not a and not b and any(in_area(engine,zone.center,zone.center,
            Position(x=x,y=y,z=z),{'shape':'sphere','size_ft':30}) for x,y,z in ray(origin,endpoint)[1:-1]))
        exempt=getattr(speaker,'entity_id',None) in placed.data(zone).get('exempt',())
        relieved=hasattr(speaker,'conditions') and _relieved(speaker,zone)
        if crosses or (a and not exempt and not relieved):
            result.append({'kind':'silence','name':'Mantra of Silence','source_cl':int(placed.source_cl(engine,zone)),
                'owner_id':zone.owner_id,'source_zone_id':zone.zone_id,'cells':[[origin.x,origin.y],[endpoint.x,endpoint.y]]})
    return result or None


@hook('event',nested=True)
def illegal_maintenance_ends(engine,event_type,kwargs):
    if event_type not in {'CONDITION_APPLIED','CONDITION_REMOVED'}:
        return
    for zone in list(placed.of(engine,TAG)):
        level=placed.source_cl(engine,zone)
        if level is not None and level<14:
            owner=engine.state.actors.get(zone.owner_id)
            if owner is not None and type(placed.data(zone).get('concentration_started')) is int:
                from ..concentration import end_copy
                end_copy(engine,owner,placed.data(zone)['concentration_started'],'MAINTENANCE_ILLEGAL')
            placed.drop(engine,zone,'MAINTENANCE_ILLEGAL')
