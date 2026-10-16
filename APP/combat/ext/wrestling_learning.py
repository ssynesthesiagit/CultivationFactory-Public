"""Applying a Slam's one learning-time choice through native source acquisition.

Uses the shared installed-sheet acquisition boundary and the canonical public
prerequisite evaluator. The client selects a canonical talent only; it cannot
grant arbitrary IDs or bypass prerequisites, CL, sphere ownership or the single
learning grant. Source overlays survive journey reopening without replacing
unrelated later sheet changes.
"""
from copy import deepcopy
from pathlib import Path
from . import hook

SOURCE = 'WRESTLING_BASE_APPLYING_A_SLAM'
SPHERE = 'tianxia.sphere.wrestling'


def choices(sheet):
    from canonical_catalog.service import CanonicalCatalogAuthorityService
    fields = sheet.get('spheres_and_talents') or {}
    if SPHERE not in fields.get('sphere_record_ids', ()):
        return []
    paths = sheet.get('path_and_subpath') or {}
    known = fields.get('learned_talent_record_ids') or []
    authority = CanonicalCatalogAuthorityService(Path(__file__).resolve().parents[2])
    projection = authority.creator_projection(target_cl=int(sheet['identity']['cultivation_level']),
        acquired_sphere_ids=fields.get('sphere_record_ids') or [], existing_talent_ids=known,
        path_ids=paths.get('path_record_ids') or [], subpath_or_tradition_ids=paths.get('subpath_record_ids') or [],
        character_feature_ids=paths.get('path_feature_record_ids') or [],
        foundation_or_feature_ids=[sheet['foundation']['foundation_id']] if (sheet.get('foundation') or {}).get('foundation_id') else [])
    return [r for r in projection['talent_dispositions'] if r['owning_canonical_sphere_id'] == SPHERE
        and r['canonical_talent_id'] not in known and r['selectable_now']
        and 'Slam' in authority.get_talent(r['canonical_talent_id']).get('tags', ())]


@hook('journey_acquisition_options')
def options(session, actor_id, source, sheet):
    if source != SOURCE:
        return None
    if SOURCE in session.state['actors'][actor_id].get('source_states', {}):
        return []
    return [{'source': SOURCE, 'label': 'Learn ' + r['display_name'] + ' with Wrestling (no training slot cost)',
             'payload': {'talent_id': r['canonical_talent_id']}} for r in choices(sheet)]


@hook('journey_source_sheet')
def overlay(sheet, session, actor_id):
    state = session.state['actors'][actor_id].get('source_states', {}).get(SOURCE)
    if not state:
        return None
    result = deepcopy(sheet)
    fields = result.setdefault('spheres_and_talents', {})
    if SPHERE not in fields.get('sphere_record_ids', ()):
        return None
    fields['learned_talent_record_ids'] = list(dict.fromkeys([
        *(fields.get('learned_talent_record_ids') or []), state['talent_id']]))
    return result


@hook('journey_acquisition')
def learn(session, actor_id, source, payload, sheet):
    if source != SOURCE:
        return None
    from ..journey import require
    from ..fact_consent_admission import digest
    actor = session.state['actors'][actor_id]
    require(not actor['incapacitated'], 'An incapacitated creature cannot complete this learning choice.')
    require(set(payload) == {'talent_id'} and type(payload['talent_id']) is str,
            'Choose exactly one Slam talent from your available Wrestling learning choices.')
    require(SOURCE not in actor.get('source_states', {}), 'The Wrestling learning choice was already used.')
    legal = {r['canonical_talent_id']: r for r in choices(sheet)}
    require(payload['talent_id'] in legal, 'That Slam does not meet your actual acquired sphere, level or prerequisites.')
    record = {'talent_id': payload['talent_id'], 'source': SOURCE, 'clock': int(session.clock())}
    record['acquisition_id'] = digest(record)
    actor.setdefault('source_states', {})[SOURCE] = record
    updated = overlay(sheet, session, actor_id)
    session.emit('SOURCE_TALENT_LEARNED', actor_id, source=SOURCE, talent_id=record['talent_id'],
        acquisition_id=record['acquisition_id'], training_slots_spent=0)
    return {'sheet': updated, 'acquisition_id': record['acquisition_id']}
