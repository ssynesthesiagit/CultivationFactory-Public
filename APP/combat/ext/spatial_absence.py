"""General temporary absence with native timers, repeat saves and return effects.

The creature remains alive/in initiative; only its battlefield presence changes.
Return records contain JSON primitives and own the exact absence instance. Native
expiry, repeat saves, dispels and concentration release all use one return path.
"""
from . import effect, hook, note

ABSENT = 'condition:typed.spatial_absence'
RETURN = 'condition:typed.spatial_return'


def absent(actor):
    return any(c.condition_id in (ABSENT, RETURN) for c in actor.conditions.values())


def _category(value):
    return str(value or '').strip().lower().rsplit('.', 1)[-1]


def _authority_access(engine, subject, action):
    """Honor an absence's explicit authority categories for a matching/equal-CL source.

    Absence rows opt in with ``authority_access``; actions declare corresponding
    ``authority_categories`` and their effective CL in typed source data. Unknown
    categories or CL fail closed. This shared seam is inert for existing absences.
    """
    held = next((c for c in subject.conditions.values() if c.condition_id == ABSENT), None)
    allowed = set((held.data or {}).get('authority_access') or ()) if held is not None else set()
    typed = ((getattr(action, 'parameters', None) or {}).get('typed') or {})
    # Compiled abilities carry the full sphere id (e.g. "tianxia.sphere.void"); the opt-in lists short
    # categories. Compare on the tail so a real Void/Secret/Samsara row can meet the printed exception.
    categories = {_category(value) for value in typed.get('authority_categories') or ()}
    categories.update(_category(typed.get(key)) for key in ('sphere', 'source_category'))
    if typed.get('interstitial_authority') is True:
        categories.add('interstitial')
    if not allowed.intersection(categories):
        return False
    try:
        source_cl = int((typed.get('numbers') or {}).get('cl'))
        absence_cl = int((held.data or {}).get('authority_cl'))
    except (TypeError, ValueError):
        return False
    return source_cl >= absence_cl


@effect('spatial_absence')
def disappear(ctx, row):
    from ..typed_executor import effect_subjects, effect_expiry
    for subject in effect_subjects(ctx, row, harmful=True):
        if absent(subject):
            continue
        rule = {'no_teleport': True}
        if row.get('incapacitated'):
            rule.update(counts_as_incapacitated=True, no_actions=True, no_reactions=True, speed_zero=True)
        engine = ctx.engine
        # Capture the owning activation before applying incapacitation: for a
        # self-target, lifecycle callbacks can synchronously end it.
        from ..concentration import copies
        starts = copies(ctx.actor, ctx.source)
        expiry = effect_expiry(ctx, row, subject, condition=True) or 'UNTIL_REMOVED'
        if row.get('duration') == 'minutes':
            from ..typed_executor import clock_expiry
            expiry = clock_expiry(engine, 'minutes', int(row.get('amount') or 1))
        label_row = {**row, 'duration': row.get('duration') or ctx.typed.get('duration')}
        data = {'rule': rule, 'label': row.get('label') or
                _absence_label(ctx.action.display_name, label_row, expiry,
                    concentration=bool(ctx.typed.get('duration', {}).get('concentration')))}
        # Authority opt-in is carried onto the live absence so that perception,
        # targeting and damage consult the same record after commit and reload.
        for key in ('authority_access', 'authority_cl'):
            if key in row:
                data[key] = row[key]
        if row.get('repeat_save'):
            data['repeat_save'] = {**row['repeat_save'], 'dc': int(ctx.numbers.get('save_dc') or 10)}
            # This repeat resists this absence, not every consequence in its action.
            if row.get('applies_to') == 'target' and ctx.actor.entity_id != subject.entity_id:
                tags = data['repeat_save'].get('named') or []
                data['repeat_save']['named'] = sorted(set(tags) | {'unwilling_spatial_transport'})
        engine._apply_condition(subject, ABSENT, ctx.source, ctx.actor.entity_id,
            expires_on=expiry, data=data)
        held = next((c for c in subject.conditions.values() if c.condition_id == ABSENT), None)
        if held is None:
            continue
        engine._apply_condition(subject, RETURN, ctx.source, ctx.actor.entity_id,
            expires_on='UNTIL_REMOVED', data={
                'absence_id': held.instance_id, 'origin': subject.position.model_dump(mode='json'), 'rule':dict(rule),
                'effects': row.get('on_return') or [], 'numbers': dict(ctx.numbers),
                'concentration': bool(ctx.typed.get('duration', {}).get('concentration')),
                'end_concentration_start': max(starts) if starts and row.get('end_concentration_on_return') else None,
                'label': _return_label(ctx.action.display_name, label_row, expiry,
                    concentration=bool(ctx.typed.get('duration', {}).get('concentration')))})
        # Applying incapacitation can synchronously end the newly cast spell's
        # concentration before its return record exists (self-targeting casts).
        # Reconcile after installing the record so that this path uses the same
        # exact-instance removal and return lifecycle as later concentration loss.
        if row.get('incapacitated') and row.get('end_concentration_on_return'):
            from ..concentration import copies
            if starts and not copies(ctx.actor, ctx.source):
                _remove_absence_instance(engine, subject, held, ctx.source)
        if row.get('incapacitated') and subject.concentration is not None:
            engine._end_concentration(subject, 'INCAPACITATED')
        from ..zones import sync_inside
        sync_inside(engine, ctx.source)
        note(engine, ctx.source, ctx.actor, f'{subject.display_name} disappears from the battlefield.', targets=(subject,))


def _remove_absence_instance(engine, subject, held, source):
    """Remove this exact absence through the journaled lifecycle event path."""
    current = subject.conditions.get(held.instance_id)
    if current is None or current.condition_id != ABSENT:
        return False
    del subject.conditions[held.instance_id]
    engine._append_event('CONDITION_REMOVED', source, actor_id=current.source_actor_id,
        target_ids=(subject.entity_id,), payload={
            'condition_id': ABSENT, 'instance_id': current.instance_id,
            'reason': 'CONCENTRATION_ENDED_DURING_APPLICATION'})
    return True


def _timing(row, expiry, concentration=False):
    duration = row.get('duration')
    minutes = None
    if isinstance(duration, dict) and duration.get('kind') == 'minutes':
        minutes = int(duration.get('amount') or 1)
    elif duration == 'minutes':
        minutes = int(row.get('amount') or 1)
    repeat = row.get('repeat_save')
    if repeat:
        ability = str(repeat.get('ability') or 'saving throw').upper()
        timing = f"until you succeed on the {ability} save repeated at the end of each of your turns"
        if concentration or row.get('concentration') or (isinstance(duration, dict) and duration.get('concentration')):
            timing += " or the caster's concentration ends"
        if minutes:
            timing += f" (up to {minutes} minute{'s' if minutes != 1 else ''})"
        return timing
    labels = {
        'START_OF_TARGET_NEXT_TURN': 'until the start of your next turn',
        'END_OF_TARGET_NEXT_TURN': 'until the end of your next turn',
        'START_OF_SOURCE_NEXT_TURN': "until the start of the caster's next turn",
        'END_OF_SOURCE_NEXT_TURN': "until the end of the caster's next turn",
        'END_OF_TARGET_TURN': 'until the end of your turn',
        'UNTIL_REMOVED': 'until the effect is ended',
    }
    if expiry.startswith('START_OF_TURN_AT:'):
        return 'until the start of your next turn'
    if expiry.startswith('END_OF_TURN_AT:'):
        return 'until the end of your next turn'
    if expiry.startswith('END_OF_SOURCE_TURN_AT:'):
        return "until the end of the caster's next turn"
    if expiry.startswith('START_OF_SLOT_AT:'):
        return f"for {minutes} minute{'s' if minutes != 1 else ''}" if minutes else 'until its stated duration ends'
    timing = labels.get(expiry, 'until the effect ends')
    if minutes and (concentration or (isinstance(duration, dict) and duration.get('concentration'))):
        return f"while the caster concentrates, up to {minutes} minute{'s' if minutes != 1 else ''}"
    return timing


def _absence_label(name, row, expiry, concentration=False):
    return f"{name}: absent from the battlefield {_timing(row, expiry, concentration)}."


def _return_label(name, row, expiry, concentration=False):
    return f"{name}: returns to the nearest open space when the absence ends ({_timing(row, expiry, concentration)})."


@hook('battlefield_presence')
def presence(engine, actor):
    return False if absent(actor) else None


@hook('perceive_absent_target')
def perceive_absent_target(engine, observer, target):
    """Expose an absent target to observers holding matching authority.

    A qualifying owned action can reveal the creature for discovery; the
    selected action is independently checked by recipient_allowed.
    """
    if not absent(target) or absent(observer) or not observer.active:
        return None
    for source_id in observer.action_ids:
        action = engine.action_catalog.get(source_id)
        if action is not None and _authority_access(engine, target, action):
            return True
    return None


@hook('recipient_allowed')
def recipients(engine, actor, target, action):
    if actor.entity_id != target.entity_id and absent(actor):
        return False
    if absent(target) and action.owner_id != target.entity_id:
        return True if _authority_access(engine, target, action) else False
    return None


@hook('effect_subject_allowed')
def subjects(ctx, row, subject):
    stored = getattr(ctx, 'effect_resolution', 'ordinary') == 'stored_consequence'
    # An absent actor reaches nothing outside a stored consequence, authority or not.
    if subject.entity_id != ctx.actor.entity_id and absent(ctx.actor) and not stored:
        return False
    if subject.entity_id != ctx.actor.entity_id and absent(subject):
        return True if _authority_access(ctx.engine, subject, ctx.action) else False
    return None


@hook('zone_subject_allowed')
def zones(engine, zone, subject):
    owner = engine.state.actors.get(zone.owner_id)
    # An absent owner's zone reaches no one, authorized absent subjects included.
    if owner is not None and absent(owner):
        return False
    if absent(subject):
        action = engine.action_catalog.get(str(zone.source_definition_id or ''))
        return True if _authority_access(engine, subject, action) else False
    return None


@hook('command_reachable')
def command_reachable(engine, owner, group, creature):
    # SELF is the command button's recipient, not the creature it affects.
    return False if absent(owner) or absent(creature) else None


@hook('summon_check')
def summon_check(engine, owner, creature, spot, was_active, source_id):
    # All summon/restore callers share this boundary, including non-typed ones.
    return False if absent(owner) or absent(creature) else None


@hook('candidate_allowed')
def candidates(engine, actor, candidate, action):
    if not absent(actor):
        return None
    if str(candidate.kind) in {'END_TURN', 'HOLD_POSITION', 'DECLINE_REACTION'}:
        return None
    if (str(candidate.kind) == 'MOVE' or action is None or action.target_kind != 'SELF'
            or action.parameters.get('summon_group')):
        return False
    return None


@hook('row_allowed')
def reactions(engine, actor, row):
    return False if absent(actor) else None


@hook('opportunity_allowed')
def opportunity(engine, reactor, mover):
    return False if absent(reactor) or absent(mover) else None


@hook('final_damage')
def damage(engine, target, amount, damage_type, source_id, source_actor_id, intent):
    origin = engine.state.actors.get(source_actor_id)
    stored = getattr(engine, '_effect_resolution_mode', 'ordinary') == 'stored_consequence'
    # A source holding the absence's explicit authority (same category, equal or
    # higher CL) may damage the absent target; every other outside source is cancelled.
    source_action = engine.action_catalog.get(str(source_id or ''))
    authorized = absent(target) and source_action is not None and _authority_access(engine, target, source_action)
    if (absent(target) and source_actor_id != target.entity_id and not authorized) or (not stored and origin is not None and absent(origin) and origin is not target):
        return {'amount': 0}
    return None


def return_creature(engine, subject, record):
    from ..gate2_runtime_models import Position
    from ..typed_executor import Context, run_effects
    origin = Position.model_validate(record.data['origin'])
    occupied = engine._occupied_volumes_except(subject.entity_id)
    cells = [Position(x=x, y=y, z=origin.z) for y in range(engine.grid.height) for x in range(engine.grid.width)]
    # Returns preserve altitude. Validate the complete occupied volume at that
    # altitude, just as the engine's commit invariant does.
    legal = [p for p in cells if engine.grid.volume_legal(p, footprint=engine._footprint(subject), occupied_cells=occupied)]
    if not legal:
        # A full map has no printed legal return yet. Retain the exact record and
        # retry on later turn starts; never occupy another creature's body.
        return False
    destination = min(legal, key=lambda p: (engine.grid.distance_ft(origin, p), p.y, p.x))
    subject.conditions.pop(record.instance_id, None)
    engine._append_event('CONDITION_REMOVED', record.source_definition_id,
        actor_id=record.source_actor_id, target_ids=(subject.entity_id,),
        payload={'condition_id': RETURN, 'instance_id': record.instance_id})
    start = subject.position
    subject.position = destination
    engine._append_event('MOVEMENT_COMMITTED', record.source_definition_id, actor_id=subject.entity_id,
        payload={'destination': destination.model_dump(mode='json'),
                 'path': [start.model_dump(mode='json'), destination.model_dump(mode='json')],
                 'cost_ft': 0, 'teleport': True})
    from ..zones import sync_inside, on_moved
    sync_inside(engine, record.source_definition_id)
    on_moved(engine, subject, start, destination, forced=True, reappeared=True)
    owner = engine.state.actors.get(record.source_actor_id)
    action = engine.action_catalog.get(record.source_definition_id)
    if owner is not None and action is not None:
        ctx = Context(engine, owner, action, getattr(engine, '_active_intent', None),
            {'numbers': record.data['numbers'], 'duration': {'kind': 'instant'}}, [subject], subject,
            effect_resolution='stored_consequence')
        run_effects(ctx, record.data['effects'])
    if owner is not None and record.data.get('end_concentration_start') is not None:
        from ..concentration import end_copy
        end_copy(engine, owner, record.data['end_concentration_start'], 'SPATIAL_RETURN')
    note(engine, record.source_definition_id, subject, f'{subject.display_name} returns to the battlefield.')
    return True


@hook('event', nested=True)
def ending(engine, event_type, kwargs):
    payload = kwargs.get('payload') or {}
    if event_type == 'CONDITION_REMOVED' and payload.get('condition_id') == ABSENT:
        for aid in kwargs.get('target_ids') or ():
            subject = engine.state.actors.get(aid)
            if subject is not None:
                for record in list(subject.conditions.values()):
                    if record.condition_id == RETURN and record.data['absence_id'] == payload.get('instance_id'):
                        return_creature(engine, subject, record)
    elif event_type == 'CONCENTRATION_ENDED':
        from ..concentration import copies, owner_copy
        owner_id = kwargs.get('actor_id')
        owner = engine.state.actors.get(owner_id)
        source = kwargs.get('source_definition_id')
        started = payload.get('started_sequence')
        starts = copies(owner, source, started) if owner is not None else []
        for subject in engine.state.actors.values():
            for record in list(subject.conditions.values()):
                if record.condition_id != RETURN or not record.data['concentration'] or record.source_actor_id != owner_id or record.source_definition_id != source:
                    continue
                if len(starts) > 1 and owner_copy(record.applied_sequence, starts) != started:
                    continue
                held = subject.conditions.pop(record.data['absence_id'], None)
                if held is not None:
                    engine._append_event('CONDITION_REMOVED', source, actor_id=owner_id, target_ids=(subject.entity_id,),
                        payload={'condition_id': ABSENT, 'instance_id': held.instance_id})


@hook('turn_start')
def retry_return(engine, actor):
    for subject in engine.state.actors.values():
        if any(c.condition_id == ABSENT for c in subject.conditions.values()):
            continue
        for record in list(subject.conditions.values()):
            if record.condition_id == RETURN:
                return_creature(engine, subject, record)
