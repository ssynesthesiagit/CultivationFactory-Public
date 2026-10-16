"""Ink Lash's printed declaration choice and native map-object delivery.

Only the owned base row opts in. The existing objects provider rolls attacks,
CL-scaled damage, criticals and object defenses; this module does not duplicate
that implementation. AI uses the first printed type, without inspecting private
defenses. Cosmetic brush shapes and discretionary writing are not damage rules.
"""
from __future__ import annotations

from . import effect, hook

LASH = "INK_BASE_INK_LASH"
CHOICE = "ink_lash_declaration"


@hook("compile_action")
def lash_declaration(action, info):
    typed = (action.parameters or {}).get("typed") or {}
    if LASH not in info["owned_ids"] or typed.get("source") != LASH:
        return None
    effects = list(typed.get("effects") or [])
    if not any(row.get("type") == CHOICE for row in effects):
        effects.insert(0, {"type": CHOICE})
    return action.model_copy(update={"parameters": {
        **action.parameters, "typed": {**typed, "effects": effects},
    }})


@effect(CHOICE, harmful=False)
def declare_lash(ctx, row):
    """Ask before either the creature or object attack roll, including misses."""
    if ctx.typed.get("source") != LASH:
        return
    from .needle import ask
    from .. import object_rules

    obj = ctx.damage_cache.get("_object")
    affected = object_rules.label(obj) if obj is not None else ", ".join(t.display_name for t in ctx.targets)
    chosen = ask(ctx.engine, ctx.intent, "TECHNIQUE_USE", ctx.actor,
        "choice:needle.ink_lash_damage", ["SLASHING", "PSYCHIC"],
        labels={"SLASHING": "Slashing damage", "PSYCHIC": "Psychic damage"},
        preferred=["SLASHING"], name="Ink Lash", feature_id=LASH,
        target_id=obj.object_id if obj is not None else (ctx.targets[0].entity_id if ctx.targets else None),
        prompt=f"Ink Lash: choose Slashing or Psychic damage for your ranged Cultivation Attack against {affected}. "
               "This uses your Action, costs no Cultivation Points, and deals damage only on a hit. "
               "The GM decides any cutting, staining, writing or weakening of unattended objects; this does not automatically open locks or disintegrate objects.")
    ctx.damage_cache[CHOICE] = chosen[0] if chosen else "SLASHING"
    from .needle import checkpoint_id
    shapes=('cutting stroke','hooked character','whip of black ink','vermilion slash','painted fang','line of scripture')
    picked=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'ink_lash_shape',ctx.source),ctx.actor,
        'choice:needle.ink_lash_shape',list(shapes),labels={s:s.capitalize() for s in shapes},name='Ink Lash',
        prompt='Choose the appearance of Ink Lash. This does not change its damage or mechanics.',preferred=[shapes[0]])
    if picked:
        ctx.engine._append_event('PASSIVE_TRIGGERED',ctx.source,actor_id=ctx.actor.entity_id,
            payload={'brush_shape':picked[0],'damage_type':ctx.damage_cache[CHOICE]})


@hook("damage_type_override")
def declared_type(ctx, kinds, targets):
    # Additional fixed-type packets keep their own printed type. This owns
    # only Lash's two-type choice, not every damage row in its activation.
    if ctx.typed.get("source") == LASH and set(kinds) == {"SLASHING", "PSYCHIC"}:
        return ctx.damage_cache.get(CHOICE)
    return None


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
    from .scoped_source_access import access
    owned=next((b.get('ink_sources',[]) for b in ctx.engine.typed_bundle_documents if b['actor_id']==ctx.actor.entity_id),[])
    if LIVING not in owned or not access(ctx.engine,ctx.actor,LIVING):raise ValueError('Living Ink requires its actual acquired source and legal Path practice.')
    if row.get('origin') not in ORIGINS:raise ValueError('Choose a printed Living Ink origin.')
    refresh_owned(ctx.engine,ctx.actor,SUPPLY,ctx.actor.entity_id,ctx.source)
    ctx.engine._apply_condition(ctx.actor,SUPPLY,ctx.source,ctx.actor.entity_id,expires_on=round_token(ctx.engine,600),
        data={'origin':row['origin'],'saleable':0,'label':'Living Ink: sufficient supply; unused ink fades in one hour'})


@hook('compile_action')
def lash_compile(action,info):
    if mechanic_of(action)!=LASH or LASH not in info['owned_ids']:return None
    t=deepcopy(action.parameters['typed'])
    if not any(r.get('type')=='ink_lash_declaration' for r in t['effects']):t['effects'].insert(0,{'type':'ink_lash_declaration'})
    for attack in t['effects']:
        if attack.get('type')=='attack' and not any(r.get('type')=='ink_object_discretion' for r in attack.get('on_hit',[])):attack['on_hit'].append({'type':'ink_object_discretion'})
        if attack.get('type')=='attack':attack.update(object_strike_lifecycle=1,object_target='any',object_before_effects=['living_ink_supply','ink_lash_declaration'],object_on_hit_effects=['ink_object_discretion'])
    t['riders']=[]
    return action.model_copy(update={'target_kind':'ANY_CREATURE','parameters':{**action.parameters,'typed':t,'action_source_fact':{'supernatural':1,'action_kind':'other'}}})






@hook('technique_used')
def ink_medium(ctx):
    owned=next((b.get('ink_sources',[]) for b in ctx.engine.typed_bundle_documents if b.get('actor_id')==ctx.actor.entity_id),[])
    t=ctx.typed
    if LIVING not in owned or not (mechanic_of(ctx.action) in (LASH,PRESS) or t.get('sphere_id')=='tianxia.sphere.ink' or '.talent.ink.' in mechanic_of(ctx.action)):return
    # Actual ink techniques expose their supernatural writing only to observers
    # who can perceive the native source. Explicitly concealed sources opt out.
    if t.get('concealed') or (ctx.action.parameters or {}).get('concealed'):return
    from ..target_knowledge import can_see
    from ..senses import of
    from ..observer_information import publish
    from .effect_durations import token
    for viewer in ctx.engine.state.actors.values():
        spiritual=of(ctx.engine,viewer).get('spiritual_sense')
        sensed=bool(spiritual and ctx.engine.grid.distance_ft(viewer.position,ctx.actor.position)<=int(spiritual['range_ft']) and ctx.engine.grid.line_of_sight(viewer.position,ctx.actor.position))
        if viewer.active and (can_see(ctx.engine,viewer,ctx.actor) or sensed):
            publish(ctx.engine,viewer,ctx.source,ctx.actor,'declaration',
                {'phenomenon':'supernatural calligraphy','source_actor':ctx.actor.entity_id},token('end',ctx.actor.entity_id,ctx.actor.turns_started+1))


@hook('journey_persistent_fields')
def persistent():return ('living_ink','ink_writings')


@hook('journey_options')
def writing_options(session,aid):
    actor=session.state['actors'][aid]
    if session.state['phase']!='travel' or actor['incapacitated'] or LIVING not in actor['bundle'].get('ink_sources',[]):return None
    from .scoped_source_access import scene_access
    if not scene_access(session,aid,LIVING):return None
    # Open text cannot be replaced by invented author content. Manual/model
    # controllers supply these declared inputs; automatic movement never writes
    # an arbitrary message just to fill a required field.
    return [{'id':'ink_write','kind':'ink_write','auto_select':0,
        'label':'Living Ink: write, stain, draw or make calligraphy on an actual touched surface. No Action or CP. Choose permanent ordinary nonmagical writing, or let it fade in one hour; ink cannot be sold.',
        'payload':{'origin':'fingertips','content':'','form':'writing','permanent':0,
            'surface':dict(actor['position'])},
        'inputs':{'content':{'type':'text','required':1,'maximum_length':16000},
            'origin':{'choices':list(ORIGINS)},
            'form':{'choices':['writing','calligraphy','label','sketch','map','signature','stain']},
            'permanent':{'choices':[0,1]},
            'surface':{'type':'document','description':'A touched mapped x/y/z surface, body actor_id, object object_id, or your actual item actor_id/item_key.'}}}]


@hook('journey_command')
def ordinary_writing(session,aid,kind,payload):
    if kind not in ('living_ink','ink_write'):return None
    from ..journey import require
    actor=session.state['actors'][aid]
    require(LIVING in actor['bundle'].get('ink_sources',[]) and not actor['incapacitated'],'An active Living Ink owner must produce this ink.')
    from .scoped_source_access import scene_access
    require(scene_access(session,aid,LIVING),'Body Refining needs actual Inked Body or admitted body-script practice for Living Ink.')
    now=session.clock()
    from .journey_turns import elapsed_deadline,live
    end=elapsed_deadline(session,3600)
    if kind=='living_ink':
        require(set(payload)=={'origin'} and payload['origin'] in ORIGINS,'Choose a printed Living Ink origin.')
        actor['living_ink']={'origin':payload['origin'],**end,'saleable':0}
        session.emit('LIVING_INK_PRODUCED',aid,origin=payload['origin'],deadline=end)
    else:
        require(set(payload)=={'origin','content','form','permanent','surface'},'Supply the actual writing, form, origin, surface and permanence choice.')
        require(payload['origin'] in ORIGINS and payload['form'] in ('writing','calligraphy','label','sketch','map','signature','stain'), 'Choose ordinary writing or a printed artistic use.')
        require(type(payload['content']) is str and 0<len(payload['content'].strip())<=16000 and type(payload['permanent']) is int and payload['permanent'] in (0,1),'Supply bounded nonempty content and a permanence flag.')
        surface=validate_writing_surface(session,aid,payload['surface'])
        serial=len(actor.setdefault('ink_writings',[]))+1
        row={**deepcopy(payload),'surface':surface,'id':f'{aid}:writing:{serial}','owner':aid,'created_num':now.numerator,'created_den':now.denominator,**({} if payload['permanent'] else end),'supernatural':0,'saleable':0}
        actor['ink_writings'].append(row)
        actor['living_ink']={'origin':payload['origin'],**end,'saleable':0}
        session.emit('INK_WRITTEN',aid,writing=deepcopy(row),cost=0,economy='NONE')
    return True


@hook('journey_elapsed')
def ink_elapsed(session,aid,before,seconds,moving):
    actor=session.state['actors'][aid]
    from .journey_turns import live
    if actor.get('living_ink') and not live(session,actor['living_ink']):actor.pop('living_ink',None)
    if 'ink_writings' in actor:
        actor['ink_writings']=[r for r in actor['ink_writings'] if live(session,r)]


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
        'parameters':{**original.parameters,'typed':t,'ink_surface_mark':1,'description':'Action, no CP: mark an object, your equipment, or a touched five-foot surface for one hour. The mark has no special effect by itself and can anchor Ink techniques.'}})]


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
    from .surface_identities import touched_mapped_surfaces
    for point in touched_mapped_surfaces(ctx.engine.grid,ctx.actor.position):
        key=f'ground:{point.x}:{point.y}:{point.z}'
        options[key]={'kind':'ground',**point.model_dump(mode='json'),'label':f'the mapped surface at ({point.x}, {point.y}), {point.z*5} feet high'}
    from .life_state import is_deceased
    for target in ctx.engine.state.actors.values():
        if is_deceased(target) and ctx.engine.grid.distance_ft(ctx.actor.position,target.position)<=5:
            options['corpse:'+target.entity_id]={'kind':'body','actor_id':target.entity_id,'label':target.display_name+'’s corpse'}
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
    if kind in ('body','item'):surface['actor_id']=record.get('actor_id',ctx.actor.entity_id)
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


@hook('candidate_allowed')
def lash_visible_objects(engine,actor,candidate,action):
    if action is None or mechanic_of(action)!=LASH:return None
    from ..senses import perceives_object
    for tid in candidate.target_ids:
        obj=engine.state.objects.get(tid)
        if obj is not None and not perceives_object(engine,actor,obj):return False
    return None


@hook('fact_admission_schema')
def object_discretion_schema(session,source,subject,kind):
    if source!=LASH or kind!='object_treatment':return None
    if LASH not in session.state['actors'][subject]['bundle'].get('ink_sources',[]):return None
    return {'value_type':'document','maximum_seconds':3600,'authority':'table_owner',
        'description':'An explicit Ink Lash treatment for one real unattended object. A committed native hit is still required; this grants neither lockpicking nor disintegration.'}


@hook('fact_admission_validate')
def validate_object_treatment(session,payload,authority):
    if payload['source']!=LASH or payload['kind']!='object_treatment':return None
    from ..journey import require
    from ..journey_assets import JourneyAssetContext
    obj=JourneyAssetContext(session).state.objects.get(payload['scope']);value=payload['value']
    require(authority=='table_owner' and obj is not None and obj.unattended and not obj.destroyed,'Choose an actual live unattended object through the native world-owner path.')
    require(isinstance(value,dict) and set(value)=={'operation','content','ac','threshold'} and value['operation'] in ('cut','stain','write','weaken'),'Choose one printed object treatment with its concrete content or weakening statistics.')
    require(type(value['content']) is str and len(value['content'])<=16000 and type(value['ac']) is int and type(value['threshold']) is int,'Treatments require bounded text and integer statistics.')
    if value['operation'] in ('stain','write'):
        require(bool(value['content'].strip()) and value['ac']==0 and value['threshold']==0,'Supply the actual stain or writing content, without unrelated stat changes.')
    elif value['operation']=='weaken':
        require(bool(value['content'].strip()) and 1<=value['ac']<=obj.ac and 0<=value['threshold']<=int(obj.damage_threshold or 0),'The GM must state the actual weakening and bounded new Armor Class/threshold; this cannot destroy or unlock the object.')
    else:require(value['content']=='' and value['ac']==0 and value['threshold']==0,'Cut uses only Ink Lash’s real native damage, without invented extra damage or destruction.')
    return True


@hook('journey_combat_setup')
def object_discretion_snapshot(bundle,session,aid):
    if LASH not in bundle.get('ink_sources',[]):return None
    from ..fact_consent_admission import read
    from ..journey_assets import JourneyAssetContext
    rows={}
    for oid in JourneyAssetContext(session).state.objects:
        fact=read(session,LASH,aid,'object_treatment',oid,aid)
        if fact:rows[oid]=fact
    return {**bundle,'ink_object_treatments':rows} if rows else None


@effect('ink_object_discretion',harmful=False)
def object_discretion(ctx,row):
    oid=row.get('recipient_object_id');obj=ctx.engine.state.objects.get(oid)
    if obj is None or obj.destroyed or not obj.unattended:return
    bundle=next((b for b in ctx.engine.typed_bundle_documents if b['actor_id']==ctx.actor.entity_id),{})
    fact=bundle.get('ink_object_treatments',{}).get(oid)
    if not fact:return
    value=fact['value'];component=deepcopy(obj.component or {})
    if value['operation'] in ('stain','write'):
        component.setdefault('ink_writings',[]).append({'owner':ctx.actor.entity_id,'source':ctx.source,
            'content':value['content'],'operation':value['operation'],'receipt_id':fact['receipt_id'],
            'sequence':ctx.engine.state.event_sequence+1})
        ctx.engine._update_object(obj.model_copy(update={'component':component}),ctx.source,ctx.actor.entity_id)
    elif value['operation']=='weaken':
        # Native damage, ownership, locks, contents and destruction stay intact.
        component.setdefault('ink_weakening_receipts',[]).append(fact['receipt_id'])
        ctx.engine._update_object(obj.model_copy(update={'component':component,'ac':min(obj.ac,value['ac']),
            'damage_threshold':min(int(obj.damage_threshold or 0),value['threshold'])}),ctx.source,ctx.actor.entity_id)


@hook('fact_admission_schema')
def ordinary_writing_consent(session,source,subject,kind):
    if source!=LIVING or kind!='writing_consent':return None
    if not any(LIVING in a['bundle'].get('ink_sources',[]) for a in session.state['actors'].values()):return None
    return {'value_type':'flag','maximum_seconds':60,'description':'Allow this writer to make ordinary nonmagical writing on your body.'}


def validate_writing_surface(session,aid,raw):
    """Actual touched map/body/item/object identity, shared by writing inputs."""
    from ..journey import require
    from ..gate2_runtime_models import Position
    from .surface_identities import mapped_surface,position
    from ..journey_equipment import context
    from ..journey_assets import JourneyAssetContext
    from .. import carry
    require(isinstance(raw,dict),'Choose an actual writing surface.')
    record={'kind':'fixed',**raw} if set(raw)=={'x','y','z'} else deepcopy(raw)
    kind=record.get('kind');native=context(session);writer=native.state.actors[aid]
    if kind=='fixed':
        require(set(record)=={'kind','x','y','z'} and all(type(record[k]) is int and record[k]>=0 for k in ('x','y','z')),'A fixed surface needs mapped integer coordinates.')
        point=Position(x=record['x'],y=record['y'],z=record['z'])
        require(mapped_surface(session.grid,point),'Writing requires an actual floor, wall or roof surface rather than empty air.')
    elif kind=='item':
        require(set(record)=={'kind','actor_id','item_key'} and record['actor_id']==aid,'Choose your own actual item; another creature’s inventory is not yours to write on.')
        item=carry.item_of(carry.carrying_of(native,aid),key=record['item_key'])
        require(item is not None and carry.remaining_quantity(native,writer,item)>0,'The writing medium must be an actual remaining acquired item.')
        point=position(native,record)
    elif kind=='object':
        require(set(record)=={'kind','object_id'},'Choose one actual object identity.')
        obj=JourneyAssetContext(session).state.objects.get(record['object_id'])
        require(obj is not None and not obj.destroyed and (obj.unattended or obj.owner_id==aid),'Choose a live unattended or controlled object, not an invented medium.')
        point=obj.position
    elif kind=='body':
        require(set(record)=={'kind','actor_id'} and record['actor_id'] in native.state.actors,'Choose an actual willing creature or corpse.')
        target=native.state.actors[record['actor_id']]
        from .life_state import is_deceased
        if target.entity_id!=aid and not is_deceased(target):
            from ..fact_consent_admission import read
            consent=read(session,LIVING,target.entity_id,'writing_consent',aid,aid)
            require(consent is not None and consent['value']==1,'This creature must allow this writer’s ordinary body writing through its own native consent input.')
        point=target.position
    else:raise ValueError('Choose a mapped surface, actual item, object or body identity.')
    require(point is not None and session.grid.distance_ft(writer.position,point)<=5 and session.grid.line_of_physical_transmission(writer.position,point),'Touch the actual writing surface through a clear physical path.')
    return record


@hook('journey_view')
def private_writing_artifacts(state,viewer_id):
    if not any('ink_writings' in a for a in state['actors'].values()):return None
    out=deepcopy(state);out.pop('replay_base',None);out.pop('command_journal',None)
    for aid,actor in out['actors'].items():
        if aid!=viewer_id:actor.pop('ink_writings',None)
    out['events']=[e for e in out['events'] if e['kind']!='INK_WRITTEN' or e['actor_id']==viewer_id]
    return out
