"""Compile native selected Subpath progressions, never guess from sphere ownership.

Both the connected sheet's parent-bound selections and NonSphereAuthority's
acquired Path rows use this adapter. Source progression is read only at compile
time; combat and reload use the resulting immutable bundle. Explicit historical
feature-only sheets retain their existing ownership contract.
"""
import json
from functools import lru_cache
from pathlib import Path

# The Subpath index's printed Source CL basis (Tianxia_Subpath_Tradition_Index_Master_P2B.json,
# feature_progression entries): every Subpath feature's numbers scale by the owning Path's
# current effective CL unless the feature's own text prints otherwise. A general, data-keyed
# rule, read per record -- consumers must key on this constant, never on one Subpath's id.
PATH_CL_BASIS = 'current_effective_owning_path_cl_unless_feature_prints_otherwise'


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


def subpath_feature_index(app):
    """Every printed Subpath feature id -> its owning Subpath id, across all Subpaths.

    A general source-level index: a feature in this map is admitted only by a
    real selection of its own Subpath at or above the feature's printed level
    (or an explicit owner-recorded native admission), never merely because some
    other record or occurrence list named its id.
    """
    return {feature['canonical_id']: row['canonical_id']
            for row in progression_index(str(app)).values()
            for feature in row.get('feature_progression') or ()
            if feature.get('canonical_id')}


def admit_subpath_features(ids, app, grants, *, explicit_admissions=()):
    """Source-level admission for every printed Subpath feature id.

    ``grants`` maps feature id -> owning Path effective CL for a real selection
    at or above the feature's printed level. A printed Subpath feature whose own
    Subpath was not selected (or is below that level) never reaches the
    character, whatever other id source named it. An explicit owner-recorded
    native admission (``source_acquisition``) is honoured as its own route.
    Ids that are not printed Subpath features (spheres, talents, foundations)
    pass through unchanged.
    """
    printed = subpath_feature_index(app)
    admitted = set(explicit_admissions)
    return [key for key in ids
            if key not in printed or key in grants or key in admitted]


def acquired_features(sheet, app, *, include_unavailable=False):
    """Feature -> {cl, min_cl, source_cl_basis} for authenticated native selections.

    NS1R admission supplies recorded acquisition provenance; connected sheets
    supply parent-bound subpaths and selected paths. An absent/wrong parent,
    unselected subpath, future tier or suppression never grants an ability.
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
                grants[feature['canonical_id']] = {
                    'cl': level, 'min_cl': int(feature['granted_at_cl']),
                    # The record's printed Source CL basis, for general CL-scaling keying.
                    'source_cl_basis': str(feature.get('source_cl_basis') or '')}
    return grants
