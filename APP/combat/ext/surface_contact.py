"""Pure shared surface contact query for surface-dependent cultivation benefits.

``contact(engine, actor, materials)`` reads actual grid support and active bodily
rules. The grid's ordinary floor and solid columns represent stable ground.
An authored condition may carry ``surface_contact`` with material, stable and
touching booleans to describe water, wood, or unstable/unsupported footing.
``surface_contact(engine, actor)`` hook providers may return that same mapping
for a richer battlefield. False touching vetoes contact; false stable does
so when stable=True. Material must match the requested lower-case names.
stable=False, standing=False permits explicitly authored touching contact
without stable standing support; absent metadata still requires map support.
No metadata changes ordinary map behavior. Mountain Core is the first consumer.
"""
from . import run_strict


def contact(engine, actor, materials, *, stable=True, standing=True):
    from ..falling import supported
    from ..typed_executor import condition_rules

    if actor is None or not actor.active or (standing and not supported(engine, actor)):
        return False
    rules = condition_rules(actor, engine=engine)
    if any(r.get('incorporeal') or r.get('no_physical_contact') for r in rules):
        return False
    replies = [r['surface_contact'] for r in rules if 'surface_contact' in r]
    replies.extend(run_strict('surface_contact', engine, actor))
    if not replies:
        return supported(engine, actor)
    for row in replies:
        if (not isinstance(row, dict) or set(row) != {'material', 'stable', 'touching'}
                or not isinstance(row['material'], str)
                or type(row['stable']) is not bool or type(row['touching']) is not bool):
            raise ValueError('surface_contact requires material, stable and touching')
        if (stable and not row['stable']) or not row['touching'] or row['material'].lower() not in materials:
            return False
    return True
