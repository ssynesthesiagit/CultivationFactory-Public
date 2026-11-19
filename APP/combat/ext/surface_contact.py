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


SOLID_MATERIALS = frozenset({'earth', 'stone', 'metal', 'wood', 'ice', 'glass', 'crystal', 'bone'})


def _contacts(engine, actor):
    from ..typed_executor import condition_rules
    rules = condition_rules(actor, engine=engine)
    replies = [r['surface_contact'] for r in rules if 'surface_contact' in r]
    replies.extend(run_strict('surface_contact', engine, actor))
    for row in replies:
        if (not isinstance(row, dict) or not {'material', 'stable', 'touching'} <= set(row)
                or set(row) - {'material', 'stable', 'touching', 'solid', 'surface_id'}
                or not isinstance(row['material'], str)
                or type(row['stable']) is not bool or type(row['touching']) is not bool
                or ('solid' in row and type(row['solid']) is not bool)
                or ('surface_id' in row and (not isinstance(row['surface_id'], str) or not row['surface_id']))):
            raise ValueError('surface_contact requires material, stable and touching; optional solid and surface_id')
    return rules, replies


def contact(engine, actor, materials, *, stable=True, standing=True, solid=False):
    from ..falling import supported

    if actor is None or not actor.active or (standing and not supported(engine, actor)):
        return False
    rules, replies = _contacts(engine, actor)
    if any(r.get('incorporeal') or r.get('no_physical_contact') for r in rules):
        return False
    if not replies:
        return supported(engine, actor)
    for row in replies:
        if ((stable and not row['stable']) or not row['touching']
                or (materials is not None and row['material'].lower() not in materials)
                or (solid and not row.get('solid', row['material'].lower() in SOLID_MATERIALS))):
            return False
    return True


def solid_contact(engine, actor):
    """Solid bodily contact for Avatar and Heaven-Drum, including authored touching without standing."""
    return contact(engine, actor, None, stable=False, standing=False, solid=True)


def connected_contact(engine, first, second):
    """Heaven-Drum's solid connection: explicit continuous-surface identities or native geometry.

    A surface_id names one authored continuous component, never just a material.
    Both contacts must name the same component. Untagged contacts require actual
    support and the native floor/finite-column/solid-roof connection; unsupported touching
    alone cannot establish a connection. Cell probes use native geometry unless
    a surface_contact provider supplies their authored component.
    """
    from ..surface_contact import connected
    if not solid_contact(engine, first) or not solid_contact(engine, second):
        return False
    identities = []
    for actor in (first, second):
        _, rows = _contacts(engine, actor)
        identities.append({row['surface_id'] for row in rows if 'surface_id' in row})
    if any(identities):
        return len(identities[0]) == len(identities[1]) == 1 and identities[0] == identities[1]
    return connected(engine, first, second)
