"""Opt-in unoccupied-cell placement shared by summons, objects and terrain.

An action with CELL targeting and parameters.cell_placement={} opts in. Range
and sight apply to the chosen anchor; the full footprint must fit and be empty.
The catalogue retains this contract, so old SELF summons keep their behavior.
"""
from .footprints import ActorFootprintDefinition


def profile(engine, actor, action):
    if action.target_kind != 'CELL' or 'cell_placement' not in action.parameters:
        return None
    rule = action.parameters['cell_placement']
    if not isinstance(rule, dict):
        raise ValueError('cell_placement requires a mapping')
    group = action.parameters.get('summon_group')
    creature = None
    if group:
        from .summons import owned_by
        creatures = list(owned_by(engine, actor.entity_id, group))
        if len(creatures) != 1:
            raise ValueError('one chosen cell requires exactly one summoned creature')
        creature = creatures[0]
        footprint = engine._footprint(creature)
    else:
        if 'copy_owner_dimensions' in rule and type(rule['copy_owner_dimensions']) is not bool:
            raise ValueError('copy_owner_dimensions must be a boolean')
        own=engine._footprint(actor) if rule.get('copy_owner_dimensions') else None
        width, height = (own.width_cells,own.height_cells) if own is not None else (rule.get('width_cells', 1), rule.get('height_cells', 1))
        if any(type(n) is not int or n<1 or (own is None and n>8) for n in (width, height)):
            raise ValueError('placement footprint dimensions must be integers from 1 to 8')
        footprint = ActorFootprintDefinition.rectangle(width, height,
            footprint_id='placement:footprint', source_definition_id=action.source_definition_id)
    return footprint, creature


def legal(engine, actor, action, position, *, placement=None, preview=False):
    """Preview uses directly known occupancy; execution checks every real body.

    A remembered square is an aim, not a confirmed obstacle. Unknown occupants
    may invalidate an accepted placement without revealing their identity.
    """
    placement = profile(engine, actor, action) if placement is None else placement
    if placement is None or position is None or action.range_ft is None or position.z < 0:
        return False
    footprint, creature = placement
    if (engine._effect_distance_to_cell(actor, position) > action.range_ft
            or not engine._line_of_sight_actor_to_cell(actor, position)):
        return False
    from .target_knowledge import actors_for, knowledge
    actors = actors_for(engine, actor) if preview else engine.state.actors.values()
    occupied = {cell for other in actors
                if other.active and (creature is None or other.entity_id != creature.entity_id)
                and (not preview or (known := knowledge(engine, actor, engine.state.actors[other.entity_id])) is not None
                     and known.mode == 'DIRECT') for cell in engine._actor_volume(other)}
    return engine.grid.volume_legal(position, footprint=footprint, occupied_cells=occupied)


def metadata(engine, actor, action, *, placement=None):
    footprint, creature = profile(engine, actor, action) if placement is None else placement
    return {'cell_placement': {'width_cells': footprint.width_cells,
                              'height_cells': footprint.height_cells},
            'expected_damage': int(action.parameters.get('expected_damage') or 0)}


def record(engine, actor, action, position):
    """Record the accepted anchor. Owning effects record their own state changes."""
    engine._append_event('PASSIVE_TRIGGERED', action.source_definition_id, actor_id=actor.entity_id,
        payload={'log': f'{actor.display_name} chooses an unoccupied space for {action.display_name}.',
                 'placement': position.model_dump(mode='json'), **metadata(engine, actor, action)})

def support_levels(engine,actor,action,levels):
    """Opt-in native support planes and finite ranged airspace for placement.

    The Mason owner's placement_surfaces flag keeps its exact support-plane
    semantics. placement_airspace additionally enumerates integer elevations
    within the action's actual finite range of the activation volume. Neither
    flag grants support, flight, sight, occupancy or permission. Missing flags
    return the original sequence and preserve default iteration/identities.
    """
    surfaces=action.parameters.get('placement_surfaces',False)
    airspace=action.parameters.get('placement_airspace',False)
    if type(surfaces) is not bool or type(airspace) is not bool:
        raise ValueError('Placement elevation flags must be booleans')
    if not surfaces and not airspace:return levels
    values=set(levels)
    if surfaces:
        values.update(row.walk_ft//5 for row in engine.grid.roof_surfaces)
        for rows in engine.grid.terrain_spans.get('BLOCKED',{}).values():
            values.update((top+4)//5 for bottom,top in rows if top is not None)
    if airspace:
        if type(action.range_ft) is not int or action.range_ft<0:
            raise ValueError('Air placement requires a finite nonnegative range')
        volume_query=getattr(engine,'_effect_volume',None) or engine._actor_volume
        volume=volume_query(actor)
        radius=(action.range_ft+engine.grid.square_size_ft-1)//engine.grid.square_size_ft
        heights=[cell[2] for cell in volume]
        values.update(range(max(0,min(heights)-radius),max(heights)+radius+1))
    return sorted(values)
