"""Scale Foe's Bonus Action climb and carrier-specific attack Disadvantage.

The shared creature_attachment receipt owns contained occupancy and following.
No other creature or dislodging ability check receives attack Disadvantage.
"""
from contextlib import contextmanager

from . import effect, hook, note
from .needle import ask, checkpoint_id, cell_id
from .. import creature_attachment
from ..dynamic_size import current_category, CATEGORIES

SOURCE = 'TAL_ATHLETICS_SCALE_FOE'
QUARTERS = 'TAL_ATHLETICS_CLOSE_QUARTERS_TRAINING'


@contextmanager
def boarding_scope(engine, actor):
    """Authorize only this action's paid entry; restore on pauses and nesting."""
    old = getattr(engine, '_scale_foe_boarding', None)
    engine._scale_foe_boarding = (actor.entity_id, actor.position)
    try:
        yield
    finally:
        engine._scale_foe_boarding = old


@hook('movement_step_capability')
def boarding_step(engine, actor, previous, destination, mode):
    """The won climbing check admits one native step into the carrier's volume."""
    if mode != 'walk' or getattr(engine, '_scale_foe_boarding', None) != (actor.entity_id, previous):
        return
    c = creature_attachment.receipt(actor)
    host = creature_attachment.carrier(engine, actor)
    if (c and c.source_definition_id == SOURCE and host
            and engine.grid.distance_ft(previous, destination) <= 5
            and set(engine._actor_volume(actor, destination)) <= set(engine._actor_volume(host))):
        return True


def preferred_skills(engine, actor):
    """Rank only the creature's own recorded ability/skill modifiers."""
    from ..ability_checks import skill_bonus
    scores = {'athletics': skill_bonus(engine, actor, 'Athletics', (actor.strength_score - 10) // 2),
              'acrobatics': skill_bonus(engine, actor, 'Acrobatics', (actor.dexterity_score - 10) // 2)}
    return sorted(scores, key=lambda key: (-scores[key], key))[:1]


@hook('compile_actions')
def climb_actions(info):
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    actions = [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.dislodge_clinger",
        display_name='Dislodge a creature using Scale Foe', owner_id=info['actor_id'], economy=EconomyKind.ACTION,
        resolution_kind='TYPED', target_kind='ANY_CREATURE', range_ft=5,
        parameters={'typed': {'source': 'system:combat.dislodge_clinger', 'numbers': info['numbers'], 'riders': [],
                    'effects': [{'type': 'scale_dislodge'}]}})]
    if SOURCE not in info['owned_ids']:
        return actions
    return actions + [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.scale_foe", display_name='Scale Foe: climb onto a bigger creature',
        owner_id=info['actor_id'], economy=EconomyKind.BONUS_ACTION, resolution_kind='TYPED', target_kind='ANY_CREATURE', range_ft=5,
        parameters={'typed': {'source': SOURCE, 'numbers': info['numbers'], 'riders': [],
                    'effects': [{'type': 'scale_foe', 'close_quarters': int(QUARTERS in info['owned_ids'])}]}})]


@hook('candidate_allowed')
def scale_offered(engine, actor, candidate, action):
    effects = ((getattr(action, 'parameters', None) or {}).get('typed') or {}).get('effects', ())
    if any(e.get('type') == 'scale_dislodge' for e in effects):
        target = engine.state.actors.get(candidate.target_ids[0]) if candidate.target_ids else None
        c = creature_attachment.receipt(target) if target else None
        return None if c and c.source_definition_id == SOURCE and creature_attachment.carrier(engine, target) is actor else False
    if not any(e.get('type') == 'scale_foe' for e in effects):
        return
    target = engine.state.actors.get(candidate.target_ids[0]) if candidate.target_ids else None
    from ..targeting import line_of_effect
    if (not target or target is actor or creature_attachment.receipt(actor)
            or engine._effective_speed(actor) <= 0 or actor.movement_remaining_ft < 5
            or not engine._line_of_sight_actor_to_actor(actor, target) or not line_of_effect(engine, actor, target=target)
            or CATEGORIES.index(current_category(engine, target)) <= CATEGORIES.index(current_category(engine, actor))):
        return False
    return None


@effect('scale_foe')
def climb(ctx, eff):
    engine, actor, target = ctx.engine, ctx.actor, ctx.target
    if target is None:
        return
    # The named optional climbing action opposes Athletics/Acrobatics with the
    # bigger creature's Dexterity (Acrobatics), rather than its attack roll.
    from ..typed_executor import resolve_opposed_check
    selected = ask(engine, ctx.intent, checkpoint_id(engine, 'scale_check', actor.entity_id, target.entity_id), actor,
        'choice:needle.scale_check', ['athletics', 'acrobatics'], name='Scale Foe', feature_id=SOURCE, target_id=target.entity_id,
        labels={'athletics': 'Strength (Athletics)', 'acrobatics': 'Dexterity (Acrobatics)'},
        prompt=f'Choose {actor.display_name}\'s check to climb onto {target.display_name} with Scale Foe (Bonus Action).',
        automatic=True, allow_decline=False, preferred=preferred_skills(engine, actor))
    check = {'ability': 'STR', 'skill': 'Athletics'} if selected == ['athletics'] else {'ability': 'DEX', 'skill': 'Acrobatics'}
    result = resolve_opposed_check(ctx, target, check, {'ability': 'DEX', 'skill': 'Acrobatics'})
    if not result.success:
        return
    creature_attachment.bind(engine, actor, target, SOURCE)
    c = creature_attachment.receipt(actor)
    engine._update_condition_data(actor, c, {**c.data, 'close_quarters': int(eff.get('close_quarters', 0)),
        'label': f'Scale Foe: clinging to {target.display_name}. Its attacks against you have Disadvantage; '
                 'move outside its space or be dislodged to let go.'}, SOURCE)
    with boarding_scope(engine, actor):
        enter_carrier(ctx, target)


def enter_carrier(ctx, target):
    """Offer every affordable contained entry, then pay through native movement."""
    from ..gate2_runtime_models import Position, CandidateKind
    from .. import flight
    engine, actor = ctx.engine, ctx.actor
    destinations = {}
    occupied = engine._occupied_volumes_except(actor.entity_id, observed=True)
    host_volume = set(engine._actor_volume(target))
    for x, y, z in sorted(host_volume, key=lambda cell: (abs(cell[2] - actor.position.z), cell[2], cell[1], cell[0])):
        at = Position(x=x, y=y, z=z)
        if (engine.grid.distance_ft(actor.position, at) <= 5
                and set(engine._actor_volume(actor, at)) <= host_volume
                and engine.grid.volume_legal(at, footprint=engine._footprint(actor), occupied_cells=occupied)
                and flight.step_allowed(engine, actor, actor.position, at, mode='walk')
                and flight.step_cost(engine, actor, actor.position, at, 'walk') <= flight.remaining(engine, actor, 'walk')):
            destinations[cell_id(at)] = at
    if not destinations:
        engine._remove_condition(actor, creature_attachment.CONDITION, SOURCE)
        return
    chosen = ask(engine, ctx.intent, checkpoint_id(engine, 'scale_position', actor.entity_id, target.entity_id), actor,
        'choice:needle.scale_position', list(destinations), name='Scale Foe', feature_id=SOURCE, target_id=target.entity_id,
        labels={key: f'Cling at square {at.x}, {at.y}, {5*at.z} feet up' for key, at in destinations.items()},
        prompt=f'Choose where {actor.display_name} climbs onto {target.display_name}; spend ordinary movement to enter its space.',
        automatic=True, allow_decline=False, preferred=[next(iter(destinations))])
    at = destinations[chosen[0]]
    if at != actor.position:
        cost = flight.step_cost(engine, actor, actor.position, at, 'walk')
        c = engine._candidate(CandidateKind.MOVE, actor, 'system:combat.movement', 'Climb onto the chosen creature',
            destination=at, path=(actor.position, at), movement_cost_ft=cost, metadata={'movement_mode': 'walk'})
        engine._resolve_movement(actor, c, ctx.intent)
    creature_attachment.reconcile(engine, actor)


@effect('scale_dislodge')
def dislodge(ctx, eff):
    target = ctx.target
    if target is None or creature_attachment.carrier(ctx.engine, target) is not ctx.actor:
        return
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'resist_dislodge', ctx.actor.entity_id, target.entity_id), target,
        'choice:needle.resist_dislodge', ['athletics', 'acrobatics'], name='Scale Foe: resist dislodging', feature_id=SOURCE,
        target_id=ctx.actor.entity_id, labels={'athletics': 'Strength (Athletics)', 'acrobatics': 'Dexterity (Acrobatics)'},
        prompt=f'{ctx.actor.display_name} uses an Action to dislodge {target.display_name}. Choose how to hold on with Scale Foe.',
        automatic=True, allow_decline=False, preferred=preferred_skills(ctx.engine, target))
    from ..typed_executor import resolve_opposed_check
    defense = {'ability': 'STR', 'skill': 'Athletics'} if picked == ['athletics'] else {'ability': 'DEX', 'skill': 'Acrobatics'}
    result = resolve_opposed_check(ctx, target, {'ability': 'STR', 'skill': 'Athletics'}, defense)
    if not result.success:
        return
    from .rider_movement import volume_route
    path = creature_attachment.release_path(ctx.engine, target, ctx.actor)
    if not path:
        note(ctx.engine, SOURCE, target,
             f'{target.display_name} has no space to fall free; the grip holds.', (ctx.actor,))
        return
    volume_route(ctx.engine, target, path, SOURCE)
    creature_attachment.reconcile(ctx.engine, target)
    from ..falling import settle
    settle(ctx.engine, SOURCE, ctx.intent)


@hook('attack_roll_modes')
def carrier_attacks(engine, attacker, target):
    c = creature_attachment.receipt(target)
    return {'DISADVANTAGE'} if c and c.source_definition_id == SOURCE and creature_attachment.carrier(engine, target) is attacker else None


@hook('button_description')
def scale_help(row):
    if any(e.get('type') == 'scale_dislodge' for e in ((row.get('parameters') or {}).get('typed') or {}).get('effects', ())):
        return ('Use an Action to shake off a creature clinging to you. Your Strength (Athletics) opposes its chosen '
                'Strength (Athletics) or Dexterity (Acrobatics). Scale Foe does not give you Disadvantage on this check.')
    if any(e.get('type') == 'scale_foe' for e in ((row.get('parameters') or {}).get('typed') or {}).get('effects', ())):
        return ('Use a Bonus Action to climb onto a creature larger than you. Choose Strength (Athletics) or Dexterity '
                '(Acrobatics), opposed by its Dexterity (Acrobatics), then choose a square in its space and spend ordinary '
                'movement to enter. While clinging, its attacks against you have Disadvantage; dislodging checks do not.')
