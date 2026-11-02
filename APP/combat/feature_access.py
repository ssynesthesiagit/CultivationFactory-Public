"""Recorded feature acquisition shared by table advancement and combat compilation.

Policies are supplied by feature_access_policy hooks, not guessed from names.
The owner records the actual access source; no Sphere or sibling is granted.
Effective Path CL can suppress use without deleting an acquired relationship.
"""
from __future__ import annotations

import copy


def policy(feature_id):
    from . import ext
    rows = ext.run_strict('feature_access_policy', feature_id)
    if len(rows) > 1:
        raise ValueError('A feature must have one acquisition policy.')
    return rows[0] if rows else None


def display_name(feature_id):
    """Player-facing name for a recorded acquisition, even if its policy is gone."""
    spec = policy(feature_id) or {}
    return spec.get('display_name') or str(feature_id).rsplit('.', 1)[-1].replace('_', ' ').title()


def spec_paths(spec):
    """Return the eligible paths for either form of an access policy."""
    return spec.get('paths') or [spec['path']]


def effective_cl(sheet, path):
    """Effective CL for a path or the best owned path in an access policy."""
    identity = sheet.get('identity') or {}
    actual = int(identity.get('cultivation_level') or 1)
    if isinstance(path, dict):
        paths = sheet.get('path_and_subpath') or {}
        owned = set(paths.get('path_record_ids') or []) | set(identity.get('path_ids') or [])
        candidates = [p for p in spec_paths(path) if p in owned]
    else:
        candidates = [path]
    return max((min(actual, int((identity.get('effective_path_cls') or {}).get(p, actual)))
                for p in candidates), default=0)


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
    required_paths = spec_paths(spec)
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
    return record(copy.deepcopy(sheet), feature_id, source)


def record(sheet, feature_id, source):
    """Write an acquisition without re-validating it.

    Used by table advancement to overlay owner-recorded evidence; compiler
    admission still checks the Path, CL and access source before use.
    """
    out = sheet
    out.setdefault('feature_access', {})[feature_id] = {
        'kind': source['kind'], 'reference': str(source['reference']).strip(),
        'classification': source['classification']}
    ids = out.setdefault('path_and_subpath', {}).setdefault('path_feature_record_ids', [])
    if feature_id not in ids:
        ids.append(feature_id)
    return out


def admit(ids, sheet, diagnostics):
    """General compiler admission; unregistered records keep their old behavior."""
    admitted = []
    for feature_id in ids:
        spec = policy(feature_id)
        if spec is not None:
            try:
                acquire(sheet, feature_id, (sheet.get('feature_access') or {}).get(feature_id))
                if effective_cl(sheet, spec) < spec['minimum_cl']:
                    raise ValueError('Unavailable under the current effective Path CL.')
            except ValueError as exc:
                diagnostics.append(f"Feature unavailable: {exc}")
                continue
        admitted.append(feature_id)
    return admitted
