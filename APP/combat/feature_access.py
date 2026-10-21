"""Data-driven acquisition and effective-level admission for restricted features.

Used by table advancement and the combat compiler. A recorded access source is
owned by one character and one feature; GM override does not fabricate it.
"""

EFFECTIVE_LEVEL = 'condition:typed.recorded_effective_cultivation_level'


def effective_cl(actor, base_cl, path_id=None):
    """A recorded suppression may lower effective CL; it never grants levels."""
    limits = [int(base_cl)]
    for condition in actor.conditions.values():
        data = condition.data or {}
        if condition.condition_id == EFFECTIVE_LEVEL and (path_id is None or data.get('path_id') == path_id):
            limits.append(int(data['cl']))
    return min(limits)


def available(actor, row):
    return effective_cl(actor, int(row.get('cl') or 1), row.get('access_path_id')) >= int(row.get('minimum_effective_cl') or 0)


def source_level(engine, actor, source_id):
    """Explicit native Source CL, or known practitioner CL; no invented level 1."""
    if actor is None:
        return None
    ids = [source_id, *actor.action_ids]
    for key in ids:
        action = engine.action_catalog.get(key)
        numbers = (((action.parameters or {}).get('typed') or {}).get('numbers') or {}) if action is not None else {}
        if type(numbers.get('cl')) is int:
            return effective_cl(actor, numbers['cl'])
    return None


def access_source(sheet, record_id, mechanic, source=None):
    """An explicit inheritance/source record or an actually owned access Sphere."""
    if isinstance(source, str) and source.strip():
        return source.strip()
    paths = sheet.get('path_and_subpath') or {}
    known = next((row.get('source') for row in paths.get('feature_access') or [] if row.get('id') == record_id), None)
    if isinstance(known, str) and known.strip():
        return known.strip()
    spheres = set((sheet.get('spheres_and_talents') or {}).get('sphere_record_ids') or [])
    for key in (mechanic.get('acquisition') or {}).get('access_spheres') or []:
        if key in spheres:
            return 'Known ' + key.rsplit('.', 1)[-1].replace('_', ' ').title() + ' Sphere'
    from . import ext
    sources = ext.run_strict('feature_access_source', sheet, record_id, mechanic)
    if any(not isinstance(value, str) or not value.strip() for value in sources):
        raise ValueError('feature_access_source requires an established nonempty source or None')
    if sources:
        return sources[0]
    return None


def status(sheet, record_id, mechanic, source=None, *, effective_cl=None):
    rule = mechanic.get('acquisition') or {}
    identity = sheet.get('identity') or {}
    paths = sheet.get('path_and_subpath') or {}
    cl = int(effective_cl if effective_cl is not None else identity.get('cultivation_level') or 1)
    known_paths = set(identity.get('path_ids') or paths.get('path_record_ids') or [])
    if paths.get('path_record_id'):
        known_paths.add(paths['path_record_id'])
    reasons = []
    if cl < int(rule.get('minimum_cl') or 1):
        reasons.append(f"Requires effective Cultivation Level {rule['minimum_cl']}.")
    if rule.get('path_id') and rule['path_id'] not in known_paths:
        reasons.append('Requires the printed cultivation Path.')
    source = access_source(sheet, record_id, mechanic, source)
    if rule.get('recorded_source') and not (isinstance(source, str) and source.strip()):
        reasons.append('Record the scripture, inheritance, teacher, revelation, scar or Secret event granting access.')
    return {'legal': not reasons, 'gm': False, 'reasons': reasons}


def admit(sheet, ids, mechanics, effective_cl, diagnostics):
    result = []
    for record_id in ids:
        mechanic = mechanics.get(record_id) or {}
        check = status(sheet, record_id, mechanic, effective_cl=effective_cl)
        if mechanic.get('acquisition') and not check['legal']:
            diagnostics.append(f"{mechanic.get('name') or record_id}: {' '.join(check['reasons'])}")
        else:
            result.append(record_id)
    return result


def option(sheet, record_id, mechanic):
    """Acquisition-menu eligibility, with required source input kept explicit."""
    check = status(sheet, record_id, mechanic)
    eligible = status(sheet, record_id, mechanic, source='pending explicit source record')['legal']
    owned = record_id in ((sheet.get('path_and_subpath') or {}).get('path_feature_record_ids') or [])
    return {'id': record_id, 'name': mechanic.get('name'), **check, 'eligible': eligible,
            'known': bool(owned and check['legal']),
            'requires_source': bool((mechanic.get('acquisition') or {}).get('recorded_source') and not access_source(sheet, record_id, mechanic))}
