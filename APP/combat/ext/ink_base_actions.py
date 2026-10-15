"""Living Ink production/writing and Ink Lash's declaration, objects and medium.

Ordinary writing is native journey input with actual content and a mapped surface;
it is a persisted nonmagical artifact, never a saleable inventory commodity.
Combat medium is produced as part of an Ink action; unused supply has the normal
one-hour clock. No Ink ownership means no buttons, supply or observations.
"""
from copy import deepcopy
from . import hook,effect
from .ability_source import mechanic_of
LIVING='INK_BASE_LIVING_INK'; LASH='INK_BASE_INK_LASH'; PRESS='INK_BASE_PRESS_MARK'
SUPPLY='condition:typed.living_ink_supply'
ORIGINS=('fingertips','brush','weapon','mouth','blood','sleeve','shadow','focus')


@hook('compile_bundle')
def ownership(bundle,info):
    ids=set(info['owned_ids']) & {LIVING,LASH,PRESS}
    if not ids:return None
    return {**bundle,'ink_sources':sorted(ids)}


@hook('compile_actions')
def produce_actions(info):
    if LIVING not in info['owned_ids']:return None
    from ..gate2_runtime_models import ActionDefinition,EconomyKind
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.living_ink.{origin}",display_name='Living Ink: from '+origin,
        owner_id=info['actor_id'],economy=EconomyKind.NONE,resolution_kind='TYPED',target_kind='SELF',
        parameters={'description':'No action or CP: produce sufficient Living Ink. Unused ink fades in one hour and cannot be sold.',
            'typed':{'source':LIVING,'numbers':dict(info['numbers']),'riders':[],
                'effects':[{'type':'living_ink_supply','origin':origin}]}}) for origin in ORIGINS]


@effect('living_ink_supply',harmful=False)
def supply(ctx,row):
    from .effect_durations import round_token
    from .condition_ownership import refresh_owned
    if row.get('origin') not in ORIGINS:raise ValueError('Choose a printed Living Ink origin.')
    refresh_owned(ctx.engine,ctx.actor,SUPPLY,ctx.actor.entity_id,ctx.source)
    ctx.engine._apply_condition(ctx.actor,SUPPLY,ctx.source,ctx.actor.entity_id,expires_on=round_token(ctx.engine,600),
        data={'origin':row['origin'],'saleable':0,'label':'Living Ink: sufficient supply; unused ink fades in one hour'})


@hook('compile_action')
def lash_compile(action,info):
    if mechanic_of(action)!=LASH or LASH not in info['owned_ids']:return None
    t=deepcopy(action.parameters['typed']); t['effects'].insert(0,{'type':'ink_lash_declaration'})
    t['riders']=[]
    return action.model_copy(update={'target_kind':'ANY_CREATURE','parameters':{**action.parameters,'typed':t,'action_source_fact':{'supernatural':1,'action_kind':'other'}}})


@effect('ink_lash_declaration',harmful=False)
def declare_lash(ctx,row):
    from .needle import ask,checkpoint_id
    selected=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'ink_lash_type',ctx.source),ctx.actor,
        'choice:needle.ink_lash_type',['slashing','psychic'],labels={'slashing':'Slashing','psychic':'Psychic'},
        name='Ink Lash',prompt='Ink Lash: choose Slashing or Psychic damage before the attack roll. Action; no CP.',preferred=['slashing'])
    if selected:ctx.damage_cache['ink_lash_type']=selected[0]
    shapes=('cutting stroke','hooked character','whip of black ink','vermilion slash','painted fang','line of scripture')
    picked=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'ink_lash_shape',ctx.source),ctx.actor,
        'choice:needle.ink_lash_shape',list(shapes),labels={s:s.capitalize() for s in shapes},name='Ink Lash',
        prompt='Choose the appearance of Ink Lash. This does not change its damage or mechanics.',preferred=[shapes[0]])
    if picked:ctx.engine._append_event('PASSIVE_TRIGGERED',ctx.source,actor_id=ctx.actor.entity_id,payload={'brush_shape':picked[0],'damage_type':selected[0] if selected else 'slashing'})


@hook('attack_damage_types')
def lash_type(ctx,attack,kinds):
    if mechanic_of(ctx.action)==LASH and ctx.damage_cache.get('ink_lash_type'):return [ctx.damage_cache['ink_lash_type']]
    return None


@hook('technique_used')
def ink_medium(ctx):
    owned=next((b.get('ink_sources',[]) for b in ctx.engine.typed_bundle_documents if b.get('actor_id')==ctx.actor.entity_id),[])
    t=ctx.typed
    if LIVING not in owned or not (mechanic_of(ctx.action) in (LASH,PRESS) or t.get('sphere_id')=='tianxia.sphere.ink' or '.talent.ink.' in mechanic_of(ctx.action)):return
    # Actual ink techniques expose their supernatural writing only to observers
    # who can perceive the native source. Explicitly concealed sources opt out.
    if t.get('concealed') or (ctx.action.parameters or {}).get('concealed'):return
    from ..target_knowledge import can_see
    from ..observer_information import publish
    from .effect_durations import token
    for viewer in ctx.engine.state.actors.values():
        if viewer.active and can_see(ctx.engine,viewer,ctx.actor):
            publish(ctx.engine,viewer,ctx.source,ctx.actor,'declaration',
                {'phenomenon':'supernatural calligraphy','source_actor':ctx.actor.entity_id},token('end',ctx.actor.entity_id,ctx.actor.turns_started+1))


@hook('journey_persistent_fields')
def persistent():return ('living_ink','ink_writings')


@hook('journey_command')
def ordinary_writing(session,aid,kind,payload):
    if kind not in ('living_ink','ink_write'):return None
    from ..journey import require
    actor=session.state['actors'][aid]
    require(LIVING in actor['bundle'].get('ink_sources',[]) and not actor['incapacitated'],'An active Living Ink owner must produce this ink.')
    now=int(session.clock())
    if kind=='living_ink':
        require(set(payload)=={'origin'} and payload['origin'] in ORIGINS,'Choose a printed Living Ink origin.')
        actor['living_ink']={'origin':payload['origin'],'expires_at':now+3600,'saleable':0}
        session.emit('LIVING_INK_PRODUCED',aid,origin=payload['origin'],expires_at=now+3600)
    else:
        require(set(payload)=={'origin','content','form','permanent','surface'},'Supply the actual writing, form, origin, surface and permanence choice.')
        require(payload['origin'] in ORIGINS and payload['form'] in ('writing','calligraphy','label','sketch','map','signature','stain'), 'Choose ordinary writing or a printed artistic use.')
        require(type(payload['content']) is str and 0<len(payload['content'].strip())<=16000 and type(payload['permanent']) is int and payload['permanent'] in (0,1),'Supply bounded nonempty content and a permanence flag.')
        surface=payload['surface']; pos=actor['position']
        require(isinstance(surface,dict) and set(surface)=={'x','y','z'} and all(type(v) is int and v>=0 for v in surface.values())
                and session.grid.in_bounds((surface['x'],surface['y'])) and max(abs(surface[k]-pos.get(k,0)) for k in surface)<=1,'Choose a mapped surface within touch.')
        serial=len(actor.setdefault('ink_writings',[]))+1
        row={**deepcopy(payload),'id':f'{aid}:writing:{serial}','owner':aid,'created_at':now,'expires_at':0 if payload['permanent'] else now+3600,'supernatural':0,'saleable':0}
        actor['ink_writings'].append(row)
        actor['living_ink']={'origin':payload['origin'],'expires_at':now+3600,'saleable':0}
        session.emit('INK_WRITTEN',aid,writing=deepcopy(row),cost=0,economy='NONE')
    return True


@hook('journey_elapsed')
def ink_elapsed(session,aid,before,seconds,moving):
    actor=session.state['actors'][aid];now=session.clock()
    if actor.get('living_ink',{}).get('expires_at',10**30)<=now:actor.pop('living_ink',None)
    if 'ink_writings' in actor:
        actor['ink_writings']=[r for r in actor['ink_writings'] if not r['expires_at'] or r['expires_at']>now]


@hook('presentation_hidden_conditions')
def private_ink(engine,actor):
    return [iid for iid,c in actor.conditions.items() if c.condition_id in ('condition:information.reading',) or c.data.get('concealed')]

SURFACE_MARK='condition:typed.ink_surface_mark'


@hook('compile_actions')
def mark_surfaces(info):
    if PRESS not in info['owned_ids']:return None
    original=next((a for a in info['actions'] if mechanic_of(a)==PRESS),None)
    if original is None:return None
    t=deepcopy(original.parameters['typed']);t.update(effects=[{'type':'ink_mark_surface'}],riders=[])
    return [original.model_copy(update={'source_definition_id':original.source_definition_id+'.surface',
        'display_name':'Press Mark: object or surface','target_kind':'SELF',
        'parameters':{**original.parameters,'typed':t,'description':'Action, no CP: mark an object, your equipment, or a touched five-foot surface for one hour. The mark has no special effect by itself and can anchor Ink techniques.'}})]


def mark_endpoints(engine,owner):
    """Public Ink source endpoints; location follows native body/item/object identity."""
    from .surface_identities import position
    from ..typed_executor import mark_condition_id
    rows=[]
    for target in engine.state.actors.values():
        for c in target.conditions.values():
            if c.condition_id==mark_condition_id('ink_mark',owner.entity_id):
                rows.append({'id':c.instance_id,'position':target.position,'target_id':target.entity_id})
    for c in owner.conditions.values():
        if c.condition_id==SURFACE_MARK:
            point=position(engine,c.data['surface'])
            if point is not None:rows.append({'id':c.instance_id,'position':point,'surface':deepcopy(c.data['surface'])})
    return rows


@effect('ink_mark_surface',harmful=False)
def mark_surface(ctx,row):
    from .. import carry
    from .glass_surfaces import choices
    from .needle import ask,checkpoint_id
    from .effect_durations import round_token
    options=choices(ctx.engine,ctx.actor)
    options.pop('body',None)
    for obj in ctx.engine.state.objects.values():
        if not obj.destroyed and ctx.engine.grid.distance_ft(ctx.actor.position,obj.position)<=5 and ctx.engine.grid.line_of_physical_transmission(ctx.actor.position,obj.position):
            options['object:'+obj.object_id]={'kind':'object','object_id':obj.object_id,'label':str((obj.component or {}).get('name') or obj.object_kind)}
    for item in (carry.carrying_of(ctx.engine,ctx.actor.entity_id) or {}).get('items',[]):
        if carry.holds(ctx.engine,ctx.actor,item['key']):options['item:'+item['key']]={'kind':'item','item_key':item['key'],'label':item.get('name','Your item')}
    selected=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'ink_surface',ctx.source),ctx.actor,
        'choice:needle.ink_surface',list(options),labels={k:v['label'] for k,v in options.items()},name='Press Mark',
        prompt='Press Mark: choose the object, equipment or touched five-foot surface. Action, no CP; lasts one hour and has no special effect by itself.')
    if not selected:return
    record=options[selected[0]];kind=record['kind']
    surface={'kind':'fixed' if kind=='ground' else kind}
    if kind in ('body','item'):surface['actor_id']=ctx.actor.entity_id
    if kind=='item':surface['item_key']=record['item_key']
    if kind=='object':surface['object_id']=record['object_id']
    if kind=='ground':surface.update({k:record[k] for k in ('x','y','z')})
    from .ink_second_pass import owned
    hours=8 if owned(ctx.engine,ctx.actor,'master') else 1
    ctx.engine._apply_condition(ctx.actor,SURFACE_MARK,ctx.source,ctx.actor.entity_id,expires_on=round_token(ctx.engine,600*hours),
        data={'surface':surface,'label':'Ink Mark on '+record['label']})
    cap=max(1,int(ctx.numbers['pb'])+int(ctx.numbers['key_mod']))+(2 if owned(ctx.engine,ctx.actor,'master') else 0)
    from ..typed_executor import mark_condition_id
    from .condition_ownership import remove_instance
    marks=[(c.applied_sequence,target,iid) for target in ctx.engine.state.actors.values() for iid,c in target.conditions.items()
        if c.condition_id==mark_condition_id('ink_mark',ctx.actor.entity_id) or (target is ctx.actor and c.condition_id==SURFACE_MARK)]
    for _,target,iid in sorted(marks,key=lambda r:r[0])[:-cap]:remove_instance(ctx.engine,target,iid,ctx.source)


@hook('mark_applied')
def combined_ink_capacity(ctx,name,subject):
    if name!='ink_mark':return
    from ..typed_executor import mark_capacity,mark_condition_id
    from .condition_ownership import remove_instance
    cap=mark_capacity(ctx,name)
    if not cap:return
    marks=[(c.applied_sequence,target,iid) for target in ctx.engine.state.actors.values() for iid,c in target.conditions.items()
        if c.condition_id==mark_condition_id(name,ctx.actor.entity_id) or (target is ctx.actor and c.condition_id==SURFACE_MARK)]
    for _,target,iid in sorted(marks,key=lambda r:r[0])[:-cap]:remove_instance(ctx.engine,target,iid,ctx.source)


@hook('compile_action')
def technique_medium(action,info):
    if LIVING not in info['owned_ids']:return None
    mid=mechanic_of(action)
    if mid in (LIVING,) or not (mid in (LASH,PRESS) or '.talent.ink.' in mid):return None
    t=deepcopy(action.parameters['typed'])
    if not any(r.get('type')=='living_ink_supply' for r in t.get('effects',[])):
        t['effects'].insert(0,{'type':'living_ink_supply','origin':'fingertips'})
    return action.model_copy(update={'parameters':{**action.parameters,'typed':t}})
