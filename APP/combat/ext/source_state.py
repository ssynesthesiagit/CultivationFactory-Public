"""Shared source-state helpers and explicit producers for contact, diagnosis and realm limits.

Shared helper used by ``combat.ext.last_inch_palm``: Contact Reveals
Disturbance reads ``categories`` and publishes ``reveal`` so a diagnosis is
personal knowledge. Other owning Source Rules reach the same facts through the
``source_state`` effect and the ``source_state.categories`` reader.

These effects record only facts declared by an owning Source Rule. They add no
unprinted penalties. Native conditions remain the lifetime/identity authority;
removing or suppressing that condition removes its facts. No display-name or
prose inference is permitted. Unknown categories remain unknown.
"""
from . import effect, hook
from functools import lru_cache
from ..source_state_records import CATEGORIES, normalize_facts, normalize_record

CONDITIONS = {'possessed': 'ordinary_possession', 'cursed': 'curse', 'curse': 'curse',
              'heart_demon': 'heart_demon', 'spiritual_contamination': 'spiritual_contamination',
              'external_controlling_link': 'external_controlling_link',
              'disguised_spirit_body_relation': 'disguised_spirit_body_relation'}


@hook('contact_path_allowed')
def sealed_contact_path(engine, origin, target, source):
    """Explicit sealed map profiles can block contact through visible openings."""
    from ..object_geometry import target_cells
    from ..space import point
    from ..effect_cover import rays
    blocked = set()
    for obj in engine.state.objects.values():
        if obj.destroyed or not (obj.component.get('spiritual_contact_denied')
                or (obj.component.get('spiritual_profile') or {}).get('contact_barrier')):
            continue
        blocked.update(point(cell) for cell in target_cells(engine, obj))
    if not blocked:
        return None
    ends = target_cells(engine, target) if hasattr(target, 'object_id') else engine._actor_volume(target)
    for _, _, ray in rays(engine, engine._effect_volume(origin), ends, purpose='effect'):
        if not blocked.intersection(point(cell) for cell in ray[1:-1]):
            return None
    return False


@effect('source_state')
def apply_source_state(ctx, row):
    """A source's explicit categories/contact/realm facts with its normal expiry.

    ``categories`` maps category to present/absent. Absence means that the source
    actually examined that category, never that no condition happened to match.
    A general state effect is also usable by table-authored native sources.
    """
    from .. import typed_executor as te
    data = normalize_facts(row)
    if row.get('categories'):
        data['recipient_id'] = ctx.actor.entity_id
    subjects = [ctx.actor] if row.get('applies_to') == 'self' else [ctx.target] if ctx.target else list(ctx.targets)
    for target in subjects:
        ctx.engine._apply_condition(target, 'condition:typed.source_state', ctx.source, ctx.actor.entity_id,
            expires_on=te.effect_expiry(ctx, row, target, condition=True) or 'END_OF_HOLDER_NEXT_TURN',
            data={**data, 'label': str(row.get('label') or 'Source effect'), 'source_cl': int(ctx.numbers.get('cl') or 0)})


@hook('match_start')
def table_source_states(engine):
    """Materialize the owner's sealed table declarations as real source state.

    This is a setup record, never an AI decision or a diagnosis guessing a fact.
    The map/arena is retained by the ordinary fight persistence path.
    """
    from ..typed_executor import clock_expiry
    for raw in (engine.battlefield_document or {}).get('source_states') or []:
        row = normalize_record(raw)
        target = engine.state.actors.get(row['target_id'])
        source_actor = row.get('source_actor_id', '')
        if target is None or (source_actor and source_actor not in engine.state.actors):
            raise ValueError('Ongoing source states must name creatures in this match')
        data = {**normalize_facts(row['facts']), 'source_cl': row['source_cl'],
                'label': row.get('label') or 'Ongoing source effect',
                'recipient_id': source_actor or 'system:table'}
        engine._apply_condition(target, 'condition:typed.source_state', row['source_rule'], source_actor,
            expires_on=clock_expiry(engine, 'rounds', row['duration_rounds']), data=data)


def categories(subject, engine=None):
    """Authoritative current category states, never source, cure, names or lore."""
    from ..condition_names import condition_key
    result = {key: 'unknown' for key in CATEGORIES}
    states = list(getattr(subject, 'conditions', {}).values())
    component = getattr(subject, 'component', {}) or {}
    for key in CATEGORIES:
        if component.get('category:' + key) in ('present', 'absent'):
            result[key] = component['category:' + key]
    for held in states:
        for key in CATEGORIES:
            value = (held.data or {}).get('category:' + key)
            if value == 'present' or (value == 'absent' and result[key] == 'unknown'):
                result[key] = value
        key = CONDITIONS.get(condition_key(held.condition_id))
        if key:
            result[key] = 'present'
    if engine is not None:
        for held in [*states, *getattr(subject, 'modifiers', {}).values()]:
            source = held.source_definition_id
            action = engine.action_catalog.get(source)
            source = ((action.parameters.get('typed') or {}).get('source') or source) if action else source
            for key in source_categories().get(source, {}).get('categories', []):
                result[key] = 'present'
    return result


@lru_cache(maxsize=1)
def source_categories():
    import json
    from pathlib import Path
    return json.loads((Path(__file__).parents[1] / 'rules' / 'source_categories.json').read_text())['sources']


def reveal(engine, viewer, subject, source, findings):
    """Persist a category-only observation on its recipient, and private journal."""
    subject_id = getattr(subject, 'entity_id', None) or subject.object_id
    label = getattr(subject, 'display_name', None) or subject.component.get('name', 'spiritual asset')
    data = {'label': f'Contact examination of {label}', 'subject': subject_id,
            'recipient_id': viewer.entity_id,
            'observed_sequence': int(engine.state.event_sequence), **{'category:' + k: v for k, v in findings.items()}}
    # This is a remembered finding at a particular contact, not a live oracle.
    condition_id = 'condition:typed.category_observation:' + subject_id
    engine._remove_condition(viewer, condition_id, source)
    engine._apply_condition(viewer, condition_id,
        source, viewer.entity_id, expires_on='UNTIL_REMOVED', data=data)
    words = '; '.join(f"{key.replace('_', ' ')}: {value}" for key, value in findings.items())
    event = engine._append_event('PASSIVE_TRIGGERED', source, actor_id=viewer.entity_id, target_ids=(subject_id,),
        payload={'recipient_id': viewer.entity_id, 'categories': findings, 'category_observation': 1,
                 'text': f'Contact Reveals Disturbance — {label}: {words}. This reveals categories only.'})
    held = next(c for c in viewer.conditions.values() if c.condition_id == condition_id)
    engine._update_condition_data(viewer, held, {**held.data, 'reveal_sequence': event.sequence}, source)


@hook('personal_memory_events')
def remembered_category_events(engine, viewer):
    sequences = tuple(c.data['reveal_sequence'] for c in viewer.conditions.values()
        if c.condition_id.startswith('condition:typed.category_observation:')
        and c.data.get('recipient_id') == viewer.entity_id and 'reveal_sequence' in c.data)
    return sequences or None


def known_categories(viewer, subject_id):
    """Personal remembered finding, for AI/rule consumers; never read the target.

    Unknown when the creature has never examined that subject. Findings are a
    past observation, not a promise that the state is still present today.
    """
    findings = [c for c in viewer.conditions.values()
                if (c.data or {}).get('recipient_id') == viewer.entity_id
                and (c.data or {}).get('subject') == subject_id
                and c.condition_id.startswith('condition:typed.category_observation:')]
    latest = max(findings, key=lambda c: int(c.data['observed_sequence']), default=None)
    return {key: latest.data.get('category:' + key, 'unknown') if latest else 'unknown' for key in CATEGORIES}
