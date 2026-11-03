"""World-Cleansing Cycle, sealed on newly reviewed zone rows.

Native zones own geometry, once-per-turn exposure, concentration and expiry.
The cycle is recorded with the zone so reload never chooses a different element.
"""
from . import effect, hook

ELEMENTS = ('wood', 'fire', 'earth', 'metal', 'water')
TAG = 'qi_world_cycle'


def _damage(count, kind):
    return {'type': 'damage', 'applies_to': 'target',
            'dice': {'count': count, 'sides': 8}, 'damage_types': [kind]}


def _condition(name, expiry='START_OF_TARGET_NEXT_TURN', *, duration=None):
    # These hostile effects last until the affected creature starts its next turn.
    result = {'type': 'condition', 'condition': name, 'applies_to': 'target'}
    result.update({'duration': duration} if duration else {'expires_on': expiry})
    return result


def _payload(element):
    half = {'type': 'half_damage'}
    slow = {'type': 'speed', 'flat': -10, 'applies_to': 'target', 'expires_on': 'START_OF_TARGET_NEXT_TURN'}
    if element == 'wood':
        ability, fail, success = 'str', [_damage(4, 'piercing'), _condition('restrained')], [half, slow]
    elif element == 'fire':
        ability, fail, success = 'dex', [_damage(5, 'fire'), _condition('reaction_denied')], [half]
    elif element == 'earth':
        ability, fail, success = 'dex', [_damage(4, 'bludgeoning'), _condition('prone')], [half]
    elif element == 'metal':
        ability, fail, success = 'dex', [_damage(5, 'slashing'), _condition('reaction_denied', duration='until_end_of_next_turn')], [half, _condition('reaction_denied')]
    else:
        def move(feet):
            return {'type': 'choose_effects', 'name': 'Water Cycle', 'result': 'is swept by the current',
                    'options': [{'label': label, 'display_label': display,
                                'effects': [{'type': 'forced_movement', 'distance_ft': feet,
                                             'direction': direction, 'applies_to': 'target',
                                             **({'choose_distance': True} if feet == 15 else {})}]}
                                for label, display, direction in [
                                    ('Push', 'Push away from you', 'away'),
                                    ('Pull', 'Pull toward you', 'toward')]]}
        ability, fail, success = 'str', [_damage(4, 'bludgeoning'), move(15)], [half, move(5)]
    return [{'type': 'save', 'applies_to': 'target', 'ability': ability,
             'dc': 'technique_save_dc', 'on_fail': fail, 'on_success': success}]


def _triggers(source, element):
    # A stable id shares native exposure usage across element changes.
    return [{'id': source + ':cycle', 'name': element.title() + ' Cycle',
             'on': ['enter', 'start'], 'who': 'hostile', 'choice_owner': 'source',
             'effects': _payload(element)}]


@effect('qi_cycle_start', harmful=False)
def start(ctx, row):
    from .needle import ask, checkpoint_id
    explanations = {
        'wood': "Wood: Strength save; piercing damage. Failed save: restrained until the affected creature's next turn. Successful save: half damage and speed reduced by 10 feet until the affected creature's next turn.",
        'fire': "Fire: Dexterity save; fire damage. Failed save: reactions are denied until the affected creature's next turn. Successful save: half damage.",
        'earth': 'Earth: Dexterity save; bludgeoning damage. Failed save: knocked prone. Successful save: half damage.',
        'metal': "Metal: Dexterity save; slashing damage. Failed save: reactions are denied until the end of the affected creature's next turn. Successful save: half damage and reactions are denied until the affected creature's next turn. The field also grants allies +1 AC.",
        'water': 'Water: Strength save; bludgeoning damage. Failed save: choose whether to push the target away or pull it toward you, up to 15 feet. Successful save: half damage and forced movement up to 5 feet.',
    }
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, TAG, ctx.source), ctx.actor,
                 'choice:needle.qi_cycle_start', list(ELEMENTS), preferred=['wood'],
                 labels={e: explanations[e] for e in ELEMENTS}, name='World-Cleansing Cycle',
                 prompt='Choose the starting element. The field changes to the next element at the start of each of your turns: Wood, Fire, Earth, Metal, then Water.')
    ctx.damage_cache[TAG] = chosen[0] if chosen else 'wood'


@hook('forced_movement_distance')
def water_distance(ctx, subject, effect, maximum_ft):
    """Let the source choose an optional Water Cycle push distance, including zero."""
    if (not effect.get('choose_distance') or type(maximum_ft) is not int or maximum_ft < 0
            or (ctx.action.parameters.get('typed', {}).get('source') !=
                'tianxia.subpath.qi.five_elements_cultivator.feature.world_cleansing_cycle')):
        return None
    from .needle import ask, checkpoint_id
    distances = list(range(maximum_ft - (maximum_ft % 5), 0, -5)) + [0]
    labels = {str(value): ('Do not move it' if value == 0 else f'Move it up to {value} feet')
              for value in distances}
    choices = ask(ctx.engine, ctx.intent,
                  checkpoint_id(ctx.engine, TAG, ctx.source, subject.entity_id, ctx.engine.state.event_sequence),
                  ctx.actor, 'choice:needle.qi_cycle_water_distance',
                  [str(value) for value in distances], preferred=[str(maximum_ft)],
                  labels=labels,
                  name='Water Cycle movement',
                  prompt=f'{subject.display_name} failed its Strength save. Choose how far to move it in the direction you selected; it can move up to {maximum_ft} feet.')
    return int(choices[0]) if choices else 0


@hook('zone_created')
def created(ctx, zone):
    if (zone.trigger_profile.get('profile') or {}).get(TAG) != 1:
        return
    element = ctx.damage_cache[TAG]
    zone.trigger_profile[TAG] = element
    zone.trigger_profile['triggers'] = _triggers(zone.source_definition_id, element)


@hook('turn_start_choice')
def advance(engine, actor):
    from .placed import reshape
    from .. import zones
    for zone in zones.typed_zones(engine):
        current = zone.trigger_profile.get(TAG)
        if zone.owner_id == actor.entity_id and current in ELEMENTS:
            if zone.duration_rounds and engine.state.round_number - zone.created_round >= zone.duration_rounds:
                continue  # native expiry runs immediately after this checkpoint
            element = ELEMENTS[(ELEMENTS.index(current) + 1) % len(ELEMENTS)]
            reshape(engine, zone, triggers=_triggers(zone.source_definition_id, element),
                    profile={TAG: element})


def fields(engine, subject, element):
    from .. import zones
    from ..relations import ALLY, relation
    from ..spatial_areas import zone_contains
    return [(z, engine.state.actors[z.owner_id]) for z in zones.typed_zones(engine)
            if z.trigger_profile.get(TAG) == element and z.owner_id in engine.state.actors
            and not (engine.state.current_actor_id == z.owner_id and z.duration_rounds
                     and engine.state.round_number - z.created_round >= z.duration_rounds)
            and relation(engine, engine.state.actors[z.owner_id], subject) == ALLY
            and zone_contains(engine, subject, z)]


@hook('ac')
def metal_ac(engine, actor):
    return 1 if fields(engine, actor, 'metal') else None


def _wood_bonus(engine, subject, *, consume):
    available = fields(engine, subject, 'wood')
    if not available:
        return None
    token = int(engine.state.round_number) * 1000 + int(engine.state.current_slot_index)
    key = 'qi_cycle_wood_turn'
    if subject.turn_flags.get(key) == token:
        return None
    if consume:
        subject.turn_flags[key] = token
    return max(2 * int(z.trigger_profile['numbers']['pb']) for z, _ in available)


@hook('healing_preparation_policy')
def prepare(engine, subject):
    return True if fields(engine, subject, 'wood') else None


@hook('healing_offered_bonus')
def healing(engine, subject, amount, *, consume):
    return _wood_bonus(engine, subject, consume=consume)


@hook('temp_hp_offered_bonus')
def temporary(engine, subject, amount, source_id=None, source_actor_id=None, *, consume):
    return _wood_bonus(engine, subject, consume=consume)


@hook('save')
def earth_save(ctx, subject, ability, named):
    if fields(ctx.engine, subject, 'earth') and {'prone', 'forced_movement'} & set(named or ()):
        return {'modes': ['ADVANTAGE']}
    return None


@hook('save_mode')
def earth_native(engine, target, ability, dc, source_id, roll_context):
    if fields(engine, target, 'earth') and {'prone', 'forced_movement'} & set((roll_context or {}).get('named') or ()):
        return 'ADVANTAGE'
    return None


@hook('contest_check_mode')
def earth_check(ctx, subject, opponent, spec):
    if fields(ctx.engine, subject, 'earth') and {'prone', 'forced_movement'} & set(spec.get('hazards') or ()):
        return 'ADVANTAGE'
    return None


@hook('event', nested=True)
def fire_damage(engine, event_type, kwargs):
    if event_type != 'DAMAGE_COMMITTED':
        return
    actor = engine.state.actors.get(kwargs.get('actor_id') or '')
    payload = kwargs.get('payload') or {}
    if (actor is None or engine.state.current_actor_id != actor.entity_id
            or int(payload.get('hp_damage') or 0) + int(payload.get('temporary_hp_absorbed') or 0) <= 0):
        return
    available = fields(engine, actor, 'fire')
    token = int(engine.state.round_number) * 1000 + int(engine.state.current_slot_index)
    if not available or actor.turn_flags.get('qi_cycle_fire_turn') == token:
        return
    actor.turn_flags['qi_cycle_fire_turn'] = token  # before nested damage notification
    from .placed import context
    from ..typed_executor import block_damage
    z, owner = max(available, key=lambda pair: int(pair[0].trigger_profile['numbers']['pb']))
    targets = [engine.state.actors[aid] for aid in kwargs.get('target_ids') or () if aid in engine.state.actors]
    if targets:
        ctx = context(engine, actor, z.source_definition_id, z.trigger_profile['numbers'], targets)
        ctx.damage_cache['_potency_used'] = True
        block_damage(ctx, {'type': 'damage', 'applies_to': 'target', 'flat': int(z.trigger_profile['numbers']['pb']), 'damage_types': ['fire']})


@hook('turn_start_choice')
def water_step(engine, actor):
    from .placed import context
    from .rider_step import step
    available = fields(engine, actor, 'water')
    if available:
        z, owner = available[0]
        ctx = context(engine, actor, z.source_definition_id, z.trigger_profile['numbers'], [actor])
        step(ctx, {'distance_ft': 10, 'no_oa': True, 'label': 'Water Cycle'})
