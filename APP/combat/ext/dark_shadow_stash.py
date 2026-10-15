"""Shadow Stash uses carry's journaled exact-object relocation contract.

Stored records stay on the inventory owner and omit held_by/hand. The shared
possession, item-use, weight and equipment queries read that same location.
"""
from __future__ import annotations
from typing import Any
from . import effect, hook, note

TALENT = 'TAL_DARK_SHADOW_STASH'
CONDITION = 'condition:typed.shadow_stash'


@hook('stored_item_access')
def stored_item_access(engine, viewer, holder, data):
    """Only a creature that knows Shadow Stash can target its silhouette objects."""
    if not data.get('stashed_by'):
        return None
    return any(action.owner_id == viewer.entity_id
               and (action.parameters.get('typed') or {}).get('source') == TALENT
               for action in engine.action_catalog.values())


def _pounds(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _stashed(engine, actor):
    return [(owner, iid, row) for owner in engine.state.actors.values()
            for iid, row in owner.conditions.items()
            if row.condition_id == CONDITION and (row.data or {}).get('stashed_by') == actor.entity_id]


def _storable(engine, actor, cl):
    """Capacity-filtered query shared by offering and resolving Store."""
    from .scoundrel_riders import possessions
    used = sum(_pounds(row.data.get('weight_lb')) for _, _, row in _stashed(engine, actor))
    return sorted((item for item in possessions(engine, actor)
                   if used + _pounds(item.get('weight_lb')) <= 5 * cl),
                  key=lambda item: bool(item.get('worn')))


@hook('compile_actions')
def shadow_stash_actions(info: dict[str, Any]):
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from ..factory_compiler import RESOURCE_IDS
    if TALENT not in info['owned_ids']:
        return None
    def make(key, name, kind, economy, paid=False):
        return ActionDefinition(source_definition_id=f"action:typed.{info['short']}.shadow_stash.{key}",
            display_name=name, owner_id=info['actor_id'], economy=economy,
            resolution_kind='TYPED', target_kind='SELF',
            costs=((RESOURCE_IDS[info['primary']], 1),) if paid else (),
            parameters={'free_primary': paid, 'ai_repeatable_utility': True,
                        'typed': {'effects': [{'type': kind}], 'numbers': info['numbers'],
                        'duration': {'kind': 'instant'}, 'riders': [], 'source': TALENT}, 'expected_damage': 0})
    return [make('store', 'Shadow Stash: Store an object (Bonus Action)', 'shadow_stash_store', EconomyKind.BONUS_ACTION),
            make('retrieve', 'Shadow Stash: Retrieve an object (Bonus Action)', 'shadow_stash_retrieve', EconomyKind.BONUS_ACTION),
            make('retrieve_paid', 'Shadow Stash: Retrieve an object (1 CP, no action on your turn)',
                 'shadow_stash_retrieve', EconomyKind.NONE, True)]


@hook('candidate_allowed')
def shadow_stash_candidates(engine, actor, _candidate, action):
    typed = (getattr(action, 'parameters', None) or {}).get('typed') or {}
    kinds = {eff.get('type') for eff in typed.get('effects') or []}
    if 'shadow_stash_store' in kinds:
        return bool(_storable(engine, actor, int((typed.get('numbers') or {}).get('cl') or 1)))
    if 'shadow_stash_retrieve' in kinds:
        return bool(_stashed(engine, actor)) and engine.state.current_actor_id == actor.entity_id
    return None


@effect('shadow_stash_store')
def store(ctx, eff):
    from .needle import ask, checkpoint_id
    from .. import carry
    engine, actor = ctx.engine, ctx.actor
    offered = _storable(engine, actor, int((ctx.typed.get('numbers') or {}).get('cl') or 1))
    if not offered:
        return
    picked = ask(engine, ctx.intent, checkpoint_id(engine, 'SHADOW_STASH_STORE', actor.entity_id), actor,
        'choice:needle.shadow_stash_store', [item['object'] for item in offered], allow_decline=True,
        name='Shadow Stash', feature_id=TALENT,
        labels={item['object']: f"Store {item.get('name') or 'the object'} belonging to "
                f"{engine.state.actors[item['object'].split('|', 1)[0]].display_name}" for item in offered},
        prompt=f'Shadow Stash: {actor.display_name} stores one carried object as a Bonus Action. '
               'It becomes weightless and cannot be used or grant bonuses until retrieved.')
    if not picked:
        return
    item = next(row for row in offered if row['object'] == picked[0])
    data = {'item_name': item.get('name') or 'the object', 'weight_lb': str(item.get('weight_lb') or '0'),
            'stashed': 1, 'stashed_by': actor.entity_id}
    if item.get('weapon_action'):
        data['disables_action'] = item['weapon_action']
    carry.relocate_object(engine, item['object'], data, ctx.source, actor.entity_id, CONDITION)
    for creature in engine.state.actors.values():
        carry.refresh(engine, creature, ctx.source)
    note(engine, TALENT, actor, f"{actor.display_name} stores {data['item_name']} inside its shadow.", ())


def _retrieve(engine, actor, intent, source, *, reaction=False, trigger=''):
    from .needle import ask, checkpoint_id
    from . import cp_pools
    from .choice_costs import Payment
    from .. import carry
    rows = _stashed(engine, actor)
    from ..typed_reactions import can_use_reaction, open_reaction
    reaction_row = {'feature_id': TALENT, 'source_id': TALENT, 'block': 'shadow_stash'}
    pool = cp_pools.of(actor, at_least=1) if reaction else None
    if not rows or (reaction and (pool is None or not can_use_reaction(engine, actor, None, reaction_row))):
        return
    payment = Payment(pool, 1) if reaction else None
    picked = ask(engine, intent, checkpoint_id(engine, 'SHADOW_STASH_RETRIEVE', actor.entity_id, trigger), actor,
        'choice:needle.shadow_stash_retrieve', [row.data['object_id'] for _, _, row in rows],
        allow_decline=True, name='Shadow Stash', feature_id=TALENT, payment=payment,
        default='decline' if reaction else 'first',
        labels={row.data['object_id']: f"Retrieve {row.data.get('item_name') or 'the object'}" for _, _, row in rows},
        prompt=f'Shadow Stash: {actor.display_name} retrieves one stored object'
               + (f' as a Reaction for 1 CP (ability energy), during {trigger}.' if reaction else '.'))
    if not picked:
        return
    if reaction:
        from ..activation_payments import reaction_completed
        payment.pay(engine, actor, TALENT)
        if not reaction_completed(engine, actor, TALENT):
            return
        open_reaction(engine, reaction_row, actor, (actor.entity_id,),
                      checkpoint_id(engine, 'SHADOW_STASH_RETRIEVE', actor.entity_id, trigger))
    owner, iid, row = next(entry for entry in rows if entry[2].data['object_id'] == picked[0])
    data = row.data
    carry.relocate_object(engine, data['object_id'],
        {'item_name': data['item_name'], 'held_by': actor.entity_id, 'object_location': 'carried',
         **({'disables_action': data['disables_action']} if data.get('disables_action') and owner != actor else {})},
        source, actor.entity_id, 'condition:typed.carried_item')
    for creature in engine.state.actors.values():
        carry.refresh(engine, creature, source)
    note(engine, TALENT, actor, f"{actor.display_name} retrieves {data['item_name']} from its shadow.", ())


@effect('shadow_stash_retrieve')
def retrieve(ctx, eff):
    _retrieve(ctx.engine, ctx.actor, ctx.intent, ctx.source)


@hook('event', nested=True)
def reaction_retrieval(engine, event_type, kwargs):
    """Offer the paid Reaction at accepted action, move and end-turn checkpoints."""
    if event_type != 'INTENT_ACCEPTED':
        return
    intent = getattr(engine, '_active_intent', None)
    if intent is None:
        return
    action = engine.action_catalog.get(kwargs.get('source_definition_id'))
    for actor in engine.state.actors.values():
        if (action is not None and action.owner_id == actor.entity_id
                and '.shadow_stash.' in action.source_definition_id):
            continue  # Only the acting owner's selected operation must not be preempted.
        if _stashed(engine, actor):
            from ..target_knowledge import located
            acting = engine.state.actors.get(kwargs.get('actor_id'))
            observed = acting is not None and (acting.entity_id == actor.entity_id or located(engine, actor, acting))
            trigger = (getattr(action, 'display_name', None) or 'the current action') if observed else 'another creature’s turn'
            _retrieve(engine, actor, intent, TALENT, reaction=True, trigger=trigger)


@hook('state_event')
def spill_on_death(engine, event):
    """Death (including a lingering soul), not unconsciousness/defeat, spills exact objects.

    Death conditions are written before this checkpoint. Relocation removes each
    stash record before emitting nested events, making repeated death events inert.
    """
    from .life_state import DEAD, SOUL, is_deceased
    if (event.event_type != 'CONDITION_APPLIED'
            or (event.payload or {}).get('condition_id') not in (DEAD, SOUL)):
        return
    from .. import carry
    for actor_id in event.target_ids or ():
        actor = engine.state.actors.get(actor_id)
        if actor is None or not is_deceased(actor):
            continue
        rows = _stashed(engine, actor)
        if not rows:
            continue
        # Objects use one ground cell. Include the dying body and every other
        # creature's footprint; choose deterministically across the finite map.
        occupied = {cell for creature in engine.state.actors.values()
                    if creature.active for cell in engine._actor_cells(creature)}
        occupied.update(engine._actor_cells(actor))
        cells = sorted((max(abs(x - actor.position.x), abs(y - actor.position.y)), x, y)
                       for x in range(engine.grid.width) for y in range(engine.grid.height))
        spot = next(({'x': x, 'y': y, 'z': 0} for _, x, y in cells
                     if engine.grid.placement_legal((x, y), occupied_cells=occupied)), None)
        if spot is None:
            note(engine, TALENT, actor, f'Shadow Stash: no unoccupied space is available for {actor.display_name}’s objects.', ())
            continue
        for _, _, row in rows:
            data = row.data
            carry.relocate_object(engine, data['object_id'],
                {'item_name': data['item_name'], 'dropped_at': spot,
                 **({'disables_action': data['disables_action']} if data.get('disables_action') else {})},
                TALENT, actor.entity_id, carry.DROPPED)
        for creature in engine.state.actors.values():
            carry.refresh(engine, creature, TALENT)
        note(engine, TALENT, actor, f'Shadow Stash: {actor.display_name} dies; its stored objects appear in the nearest unoccupied space.', ())
