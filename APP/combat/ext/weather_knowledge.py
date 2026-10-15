"""Read the Sky and the object half of Cloud Shroud.

Native Weather placements are read only through public owner APIs. Sealed GM
weather inputs describe the larger world, with explicit coverage and air access.
Neither a missing field nor a failed reading establishes clear weather.
"""
from . import hook, effect
from . import weather_signs
from .knowledge_readings import SKY, choice
from ..encounter_sources import facts
from ..observer_information import publish

SHROUD='WEATHER_BASE_CLOUD_SHROUD'


def weather_answers(battlefield, *, careful=False, reader_cl=None):
    data=facts(battlefield,'scene')
    def value(key):
        return data.get('weather.'+key,{}).get('value')
    if careful:
        forecast=value('forecast')
        if (value('interference') is not False or any(value(k) is True for k in ('sealed','divine','narrative'))
                or reader_cl is not None and (value('cultivation_cl') or 0)>reader_cl
                or (value('forecast_radius_ft') or 0)<26400):
            forecast='Unknown: the prediction is not established or is obstructed.'
        return {'Natural weather for the next 48 hours within 5 miles':forecast or 'Unknown'}
    if value('air') is not True:
        return {'Weather':'Unknown: outdoor air access has not been established.'}
    return {
        'Current categories and severity within 1 mile':value('categories') if (value('categories_radius_ft') or 0)>=5280 else 'Unknown',
        'Weather origin and Concentration within 300 feet':value('origin') if (value('origin_radius_ft') or 0)>=300 else 'Unknown',
    }


@hook('compile_action')
def compile_sky(action, info):
    typed=action.parameters.get('typed') or {}
    if typed.get('source')==SKY and SKY in info['owned_ids']:
        return action.model_copy(update={'target_kind':'SELF','parameters':{**action.parameters,
            'typed':{**typed,'effects':[{'type':'weather_reading'}],'riders':[]}}})
    return None


@effect('weather_reading')
def immediate(ctx, spec):
    answers=weather_answers(ctx.engine.battlefield_document,reader_cl=ctx.numbers.get('cl'))
    from .weather_fields import fields,signs
    native=[]
    for field in fields(ctx.engine):
        distance=ctx.engine.grid.distance_ft(ctx.actor.position,field.center)
        if distance<=5280:
            native.append({'categories':{weather_signs.CATEGORIES[s]:level for s,level in signs(field).items()},
                'origin':'cultivation-made','concentration':int(field.concentration_link) if distance<=300 else 'Unknown'})
    if native:
        answers['Gathered weather in this scene']=native
    publish(ctx.engine,ctx.actor,ctx.action.source_definition_id,ctx.actor,'answer',
        {'ability':'Read the Sky','answers':answers},'UNTIL_REMOVED')


def active_signs(engine):
    """Printed active-sign alternatives, across the actual scene."""
    from .weather_mantle import all_mantles
    from .weather_shroud import shrouds, sign_of
    from .weather_fields import fields, signs
    result=set()
    for actor in engine.state.actors.values():
        result.update(c.data.get('sign') for c in all_mantles(actor))
        result.update(sign_of(c) for c in shrouds(actor))
    for obj in engine.state.objects.values():
        shroud=(obj.component or {}).get('cloud_shroud')
        if shroud:
            owner=engine.state.actors.get(shroud['owner_id'])
            from ..concentration import copies
            if owner and shroud['started_sequence'] in copies(owner,shroud['source_id']):
                result.add(shroud['sign'])
    for field in fields(engine):
        result.update(sign for sign,level in signs(field).items() if level>=1)
    categories=facts(engine.battlefield_document,'scene').get('weather.categories',{}).get('value',{})
    result.update(sign for sign,category in weather_signs.CATEGORIES.items() if categories.get(category,0)>=1)
    return [sign for sign in weather_signs.names() if sign in result]


@hook('technique_final')
def battle_reading(ctx):
    from ..alternative_payments import owned
    if ctx.typed.get('sphere')!=weather_signs.SPHERE or not owned(ctx.engine,ctx.actor,SKY):
        return
    selected=choice(ctx,'battle_sign',active_signs(ctx.engine),optional=True,
        labels={s:weather_signs.sign(s)['name'] for s in active_signs(ctx.engine)},
        prompt='Read the Sky: identify one active Weather Sign in this scene, without an action or CP.')
    if selected:
        publish(ctx.engine,ctx.actor,ctx.action.source_definition_id,ctx.actor,'answer',
            {'ability':'Read the Sky — Battle Reading','sign':selected[0]},'UNTIL_REMOVED')


@hook('compile_actions')
def object_shroud(info):
    if SHROUD not in info['owned_ids']:
        return None
    base=next((a for a in info['actions'] if (a.parameters.get('typed') or {}).get('source')==SHROUD),None)
    if base is None:
        return None
    return [base.model_copy(update={'source_definition_id':base.source_definition_id+'#object',
        'display_name':'Cloud Shroud (unattended object)','target_kind':'OBJECT','range_ft':60,
        'parameters':{**base.parameters,'weather_object_shroud':1,
            'typed':{**base.parameters['typed'],'effects':[], 'duration':{'kind':'minutes','amount':1,'concentration':True}}}})]


@hook('empty_action_implemented')
def object_shroud_implemented(action, info):
    return True if action.parameters.get('weather_object_shroud') else None


@hook('object_targets')
def shroud_objects(engine, actor, action):
    if not action.parameters.get('weather_object_shroud'):
        return []
    return [obj.object_id for obj in engine.state.objects.values() if obj.unattended and not obj.destroyed]


@hook('object_action')
def shroud_object(engine, actor, action, obj, candidate, intent):
    if not action.parameters.get('weather_object_shroud'):
        return None
    if action.owner_id!=actor.entity_id or not obj.unattended or obj.destroyed:
        raise ValueError('Cloud Shroud requires an unattended object.')
    from ..typed_executor import Context
    from .weather_shroud import sign_menu
    ctx=Context(engine,actor,action,intent,action.parameters['typed'],[])
    # sign_menu needs only a display name and stable identity, not a creature.
    from types import SimpleNamespace
    from ..object_rules import label
    target=SimpleNamespace(entity_id=obj.object_id,display_name=label(obj))
    sign=sign_menu(ctx,target,'Cloud Shroud')
    if not sign:
        raise ValueError('Choose a Weather Sign you know.')
    previous=(obj.component or {}).get('cloud_shroud')
    if previous and previous['owner_id']==actor.entity_id:
        from ..concentration import end_copy
        end_copy(engine,actor,previous['started_sequence'],'REPLACED')
    engine._start_concentration(actor,action.source_definition_id)
    data=facts(engine.battlefield_document,obj.object_id)
    vulnerable=data.get('weather.vulnerable.'+sign,{}).get('value')
    outcome=data.get('weather.object_effect.'+sign,{}).get('value')
    # The GM supplies a concrete object interaction, never an approve/done
    # receipt. Unknown vulnerability produces weather, not invented harm.
    component={**(obj.component or {}),'cloud_shroud':{'sign':sign,'owner_id':actor.entity_id,
        'source_id':action.source_definition_id,'expiry_round':engine.state.round_number+10,'expiry_slot':engine.state.current_slot_index,
        'started_sequence':actor.concentration.started_sequence if actor.concentration else 0,
        'vulnerable':'unknown' if vulnerable is None else int(vulnerable)}}
    updates={'component':component}
    if vulnerable is True and outcome:
        response={'state':outcome} if isinstance(outcome,str) else outcome
        if response.get('state'):
            component['weather_state']=response['state']
        if response.get('state')=='doused' or response.get('ignited') is False:
            updates.update(ignited=False,ignition_source_definition_id=None,ignition_actor_id=None,ignition_sequence=None)
        if response.get('ignited') is True:
            from .objects import ignite
            ignite(engine,obj.object_id,action.source_definition_id,actor.entity_id)
            obj=engine.state.objects[obj.object_id]
        if response.get('destination'):
            from ..gate2_runtime_models import Position
            from ..object_geometry import target_cells
            from ..asset_anchor_runtime import legal_placement
            from . import run_strict
            end=Position.model_validate(response['destination'])
            dx,dy,dz=end.x-obj.position.x,end.y-obj.position.y,end.z-obj.position.z
            steps=max(abs(dx),abs(dy),abs(dz))
            for i in range(1,steps+1):
                point=Position(x=obj.position.x+round(dx*i/steps),y=obj.position.y+round(dy*i/steps),z=obj.position.z+round(dz*i/steps))
                moved=obj.model_copy(update={'position':point})
                if not legal_placement(engine,target_cells(engine,moved),obj.height_ft or 5,ignore=(obj.object_id,)):
                    raise ValueError('The declared object weather movement has a blocked route.')
            if False not in run_strict('object_operation_gate',engine,actor,obj,'move',ctx.source,intent):
                updates['position']=end
    engine._update_object(obj.model_copy(update=updates),action.source_definition_id,actor.entity_id)
    if vulnerable is True and isinstance(outcome,dict) and outcome.get('damage'):
        from .objects import deal
        damage=outcome['damage']
        deal(engine,actor,engine.state.objects[obj.object_id],[(damage['amount'],damage['type'])],action.source_definition_id)
    battle_reading(ctx)
    return True


@hook('turn_start')
def expire_object_shrouds(engine, actor):
    for obj in list(engine.state.objects.values()):
        shroud=(obj.component or {}).get('cloud_shroud')
        if not shroud:
            continue
        owner=engine.state.actors.get(shroud['owner_id'])
        from ..concentration import copies,end_copy
        if obj.destroyed or (engine.state.round_number>shroud['expiry_round'] or engine.state.round_number==shroud['expiry_round'] and engine.state.current_slot_index>=shroud.get('expiry_slot',0)) or owner is None or shroud['started_sequence'] not in copies(owner,shroud['source_id']):
            component=dict(obj.component);component.pop('cloud_shroud')
            engine._update_object(obj.model_copy(update={'component':component}),shroud['source_id'],shroud['owner_id'])
            if owner:
                end_copy(engine,owner,shroud['started_sequence'],'DURATION_END')


@hook('acquisition_choices')
def weather_starting_choice(source_id, sheet):
    if source_id==weather_signs.SPHERE:
        return [{'key':'weather_starting_sign','source_id':SHROUD,'count':1,
                 'options':weather_signs.names(),'labels':{s:weather_signs.sign(s)['name'] for s in weather_signs.names()},'label':'Choose the Weather Sign talent you learn with Weather'}]


@hook('compile_action')
def learned_signs(action, info):
    typed=action.parameters.get('typed') or {}
    if typed.get('source')!=SHROUD or SHROUD not in info['owned_ids']:
        return None
    acquisition=(info['owner_sheet'].get('acquisition_choices') or {}).get(weather_signs.SPHERE,{})
    starting=acquisition.get('weather_starting_sign',[])
    selected=starting+acquisition.get('weather_additional_signs',[])
    if selected:
        from ..acquisition_choices import validate
        validate(weather_signs.SPHERE,info['owner_sheet'],{'weather_starting_sign':starting}) if starting else None
        return action.model_copy(update={'parameters':{**action.parameters,'typed':{**typed,'known_weather_signs':selected,'weather_starting_sign_pending':int(not starting)}}})
    return None


@hook('event')
def object_concentration_changed(engine, event_type, kwargs):
    if event_type in {'CONCENTRATION_ENDED','CONCENTRATION_STARTED','OBJECT_UPDATED'}:
        expire_object_shrouds(engine,None)


@hook('acquisition_source_options')
def additional_weather_signs(sheet):
    from ..table_advance import known
    have=known(sheet)
    selections=(sheet.get('acquisition_choices') or {}).get(weather_signs.SPHERE,{})
    learned=set(selections.get('weather_starting_sign',[]))|set(selections.get('weather_additional_signs',[]))
    return [{'id':'weather.sign.'+sign,'name':weather_signs.sign(sign)['name'],'sphere':'Weather',
        'source_heading':'Weather Sign talents','source_sha256':'67f67275889467d43605debaa0c05dc5ddde9ba079222819aabea27c66167775',
        'source_id':weather_signs.SPHERE,'key':'weather_additional_signs','value':sign,
        'legal':weather_signs.SPHERE in have['spheres'] and sign not in learned,
        'reasons':[] if weather_signs.SPHERE in have['spheres'] and sign not in learned else ['Learn Weather first; each Weather Sign can be learned once.']}
        for sign in weather_signs.names()] if weather_signs.SPHERE in have['spheres'] else []


@hook('object_detail_lines')
def weather_object_details(engine,obj):
    data=obj.component or {}
    lines=[]
    if data.get('weather_state'):
        lines.append(str(data['weather_state']).capitalize())
    shroud=data.get('cloud_shroud')
    if shroud:
        lines.append('Cloud Shroud: '+weather_signs.sign(shroud['sign'])['name'])
    return lines or None
