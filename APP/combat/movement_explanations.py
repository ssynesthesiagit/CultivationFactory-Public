"""Read-only movement diagnostics for presentation clients.

This describes existing restrictions, not permission to move. Native candidate
validation still decides paths, occupancy, walls and ability-specific rules.
Queries change no state, events, RNG, legal candidates or saved-fight data.
"""
from .gate2_runtime_models import Position


def label(engine, source, fallback):
    action = engine.action_catalog.get(source)
    return action.display_name if action is not None else fallback


def describe(engine, actor_id, destination=None):
    from . import ext
    from .typed_executor import condition_rules
    from .target_knowledge import actors_for
    actor = engine.state.actors[actor_id]
    if destination is not None and not isinstance(destination, Position):
        raise TypeError('destination must be a Position or None')
    observed = {a.entity_id:a for a in actors_for(engine, actor)}
    speed = max(0, engine._effective_speed(actor))
    reasons = []
    def add(code, message, *, blocks=False, **details):
        reasons.append({'code':code, 'message':message, 'blocks_destination':blocks, **details})
    if actor.life_state is not None:
        add('LIFE_STATE', 'This creature cannot move while dying or dead.', blocks=True)
    causes = []
    for c in actor.conditions.values():
        own = actor.model_copy(update={'conditions':{c.instance_id:c}})
        rules = condition_rules(own)
        kind = c.condition_id.rsplit('.',1)[-1]
        name = str(c.data.get('label') or label(engine,c.source_definition_id,kind.replace('_',' ').title()))
        if any(r.get('walking_extra_cost') for r in rules):
            from .posture import walking_extra
            extra = walking_extra(engine, actor)
            cost_text = (f'each foot costs {extra} extra foot of movement' if extra else
                         'an active ability lets you crawl without extra movement cost')
            add('CRAWLING', f'{name}: walking is crawling; {cost_text}. '
                f'Standing ends Prone and normally costs {speed // 2} feet of movement (half Speed).',
                condition_id=c.condition_id)
        if c.condition_id == 'condition:core.grappled' or any(r.get('speed_zero') for r in rules):
            code = 'GRAPPLED' if kind == 'grappled' else 'RESTRAINED' if kind == 'restrained' else 'SPEED_ZERO_EFFECT'
            causes.append(name)
            add(code, f'{name} sets Speed to 0; no movement is available.', blocks=True,
                condition_id=c.condition_id, source_id=c.source_definition_id)
        if int(c.data.get('speed_delta') or 0) < 0:
            delta = int(c.data['speed_delta']); causes.append(name)
            add('SPEED_PENALTY', f'{name} reduces Speed by {-delta} feet.', delta_ft=delta,
                source_id=c.source_definition_id)
        if c.condition_id == 'condition:typed.frightened' and c.source_actor_id in observed:
            fear = observed[c.source_actor_id]
            closer = None if destination is None else (
                engine.grid.distance_ft(destination, fear.position) <
                engine.grid.distance_ft(actor.position, fear.position))
            add('FRIGHTENED_CLOSER', f'Frightened: you cannot willingly move closer to {fear.display_name}.',
                blocks=closer, source_actor_id=fear.entity_id,
                current_distance_ft=engine.grid.distance_ft(actor.position,fear.position),
                **({'destination_distance_ft':engine.grid.distance_ft(destination,fear.position)}
                   if destination is not None else {}))
    for m in actor.modifiers.values():
        if m.target_field == 'speed_ft' and m.operation == 'ADD' and int(m.value) < 0:
            name = label(engine,m.source_definition_id,'A movement effect'); causes.append(name)
            add('SPEED_PENALTY', f'{name} reduces Speed by {-int(m.value)} feet.',
                delta_ft=int(m.value), source_id=m.source_definition_id)
        if m.target_field == 'speed_halved' and not m.consumed:
            name = label(engine,m.source_definition_id,'A movement effect'); causes.append(name)
            add('SPEED_HALVED', f'{name} halves Speed.', source_id=m.source_definition_id)
    # Grouped condition penalties use maximum-per-group semantics. Explain the
    # live contribution once per group, using the winning instance as provenance.
    from .motion import grouped_speed_penalty
    grouped = {}
    for condition in actor.conditions.values():
        amount = grouped_speed_penalty(engine, actor, condition)
        group = (condition.data or {}).get('speed_penalty_group')
        if amount and isinstance(group, str) and (group not in grouped or amount > grouped[group][0]):
            grouped[group] = (amount, condition)
    for amount, condition in grouped.values():
        name = str((condition.data or {}).get('label') or
                   label(engine, condition.source_definition_id, 'A movement effect'))
        causes.append(name)
        add('SPEED_PENALTY', f'{name} reduces Speed by {amount} feet.', delta_ft=-amount,
            source_id=condition.source_definition_id)
    from . import ext
    for contribution in ext.run('speed', engine, actor):
        for source, name, delta in getattr(contribution, 'sources', ()):
            if delta < 0:
                causes.append(name)
                add('SPEED_PENALTY', f'{name} reduces Speed by {-delta} feet.',
                    delta_ft=delta, source_id=source)
    for rows in ext.run('speed_explanation', engine, actor):
        for row in rows:
            delta = int(row['delta_ft'])
            if delta < 0:
                name = str(row['label']); causes.append(name)
                add('SPEED_PENALTY', f'{name} reduces Speed by {-delta} feet while the effect lasts.',
                    delta_ft=delta, source_id=row.get('source_id'))
    if speed == 0:
        cause = ', '.join(dict.fromkeys(causes))
        message = 'Speed is 0; no movement is available.'
        if cause: message += ' Caused by: '+cause+'.'
        elif actor.speed_ft == 0: message += ' This creature has no walking Speed.'
        elif actor.life_state is None: message += ' Active movement effects reduce its Speed to 0.'
        add('SPEED_ZERO', message, blocks=True, base_speed_ft=actor.speed_ft)
    if actor.movement_remaining_ft <= 0:
        add('MOVEMENT_SPENT', 'No movement remains this turn.', blocks=True)
    from . import motion
    with motion.terrain_for(engine, actor):
        from .read_queries import memo
        # All destination cards use this actor's unchanged origin and terrain.
        # Reuse only inside a pure read frame (movement_presentation.for_menu);
        # standalone diagnostics and later table answers compute it afresh.
        # Keep the actor alive with the memo and copy the set for each reader.
        origin = (actor.position.x, actor.position.y, actor.position.z)
        difficult = set(memo(engine, ('movement_explanation_difficult', id(actor), origin),
                             lambda: (actor, frozenset(engine._hostile_difficult_cells(actor))))[1])
        cells = difficult | {cell for cell, cost in engine.grid.base_movement_cost.items() if cost > 1}
        details = {'cells':[{'x':x,'y':y} for x,y in sorted(cells,key=lambda p:(p[1],p[0]))]}
        if destination is not None and engine.grid.distance_ft(actor.position, destination) == engine.grid.square_size_ft:
            multiplier = engine.grid.movement_step_multiplier(
                actor.position, destination, footprint=engine._footprint(actor), difficult_cells=difficult)
            if multiplier > 1:
                from .flight import step_cost
                step = step_cost(engine, actor, actor.position, destination, difficult=difficult)
                add('DIFFICULT_TERRAIN', f'Difficult terrain: this {engine.grid.square_size_ft}-foot step costs {step} feet of movement, including other movement costs.',
                    step_cost_ft=step, **details)
        elif cells:
            add('DIFFICULT_TERRAIN', 'Difficult terrain costs extra movement when entering it; the cost depends on the path.', **details)
    return {'actor_id':actor_id, 'effective_speed_ft':speed,
            'movement_remaining_ft':actor.movement_remaining_ft, 'reasons':reasons,
            'explained_refusal':any(r['blocks_destination'] is True for r in reasons)}
