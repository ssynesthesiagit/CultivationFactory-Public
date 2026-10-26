"""Owned Air Insight riders on sealed rows and native physical movement.

A Current's three-dimensional direction is chosen when created, and retained on its
zone. Wind-Line Archer reads the exact strike's crossing before its roll; its
optional five-foot push uses the normal forced-movement defenses/collisions.
Cloud-Step Novice delays one end-turn fall per fight and may drift horizontally
before a self-cushioned fall. No lasting Fly Speed or teleport is granted.
"""
from . import hook
from .air_currents import currents, projectile_crosses_current, owned_air_rows

WIND_LINE = 'insight.wind-line-archer'
CLOUD_STEP = 'insight.cloud-step-novice'
FEATHER = 'TAL_AIR_FEATHER_FALL_BREATH'
DIRECTION = 'air_current_direction'
HORIZONTAL = {'east': (1, 0), 'west': (-1, 0), 'north': (0, -1), 'south': (0, 1),
              'northeast': (1, -1), 'northwest': (-1, -1), 'southeast': (1, 1), 'southwest': (-1, 1)}
DIRECTIONS = {key: (*xy, 0) for key, xy in HORIZONTAL.items()}
DIRECTIONS.update({'up': (0, 0, 1), 'down': (0, 0, -1)})
DIRECTIONS.update({f'{height}-{key}': (*xy, dz)
                   for height, dz in (('up', 1), ('down', -1)) for key, xy in HORIZONTAL.items()})
FIXED_FLOW = {'TAL_AIR_UPDRAFT_GATE': (0, 0, 1), 'TAL_AIR_DOWNBURST_SEAL': (0, 0, -1)}



@hook('compile_action')
def named_wind_line_penalty(action, info):
    if WIND_LINE not in info.get('owned_ids', ()):
        return None
    typed = action.parameters.get('typed') or {}
    if typed.get('weapon') and typed.get('long_range_ft'):
        return action.model_copy(update={'parameters': {**action.parameters,
            'typed': {**typed, 'strike_penalty_provenance': 1}}})


@hook('technique_used')
def choose_current_direction(ctx):
    if not owned_air_rows(ctx.engine, ctx.actor.entity_id, 'wind_line'):
        return
    # Only zones created by THIS action, not earlier currents with the same source.
    created = {e.payload['zone']['zone_id'] for e in ctx.engine.events
               if e.event_type == 'ZONE_CREATED' and e.actor_id == ctx.actor.entity_id
               and e.trigger_or_intent_id == ctx.intent.intent_id}
    from .needle import ask, checkpoint_id
    for zone in currents(ctx.engine, ctx.actor):
        if zone.zone_id not in created or DIRECTION in zone.trigger_profile:
            continue
        from ..zone_sources import of
        fixed = FIXED_FLOW.get(str((of(zone) or {}).get('mechanic_id') or ''))
        if fixed:
            direction = fixed
        else:
            chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, WIND_LINE, zone.zone_id), ctx.actor,
                'choice:needle.wind_line_direction', list(DIRECTIONS),
                labels={key: key.replace('-', ' and ').title() for key in DIRECTIONS},
                prompt="Choose the Current's direction. Wind-Line Archer may move a creature hit through it 5 feet in this direction.",
                name='Wind-Line Archer', feature_id=WIND_LINE)
            direction = DIRECTIONS[chosen[0]] if chosen else None
        if direction:
            zone.trigger_profile = {**zone.trigger_profile, DIRECTION: list(direction)}
            ctx.engine._append_event('ZONE_CREATED', zone.source_definition_id, actor_id=zone.owner_id,
                                     payload={'zone': zone.model_dump(mode='json')})



def crossing(engine, actor, target, action, effect=None):
    typed = (getattr(action, 'parameters', None) or {}).get('typed') or {}
    if not typed.get('weapon') or not (typed.get('range_ft') or typed.get('long_range_ft')):
        return None
    if not owned_air_rows(engine, actor.entity_id, 'wind_line'):
        return None
    return next((zone for zone in currents(engine, actor)
        if projectile_crosses_current(engine, zone, actor, target, {'through': True})), None)


@hook('attack_mode_removed')
def wind_line_range(engine, attacker, target, ranged):
    from .attack_scope import current
    frame = current(engine)
    if not frame or frame['actor_id'] != attacker.entity_id or frame['target_id'] != target.entity_id:
        return None
    action = engine.action_catalog.get(frame['source'])
    typed = (getattr(action, 'parameters', None) or {}).get('typed') or {}
    if typed.get('strike_penalty_provenance') == 1 and crossing(engine, attacker, target, action):
        return ['DISADVANTAGE:long_range']


@hook('attack_mode')
def remember_wind_line(ctx, target):
    zone = crossing(ctx.engine, ctx.actor, target, ctx.action, ctx.attack_effect)
    ctx.damage_cache['_wind_line_crossing'] = (zone.zone_id, target.entity_id) if zone else None


@hook('attack_result')
def wind_line_push(ctx, target, hit, critical):
    cached = ctx.damage_cache.pop('_wind_line_crossing', None)
    if not hit or not cached or cached[1] != target.entity_id:
        return
    from .needle import ai_controlled
    if ai_controlled(ctx.engine, ctx.actor) and target.team_id == ctx.actor.team_id:
        return
    from .. import dynamic_size
    sizes = dynamic_size.CATEGORIES
    if sizes.index(dynamic_size.current_category(ctx.engine, target)) > sizes.index(dynamic_size.current_category(ctx.engine, ctx.actor)) + 1:
        return
    stamp = f'{ctx.engine.state.round_number}:{ctx.engine.state.current_actor_id}:{ctx.engine.state.actors[ctx.engine.state.current_actor_id].turns_started}'
    if ctx.actor.turn_flags.get('wind_line_used') == stamp:
        return
    zone = next((z for z in currents(ctx.engine, ctx.actor) if z.zone_id == cached[0]), None)
    direction = (zone.trigger_profile.get(DIRECTION) if zone else None)
    if not direction:
        return
    from .rider_choices import pick
    if not pick(ctx.engine, ctx.actor, 'wind_line_push', 'Wind-Line Archer', ['move'], subject=target,
            labels={'move': f'Move {target.display_name} 5 feet in the Current\'s direction'},
            trigger=f'Your ranged weapon attack through an Air Current hits {target.display_name}', intent=ctx.intent):
        return
    ctx.actor.turn_flags['wind_line_used'] = stamp
    from ..movement_paths import resolve
    destination = target.position.model_copy(update={'x': target.position.x + direction[0], 'y': target.position.y + direction[1], 'z': target.position.z + direction[2]})
    resolve(ctx.engine, target, (target.position, destination), WIND_LINE, kind='forced', feet=5,
            source_actor_id=ctx.actor.entity_id, ctx=ctx, intent=ctx.intent)


@hook('falling_prepare')
def cloud_step_prepare(engine, actors, cause, intent):
    if intent is None:
        return
    ended = any(e.event_type == 'INTENT_ACCEPTED' and e.payload.get('kind') == 'END_TURN' and e.actor_id == intent.actor_id
                and e.trigger_or_intent_id == intent.intent_id for e in engine.events)
    if not ended:
        return
    for actor in actors:
        if actor.entity_id == intent.actor_id:
            cloud_step_delay(engine, actor)


def cloud_step_delay(engine, actor):
    if not owned_air_rows(engine, actor.entity_id, 'cloud_step') or actor.turn_flags.get('cloud_step_round_scene_used'):
        return
    from ..falling import required
    if not required(engine, actor):
        return
    from .rider_choices import pick
    if not pick(engine, actor, 'cloud_step_delay', 'Cloud-Step Novice', ['delay'], subject=actor,
            labels={'delay': 'Delay this fall until the end of your next turn (once per scene)'},
            trigger='You end your turn unsupported in the air'):
        return
    from .effect_durations import token
    actor.turn_flags['cloud_step_round_scene_used'] = True
    engine._apply_condition(actor, 'condition:typed.cloud_step_delay', CLOUD_STEP, actor.entity_id,
        expires_on=token('end', actor.entity_id, actor.turns_started + 1),
        data={'flight_suspended': 1, 'label': 'Cloud-Step Novice: fall delayed until the end of your next turn'})


@hook('falling_ready')
def cloud_step_drift(engine, actors, cause, intent):
    from .altitude_abilities import CUSHION_CONDITION
    from ..falling import required
    from .needle import ask, checkpoint_id
    from ..gate2_runtime_models import Position
    from ..granted_movement import path_cost, resolve_path
    for actor in actors:
        if not required(engine, actor) or not owned_air_rows(engine, actor.entity_id, 'cloud_step') or not any(c.condition_id == CUSHION_CONDITION
                and c.source_actor_id == actor.entity_id and c.source_definition_id == FEATHER for c in actor.conditions.values()):
            continue
        # Physical, horizontal travel before landing; no teleport, no ordinary allowance.
        paths = {}
        # Query a projected grant, without mutating the creature or recording a
        # condition while offering choices. Native admission sees the same max
        # Fly Speed as the consumed grant below, including disabled flight,
        # perceived occupancy, Difficult Terrain, drag and Frightened.
        granted_actor = actor.model_copy(update={'fly_speed_ft': max(10, actor.fly_speed_ft)})
        costs = {}
        queue = [(actor.position,)]
        for path in queue:
            if len(path) > 2:
                continue
            for dx, dy in HORIZONTAL.values():
                nxt = Position(x=path[-1].x + dx, y=path[-1].y + dy, z=actor.position.z)
                if nxt == actor.position:
                    continue
                route = (*path, nxt)
                try:
                    cost = path_cost(engine, granted_actor, route, mode='fly')
                except ValueError:
                    continue  # native admission rejects this physical route
                key = f'drift:{nxt.x},{nxt.y}'
                if cost <= 10 and cost < costs.get(key, 11):
                    paths[key], costs[key] = route, cost
                    queue.append(route)
        selected = ask(engine, intent, checkpoint_id(engine, CLOUD_STEP, actor.entity_id), actor,
            'choice:needle.cloud_step_drift', list(paths),
            labels={k: f'Move to ({p[-1].x}, {p[-1].y}) before landing' for k, p in paths.items()},
            prompt='Feather-Fall Breath cushions your own fall. You may move up to 10 feet horizontally before landing.',
            allow_decline=True, default='decline', name='Cloud-Step Novice', feature_id=CLOUD_STEP)
        if selected:
            path = paths[selected[0]]
            cid = 'condition:typed.cloud_step_drift'
            engine._apply_condition(actor, cid, CLOUD_STEP, actor.entity_id,
                expires_on='CONSUMED', data={'fly_speed_ft': 10})
            try:
                resolve_path(engine, actor, path, CLOUD_STEP, feet=10, intent=intent, mode='fly')
            finally:
                engine._remove_condition(actor, cid, CLOUD_STEP)
