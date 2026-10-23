"""Typed producer for explicitly classified source-owned protection.

An author supplies origin and authority in reviewed data. This does not classify
creatures by their type, grant an ability, or infer biology from Poison immunity.
source_authority consumes the saved profile for damage and condition defenses.

The effect name is ``source_protection_profile``: ``source_protection`` is the
older source-record producer in ``source_records.py`` (category/ordinary/scope),
and one effect name may have only one registration.
"""
from . import effect, hook

CONDITION = 'condition:typed.source_protection'


@effect('source_protection_profile')
def protect(ctx, row):
    from ..typed_executor import effect_subjects, effect_expiry
    profile = dict(row.get('protection_authority') or {})
    if profile.get('origin') not in {'ordinary_biology', 'cultivated', 'unknown'}:
        raise ValueError('source_protection requires an explicit origin')
    if profile.get('authority') not in {'ordinary', 'artifact', 'immortal', 'secret', 'conceptual', 'absolute', 'heavenly', 'world_law'}:
        raise ValueError('source_protection requires an explicit authority')
    profile['source_cl'] = int(profile.get('source_cl', ctx.numbers.get('cl', 0)))
    for subject in effect_subjects(ctx, row, harmful=False):
        expires = effect_expiry(ctx, row, subject, condition=True)
        if not expires:
            raise ValueError('source_protection requires an explicit duration')
        ctx.engine._apply_condition(subject, CONDITION, ctx.source, ctx.actor.entity_id,
            expires_on=expires,
            data={'protection_authority': profile,
                  'rule': {'condition_immunities': list(row.get('conditions') or [])},
                  'defenses': list(row.get('defenses') or []),
                  'label': str(row.get('label') or ctx.action.display_name)})


@hook('damage_defenses')
def defenses(engine, target, kind, typed, source_actor_id):
    return [{**row, 'protection_authority': held.data['protection_authority']}
            for held in target.conditions.values() if held.condition_id == CONDITION
            for row in held.data.get('defenses', ())]
