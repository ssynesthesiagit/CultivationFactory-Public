"""Shared helper module: combat/ext/athletics.py uses owns.

Owned Sure Grip checks/catches and Strong Lungs benefits.

Shared public helper: consumed by athletics.py. Its exported functions are
the stable cross-plugin API; private helpers stay private.

Catch difficulty is explicitly authored on a scene surface, never inferred
from the talent. Recorded catch supports last only while their anchor remains
reachable and able to hold; ordinary falling resumes when support is lost.
Explicit breath clocks track the owner's remaining seconds. Actual climb/fall
checks and categorized combat saves receive their printed Advantage; Sure
Grip's physical holds survive Incapacitated.
"""
from . import hook, effect
from .. import breath_clock
BLOCK = 'athletics_grip_lungs'
GRIP = 'TAL_ATHLETICS_SURE_GRIP'
LUNGS = 'TAL_ATHLETICS_STRONG_LUNGS'
SHARK = 'TAL_ATHLETICS_SHARK_SWIM'


@hook('compile_block')
def compile_benefits(block, spec, row, numbers):
    if block == BLOCK:
        return [{**row, 'block': BLOCK, 'kind': spec['kind']}]


def owns(engine, actor, kind):
    return any(r.get('block') == BLOCK and r.get('kind') == kind
               for r in engine.typed_passive_rows.get(actor.entity_id, ()))


@hook('maintain_grapples_incapacitated')
def maintain_grip(engine, actor):
    return True if owns(engine, actor, 'sure_grip') else None


@hook('climbing')
def sure_grip_climbing(engine, actor):
    """The same owned Sure Grip row supplies native roof-climbing Advantage.

    Kept here with its physical-hold and ordinary climb-check benefits so a
    later feature file cannot replace one half of the talent with the other.
    """
    return {'climb_check_modes': ['ADVANTAGE']} if owns(engine, actor, 'sure_grip') else None


@hook('ability_check_hazards')
def climb_and_fall(engine, actor, ability, skill, hazards):
    if (owns(engine, actor, 'sure_grip') and str(skill).lower() == 'athletics'
            and set(hazards) & {'climb', 'prevent_falling'}):
        return 'ADVANTAGE'


CAUGHT = 'condition:typed.sure_grip_caught'


def catch_faces(engine, target):
    """Physical supports with an authored catch DC; air is never a handhold."""
    from ..roof_movement import faces
    sites = [(face.id, face.catch_dc if face.catch_dc is not None else engine.grid.catch_dc)
             for face in faces(engine, target, target.position, include_virtual=False)
             if face.catch_dc is not None or engine.grid.catch_dc is not None]
    if engine.grid.catch_dc is not None:
        # A scene can also declare a catch difficulty for ordinary solid walls
        # or pillars without a roof. Only actually adjacent solid voxels qualify.
        for x, y in sorted(engine._actor_cells(target)):
            for dx, dy in ((-1, 0), (0, -1), (0, 1), (1, 0)):
                at = (x + dx, y + dy, target.position.z)
                if engine.grid.roof_at(at[0], at[1]) is None and engine.grid.terrain_at(at, 'BLOCKED'):
                    sites.append(('solid:%d,%d,%d' % at, engine.grid.catch_dc))
    return tuple(dict.fromkeys(sites))


@hook('choice_reactors')
def catch_owners(engine):
    from ..tabletop_service import MANUAL_MODES
    modes = getattr(engine, 'typed_control_modes', {}) or {}
    return tuple(actor.entity_id for actor in engine.state.actors.values()
                 if owns(engine, actor, 'sure_grip') and modes.get(actor.entity_id) in MANUAL_MODES)


def held_support(engine, subject, data, position=None):
    """Recheck native anchor support; cyclic catch chains supply no support.

    The recursion guard is transient query state, restored on every exit and
    never stored in the fight. Ground, physical grips, flight and other native
    supports share the ordinary falling eligibility query.
    """
    from ..roof_movement import faces
    from ..falling import required
    from ..typed_executor import condition_rules
    from ..targeting import line_of_effect
    from .reach_bonus import natural_reach_ft
    anchor = engine.state.actors.get(data.get('anchor_id'))
    at = position or subject.position
    if (at.x, at.y, at.z) != (data.get('x'), data.get('y'), data.get('z')):
        return False
    if anchor is None or not anchor.active or any(row.get('no_actions') for row in condition_rules(anchor)):
        return False
    if anchor.entity_id == subject.entity_id:
        if str(data.get('surface_id', '')).startswith('solid:'):
            from ..gate2_runtime_models import Position
            coordinates = str(data['surface_id']).removeprefix('solid:').split(',')
            if len(coordinates) != 3:
                return False
            x, y, z = map(int, coordinates)
            return bool(engine.grid.terrain_at((x, y, z), 'BLOCKED') and
                engine._distance_actor_to_cell(subject, Position(x=x, y=y, z=z)) <= natural_reach_ft(engine, subject))
        return any(face.id == data.get('surface_id') for face in faces(
            engine, subject, at, include_virtual=False))
    prior = getattr(engine, '_catch_support_chain', frozenset())
    if anchor.entity_id in prior:
        return False
    engine._catch_support_chain = prior | {subject.entity_id}
    try:
        grounded = not required(engine, anchor)
    finally:
        engine._catch_support_chain = prior
    return bool(grounded and engine._distance_actor_to_actor(anchor, subject, target_position=at) <= natural_reach_ft(engine, anchor)
                and line_of_effect(engine, anchor, destination=at))


@hook('support_surface')
def caught_support(engine, actor, position):
    for condition in actor.conditions.values():
        if condition.condition_id == CAUGHT and held_support(engine, actor, condition.data, position):
            return True


@hook('event')
def catch_separation(engine, event_type, kwargs):
    if event_type not in {'MOVEMENT_COMMITTED', 'TURN_STARTED', 'CONDITION_APPLIED'} or not hasattr(engine, 'state'):
        return
    for actor in engine.state.actors.values():
        for c in list(actor.conditions.values()):
            if c.condition_id == CAUGHT and not held_support(engine, actor, c.data):
                # Use the engine's public evented removal for this owned id.
                engine._remove_condition(actor, CAUGHT, GRIP)
                break


@hook('falling')
def sure_grip_catch(engine, falling_actors, intent):
    from .. import falling, typed_reactions
    from ..target_knowledge import knowledge
    from ..targeting import line_of_effect
    from ..typed_executor import Context, resolve_opposed_check
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from .needle import ask, checkpoint_id, numbers_of
    from .reach_bonus import natural_reach_ft
    for catcher in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        row = {'feature_id': GRIP, 'kind': 'sure_grip_catch'}
        if not owns(engine, catcher, 'sure_grip') or not typed_reactions.can_react(engine, catcher, row):
            continue
        options = {}
        for target in falling_actors:
            if not falling.required(engine, target) or not typed_reactions.can_use_reaction(engine, catcher, target, row):
                continue
            if target is not catcher:
                known = knowledge(engine, catcher, target)
                if (falling.required(engine, catcher) or known is None or known.mode != 'DIRECT'
                        or engine._distance_actor_to_actor(catcher, target) > natural_reach_ft(engine, catcher)
                        or not line_of_effect(engine, catcher, target=target)):
                    continue
            sites = list(catch_faces(engine, target))
            if target is not catcher and engine.grid.catch_dc is not None:
                sites = [('scene', engine.grid.catch_dc)]
            for site_id, dc in sites:
                options[f'{target.entity_id}|{site_id}'] = (target, site_id, dc)
        if not options:
            continue
        labels = {key: f'Catch {target.display_name} (Athletics DC {dc}; Reaction)' for key, (target, site_id, dc) in options.items()}
        selected = ask(engine, intent, checkpoint_id(engine, 'sure-grip-fall', catcher.entity_id), catcher,
            'choice:needle.athletics.sure_grip_catch', list(options), labels=labels,
            prompt=f'Sure Grip: a fall is starting. {catcher.display_name} may catch itself or one visible creature within {natural_reach_ft(engine, catcher)} feet, using a Reaction and an Athletics check against the scene difficulty. A success holds it here until support or reach is lost.',
            name='Sure Grip', feature_id=GRIP, allow_decline=True,
            prompt_context={'cost': 'Reaction', 'action_name': 'Falling', 'affected_id': ''})
        if not selected:
            continue
        target, site_id, dc = options[selected[0]]
        typed_reactions.open_reaction(engine, row, catcher, (target.entity_id,), 'SURE_GRIP_FALL')
        action = ActionDefinition(source_definition_id=GRIP, display_name='Sure Grip catch', owner_id=catcher.entity_id,
            economy=EconomyKind.NONE, resolution_kind='TYPED', target_kind='SELF')
        ctx = Context(engine, catcher, action, intent, {'source': GRIP, 'numbers': numbers_of(engine, catcher)}, [target], target)
        result = resolve_opposed_check(ctx, target, {'ability': 'STR', 'skill': 'Athletics', 'hazards': ['prevent_falling']},
            {'kind': 'dc', 'dc': dc})
        if result.success:
            engine._apply_condition(target, CAUGHT, GRIP, catcher.entity_id, expires_on=None,
                data={'anchor_id': catcher.entity_id, 'surface_id': site_id,
                      'x': target.position.x, 'y': target.position.y, 'z': target.position.z,
                      'label': f'Sure Grip: caught by {catcher.display_name} until support or reach is lost'})


@hook('save')
def lungs_saves(ctx, subject, ability, named):
    if not owns(ctx.engine, subject, 'strong_lungs'):
        return
    categories = set(named or ())
    if 'smoke_nonbreather_advantage' in ctx.typed or categories & {'category:inhalation', 'category:suffocation'} or (
            str(ability).upper() == 'CON' and 'category:forced_march_exhaustion' in categories):
        return {'bonus': 0, 'modes': ['ADVANTAGE']}


@hook('breath_duration')
def lungs_duration(engine, actor, normal_seconds, constitution_modifier):
    if not owns(engine, actor, 'strong_lungs'):
        return None
    if owns(engine, actor, 'shark_swim'):
        return max(1, constitution_modifier) * 3600
    return normal_seconds * actor.proficiency_bonus


@hook('swimming')
def shark_speed(engine, actor):
    return {'swim_speed_ft': max(0, engine._effective_speed(actor))} if owns(engine, actor, 'shark_swim') else None


@hook('compile_actions')
def breath_actions(info):
    if LUNGS not in info['owned_ids']:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.breath_{operation}",
        display_name='Strong Lungs: ' + label, owner_id=info['actor_id'], economy=EconomyKind.NONE,
        resolution_kind='TYPED', target_kind='SELF',
        parameters={'typed': {'source': LUNGS, 'numbers': info['numbers'], 'riders': [],
                    'effects': [{'type': 'athletics_breath', 'operation': operation}]}})
        for operation, label in [('hold', 'hold your breath'), ('breathe', 'breathe again')]]


@hook('candidate_allowed')
def breath_available(engine, actor, candidate, action):
    effects = ((getattr(action, 'parameters', None) or {}).get('typed') or {}).get('effects', ())
    for row in effects:
        if row.get('type') == 'athletics_breath':
            holding = any(c.condition_id == breath_clock.CLOCK for c in actor.conditions.values())
            return None if holding == (row['operation'] == 'breathe') else False


@effect('athletics_breath')
def change_breath(ctx, eff):
    if eff['operation'] == 'breathe':
        breath_clock.stop(ctx.engine, ctx.actor, LUNGS)
    else:
        con = int(ctx.numbers.get('con_mod', 0))
        breath_clock.start(ctx.engine, ctx.actor, LUNGS, max(30, (1 + con) * 60), con)


@hook('button_description')
def breath_help(row):
    effects = ((row.get('parameters') or {}).get('typed') or {}).get('effects', ())
    if any(e.get('type') == 'athletics_breath' for e in effects):
        return ('Hold your breath without spending an Action. Strong Lungs multiplies the normal duration by '
                'your Proficiency Bonus; with Shark Swim it becomes hours equal to your Constitution modifier '
                '(at least one hour). Each completed turn spends six seconds. Breathe again to end the clock.')
