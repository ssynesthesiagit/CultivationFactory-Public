"""Source-requested ordinary holding/stowing of actual nonweapon possessions.

Uses the same transfer/hand ledger as Scoundrel and the ordinary object-interaction
budget used by doors and grabs. Weapon/shield readiness remains with equipment.
No requesting source means no actions or changed behavior for that character.
Glass Surface consumers request this producer for real held-object acquisition.
"""
from . import effect, hook, run_strict

PREFIX = 'system:combat.carried_item.'


def enabled(engine, actor):
    answers = run_strict('carried_item_interactions', engine, actor)
    if any(type(value) is not bool for value in answers):
        raise ValueError('carried_item_interactions returns bool or None.')
    return any(answers)


def options(engine, actor, operation):
    if not enabled(engine, actor):
        return []
    from ..item_uses import possessions
    from .scoundrel_riders import held_possessions
    from .hand_occupancy import free_hands
    held = {item['object'] for item in held_possessions(engine, actor)}
    if operation == 'hold' and not free_hands(engine, actor):
        return []
    return [item for item in possessions(engine, actor)
        if not item.get('weapon_action') and not item.get('shield') and not item.get('worn')
        and (item['object'] in held) == (operation == 'stow')]


@hook('match_start')
def install(engine):
    if not any(enabled(engine, actor) for actor in engine.state.actors.values()):
        return
    from ..gate2_runtime_models import ActionDefinition
    for operation in ('hold', 'stow'):
        for payment in ('free', 'utilize'):
            source = PREFIX + operation + '.' + payment
            cost = 'free object interaction' if payment == 'free' else 'Utilize Action'
            engine.action_catalog[source] = ActionDefinition(source_definition_id=source,
                display_name=f'{operation.title()} a carried object ({cost})', owner_id='*',
                economy='NONE' if payment == 'free' else 'ACTION', resolution_kind='TYPED', target_kind='SELF',
                parameters={'carried_item_operation': operation, 'carried_item_payment': payment,
                    'free_primary': payment == 'free',
                    'typed': {'effects': [{'type': 'carried_item_reposition'}], 'numbers': {}, 'riders': []},
                    'description': f'{operation.title()} one of your actual carried objects '
                        + ('in a free hand' if operation == 'hold' else 'in an accessible carried location')
                        + f'. Uses your {cost}; does not activate or use the object.'})


@hook('additional_actions')
def actions(engine, actor):
    from ..object_interaction import used
    payment = 'utilize' if used(actor) else 'free'
    return [source for operation in ('hold', 'stow')
        if (source := PREFIX + operation + '.' + payment) in engine.action_catalog
        and options(engine, actor, operation)]


@hook('candidate_allowed')
def allowed(engine, actor, candidate, action):
    if action is None or not action.source_definition_id.startswith(PREFIX):
        return None
    from ..object_interaction import used
    params = action.parameters
    return ((params['carried_item_payment'] == 'utilize') == used(actor)
        and bool(options(engine, actor, params['carried_item_operation'])))


@effect('carried_item_reposition')
def reposition(ctx, row):
    from .needle import ask, checkpoint_id
    from .scoundrel_riders import transfer_object, REPOSITION, held_possessions
    from .hand_occupancy import free_hands
    from ..object_interaction import used, claim
    params = ctx.action.parameters
    if (params['carried_item_payment'] == 'utilize') != used(ctx.actor):
        raise ValueError('Refresh your available object interactions.')
    operation = params['carried_item_operation']
    pool = options(ctx.engine, ctx.actor, operation)
    if not pool:
        return
    selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'CARRIED_ITEM', operation, ctx.actor.entity_id),
        ctx.actor, 'choice:needle.carried_item', [item['object'] for item in pool],
        labels={item['object']: f'{operation.title()} {item.get("name") or "this object"}' for item in pool},
        preferred=[pool[0]['object']], name=ctx.action.display_name,
        prompt=ctx.action.parameters['description'] + ' Choose the object.')
    if not selected:
        return
    item = next(item for item in pool if item['object'] == selected[0])
    location = 'carried'
    if operation == 'hold':
        hands = free_hands(ctx.engine, ctx.actor)
        if not hands:
            return
        hand = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'CARRIED_ITEM_HAND', ctx.actor.entity_id),
            ctx.actor, 'choice:needle.carried_item_hand', list(hands),
            labels={part: f'Your free hand {i + 1}' for i, part in enumerate(hands)}, preferred=list(hands[:1]),
            name='Hold a carried object', prompt='Choose a free hand for this object. This uses the same object interaction.')
        if not hand:
            return
        location = 'hand:' + hand[0]
    # Self relocation uses the same physical identity and retained hand record;
    # no inventory row, ownership, item use or attack receipt is fabricated.
    from dataclasses import replace
    transfer_object(replace(ctx, target=ctx.actor, targets=[ctx.actor]), {'as': REPOSITION, 'from': 'thief', 'item': item['key'],
        'object': item['object'], 'destination_location': location, 'ability': ctx.action.display_name})
    held = any(value['object'] == item['object'] for value in held_possessions(ctx.engine, ctx.actor))
    if held != (operation == 'hold'):
        raise ValueError('The selected object did not reach its chosen carried location.')
    if params['carried_item_payment'] == 'free':
        claim(ctx.engine, ctx.actor, ctx.source)
