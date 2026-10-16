"""Opt-in ordinary scene illumination and source-created physical emitters.

The scene owner declares ambient BRIGHT/DIM/DARKNESS through native map save.
Absent that declaration, old arenas retain their existing perception policy.
Emitter profiles never defeat supernatural darkness or opaque geometry.
"""
LEVELS=('DARKNESS','DIM','BRIGHT')


def declared(document):
    if 'ambient_illumination' not in document:
        if 'illumination_declaration' in document:
            raise ValueError('Declare an ambient illumination level with its scene fact.')
        return {}
    level=document['ambient_illumination'];fact=document.get('illumination_declaration')
    if level not in LEVELS or not isinstance(fact,dict) or set(fact)!={'actor','authority','source_rule','visibility','expiry'}:
        raise ValueError('Illumination needs BRIGHT, DIM or DARKNESS and a complete scene-owner declaration.')
    if (fact['authority']!='GM' or fact['visibility']!='public' or fact['expiry']!='map_revision'
            or any(not isinstance(fact[k],str) or not fact[k].strip() or len(fact[k])>500 for k in ('actor','source_rule'))):
        raise ValueError('Use public GM scene illumination, its governing rule and map_revision expiry.')
    return {'ambient_illumination':level,'illumination_declaration':dict(fact)}


def emitter(bright_ft,dim_ft):
    if any(type(v) is not int for v in (bright_ft,dim_ft)) or not 0<=bright_ft<=dim_ft<=10000:
        raise ValueError('Light emitter radii must be bounded nonnegative whole feet, dim at least bright.')
    return {'bright_ft':bright_ft,'dim_ft':dim_ft}


def level_at(engine,position):
    document=getattr(engine,'battlefield_document',None) or {}
    ambient=document.get('ambient_illumination')
    if ambient not in LEVELS:
        return None
    value=LEVELS.index(ambient)
    if value==2:
        return ambient
    from .gate2_runtime_models import ActorState
    from .senses import physical_sight
    # Geometry-only sight endpoints; no creature identity, senses or ownership
    # is copied from a caster. The same native ray respects height and roofs.
    def endpoint(identity,where):
        return ActorState(entity_id=identity,display_name='Light ray',team_id='system:light',primary_combatant=False,
            armor_class=0,maximum_hp=1,current_hp=1,position=where,speed_ft=0,movement_remaining_ft=0,
            initiative_bonus=0,dexterity_score=10,proficiency_bonus=0,saving_throws={},resources={},resource_maximums={})
    target=endpoint('light:target',position)
    for obj in engine.state.objects.values():
        profile=(obj.component or {}).get('light_emitter')
        if not profile or obj.destroyed or obj.suppressed or not obj.current_hp:
            continue
        from . import ext
        if any(result is False for result in ext.run_strict('object_light_allowed',engine,obj)):
            continue
        source=endpoint('light:'+obj.object_id,obj.position)
        if not physical_sight(engine,source,target):
            continue
        feet=engine.grid.distance_ft(obj.position,position)
        value=max(value,2 if feet<=profile['bright_ft'] else 1 if feet<=profile['dim_ft'] else 0)
        if value==2:
            break
    return LEVELS[value]


def perceived_level(engine,viewer,seen):
    level=level_at(engine,seen.position)
    if level is None or level=='BRIGHT':
        return level
    from . import senses
    if any(senses._within(engine,viewer,seen,senses.reach(engine,viewer,kind,seen))
           for kind in ('darkvision','truesight')):
        return 'DIM' if level=='DARKNESS' else 'BRIGHT'
    return level


def sight_available(engine,viewer,seen,*,sight_only=False):
    if perceived_level(engine,viewer,seen)!='DARKNESS':
        return True
    if sight_only:
        return False
    from . import senses
    return any(kind in ('blindsight','spiritual_sense') and senses._within(
        engine,viewer,seen,senses.reach(engine,viewer,kind,seen))
        for kind in senses.perception_senses(engine,viewer))
