"""Public scene-duty contract used by Iron Oath and its companion consumers.

All subjective inputs enter through TabletopService.record_fact's owner-only
native intent. Native damage and voluntary movement supply objective pressure.
No ownership, willingness, threat, scope or actual defense is guessed from tags.
"""
from .table_facts import records
from .gate2_runtime_models import Position
from . import engine_seam as seam


def duties(engine, actor):
    """Known meaningful subjects, keyed by durable table fact record ID."""
    return {key: (fact, defense) for key, fact in records(engine, actor).items()
            for defense in fact.defenses
            if defense.defender_id == actor.entity_id and defense.meaningful}


def declaration_open(engine, actor, fact, defense):
    """Initiative/new-duty opportunity, retained through an initiative wrap.

    A duty appearing after the bearer's turn must not disappear merely because
    the round counter advances before the player can answer. Their next native
    action consumes that deferred opportunity; fact corrections do not reopen it.
    """
    if ((engine.state.round_number == 1 and actor.turns_started <= 1)
            or defense.appeared_round == engine.state.round_number):
        return True
    first = next((e.sequence for e in engine.events if e.event_type == 'TABLE_FACT_RECORDED'
                  and e.payload['fact']['record_id'] == fact.record_id
                  and any(d['defender_id'] == actor.entity_id and d['appeared_round'] == defense.appeared_round
                          for d in e.payload['fact'].get('defenses', []))), None)
    if first is None:
        return False
    active = seam.active_intent_id(engine)
    return not any(e.sequence > first and e.event_type == 'INTENT_ACCEPTED' and e.actor_id == actor.entity_id
                   and e.source_definition_id != 'system:combat.table_fact' and e.trigger_or_intent_id != active
                   for e in engine.events)


def position(engine, fact):
    creature = engine.state.actors.get(fact.subject_id)
    obj = engine.state.objects.get(fact.subject_id)
    return creature.position if creature else obj.position if obj else Position.model_validate(fact.position)


def defending(engine, actor, record_id):
    """Current actual defense, including source corrections and map counterplay."""
    entry = duties(engine, actor).get(record_id)
    if entry is None:
        return False
    fact, defense = entry
    if defense.status != 'defending':
        return False
    subject = engine.state.actors.get(fact.subject_id)
    obj = engine.state.objects.get(fact.subject_id)
    # Combat participation isn't consciousness or eligibility as a protected
    # creature: a fallen helpless ally can still be the very subject defended.
    # The GM's meaningful-duty assessment owns that distinction.
    if obj and obj.destroyed and defense.subject_kind == 'object':
        return False
    point = position(engine, fact)
    if defense.maximum_distance_ft is not None and engine.grid.distance_ft(actor.position, point) > defense.maximum_distance_ft:
        return False
    if defense.requires_sight:
        from .target_knowledge import can_see
        from .senses import perceives_cell
        if not (can_see(engine, actor, subject) if subject else perceives_cell(engine, actor, point)):
            return False
    return True


def power_states(engine, actor):
    """Corrections are source-local; independent suppressions cannot cancel each other.

    Aggregate the strongest remaining power state and all suppressed resources.
    Full severance is durable beyond the scene clock. A restoration updates its
    own record; it never silently erases a separate source's suppression.
    """
    latest = {}
    for event in engine.events:
        if event.event_type != 'TABLE_FACT_RECORDED':
            continue
        document = event.payload['fact']
        latest[document['record_id']] = document
    by_power = {}
    for document in latest.values():
        if actor.entity_id not in document['witness_ids'] or not document.get('active', True):
            continue
        for state in document.get('power_states', []):
            if (state['actor_id'] == actor.entity_id
                    and (state['state'] == 'fully_severed' or document['valid_through_round'] >= engine.state.round_number)):
                by_power.setdefault(state['power_id'], []).append(state)
    result = {}
    def priority(state):
        return (3 if state['state'] == 'fully_severed' else
                2 if state['state'] == 'suppressed' and state.get('scope', 'power') == 'power' else
                1 if state['state'] == 'suppressed' else 0)
    for power, states in by_power.items():
        strongest = max(states, key=priority)
        result[power] = {**strongest, 'resource_ids': sorted({resource for state in states
            if state['state'] != 'available' for resource in state['resource_ids']})}
    return result


def resource_available(engine, actor, resource_id):
    return not any(resource_id in s['resource_ids'] and s['state'] != 'available'
                   for s in power_states(engine, actor).values())


def source_in_scope(engine, actor, source, power_id, scope):
    """Exact native source interpretation; never infer compatibility from a name."""
    return any(s.actor_id == actor.entity_id and s.source_definition_id == source
               and s.power_id == power_id and s.scope == scope
               for fact in records(engine, actor).values() for s in fact.technique_scopes)


def qualified_pressure(engine, actor, record_id, target, *, known_only=False):
    """This combat's real damage/approach or sourced external threat/bypass."""
    entry = duties(engine, actor).get(record_id)
    if entry is None:
        return False
    fact, _ = entry
    pressures = [p for p in fact.subject_pressures if p.actor_id == target.entity_id]
    if any(p.verdict == 'artificial_denied' for p in pressures):
        return False
    if pressures:
        return True
    visible_sequences = None
    if known_only:
        from .target_knowledge import recent_events
        visible_sequences = {e['sequence'] for e in recent_events(engine, actor, engine.events)}
    # Native creatures have a known initial point (the first committed route's
    # start, or their current point if never moved). Objects are introduced by
    # their real OBJECT_UPDATED upsert. External places/duties remain spatially
    # unknown until a sourced scene record supplies their position.
    point = position(engine, fact) if fact.subject_kind == 'creature' else None
    if fact.subject_kind == 'creature':
        first_move = next((e for e in engine.events if e.actor_id == fact.subject_id
                           and e.event_type == 'MOVEMENT_COMMITTED' and e.payload.get('path')), None)
        if first_move:
            point = Position.model_validate(first_move.payload['path'][0])
    for event in engine.events:
        p = event.payload
        if event.actor_id == fact.subject_id and event.event_type == 'MOVEMENT_COMMITTED':
            point = Position.model_validate(p['destination'])
        if event.event_type == 'OBJECT_UPDATED' and fact.subject_id in event.target_ids:
            point = Position.model_validate(p['object']['position'])
        if event.event_type == 'TABLE_FACT_RECORDED' and fact.subject_kind not in {'creature', 'object'}:
            if p['fact']['subject_id'] == fact.subject_id:
                point = Position.model_validate(p['fact']['position'])
        if event.actor_id != target.entity_id:
            continue
        if visible_sequences is not None and event.sequence not in visible_sequences:
            continue
        if event.event_type in {'DAMAGE_COMMITTED', 'OBJECT_UPDATED'} and fact.subject_id in event.target_ids:
            object_damage = p.get('damage') or {}
            if int(p.get('hp_damage') or (object_damage.get('taken') if isinstance(object_damage, dict) else 0) or 0) + int(p.get('temporary_hp_absorbed') or 0) > 0:
                return True
        if event.event_type == 'MOVEMENT_COMMITTED' and point is not None:
            path = p.get('path') or []
            def distance_squared(raw):
                pos = Position.model_validate(raw)
                return sum((getattr(pos, axis) - getattr(point, axis)) ** 2 for axis in ('x', 'y', 'z'))
            for start, end in zip(path, path[1:]):
                if distance_squared(end) < distance_squared(start):
                    return True
    return False
