"""Emergency Stroke: a particular known temporary formula on a real surface.

Uses the Artifact reserve public acquisition_inventory ledger unchanged. The
source-specific crafting effect produces one intent-derived item identity;
formula activation consumes that same identity. No pooled token can change its
formula, become permanent/reusable, be sold as stable goods or enter a project.
"""
from hashlib import sha256
from . import hook
from . import needle
from .talismans import BASE_STROKE, FORMULAS, EMERGENCY, STROKES
from .. import acquisition_inventory as inventory

MARKER = 'condition:typed.emergency_talisman:'
TOOLS = frozenset({'tianxia.mortal.tool.calligrapher_s_supplies', 'tianxia.mortal.gear.ink',
                   'tianxia.mortal.gear.chalk'})


def stroke(action):
    return any(r.get('type') == 'talisman_stroke' and r.get('variant') != 'ready'
               for r in ((getattr(action,'parameters',None) or {}).get('typed') or {}).get('effects') or [])


@hook('compile_action')
def compile_stroke(action, info):
    if not stroke(action):
        return None
    known = [name for name,rank in FORMULAS.items() if rank == 'common'
             and any(str(k).endswith('.'+name) or str(k).upper().endswith('_'+name.upper()) for k in info['owned_ids'])]
    return action.model_copy(update={'parameters': {**action.parameters, 'emergency_instance_model': 1,
        'emergency_known_formulas': known, 'emergency_visible_qi': int('tianxia.talent.talismans.talisman_god_body' in info['owned_ids']), 'typed': {**action.parameters['typed'], 'riders': [], 'manual_inline_choice': True}}})


def methods(engine, actor):
    from ..carry import carrying_of, remaining_quantity
    out = {}
    if any(a.owner_id==actor.entity_id and a.parameters.get('emergency_visible_qi') for a in engine.action_catalog.values()):
        out['visible_qi']='Visible Qi (Talisman God Body)'
    for row in (carrying_of(engine, actor.entity_id) or {}).get('items') or []:
        if row.get('item_id') in TOOLS and remaining_quantity(engine,actor,row) > 0:
            out['item:'+row['key']] = str(row.get('name') or 'Writing supplies')
    # Another visible method is an explicit controller input, not inferred from
    # damage, an inventory name, a resource pool, or an allied relationship.
    from ..fact_consent_admission import combat_records
    for record in combat_records(engine,actor,source=BASE_STROKE,kind='visible_writing_method'):
        if record['subject'] == actor.entity_id:
            out['declared:'+record['receipt_id']] = record['value']
    return out


@hook('candidate_allowed')
def gate_stroke(engine, actor, candidate, action):
    if not (getattr(action,'parameters',None) or {}).get('emergency_instance_model'):
        return None
    from .hand_occupancy import free_hands
    return None if free_hands(engine,actor) and action.parameters.get('emergency_known_formulas') and methods(engine,actor) else False


def surfaces(ctx):
    from ..carry import carrying_of,remaining_quantity
    from ..senses import perceives_cell
    from ..effect_cover import rays
    from ..object_rules import label
    out = {'skin:'+ctx.actor.entity_id: 'Your own skin',
           f'floor:{ctx.actor.position.x},{ctx.actor.position.y},{ctx.actor.position.z}': 'The floor at your feet'}
    for row in (carrying_of(ctx.engine,ctx.actor.entity_id) or {}).get('items') or []:
        if remaining_quantity(ctx.engine,ctx.actor,row)>0:
            out['item:'+row['key']] = str(row.get('name') or 'Carried item')
    from ..target_knowledge import can_see
    for other in ctx.engine.state.actors.values():
        if other.entity_id != ctx.actor.entity_id and other.active and ctx.engine.grid.distance_ft(ctx.actor.position,other.position)<=5 and can_see(ctx.engine,ctx.actor,other):
            out['skin:'+other.entity_id] = other.display_name + ' — skin (their controller must permit the writing)'
    for obj in ctx.engine.state.objects.values():
        if (not obj.destroyed and ctx.engine.grid.distance_ft(ctx.actor.position,obj.position)<=5
                and perceives_cell(ctx.engine,ctx.actor,obj.position)
                and next(rays(ctx.engine,(ctx.actor.position,),(obj.position,),purpose='effect'),None) is not None):
            out[obj.object_id] = label(obj)
    return out


def draw(ctx, eff):
    """Called by the one existing talisman_stroke effect owner after native payment."""
    action = ctx.action
    if not action.parameters.get('emergency_instance_model'):
        return False
    known = action.parameters['emergency_known_formulas']
    names = {f: f.replace('_',' ').title() for f in known}
    formula = needle.ask(ctx.engine,ctx.intent,needle.checkpoint_id(ctx.engine,'emergency_formula',ctx.actor.entity_id),
        ctx.actor,'choice:needle.emergency_formula',known,labels=names,preferred=known[:1],
        name='Emergency Stroke',feature_id=BASE_STROKE,
        prompt='Emergency Stroke: choose one Common formula you know. This temporary talisman lasts one hour or until activated; it cannot be reusable, permanent, stable goods or a project component.')
    available = methods(ctx.engine,ctx.actor)
    method = needle.ask(ctx.engine,ctx.intent,needle.checkpoint_id(ctx.engine,'emergency_method',ctx.actor.entity_id),
        ctx.actor,'choice:needle.emergency_method',list(available),labels=available,preferred=list(available)[:1],
        name='Emergency Stroke',feature_id=BASE_STROKE,prompt='Emergency Stroke: choose your visible writing method. You need a free hand.')
    legal = surfaces(ctx)
    surface = needle.ask(ctx.engine,ctx.intent,needle.checkpoint_id(ctx.engine,'emergency_surface',ctx.actor.entity_id),
        ctx.actor,'choice:needle.emergency_surface',list(legal),labels=legal,preferred=list(legal)[:1],
        name='Emergency Stroke',feature_id=BASE_STROKE,prompt='Emergency Stroke: choose the surface for this particular talisman. The strokes are visibly crude.')
    if not formula or not method or not surface:
        raise ValueError('Emergency Stroke needs a known formula, visible writing method and legal surface; nothing is created.')
    if surface[0].startswith('skin:') and surface[0] != 'skin:'+ctx.actor.entity_id:
        from ..fact_consent_admission import admit_choice
        from .effect_durations import round_token
        subject=ctx.engine.state.actors[surface[0][len('skin:'):]]
        consent=admit_choice(ctx,subject,BASE_STROKE,'writing_surface_permission',ctx.intent.intent_id,
            ['permit_visible_writing'],labels={'permit_visible_writing':'Permit this temporary visible talisman on my skin'},
            prompt=f'Emergency Stroke: {ctx.actor.display_name} wants to draw {names[formula[0]]} on your skin. Permit this particular writing? It is visibly crude and lasts one hour or until activated.',
            expires_on=round_token(ctx.engine,600),readers=(ctx.actor.entity_id,),automatic_options=())
        if consent is None:
            raise ValueError('Emergency Stroke was not permitted on that creature; no talisman or payment is committed.')
    uid = 'emergency.'+sha256((ctx.actor.entity_id+':'+ctx.intent.intent_id).encode()).hexdigest()[:24]
    items = inventory.read(ctx.actor)
    if uid in items:
        raise ValueError('This Emergency Stroke has already created its talisman.')
    profile = inventory.normalize_profile({'source_rule':BASE_STROKE,'authority':ctx.actor.entity_id,
        'source_cl':int(ctx.numbers.get('cl') or 1),'kind':'magic_item','weight_lb':0,'cube_ft':0,
        'recharge':'none','properties':[], 'flags':{'prerequisites_met':1},
        'facts':{'formula':formula[0],'rank':'common','temporary':1,'reusable':0,'permanent':0,
                 'stable_goods':0,'project_component':0,'visibly_crude':1,'surface':surface[0],
                 'writing_method':method[0]}})
    items[uid] = {'id':uid,'name':'Temporary '+names[formula[0]],'owner':ctx.actor.entity_id,'holder':ctx.actor.entity_id,
        'location':'carried' if surface[0].startswith(('skin:','item:')) else 'ground',
        'profile':profile,'charges':0,'spent':0,'surge':0,'version':0,'attuned':0,'bound':0,'quantity':1,
        'inventory_key':uid,'acquisition':{'route':'emergency_stroke','source_rule':BASE_STROKE,
        'intent_id':ctx.intent.intent_id,'sequence':ctx.engine.state.event_sequence+1},
        'temporary_remaining_seconds':3600}
    inventory.write(ctx.engine,ctx.actor,items,ctx.source)
    from .effect_durations import round_token
    ctx.engine._apply_condition(ctx.actor,MARKER+uid,ctx.source,ctx.actor.entity_id,
        expires_on=round_token(ctx.engine,600),data={'item':uid,'label':items[uid]['name']})
    variant=str(eff.get('variant') or 'base')
    if variant in ('base','bonus') and ctx.actor.resources.get(STROKES,0)>0:
        ctx.engine._spend_resource(ctx.actor,STROKES,1,ctx.source)
    from . import note
    note(ctx.engine,ctx.source,ctx.actor,f'Emergency Stroke: {items[uid]["name"]} is drawn on {legal[surface[0]]}. It lasts one hour or until activated and is visibly crude.')
    return True


def available_formula(engine,actor,formula):
    """Live actual temporary instances of exactly this known Common formula."""
    if FORMULAS.get(formula) != 'common':
        return []
    active = {c.data.get('item') for c in actor.conditions.values() if c.condition_id.startswith(MARKER)}
    return [i for uid,i in inventory.read(actor).items() if uid in active and i['quantity']>0
            and i['owner']==actor.entity_id and i['holder']==actor.entity_id
            and i['profile']['facts'].get('formula')==formula]


def consume_formula(engine,actor,formula,source):
    actual = available_formula(engine,actor,formula)
    if not actual:
        return False
    item = actual[0]; items = inventory.read(actor)
    items[item['id']]['quantity']=0
    items[item['id']]['profile']['flags']['consumed']=1
    items[item['id']]['version']+=1
    inventory.write(engine,actor,items,source)
    engine._remove_condition(actor,MARKER+item['id'],source)
    return True


@hook('fact_admission_schema')
def visible_method_schema(session,source,subject,kind):
    if source != BASE_STROKE or kind != 'visible_writing_method':
        return None
    actor = session.state['actors'].get(subject)
    if not actor or not any(a.get('parameters',{}).get('emergency_instance_model') for a in actor['bundle']['action_catalog']):
        return None
    return {'value_type':'text','maximum_seconds':3600,
        'description':'State the actual visible method you can use to write now, such as your blood or another available marking medium. This creates no item or supplies.'}


@hook('event', nested=True)
def expired_instance(engine, event_type, kwargs):
    if event_type != 'CONDITION_REMOVED':
        return
    cid = str((kwargs.get('payload') or {}).get('condition_id') or '')
    if not cid.startswith(MARKER):
        return
    uid = cid[len(MARKER):]
    for actor_id in kwargs.get('target_ids') or ():
        actor = engine.state.actors.get(actor_id)
        if actor is None:
            continue
        items = inventory.read(actor)
        if uid in items and items[uid]['quantity']>0:
            items[uid]['quantity']=0
            items[uid]['profile']['flags']['consumed']=1
            items[uid]['version']+=1
            inventory.write(engine,actor,items,BASE_STROKE)


@hook('journey_encounter_actor')
def continuation_view(actor, session, engine):
    """Transfer finite talismans to the journey clock without editing the fight."""
    if not any(c.condition_id.startswith(MARKER) for c in actor.conditions.values()):
        return None
    out=actor.model_copy(deep=True)
    out.conditions={k:c for k,c in out.conditions.items() if not c.condition_id.startswith(MARKER)
                    and c.condition_id != inventory.CONDITION}
    return out


@hook('journey_encounter_settled')
def import_talismans(session, actor_id, engine, creature):
    items=inventory.read(creature)
    if not any(i.get('acquisition',{}).get('route')=='emergency_stroke' for i in items.values()):
        return
    from .effect_durations import parse_round
    for item in items.values():
        if item.get('acquisition',{}).get('route') != 'emergency_stroke' or item['quantity']<1:
            continue
        marker=next((c for c in creature.conditions.values() if c.condition_id == MARKER+item['id']),None)
        if marker is None:
            item['quantity']=0
            continue
        deadline=parse_round(marker.expires_on)
        if deadline is None:
            raise ValueError('Temporary talisman has no recognized expiry clock.')
        item['temporary_expires_at']=int(session.clock())+max(0,(deadline[0]-engine.state.round_number)*6)
        item['temporary_remaining_seconds']=max(0,item['temporary_expires_at']-int(session.clock()))
    actor=session.state['actors'][actor_id]
    actor['recorded_inventory']=items
    actor['bundle']['acquisition_inventory']=items


@hook('journey_elapsed')
def expire_travel_talismans(session, actor_id, before, elapsed, moving):
    actor=session.state['actors'][actor_id]
    items=actor.get('recorded_inventory') or {}
    for item in items.values():
        if item.get('acquisition',{}).get('route')=='emergency_stroke' and item['quantity']>0:
            deadline=item.get('temporary_expires_at')
            if deadline is not None:
                item['temporary_remaining_seconds']=max(0,deadline-int(session.clock()))
                if deadline<=session.clock():
                    item['quantity']=0
                    item['profile']['flags']['consumed']=1
                    session.emit('TEMPORARY_ITEM_EXPIRED',actor_id,item=item['id'],source=BASE_STROKE)
    if items:
        actor['bundle']['acquisition_inventory']=items


@hook('match_initialize')
def restore_temporary_items(engine):
    from .effect_durations import round_token
    for bundle in engine.typed_bundle_documents:
        items=bundle.get('acquisition_inventory') or {}
        temporary=[i for i in items.values() if i.get('acquisition',{}).get('route')=='emergency_stroke' and i['quantity']>0]
        if not temporary:
            continue
        actor=engine.state.actors.get(bundle['actor_id'])
        if actor is None:
            continue
        inventory.write(engine,actor,items,BASE_STROKE)
        for item in temporary:
            remaining=int(item['temporary_remaining_seconds'])
            if remaining>0 and not any(c.condition_id==MARKER+item['id'] for c in actor.conditions.values()):
                engine._apply_condition(actor,MARKER+item['id'],BASE_STROKE,actor.entity_id,
                    expires_on=round_token(engine,max(1,(remaining+5)//6)),data={'item':item['id'],'label':item['name']})
