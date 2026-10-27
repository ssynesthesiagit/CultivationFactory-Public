"""Ordinary simple doors: one free object interaction per turn, then Utilize.

Uses existing match_start, additional_actions, object_targets and object_action hooks. The shared
integer ONCE_PER_TURN_CLAIMED receipt persists the free object interaction budget.
AI strategy is unchanged (player_only); no ability ownership is required.
"""
from . import hook, note
from itertools import product
from .door_state import change_door, closing_blocked
from ..object_rules import simple_door_state, label
from ..object_interaction import FLAG, claim, used


@hook('match_start')
def install_doors(engine):
    from ..gate2_runtime_models import ActionDefinition
    rows = (getattr(engine, 'battlefield_document', None) or {}).get('map_objects') or []
    if not any(simple_door_state(row) is not None for row in rows):
        return
    for operation, payment in product(('open', 'close'), ('free', 'utilize')):
        source = f'system:door.{operation}.{payment}'
        engine.action_catalog[source] = ActionDefinition(
            source_definition_id=source,
            display_name=f'{operation.title()} Door ({"free interaction" if payment == "free" else "Utilize action"})',
            owner_id='*', economy='NONE' if payment == 'free' else 'ACTION',
            resolution_kind='TYPED', target_kind='OBJECT', range_ft=5,
            parameters={'door_interaction': operation, 'door_payment': payment, 'player_only': True,
                        # Match-start catalog entries bypass the compiler's owned-builder seal.
                        'free_primary': payment == 'free',
                        'description': f'{operation.title()} an unlocked, unstuck door within 5 feet. '
                        + ('Uses your one free object interaction this turn.' if payment == 'free'
                           else 'Uses your Action because your free object interaction is already used.')})


@hook('additional_actions')
def offer_doors(engine, actor):
    return [source for source in ('system:door.open.free', 'system:door.close.free',
                                 'system:door.open.utilize', 'system:door.close.utilize')
            if source in engine.action_catalog and door_targets(engine, actor, engine.action_catalog[source])]


@hook('button_description')
def describe_door(action):
    params = action.get('parameters') or {}
    return params.get('description') if params.get('door_interaction') else None


@hook('object_targets')
def door_targets(engine, actor, action):
    params = action.parameters or {}
    operation = params.get('door_interaction')
    if not operation:
        return []
    if used(actor) != (params['door_payment'] == 'utilize'):
        return []
    result = []
    for obj in engine.state.objects.values():
        state = simple_door_state(obj.component or {})
        if (state is None or obj.destroyed or state['door_locked'] or state['door_jammed']
                or bool(state['door_open']) == (operation == 'open')
                or (operation == 'close' and closing_blocked(engine, obj))):
            continue
        result.append(obj.object_id)
    return result


@hook('object_action')
def interact(engine, actor, action, obj, candidate, intent):
    params = action.parameters or {}
    if not params.get('door_interaction'):
        return None
    if obj.object_id not in door_targets(engine, actor, action):
        raise ValueError('This door interaction is no longer available.')
    opening = params['door_interaction'] == 'open'
    change_door(engine, actor, obj, opening, action.source_definition_id)
    if params['door_payment'] == 'free':
        claim(engine, actor, action.source_definition_id)
    note(engine, action.source_definition_id, actor,
         f'{actor.display_name} {"opens" if opening else "closes"} {label(obj)} '
         f'using {"their free object interaction" if params["door_payment"] == "free" else "their Utilize action"}.',
         targets=(obj.object_id,))
    return True
