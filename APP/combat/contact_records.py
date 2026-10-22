"""Source-bound contact relationships for Handspan and other touch permissions.

Identity and history persist independently of current targeting permission.
Only an owning rule may create a relationship. Queries never create a path,
physical adjacency, perception, or permission to deliver another effect.
"""
from . import ext


def effective_cl(engine, actor, path, nominal):
    """Read explicit source-produced level limits; unrelated paths stay inert."""
    limits = [int(nominal)]
    for condition in actor.conditions.values():
        data = condition.data or {}
        if data.get('level_limit_path') in ('*', path):
            limits.append(int(data['level_limit_cl']))
    return min(limits)


def permitted(engine, origin, subject, *, source, path='', minimum_cl=0, nominal_cl=0, require_identity=True):
    """Pure live spiritual line of effect, without deleting a relationship.

    Plane/concealment/denial facts must be explicit condition data. Map cover
    uses the engine's line of effect; contact_path_allowed providers can deny
    a sealed boundary even where ordinary sight passes through it.
    """
    is_object = hasattr(subject, 'object_id')
    if origin is None or subject is None or not origin.active or (subject.destroyed if is_object else not subject.active):
        return False
    if effective_cl(engine, origin, path, nominal_cl) < minimum_cl:
        return False
    def facts(actor):
        if hasattr(actor, 'object_id'):
            data = actor.component or {}
            return [data, data.get('spiritual_profile') or {}]
        return [c.data or {} for c in actor.conditions.values()]
    mine, theirs = facts(origin), facts(subject)
    planes = [next((d['plane'] for d in reversed(rows) if 'plane' in d), 'material') for rows in (mine, theirs)]
    if planes[0] != planes[1] or (require_identity and any(d.get('perfect_spiritual_concealment') for d in theirs)):
        return False
    if any(d.get('spiritual_contact_denied') for d in mine + theirs):
        return False
    from .targeting import line_of_effect
    clear = (line_of_effect(engine, origin, destination=subject.position) if is_object
             else line_of_effect(engine, origin, target=subject))
    if not clear:
        return False
    return not ext.any_false('contact_path_allowed', engine, origin, subject, source)


def record(engine, origin, subject, *, condition_id, source, expires, source_cl, trigger, slot='practitioner', label=''):
    """Replace one owner's slot, retaining a complete primitive provenance record."""
    from .ext import spirit_traditions as st
    for holder in engine.state.actors.values():
        for held in list(holder.conditions.values()):
            if (held.condition_id == condition_id and held.source_actor_id == origin.entity_id
                    and (held.data or {}).get('ownership_kind', 'practitioner') == slot):
                st.remove(engine, holder, held, 'REPLACED')
    for obj in list(engine.state.objects.values()):
        records = obj.component.get('contact_records') or []
        retained = [r for r in records if not (r['condition_id'] == condition_id and r['origin'] == origin.entity_id
                    and r['ownership_kind'] == slot)]
        if records != retained:
            engine._update_object(obj.model_copy(update={'component': {**obj.component, 'contact_records': retained}}), source, origin.entity_id)
    is_object = hasattr(subject, 'object_id')
    if is_object and str(expires).startswith('END_OF_SOURCE_TURN_AT:'):
        from .ext.effect_durations import token
        expires = token('end', origin.entity_id, int(expires.rsplit(':', 1)[1]))
    data = {'label': label, 'subject': subject.object_id if is_object else subject.entity_id, 'origin': origin.entity_id,
              'origin_feature': source, 'source_cl': int(source_cl), 'created_sequence': int(engine.state.event_sequence),
              'created_round': int(engine.state.round_number), 'expiration': expires,
              'ownership_kind': slot, 'trigger': trigger,
              'line_of_effect': int(permitted(engine, origin, subject, source=source))}
    if is_object:
        # Re-read after replacement; never overwrite an intervening object update.
        current = engine.state.objects[subject.object_id]
        records = [*(current.component.get('contact_records') or []), {**data, 'condition_id': condition_id}]
        engine._update_object(current.model_copy(update={'component': {**current.component, 'contact_records': records}}), source, origin.entity_id)
    else:
        engine._apply_condition(subject, condition_id, source, origin.entity_id, expires_on=expires, data=data)


def refresh(engine, condition_id, *, source, path, minimum_cl, numbers):
    """Refresh persisted line-of-effect status on committed events, never reads."""
    for subject in engine.state.actors.values():
        for held in list(subject.conditions.values()):
            if held.condition_id != condition_id:
                continue
            origin = engine.state.actors.get(held.source_actor_id)
            allowed = int(permitted(engine, origin, subject, source=source, path=path,
                minimum_cl=minimum_cl, nominal_cl=int(numbers(engine, origin).get('cl') or 0)) if origin else False)
            if (held.data or {}).get('line_of_effect') != allowed:
                engine._update_condition_data(subject, held, {**held.data, 'line_of_effect': allowed}, source)
    for obj in list(engine.state.objects.values()):
        records = obj.component.get('contact_records') or []
        updated = []
        for held in records:
            if held['condition_id'] != condition_id:
                updated.append(held)
                continue
            origin = engine.state.actors.get(held['origin'])
            allowed = int(permitted(engine, origin, obj, source=source, path=path, minimum_cl=minimum_cl,
                nominal_cl=int(numbers(engine, origin).get('cl') or 0)) if origin else False)
            updated.append({**held, 'line_of_effect': allowed})
        if updated != records:
            engine._update_object(obj.model_copy(update={'component': {**obj.component, 'contact_records': updated}}), source)


def object_record(engine, origin, obj, condition_id):
    from .ext.effect_durations import due
    return next((r for r in obj.component.get('contact_records') or []
                 if r['condition_id'] == condition_id and r['origin'] == origin.entity_id
                 and not due(engine, r['expiration'])), None)
