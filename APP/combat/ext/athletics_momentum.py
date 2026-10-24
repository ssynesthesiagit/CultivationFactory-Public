"""Printed Unwilling Boost: round-scoped, direction-specific movement allowances.

The source creature's actual Strength and size determine the grant. Misses cost
one Bonus Action; hits do not. Assistance is an ally's consensual Reaction attack.
The two free movement buttons spend only momentum, through native movement with
normal hazards, difficult terrain, dragging and Opportunity Attacks. They never
increase Speed or Dash distance. All state is evented condition data.
"""
from contextlib import contextmanager
from . import effect, hook
from .needle import ask, checkpoint_id, cell_id, incapacitated

SOURCE = 'TAL_ATHLETICS_UNWILLING_BOOST'
BLOCK = 'athletics_momentum'
POOL = 'condition:typed.athletics_momentum'


def owns(engine, actor):
    return any(r.get('block') == BLOCK for r in engine.typed_passive_rows.get(actor.entity_id, ()))


@hook('compile_block')
def compile_momentum(block, spec, row, numbers):
    if block == BLOCK:
        return [{**row, 'block': BLOCK}]


def pools(engine, actor, direction=None):
    return [c for c in actor.conditions.values() if c.condition_id == POOL
            and c.data.get('round') == engine.state.round_number
            and (direction is None or c.data.get('direction') == direction)
            and int(c.data.get('half_feet', 0)) > 0]


def feet_label(half_feet):
    whole, half = divmod(half_feet, 2)
    return str(whole) + ('.5' if half else '')


def eligible(engine, attacker, target):
    from ..dynamic_size import current_category
    sizes = ("Tiny", "Small", "Medium", "Large", "Huge", "Gargantuan")
    return (target.active and owns(engine, target) and not incapacitated(target)
            and sizes.index(current_category(engine, attacker)) >= sizes.index(current_category(engine, target)))


def offer(engine, attacker, target, hit, intent):
    if not eligible(engine, attacker, target) or (not hit and not target.bonus_action_available):
        return
    feet = max(5, 5 * ((int(attacker.strength_score) - 10) // 2))
    options = ['horizontal', 'vertical']
    chosen = ask(engine, intent, checkpoint_id(engine, 'unwilling_boost', attacker.entity_id, target.entity_id),
        target, 'choice:needle.athletics.momentum', options,
        labels={'horizontal': f'{feet} feet of horizontal movement this round',
                'vertical': f'{feet_label(feet)} feet of vertical movement this round'},
        name='Unwilling Boost', feature_id=SOURCE, target_id=attacker.entity_id,
        prompt=f'{attacker.display_name}\'s Opportunity Attack {"hits" if hit else "misses"} {target.display_name}. '
               f'Convert it into momentum{ " (spend your Bonus Action)" if not hit else ""}?',
        allow_decline=True, automatic=True, preferred=['horizontal'])
    if not chosen:
        return
    direction = chosen[0]
    if not hit:
        target.bonus_action_available = False
        engine._append_event('PASSIVE_TRIGGERED', SOURCE, actor_id=target.entity_id,
                             payload={'log': f'{target.display_name} uses their Bonus Action to convert a missed Opportunity Attack into momentum.'})
    engine._apply_condition(target, POOL, SOURCE, target.entity_id,
        expires_on=f'START_OF_SLOT_AT:{engine.state.round_number + 1}:0',
        data={'round': engine.state.round_number, 'direction': direction,
              'half_feet': 2 * feet if direction == 'horizontal' else feet,
              'label': f'Unwilling Boost: {direction} momentum'})


@hook('attack_completed')
def opportunity_momentum(engine, notice, intent):
    attacker = engine.state.actors[notice.attacker_id]
    target = engine.state.actors[notice.target_id]
    # Only the owner's provoking movement and the printed assistance exception
    # qualify. Deferred delivery retains the trigger after OA scopes unwind.
    if notice.opportunity and notice.opportunity_trigger in ('movement', 'assistance'):
        offer(engine, attacker, target, notice.hit, intent)


@hook('compile_actions')
def momentum_actions(info):
    if SOURCE not in info['owned_ids']:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    result = []
    for direction in ('horizontal', 'vertical'):
        result.append(ActionDefinition(source_definition_id=f"action:typed.{info['short']}.momentum_{direction}",
            display_name=f'Unwilling Boost: use {direction} momentum', owner_id=info['actor_id'],
            economy=EconomyKind.NONE, resolution_kind='TYPED', target_kind='SELF',
            parameters={'typed': {'source': SOURCE, 'effects': [{'type': 'athletics_momentum_move',
                         'direction': direction}], 'numbers': info['numbers'], 'riders': []}}))
    result.append(ActionDefinition(source_definition_id=f"action:typed.{info['short']}.momentum_assist",
        display_name='Unwilling Boost: ask an ally to assist', owner_id=info['actor_id'],
        economy=EconomyKind.NONE, resolution_kind='TYPED', target_kind='ALLY_OR_SELF',
        parameters={'typed': {'source': SOURCE, 'effects': [{'type': 'athletics_momentum_assist'}],
                    'numbers': info['numbers'], 'riders': []}}))
    return result


@contextmanager
def vertical_scope(engine, actor):
    old = getattr(engine, '_athletics_momentum_mover', None)
    engine._athletics_momentum_mover = actor.entity_id
    try:
        yield
    finally:
        engine._athletics_momentum_mover = old


@hook('movement_step_capability')
def momentum_vertical(engine, actor, previous, destination, mode):
    if mode == 'impulse' and getattr(engine, '_athletics_momentum_mover', None) == actor.entity_id:
        return previous.x == destination.x and previous.y == destination.y and abs(previous.z - destination.z) == 1


def routes(engine, actor, direction, feet):
    if not actor.active or engine._effective_speed(actor) <= 0:
        return []
    from ..gate2_runtime_models import CandidateKind
    from .. import flight
    if direction == 'horizontal':
        # Flight's normal route query prices from the actor's remaining flight
        # allowance (including overrun). A separate grant is a complete budget
        # of its own; ask the native candidate builder to enumerate with it.
        return [c for c in engine._movement_candidates(actor, movement_grant_ft=feet)
                if c.destination.z == actor.position.z
                and all(p.z == actor.position.z for p in c.canonical_path)]
    paths = []
    with vertical_scope(engine, actor):
        for sign in (1, -1):
            path, cost = [actor.position], 0
            for _ in range(int(feet // 5)):
                end = path[-1].model_copy(update={'z': path[-1].z + sign})
                if end.z < 0 or not flight.step_allowed(engine, actor, path[-1], end, mode='impulse', observed=True):
                    break
                cost += flight.step_cost(engine, actor, path[-1], end, 'impulse')
                if cost > feet:
                    break
                path.append(end)
                paths.append(engine._candidate(CandidateKind.MOVE, actor, 'system:combat.move',
                    'Vertical momentum', destination=end, path=tuple(path), movement_cost_ft=cost,
                    metadata={'movement_mode': 'impulse'}))
    return paths


@hook('candidate_allowed')
def momentum_offered(engine, actor, candidate, action):
    typed = (getattr(action, 'parameters', None) or {}).get('typed') or {}
    effects = typed.get('effects') or []
    if not effects:
        return
    kind = effects[0].get('type')
    if kind == 'athletics_momentum_move':
        direction = effects[0]['direction']
        feet = sum(c.data['half_feet'] for c in pools(engine, actor, direction)) // 2
        return None if feet and routes(engine, actor, direction, feet) else False
    if kind == 'athletics_momentum_assist':
        target = engine.state.actors.get(candidate.target_ids[0]) if candidate.target_ids else None
        return None if assistance_allowed(engine, actor, target) else False


def assistance_allowed(engine, owner, ally):
    """Public pure eligibility, shared by offering and paid execution."""
    from ..relations import ALLY, relation
    from ..target_knowledge import can_see, located
    from ..typed_reactions import can_use_reaction, opportunity_profile, opportunity_permitted_against
    if ally is None or ally is owner or relation(engine, owner, ally) != ALLY:
        return False
    row, _, reach = opportunity_profile(engine, ally)
    if row is None:
        return False
    return (eligible(engine, ally, owner) and can_use_reaction(engine, ally, owner, row)
            and opportunity_permitted_against(engine, ally, owner)
            and engine._distance_actor_to_actor(ally, owner) <= reach
            and located(engine, owner, ally) and can_see(engine, ally, owner))


@effect('athletics_momentum_assist', harmful=False)
def assist(ctx, effect_row):
    from ..relations import ALLY, relation
    from .. import typed_reactions
    ally = ctx.target
    if not assistance_allowed(ctx.engine, ctx.actor, ally):
        return
    row = typed_reactions.opportunity_profile(ctx.engine, ally)[0]
    if row is None:
        return
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'momentum_assist', ally.entity_id, ctx.actor.entity_id),
        ally, 'choice:needle.athletics.momentum_assist', ['assist'], labels={'assist': 'Use your Reaction to assist'},
        name='Unwilling Boost: allied assistance', feature_id=SOURCE, target_id=ctx.actor.entity_id,
        prompt=f'{ctx.actor.display_name} asks {ally.display_name} for an assisting Opportunity Attack. Use your Reaction?',
        allow_decline=True, automatic=True)
    if chosen and assistance_allowed(ctx.engine, ctx.actor, ally):
        target_ids = (ctx.actor.entity_id,)
        notice = typed_reactions.opportunity_reaction_notice(ctx.engine, ally, target_ids)
        if notice is None:
            return
        typed_reactions.open_reaction(ctx.engine, row, ally, target_ids,
                                     checkpoint_id(ctx.engine, 'momentum_assist_paid', ally.entity_id),
                                     reaction_notice=notice)
        typed_reactions.opportunity_attack(ctx.engine, ally, ctx.actor, ctx.intent, reaction_opened=True, trigger="assistance")


@effect('athletics_momentum_move', harmful=False)
def move_momentum(ctx, effect_row):
    direction = effect_row['direction']
    held = pools(ctx.engine, ctx.actor, direction)
    half_feet = sum(c.data['half_feet'] for c in held)
    feet = half_feet // 2
    candidates = routes(ctx.engine, ctx.actor, direction, feet)
    if not candidates:
        return
    lookup = {cell_id(c.destination, include_altitude=direction == "vertical"): c for c in candidates}
    from ..target_knowledge import actors_for
    enemies = [a for a in actors_for(ctx.engine, ctx.actor) if a.active and a.team_id != ctx.actor.team_id]
    preferred = sorted(lookup, key=lambda k: (min((ctx.engine.grid.distance_ft(lookup[k].destination, a.position)
                                                 for a in enemies), default=0), lookup[k].movement_cost_ft, k))[:1]
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'momentum_move', ctx.actor.entity_id), ctx.actor,
        'choice:needle.athletics.momentum_destination', list(lookup),
        name=f'Unwilling Boost: {direction} movement', feature_id=SOURCE,
        labels={k: f'Move to square {c.destination.x}, {c.destination.y}'
                  + (f', {5*c.destination.z} feet up' if direction == 'vertical' else '')
                  + f' ({c.movement_cost_ft} feet of movement)' for k, c in lookup.items()},
        prompt=f'Choose where to spend up to {feet_label(half_feet)} feet of {direction} momentum. Ordinary movement is unchanged.',
        allow_decline=True, automatic=True, preferred=preferred)
    if not chosen:
        return
    before = len(ctx.engine.events)
    with vertical_scope(ctx.engine, ctx.actor):
        ctx.engine._resolve_movement(ctx.actor, lookup[chosen[0]], ctx.intent, granted_ft=feet, grant_source=SOURCE)
    spent = sum(int(e.payload.get('granted_cost_ft', 0)) for e in ctx.engine.events[before:]
                if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == ctx.actor.entity_id and e.source_definition_id == SOURCE)
    spent *= 2
    for c in held:
        used = min(spent, c.data['half_feet'])
        if used:
            ctx.actor.conditions.pop(c.instance_id)
            ctx.engine._append_event('CONDITION_REMOVED', SOURCE, actor_id=ctx.actor.entity_id,
                target_ids=(ctx.actor.entity_id,), payload={'condition_id': POOL, 'instance_id': c.instance_id,
                                                         'reason': 'MOMENTUM_SPENT'})
            if c.data['half_feet'] > used:
                ctx.engine._apply_condition(ctx.actor, POOL, SOURCE, ctx.actor.entity_id,
                    expires_on=c.expires_on,
                    data={**c.data, 'half_feet': c.data['half_feet'] - used})
        spent -= used


@hook('button_description', priority=-10)
def momentum_help(row):
    typed = (row.get('parameters') or {}).get('typed') or {}
    for effect_row in typed.get('effects') or ():
        if effect_row.get('type') == 'athletics_momentum_assist':
            return ('Ask one ally whose reach includes you to use its Reaction to make an assisting Opportunity Attack. '
                    'If the attack hits, choose extra movement for this round. If it misses, you must spend your Bonus Action. '
                    'The ally must be at least your size. The amount is 5 feet times its Strength modifier, minimum 5 feet; '
                    'choose horizontal movement or half as much vertical movement.')
        if effect_row.get('type') == 'athletics_momentum_move':
            return ('Use some or all of your remaining ' + effect_row['direction'] + ' momentum before this round ends. '
                    'Choose an open destination. This spends no Action and does not use your ordinary movement; '
                    'Difficult Terrain and Opportunity Attacks still apply. Vertical movement does not keep you airborne.')
