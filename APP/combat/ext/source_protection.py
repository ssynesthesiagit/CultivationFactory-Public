"""Typed producer for explicitly classified source-owned protection; a shared helper.

Owned by ext/source_records.py, which registers the single `source_protection`
effect name and delegates source-authority rows here.
An author supplies origin and authority in reviewed data. This does not classify
creatures by their type, grant an ability, or infer biology from Poison immunity.
source_authority consumes the saved profile for damage and condition defenses.
"""
from . import hook

CONDITION = 'condition:typed.source_protection'


def protect(ctx, row):
    """Producer for the explicit source-authority row shape.

    `ext/source_records.py` owns the single `source_protection` effect name and
    delegates rows that carry `protection_authority` here, so both declared row
    shapes have exactly one registered owner.
    """
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
