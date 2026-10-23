"""Recorded feature acquisition shared by table advancement and combat compilation.

Policies are supplied by feature_access_policy hooks, not guessed from names.
The owner records the actual access source; no Sphere or sibling is granted.
"""
from __future__ import annotations

import copy


def policy(feature_id):
    from . import ext
    rows = ext.run_strict('feature_access_policy', feature_id)
    if len(rows) > 1:
        raise ValueError('A feature must have one acquisition policy.')
    return rows[0] if rows else None


def acquire(sheet, feature_id, source):
    """Return a new acquired sheet after validating a real, explicit source.

    This is an owner/GM authoring operation. Source references are evidence,
    never automatic permission inferred from a title or free-form label.
    """
    spec = policy(feature_id)
    if spec is None:
        raise ValueError('This feature has no recorded acquisition policy.')
    if not isinstance(source, dict) or source.get('kind') not in spec['source_kinds']:
        raise ValueError('Record a legal access source: ' + ', '.join(spec['source_kinds']) + '.')
    if not str(source.get('reference') or '').strip() or source.get('classification') != spec['classification']:
        raise ValueError('Record the explicit access classification and its source reference.')
    identity = sheet.get('identity') or {}
    paths = sheet.get('path_and_subpath') or {}
    required_paths = spec.get('paths') or [spec['path']]
    if not set(required_paths).intersection([*(paths.get('path_record_ids') or []), *(identity.get('path_ids') or [])]):
        raise ValueError('The character does not own the required Path.')
    if int(identity.get('cultivation_level') or 1) < spec['minimum_cl']:
        raise ValueError(f"This feature requires CL {spec['minimum_cl']}.")
    from . import ext
    projected = ext.run_strict('feature_access_projection', sheet, feature_id, source)
    if len(projected) > 1:
        raise ValueError('A source must have one acquisition projection.')
    if projected:
        return projected[0]
    out = copy.deepcopy(sheet)
    out.setdefault('feature_access', {})[feature_id] = {
        'kind': source['kind'], 'reference': source['reference'].strip(),
        'classification': source['classification']}
    ids = out.setdefault('path_and_subpath', {}).setdefault('path_feature_record_ids', [])
    if feature_id not in ids:
        ids.append(feature_id)
    return out
