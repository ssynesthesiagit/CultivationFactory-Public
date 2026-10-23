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


def effective_cl(sheet, path):
    identity = sheet.get('identity') or {}
    actual = int(identity.get('cultivation_level') or 1)
    bounds = [actual, int((identity.get('effective_path_cls') or {}).get(path, actual))]
    if 'effective_cl' in identity:
        bounds.append(int(identity['effective_cl']))
    for row in (sheet.get('path_and_subpath') or {}).get('paths', []):
        if isinstance(row, dict) and row.get('path_id') == path:
            bounds.extend([int(row.get('attainment', actual)), int(row.get('effective_cl', actual))])
    return min(bounds)


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
    native_paths = [r for r in paths.get('paths', []) if isinstance(r, dict)]
    if spec['path'] not in [*(paths.get('path_record_ids') or []), *(identity.get('path_ids') or []),
                            *(r.get('path_id') for r in native_paths)]:
        raise ValueError('The character does not own the required Path.')
    if spec.get('subpath'):
        selected = [r.get('subpath_id') for r in paths.get('subpaths', [])
            if isinstance(r, dict) and r.get('owning_path_id') == spec['path']]
        selected += [r.get('subpath_or_tradition_id') for r in native_paths
            if r.get('path_id') == spec['path'] and r.get('subpath_or_tradition_id')]
        if any(s != spec['subpath'] for s in selected):
            raise ValueError('The selected Subpath or replacement progression does not grant this feature.')
    if int(identity.get('cultivation_level') or 1) < spec['minimum_cl']:
        raise ValueError(f"This feature requires CL {spec['minimum_cl']}.")
    present = set(paths.get('path_feature_record_ids') or [])
    if present.intersection(spec.get('replaced_by', ())):
        raise ValueError('The replacement progression replaces this feature; both cannot function together.')
    out = copy.deepcopy(sheet)
    out.setdefault('feature_access', {})[feature_id] = {
        'kind': source['kind'], 'reference': source['reference'].strip(),
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
                if effective_cl(sheet, spec['path']) < spec['minimum_cl']:
                    raise ValueError('Unavailable under the current effective Path CL.')
            except ValueError as exc:
                diagnostics.append(f"Feature unavailable: {exc}")
                continue
        admitted.append(feature_id)
    return admitted
