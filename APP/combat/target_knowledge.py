"""Observed targeting shared by native attacks, typed attacks and controllers.

Only creation and committed transactions record observations. Candidate/context
reads are pure. A remembered location is an aim, never an assertion that a
creature still occupies it. Historical states without observations know no square.
"""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
from typing import Any

from .gate2_runtime_models import Position
from .read_queries import pure, memo


@dataclass(frozen=True)
class Knowledge:
    mode: str
    position: Position


def concealed(target: Any) -> bool:
    from .stealth import hidden
    return bool(hidden(target) or any(c.condition_id == 'condition:typed.invisible' for c in target.conditions.values()))


@pure
def can_see(engine: Any, viewer: Any, target: Any) -> bool:
    from . import senses
    from .candidate_knowledge import perceived_ids
    permitted = perceived_ids(engine)
    if permitted is not None and target.entity_id not in permitted:
        return False
    # Sight depends on both squares, not only on who is looking and who is seen:
    # a route query projects one creature object across many positions inside
    # one read-only frame. Retain the queried objects too, so a short-lived
    # projected actor's identity cannot be recycled for another footprint. A
    # scoped plug-in sight route can be action-specific (senses.perceives), so
    # the owning action is an input as well.
    from .space import point
    frame = getattr(engine, '_shot_geometry', None)
    sight_action = (str(frame['action'].source_definition_id)
                    if frame and frame.get('actor_id') == viewer.entity_id else None)
    return memo(engine, ('can_see', permitted, id(viewer), point(viewer.position),
                         id(target), point(target.position), sight_action),
                lambda: (viewer, target, viewer.entity_id == target.entity_id or
                         senses.perceives(engine, viewer, target, locate_concealed=True)))[2]


@pure
def located(engine: Any, viewer: Any, target: Any) -> bool:
    """Current perception by sight or a pinpointing sense; never remembered aim.

    Shared by targeting/observation and perception-triggered reactions. A caller
    may project an actor's earlier footprint with model_copy for a step trigger.
    """
    from . import senses
    from .candidate_knowledge import target_allowed
    if not target_allowed(engine, target):
        return False
    return can_see(engine, viewer, target) or senses.pinpoints(engine, viewer, target)


def requires_sight(action: Any) -> bool:
    typed = action.parameters.get('typed') or {}
    return bool(typed.get('requires_seen_target') or action.parameters.get('requires_seen_target'))


def perceives_target(engine: Any, viewer: Any, target: Any, action: Any) -> bool:
    """Current creature perception under an action's explicit targeting contract.

    Default is sight. Compilers may seal requires_perception=True for printed
    perceived-creature selectors; pinpointing senses then suffice, not memories
    or team-shared positions. Explicit seen-target requirements retain priority.
    This never grants sight or waives range/effect-path checks.
    """
    typed = action.parameters.get('typed') or {}
    if typed.get('requires_perception') is True and not requires_sight(action):
        return located(engine, viewer, target)
    return can_see(engine, viewer, target)


def is_attack(action: Any) -> bool:
    typed = action.parameters.get('typed') or {}
    return action.attack_bonus is not None or any(effect.get('type') == 'attack' for effect in typed.get('effects', []))


def sight_bypassed(engine: Any, viewer: Any, target: Any, action: Any) -> bool:
    """Pure owned sight exception, shared by menus and resolution checkpoints.

    This never changes can_see, observations, range, or map barriers.
    """
    from . import ext
    if action is None:
        return False
    replies = ext.run_strict('target_sight_bypass', engine, viewer, target, action)
    if any(type(reply) is not bool for reply in replies):
        raise ValueError('target_sight_bypass must return None or a boolean')
    return True in replies and False not in replies


@pure
def knowledge(engine: Any, viewer: Any, target: Any, action: Any = None) -> Knowledge | None:
    if viewer is target:
        return Knowledge('DIRECT', target.position)  # Self-use needs no outside perception.
    from .candidate_knowledge import target_allowed
    if not engine._on_battlefield(viewer) or not engine._on_battlefield(target) or not target_allowed(engine, target):
        return None
    if sight_bypassed(engine, viewer, target, action):
        return Knowledge('DIRECT', target.position)
    if action is not None and not is_attack(action) and not perceives_target(engine, viewer, target, action):
        return None
    from . import ext
    from .candidate_knowledge import active
    # Personal estimates belong to explicit AI queries, never native/manual
    # targeting or the execution of a chosen intent.
    personal = ext.run_strict('target_personal_knowledge', engine, viewer, target) if active(engine) else []
    if personal:
        answer = personal[0]
        return None if answer is False else answer
    if viewer.team_id == target.team_id:
        return Knowledge('DIRECT', target.position)  # The table shares teammates' current locations.
    if located(engine, viewer, target):
        return Knowledge('DIRECT', target.position)
    if action is not None and not is_attack(action):
        return None
    position = engine.state.observations.get(viewer.team_id, {}).get(target.entity_id)
    return Knowledge('LAST_OBSERVED', position) if position is not None else None


def observe(engine: Any) -> None:
    """Record perceived positions and opt-in freshness; never follow concealment."""
    from . import ext
    refresh = ext.run_strict('target_observation_refresh', engine)
    if any(type(reply) is not bool for reply in refresh):
        raise ValueError('target_observation_refresh must return None or a boolean')
    renew = True in refresh and False not in refresh
    changes: dict[str, dict[str, dict[str, int]]] = {}
    viewers = [actor for actor in engine.state.actors.values() if actor.active and actor.life_state in (None, "CONSCIOUS")]
    for target in engine.state.actors.values():
        for side in sorted({viewer.team_id for viewer in viewers if viewer.team_id != target.team_id}):
            if not any(located(engine, viewer, target) for viewer in viewers if viewer.team_id == side):
                continue
            old = engine.state.observations.get(side, {}).get(target.entity_id)
            if old == target.position and not renew:
                continue
            engine.state.observations.setdefault(side, {})[target.entity_id] = target.position.model_copy()
            changes.setdefault(side, {})[target.entity_id] = target.position.model_dump(mode='json')
    if changes:
        event = engine.events[-1] if engine.events else None
        transaction = getattr(engine, '_transaction_id', None)
        if event is None or (transaction is not None and event.transaction_id != transaction):
            engine._append_event('TARGETS_OBSERVED', 'system:combat.observation', payload={'observations': changes})
        else:
            # Keep ordinary event numbers, candidate tie-breaks and roll identities
            # unchanged. Enrich this transaction's final event, never an older one.
            engine.events[-1] = event.model_copy(update={'payload': {**event.payload, 'observations_after': changes}})

    # General committed observation receipts. Providers return journal-safe
    # primitives; queries never write memories. No provider means no event change.
    for receipt in ext.run_strict('personal_observation_receipt', engine):
        if receipt:
            event = engine.events[-1]
            engine.events[-1] = event.model_copy(update={
                'payload': {**event.payload, 'personal_observations': receipt}})


def actors_for(engine: Any, viewer: Any) -> list[Any]:
    """Controller geometry. Unknown enemies are absent; remembered enemies have no live hidden stats.

    One candidate pass shares the answer for one unchanged viewer and knowledge
    scope. Remembered enemies are projected copies, so rebuilding them per
    sampled square also invalidated every downstream perception key; sharing the
    projection lets sight/obscurement answers for those copies be reused too.
    Callers receive a fresh list of read-only actor records.
    """
    from .read_queries import invariant_query
    from .candidate_knowledge import active, perceived_ids
    from .space import point

    key = ('actors_for', id(viewer), viewer.entity_id, point(viewer.position),
           bool(active(engine)), perceived_ids(engine))
    return list(invariant_query(engine, key, lambda: _actors_for(engine, viewer), refs=(viewer,)))


def _actors_for(engine: Any, viewer: Any) -> list[Any]:
    result = []
    for target in engine.state.actors.values():
        known = knowledge(engine, viewer, target)
        if known is None:
            continue
        if known.mode == 'DIRECT':
            result.append(target)
        else:
            maximum = engine.actor_templates[target.entity_id].maximum_hp
            result.append(target.model_copy(update={'position': known.position, 'current_hp': maximum, 'maximum_hp': maximum,
                'active': True, 'life_state': None,
                'temporary_hp': 0, 'armor_class': 0, 'speed_ft': 0, 'movement_remaining_ft': 0,
                'action_available': False, 'bonus_action_available': False, 'reaction_available': False,
                'resources': {}, 'conditions': {}, 'concentration': None}))
    return result


def movement_contact(engine: Any, viewer: Any, destination: Position) -> bool:
    """Stop a failed path step on an unperceived creature, recording contact cells.

    Match the grid's destination and both diagonal side placements, using the
    mover's complete footprint. Execution calls this for each failed path step;
    a blocker may have become located since the whole path was accepted.
    """
    from itertools import combinations
    from .space import point, position
    start, end = point(viewer.position), point(destination)
    axes = [i for i in range(3) if start[i] != end[i]]
    placements = [position(tuple(end[i] if i in selected else start[i] for i in range(3)))
                  for size in range(1, len(axes)+1) for selected in combinations(axes, size)]
    spatial = bool(viewer.position.z or destination.z or any(a.position.z for a in engine.state.actors.values() if a.active))
    occupied = engine._actor_volume if spatial else engine._actor_cells
    cells = {cell for anchor in placements for cell in occupied(viewer, position=anchor)}
    def encoded(cell):
        return position(cell).model_dump(mode="json")
    found = False
    all_concealed = True
    for target in engine.state.actors.values():
        if (target.entity_id == viewer.entity_id or not target.active or not engine._on_battlefield(target)
                or engine._shared_occupancy_pair(viewer.entity_id, target.entity_id)
                or not cells.intersection(occupied(target))):
            continue
        # Darkness, obstructed sight and missing senses can hide an ordinary
        # creature too. Physical contact confirms occupancy in every such case.
        if not concealed(target) and located(engine, viewer, target):
            continue
        engine.state.observations.setdefault(viewer.team_id, {})[target.entity_id] = target.position.model_copy()
        # Until the next turn, don't offer another path through a square that
        # just physically blocked this mover. This avoids repeated zero-foot moves.
        viewer.turn_flags.setdefault('unseen_blockers', {})[target.entity_id] = target.position.model_dump(mode='json')
        # Contact proves these occupied cells, not the rest of a concealed
        # creature's footprint. Use the same mover/obstacle geometry as execution.
        contacted = cells.intersection(occupied(target))
        learned = {(p['x'], p['y'], p.get('z', 0)) if spatial else (p['x'], p['y'])
                   for p in viewer.turn_flags.get('unseen_contact_cells', [])}
        viewer.turn_flags['unseen_contact_cells'] = [
            encoded(cell) for cell in sorted(learned | contacted)]
        engine._append_event('TARGETS_OBSERVED', 'system:combat.observation', actor_id=viewer.entity_id,
            payload={'observations': {viewer.team_id: {target.entity_id: target.position.model_dump(mode='json')}},
                     'contacted_cells': [encoded(cell) for cell in sorted(contacted)]})
        found = True
        all_concealed = all_concealed and concealed(target)
    if found:
        engine._append_event('PASSIVE_TRIGGERED', 'system:combat.move', actor_id=viewer.entity_id,
            payload={'log': ('Movement stopped on contact with a concealed creature. You now know the occupied space.'
                             if all_concealed else
                             'Movement stopped on contact with an unseen creature. You now know the occupied space.')})
    return found


def recent_events(engine: Any, viewer: Any, events: Any) -> tuple[dict, ...]:
    """Project the journal without internal state snapshots or hidden spatial events.

    Raw events remain authoritative on disk. Removing old spatial events from a
    currently concealed actor is deliberately conservative; it cannot reveal a
    hidden path through an earlier event's embedded reducer state.
    """
    concealed_ids = {target.entity_id for target in engine.state.actors.values()
                     if target.team_id != viewer.team_id and concealed(target)}
    from .knowledge_policy import enabled
    restricted = enabled(engine)
    opponent_ids = {target.entity_id for target in engine.state.actors.values() if target.team_id != viewer.team_id}
    unknown_ids = {target.entity_id for target in engine.state.actors.values()
                   if target.entity_id in opponent_ids and knowledge(engine, viewer, target) is None} if restricted else set()
    result = []
    for event in events:
        if event.source_definition_id == 'system:combat.table_fact':
            continue  # Private authoring and provenance are never model observations.
        # Owner-only learned observations use observer_information. Even their
        # owner receives that permitted projection, never internal source/toxin
        # identity through a model's recent-events context.
        if 'private_information' in event.payload:
            continue
        if event.event_type == 'TARGETS_OBSERVED':
            continue
        if restricted and (event.actor_id in unknown_ids or unknown_ids.intersection(event.target_ids)):
            continue
        document = event.model_dump(mode='json')
        if event.event_type == 'MOVEMENT_COMMITTED' and viewer.team_id not in event.payload.get('observed_by', []):
            continue
        if event.actor_id in concealed_ids:
            continue
        document['payload'] = {key: value for key, value in document['payload'].items()
                               if not key.startswith('gate3_') and key not in {'observations_after', 'personal_observations'}}
        referenced = payload_actor_ids(document['payload'], opponent_ids) if restricted else set()
        if unknown_ids.intersection(referenced):
            continue
        if event.event_type == 'MOVEMENT_COMMITTED':
            # A seen endpoint does not prove every intervening square was seen.
            document['payload'].pop('path', None)
            document['payload'].pop('observed_by', None)
        if concealed_ids.intersection(event.target_ids):
            document['payload'] = {}  # a targeted effect may carry its hidden recipient's geometry
        if restricted and (event.actor_id in opponent_ids or opponent_ids.intersection(event.target_ids) or referenced):
            # Payments and initiative rolls are private even if the actor is seen.
            # Clear their prose too: logs can repeat amounts removed from keys.
            if event.event_type in {'RESOURCE_SPENT', 'RESOURCE_GAINED', 'RESOURCE_RESTORED', 'RESOURCE_EXPIRED', 'INITIATIVE_ROLLED'}:
                document['payload'] = {}
            else:
                document['payload'] = public_opponent_payload(document['payload'])
        result.append(document)
    return tuple(result)


def payload_actor_ids(value: Any, actor_ids: set[str]) -> set[str]:
    """Find creature references outside reducer snapshots, including nested subjects."""
    if isinstance(value, str):
        return {value} if value in actor_ids else set()
    if isinstance(value, dict):
        return set().union(*(payload_actor_ids(item, actor_ids) for item in value.values()))
    if isinstance(value, (list, tuple)):
        return set().union(*(payload_actor_ids(item, actor_ids) for item in value))
    return set()


def public_opponent_payload(value: Any) -> Any:
    """Recursive public journal projection; never mutate authoritative payloads."""
    # Non-resource outcomes (for example damage soak and interception) also
    # carry payments under "spend"; retain their public outcome fields.
    private = {'amount', 'amount_spent', 'spend', 'spent', 'remaining', 'resources', 'resource_remaining',
               'dice', 'die', 'roll', 'rolls', 'modifier', 'modifiers', 'initiative', 'initiative_bonus',
               'roll_counter', 'roll_counter_before', 'roll_counter_after', 'expires_on', 'expires_at',
               'expiry', 'duration', 'created_round', 'created_turn', 'data', 'conditions_after',
               'counter_start', 'counter_end', 'roll_id'}
    if isinstance(value, dict):
        return {key: public_opponent_payload(item) for key, item in value.items()
                if key not in private and not any(word in key.lower() for word in
                    ('expir', 'remaining', 'amount_spent', 'roll_counter', 'initiative'))}
    if isinstance(value, list):
        return [public_opponent_payload(item) for item in value]
    return value


@contextmanager
def attack_aim(engine: Any, actor: Any, target: Any, action: Any):
    """Freeze a nested weapon attack's own aim inside an accepted transaction.

    Free melee and improvised attacks use this instead of inheriting the outer
    action's candidate. The receipt is transient, nestable and restored on
    consent pauses/errors; no candidate, observations or saved state are changed.
    Resolution still uses the shared empty-square and concealment rules.
    """
    previous = getattr(engine, '_nested_attack_aim', None)
    engine._nested_attack_aim = (actor.entity_id, target.entity_id,
                                action.source_definition_id, knowledge(engine, actor, target, action))
    try:
        yield
    finally:
        engine._nested_attack_aim = previous


def location_missed(engine: Any, actor: Any, target: Any, source_id: str, index: int = 1) -> bool:
    """Resolve a frozen accepted aim before defender reactions or creature effects."""
    candidate = getattr(engine, '_active_candidate', None)
    action = engine.action_catalog.get(source_id)
    nested = getattr(engine, '_nested_attack_aim', None)
    if nested is not None and nested[:3] == (actor.entity_id, target.entity_id, source_id):
        from types import SimpleNamespace
        known = nested[3]
        candidate = SimpleNamespace(actor_id=actor.entity_id, source_definition_id=source_id,
            target_ids=(target.entity_id,), destination=known.position if known else None,
            metadata={'target_knowledge': known.mode if known else 'LAST_OBSERVED'})
    if candidate is not None and (candidate.actor_id != actor.entity_id or candidate.source_definition_id != source_id):
        return False
    lost_sight = (action is not None and not is_attack(action) and requires_sight(action) and not can_see(engine, actor, target)
                  and not sight_bypassed(engine, actor, target, action))
    aimed = candidate is not None and candidate.metadata.get('target_knowledge') == 'LAST_OBSERVED' and target.entity_id in candidate.target_ids
    destination = candidate.destination if aimed else None
    if (not aimed and action is not None and is_attack(action)
            and action.target_kind not in {'SELF', 'SELF_OR_CELL', 'CELL'}
            and not located(engine, actor, target)):
        # A visible declaration can become unseen during a reaction. Never
        # follow the new hidden position; use the last committed observation.
        destination = engine.state.observations.get(actor.team_id, {}).get(target.entity_id)
        aimed = destination is not None
    absent = not engine._on_battlefield(target) or (aimed and (destination is None or not target.active or destination != target.position))
    if not lost_sight and not absent:
        return False
    engine._append_event('ATTACK_LOCATION_MISSED', source_id, actor_id=actor.entity_id,
        payload={'destination': destination.model_dump(mode='json') if destination else None,
                 'attack_index': index, 'reason': 'LOST_SIGHT' if lost_sight else 'EMPTY_REMEMBERED_SQUARE',
                 'text': (f'{actor.display_name} cannot see {target.display_name} anymore; the attack misses.' if lost_sight else
                          f'{actor.display_name} attacks the square where they last saw {target.display_name}, but hits nothing.')})
    return True
