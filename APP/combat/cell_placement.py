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
        width, height = rule.get('width_cells', 1), rule.get('height_cells', 1)
        if any(type(n) is not int or not 1 <= n <= 8 for n in (width, height)):
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
