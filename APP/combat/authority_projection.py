"""Native NS1R acquisition -> combat-sheet bridge.

Used by compile_project_character for callers with a persisted authority project.
Feature ownership comes from the service's revalidated state and source progressions,
never from feature IDs submitted in the accompanying statistics/equipment sheet.
The ordinary portable-sheet compiler remains available to exported characters.
"""
from copy import deepcopy


def project_sheet(authority, project_id, sheet):
    from app.core import FoundryError

    state = authority.get_state(project_id, create_legacy_shell=False)
    if not state.get('readiness', {}).get('ready'):
        raise FoundryError('COMBAT_ACQUISITION_NOT_READY',
                           'Resolve the character’s Path, Method and access requirements before starting combat.',
                           details={'blockers': state.get('readiness', {}).get('blockers') or []})
    out = deepcopy(sheet)
    active = [row for row in state['paths'] if row['status'] == 'ACTIVE']
    paths, subpaths, ids, source_cls = [], [], [], {}
    for row in active:
        path_id, level = row['path_id'], row['attainment']
        paths.append({'path_id': path_id, 'attainment': level, 'effective_cl': level,
                      'key_ability': out.get('identity', {}).get('key_ability', 'INT')})
        profile = authority.project_locked_path_catalog_record(path_id)
        stage = profile['compatibility']['factory']['stage2_authority']
        for cl, grant in stage['progression_by_cl'].items():
            if int(cl) <= level:
                ids.extend(grant.get('feature_record_ids') or [])
                source_cls.update({feature: level for feature in grant.get('feature_record_ids') or []})
        selection = row.get('subpath_or_tradition_id')
        if selection:
            record = authority.project_locked_subpath_catalog_record(selection)
            if record['owning_path_id'] != path_id:
                raise FoundryError('COMBAT_PATH_OWNER_INVALID', 'The Subpath belongs to another Path.')
            subpaths.append({'subpath_id': selection, 'owning_path_id': path_id})
            progression = record['compatibility']['factory']['stage2_authority']['feature_progression']
            ids.extend(feature['canonical_id'] for feature in progression
                       if int(feature['granted_at_cl']) <= level)
            source_cls.update({feature['canonical_id']: level for feature in progression
                               if int(feature['granted_at_cl']) <= level})
    out['path_and_subpath'] = {'path_record_ids': [row['path_id'] for row in paths],
                              'paths': paths, 'subpaths': subpaths,
                              'path_feature_record_ids': list(dict.fromkeys(ids)),
                              'source_cl_by_feature': source_cls}
    out.setdefault('identity', {})['cultivation_level'] = state['target_cl']
    definitions = []
    for row in active:
        resource = row['resource']
        if type(resource.get('maximum')) is not int or type(resource.get('current')) is not int:
            raise FoundryError('COMBAT_RESOURCE_UNRESOLVED', 'Record each active Path resource before starting combat.')
        definitions.append({'name': resource['resource_name'], 'maximum': resource['maximum'],
                            'current': resource['current']})
    stats = out['ability_scores_and_statistics']
    primary = (stats.get('primary_resource') or {}).get('name', '').lower()
    chosen = next((row for row in definitions if row['name'].lower() == primary), None)
    if chosen is None:
        raise FoundryError('COMBAT_PRIMARY_PATH_INACTIVE', 'Choose an active Path as the primary combat resource.')
    stats['primary_resource'] = {**chosen, 'build_state_current': chosen['current'], 'definitions': definitions}
    return out


def compile_project_character(authority, project_id, sheet, **kwargs):
    """Compile native acquired ownership and preserve the recorded (not refilled) pools."""
    from .factory_compiler import compile_character
    from .gate2_runtime_models import ResourceDefinition
    from .canonical import canonical_sha256

    projected = project_sheet(authority, project_id, sheet)
    bundle = compile_character(projected, **kwargs)
    levels = projected['path_and_subpath']['source_cl_by_feature']

    def stamp(node):
        if isinstance(node, list):
            for child in node:
                stamp(child)
        elif isinstance(node, dict):
            feature = node.get('option_of') or node.get('feature_id') or node.get('source')
            if isinstance(feature, str) and isinstance(node.get('numbers'), dict):
                level = levels.get(feature.split('#', 1)[0])
                if level is not None and 'source_cl' not in node['numbers']:
                    node['numbers'] = {**node['numbers'], 'source_cl': level}
            for child in node.values():
                stamp(child)

    # Source authority is an owning-Path fact, separate from character level.
    # Keep ordinary compiler statistics/scaling and seal the explicit source
    # level for min-CL admission and consumers performing authority contests.
    stamp(bundle)
    by_name = {row['name'].lower(): row for row in
               projected['ability_scores_and_statistics']['primary_resource']['definitions']}
    # The portable compiler starts a fresh fight at maximum. A live authority
    # project has explicit current values; carry them without restoring a point.
    for resource in bundle['actor_template']['resources']:
        row = by_name.get(resource['resource_id'].removeprefix('resource:core.'))
        if row is not None:
            resource['initial'] = row['current']
            ResourceDefinition.model_validate(resource)
    bundle.pop('bundle_sha256', None)
    bundle['bundle_sha256'] = canonical_sha256(bundle)
    return bundle
