"""Compile native selected Subpath progressions, never guess from sphere ownership.

A sheet that records a Subpath selection -- the connected sheet's parent-bound
``paths[].subpaths`` rows and NonSphereAuthority's acquired Path row
(``subpath_or_tradition_acquisition_provenance``) -- grants that Subpath's
printed feature progression here, at compile time only. The bundle it produces
is immutable, so combat and reload never re-read the index.

Nothing is granted without an authenticated selection bound to an owning Path
the sheet itself carries: an absent or wrong parent, an unselected Subpath, a
future tier or a suppressed (effective-CL-reduced) Path yields no ability.
Sheets that own features directly (``path_feature_record_ids``) keep their
existing ownership contract and never pass through this adapter.
"""
import json
from functools import lru_cache
from pathlib import Path


def progression_index(app):
    app = Path(app)
    files = [app / 'non_sphere_authority/authority/Tianxia_Subpath_Tradition_Index_Master_P2B.json',
             *sorted((app / 'non_sphere_authority/authority/owner_subpaths.d').glob('*.json'))]
    stamps = tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in files)
    return _progression_index(str(app), stamps)


@lru_cache(maxsize=4)
def _progression_index(app, stamps):
    from non_sphere_authority.owner_subpaths import load_owner_subpaths
    app = Path(app)
    rows = json.loads((app / 'non_sphere_authority/authority/Tianxia_Subpath_Tradition_Index_Master_P2B.json').read_text())['entries']
    additions, _ = load_owner_subpaths(app, [row['canonical_id'] for row in rows])
    return {row['canonical_id']: row for row in [*rows, *additions]}


def acquired_features(sheet, app, *, include_unavailable=False):
    """Feature -> {cl, min_cl} for authenticated native selections.

    NS1R admission supplies recorded acquisition provenance; connected sheets
    supply parent-bound subpaths and selected paths. The granted level is the
    lowest of the identity's Cultivation Level and the owning Path row's
    attainment and effective CL, so a suppressed Path never reopens a tier.
    """
    paths = sheet.get('path_and_subpath') or {}
    rows = [row for row in paths.get('paths', []) if isinstance(row, dict)]
    parents = {row.get('path_id'): row for row in rows}
    parents.update({key: {} for key in paths.get('path_record_ids', []) if key not in parents})
    selected = [(row.get('subpath_id'), row.get('owning_path_id'))
                for row in paths.get('subpaths', []) if isinstance(row, dict)]
    for row in rows:
        if (row.get('subpath_or_tradition_acquisition_provenance') or {}).get('recorded') is True:
            selected.append((row.get('subpath_or_tradition_id'), row.get('path_id')))
    if not selected or not parents:
        return {}
    index = progression_index(str(app))
    identity = sheet.get('identity') or {}
    default_cl = int(identity.get('cultivation_level') or identity.get('cl') or 1)
    grants = {}
    for sid, parent in selected:
        source = index.get(sid)
        if source is None:
            continue
        valid_parent = parent in parents and source['owning_path_id'] == parent
        row = parents.get(parent, {})
        level = min(default_cl, int(row.get('attainment', default_cl)), int(row.get('effective_cl', default_cl)))
        if not valid_parent:
            level = 0
        if 'effective_cl' in identity:
            level = min(level, int(identity['effective_cl']))
        for feature in source['feature_progression']:
            if include_unavailable or int(feature['granted_at_cl']) <= level:
                grants[feature['canonical_id']] = {'cl': level, 'min_cl': int(feature['granted_at_cl'])}
    return grants
