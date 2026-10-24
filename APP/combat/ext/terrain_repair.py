"""Action clearing for retained physical terrain with declared suitable tools."""
from . import effect, hook

CLEAR = 'system:combat.repair_terrain'


def options(engine, actor):
    from .. import carry, senses, targeting
    items = (carry.carrying_of(engine, actor.entity_id) or {}).get('items') or []
    held = {item.get('item_id') for item in items if carry.holds(engine, actor, item['key'])}
    pool = {}
    for zone in engine.state.zones.values():
        profile = (zone.trigger_profile or {}).get('profile') or {}
        tools = profile.get('repair_tools') or []
        if not zone.active or not tools or not held.intersection(tools):
            continue
        for cell in zone.affected_cells:
            if (engine._distance_actor_to_cell(actor, cell) <= 5
                    and targeting.line_of_effect(engine, actor, destination=cell)
                    and senses.perceives_cell(engine, actor, cell)):
                key = f'{cell.x}|{cell.y}|{cell.z}'
                entry = pool.setdefault(key, {'cell': cell, 'zones': []})
                if zone not in entry['zones']:
                    entry['zones'].append(zone)
    return pool


@hook('match_start')
def add_repair(engine):
    return ensure_action(engine)


def ensure_action(engine):
    """Public installer for authored or dynamically created repairable terrain."""
    from ..gate2_runtime_models import ActionDefinition
    if not any((((a.parameters.get('typed') or {}).get('zone_spec') or {}).get('profile') or {}).get('repair_tools')
               for a in engine.action_catalog.values()) and not any((z.trigger_profile.get('profile') or {}).get('repair_tools') for z in engine.state.zones.values() if z.active):
        return
    engine.action_catalog[CLEAR] = ActionDefinition(
        source_definition_id=CLEAR, display_name='Clear broken ground', owner_id='*',
        economy='ACTION', resolution_kind='TYPED', target_kind='SELF', parameters={
            'typed': {'effects': [{'type': 'repair_terrain_square'}], 'numbers': {}, 'riders': []},
            'description': 'Use a shovel or masonry tools and your Action to clear one 5-foot square of broken ground within 5 feet.'})


@hook('additional_actions')
def offer_repair(engine, actor):
    # Dynamic terrain survives in MatchState; the runtime action catalog is
    # rebuilt on cold load. Derive its public command from the retained zone
    # before offering it, never from a prior engine instance's installation.
    ensure_action(engine)
    return [CLEAR] if CLEAR in engine.action_catalog and options(engine, actor) else []


@hook('candidate_allowed')
def repair_allowed(engine, actor, candidate, action):
    if action is not None and action.source_definition_id == CLEAR:
        return bool(options(engine, actor))
    return None


@effect('repair_terrain_square')
def repair_square(ctx, row):
    from .needle import ask, checkpoint_id
    from .retained_updates import record_zone_update
    from .. import zones
    pool = options(ctx.engine, ctx.actor)
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'REPAIR_TERRAIN', ctx.actor.entity_id),
                 ctx.actor, 'choice:needle.repair_terrain', list(pool),
                 labels={key: f'Clear square {entry["cell"].x},{entry["cell"].y}' for key, entry in pool.items()},
                 name='Clear broken ground', prompt='Choose one reachable square to clear with your tools and Action.')
    if len(chosen) != 1 or chosen[0] not in pool:
        return
    entry = pool[chosen[0]]
    cell = entry['cell']
    for zone in entry['zones']:
        profile=zone.trigger_profile.get('profile') or {}
        required=int(profile.get('repair_seconds') or 6)
        key=f'{cell.x}|{cell.y}|{cell.z}'
        progress=dict(zone.trigger_profile.get('repair_progress') or {})
        progress[key]=int(progress.get(key,0))+6
        zone.trigger_profile={**zone.trigger_profile,'repair_progress':progress}
        if progress[key]<required:
            record_zone_update(ctx.engine,zone)
            continue
        zone.affected_cells = tuple(p for p in zone.affected_cells if p != cell)
        record_zone_update(ctx.engine, zone)
        if not zone.affected_cells:
            zones.remove(ctx.engine, zone, 'REPAIRED')
    zones.sync_inside(ctx.engine, ctx.source)


@hook('journey_encounter_settled')
def retain_physical_ground(session,aid,engine,actor):
    """Physical repairable ground outlives an encounter, not a second timer."""
    state=session.state['actors'][aid].setdefault('source_states',{})
    rows=[z.model_dump_json() for z in engine.state.zones.values() if z.active and z.owner_id==aid
          and z.duration_rounds is None and (z.trigger_profile.get('profile') or {}).get('repair_tools')]
    if rows:state[CLEAR]={'zones':rows}
    else:state.pop(CLEAR,None)


def journey_zones(session):
    import json
    from ..gate2_runtime_models import ZoneState
    for actor in session.state['actors'].values():
        for raw in actor.get('source_states',{}).get(CLEAR,{}).get('zones',[]):
            yield ZoneState.model_validate(json.loads(raw))


@hook('journey_combat_bundle')
def transfer_physical_ground(bundle,session,aid):
    state=session.state['actors'][aid].get('source_states',{}).get(CLEAR)
    if state:bundle['retained_repairable_terrain']=list(state['zones'])


@hook('match_start',priority=-160)
def restore_physical_ground(engine):
    import json
    from ..gate2_runtime_models import ZoneState
    from .. import zones
    for bundle in getattr(engine,'typed_bundle_documents',()):
        for raw in bundle.get('retained_repairable_terrain',[]):
            zone=ZoneState.model_validate(json.loads(raw))
            if zone.zone_id in engine.state.zones:continue
            zone.created_round=engine.state.round_number
            engine.state.zones[zone.zone_id]=zone
            engine._append_event('ZONE_CREATED',zone.source_definition_id,actor_id=zone.owner_id,
                payload={'zone':zone.model_dump(mode='json'),'retained_instance_update':1})
    if any(b.get('retained_repairable_terrain') for b in getattr(engine,'typed_bundle_documents',())):
        zones.sync_inside(engine,CLEAR)
        ensure_action(engine)


@hook('journey_step')
def physical_ground_cost(session,aid,old,nxt,regions):
    if any(nxt in z.affected_cells and z.trigger_profile.get('difficult')=='all' for z in journey_zones(session)):
        return {'movement_cost':2}


def journey_repair_options(session,aid):
    import json
    from ..gate2_runtime_models import Position
    actor=session.state['actors'][aid]
    if actor['incapacitated'] or session.state['phase']!='travel':return []
    conditions=[json.loads(raw) for raw in actor.get('encounter_snapshot',{}).get('conditions',{}).values()]
    dropped={r.get('data',{}).get('item_key') for r in conditions if r.get('condition_id')=='condition:typed.dropped_item'}
    held={r['item_id'] for r in (actor['bundle'].get('carrying') or {}).get('items',[]) if r['key'] not in dropped}
    position=Position.model_validate(actor['position']);out={}
    for zone in journey_zones(session):
        if not held.intersection((zone.trigger_profile.get('profile') or {}).get('repair_tools',[])):continue
        for cell in zone.affected_cells:
            if session.grid.distance_ft(position,cell)>5 or not session.grid.line_of_sight(position,cell) or not session.grid.line_of_physical_transmission(position,cell):continue
            key=f'{cell.x}|{cell.y}|{cell.z}'
            out[key]={'id':'repair:'+key,'kind':'activity_start','payload':{'source':CLEAR,'parameters':{'cell':cell.model_dump(mode='json')}},
                'label':f"{actor['name']}: clear square {cell.x},{cell.y} with suitable tools; takes {int((zone.trigger_profile.get('profile') or {}).get('repair_seconds',6))} seconds."}
    return list(out.values())


@hook('journey_options')
def repair_journey_menu(session,aid):
    return journey_repair_options(session,aid) or None


@hook('activity_spec')
def repair_activity_spec(session,aid,source,parameters):
    if source!=CLEAR:return
    from ..journey import require
    require(set(parameters)=={'cell'} and any(r['payload']['parameters']==parameters for r in journey_repair_options(session,aid)),
            'Choose nearby broken ground and carry its required suitable tools.')
    from ..gate2_runtime_models import Position
    cell=Position.model_validate(parameters['cell']);key=f'{cell.x}|{cell.y}|{cell.z}'
    zones=[z for z in journey_zones(session) if cell in z.affected_cells]
    seconds=max(max(0,int((z.trigger_profile.get('profile') or {}).get('repair_seconds',6))-int(z.trigger_profile.get('repair_progress',{}).get(key,0))) for z in zones)
    return {'seconds':seconds,'label':f'clear broken ground at {cell.x},{cell.y} with suitable tools'}


@hook('activity_validate')
def repair_activity_validate(session,aid,row):
    if row['source']==CLEAR:
        repair_activity_spec(session,aid,CLEAR,row['parameters'])


@hook('activity_can_continue')
def repair_activity_continues(session,aid,row):
    if row['source']==CLEAR:
        return any(r['payload']['parameters']==row['parameters'] for r in journey_repair_options(session,aid))


@hook('activity_finished')
def repair_activity_finish(session,aid,row):
    if row['source']!=CLEAR:return
    import json
    cell=row['parameters']['cell']
    for actor in session.state['actors'].values():
        state=actor.get('source_states',{}).get(CLEAR)
        if not state:continue
        keep=[]
        for raw in state['zones']:
            zone=json.loads(raw)
            zone['affected_cells']=[p for p in zone['affected_cells'] if p!=cell]
            if zone['affected_cells']:keep.append(json.dumps(zone,sort_keys=True))
        state['zones']=keep
    session.emit('GROUND_REPAIRED',aid,cell=cell,elapsed_seconds=row['worked_seconds'])
