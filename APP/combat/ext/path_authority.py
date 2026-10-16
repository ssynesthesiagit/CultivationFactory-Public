"""Effective owning-Path CL from sealed acquisition and explicit table rulings.

Consumers: Drunken Fist activation/dormancy and future Path providers. Compilation
records known acquired Paths, never a Path guessed from an ability's flavor.
The journey command records the table owner's external Realm Suppression ruling;
no AI inference supplies it. A ruling lasts this scene or until replaced. Combat
uses a replayed condition. Paid states and their original Source CL are untouched.
"""
from copy import deepcopy
from . import hook, effect

BLOCK = 'path_authority'
CONDITION = 'condition:typed.path_effective_cl'


def bundle_levels(bundle):
    return {r['path_id']: r for r in bundle.get('typed_passives', []) if r.get('block') == BLOCK}


@hook('compile_passives')
def compile_levels(rows, info):
    paths = set((info.get('owner_sheet',{}).get('path_and_subpath') or {}).get('path_record_ids') or []) | {fid.split('.feature.')[0] for fid in info['owned_ids'] if fid.startswith('tianxia.path.') and '.feature.' in fid}
    declarations = (info.get('owner_sheet', {}).get('path_and_subpath') or {}).get('paths') or []
    declared = {p['path_id']: p for p in declarations if isinstance(p, dict) and isinstance(p.get('path_id'), str)}
    result = list(rows)
    for path in sorted(paths):
        declaration = declared.get(path, {})
        candidates=[declaration[k] for k in ('attained_cl','attainment','owning_path_level') if k in declaration]
        if candidates and (any(type(n) is not int for n in candidates) or len(set(candidates))!=1):
            raise ValueError('Acquired Path attainment declarations must be integer and consistent.')
        attained=candidates[0] if candidates else int(info['numbers'].get('cl') or 1)
        current = declaration.get('effective_cl', attained)
        if type(attained) is not int or type(current) is not int or not 0 <= current <= attained <= 20:
            raise ValueError('An acquired Path needs integer effective CL between 0 and its attained CL (at most 20).')
        result.append({'block': BLOCK, 'feature_id': path, 'path_id': path, 'attained_cl': attained, 'effective_cl': current})
    return result


def effective_cl(engine, actor, path_id, fallback):
    """Pure live Path query; absent declarations preserve the supplied legacy CL."""
    base = next((r['effective_cl'] for r in (getattr(engine, 'typed_passive_rows', {}) or {}).get(actor.entity_id, [])
                 if r.get('block') == BLOCK and r.get('path_id') == path_id), fallback)
    from .effect_durations import due
    held = [c for c in actor.conditions.values() if c.condition_id == CONDITION and c.data.get('path_id') == path_id
            and not due(engine, c.expires_on)]
    # Each native producer is scoped by source; concurrent suppression uses the lowest level.
    return min([int(base), *[int(c.data['effective_cl']) for c in held]])


def journey_cl(session, aid, path_id, fallback):
    actor = session.state['actors'][aid]
    row = bundle_levels(actor['bundle']).get(path_id)
    base = row['effective_cl'] if row else fallback
    held = actor.get('source_states', {}).get(BLOCK, {}).get(path_id)
    return min(base, held['effective_cl']) if held else base


@effect('path_effective_cl')
def apply_level(ctx, row):
    """Rule-authored runtime suppression; expiry is the native effect duration."""
    path, value = row.get('path_id'), row.get('effective_cl')
    if not isinstance(path, str) or type(value) is not int or not 0 <= value <= 20:
        raise ValueError('Path suppression requires an exact Path ID and integer effective CL from 0 to 20.')
    from ..typed_executor import effect_expiry
    subject = ctx.target if row.get('applies_to') == 'target' else ctx.actor
    for c in list(subject.conditions.values()):
        if c.condition_id == CONDITION and c.source_definition_id == ctx.source and c.data.get('path_id') == path:
            from .condition_ownership import remove_instance
            remove_instance(ctx.engine,subject,c.instance_id,ctx.source)
    ctx.engine._apply_condition(subject, CONDITION, ctx.source, ctx.actor.entity_id,
        expires_on=effect_expiry(ctx, row, subject, condition=True) or 'UNTIL_REMOVED',
        data={'path_id': path, 'effective_cl': value, 'label': f'Effective Path CL {value}'})


@hook('journey_command')
def record_level(session, aid, kind, payload):
    if kind != 'path_effective_cl':
        return None
    from ..journey import require
    actor = session.state['actors'][aid]
    path = payload.get('path_id')
    known = bundle_levels(actor['bundle']).get(path)
    require(set(payload) == {'path_id', 'effective_cl', 'authority', 'reason'} and known is not None
            and payload.get('authority') == 'GM' and isinstance(payload.get('reason'), str)
            and bool(payload['reason'].strip()) and len(payload['reason']) <= 2000
            and type(payload.get('effective_cl')) is int and 0 <= payload['effective_cl'] <= known['attained_cl'],
            'The table owner must supply an acquired Path, a bounded integer CL, GM authority and the sourced reason. The ruling lasts this scene.')
    from ..fact_consent_admission import read
    receipt=read(session,'system:path_authority',aid,'effective_cl',path,aid)
    require(receipt is not None and receipt['value']=={'path_id':path,'effective_cl':payload['effective_cl'],
        'reason':payload['reason'],'scene_id':session.state.get('scene_id',session.state['journey_id'])},
        'A native table-owner world declaration for this exact scene, Path, CL and reason is required; an actor cannot claim GM authority.')
    committed={'path_id':path,'effective_cl':payload['effective_cl'],'authority':'table_owner','declaration_receipt':receipt['receipt_id']}
    actor.setdefault('source_states', {}).setdefault(BLOCK, {})[path] = committed
    sync(session, aid)
    session.emit('PATH_CL_DECLARED', aid, path_id=path,effective_cl=payload['effective_cl'],authority='table_owner',declaration_receipt=receipt['receipt_id'], text=f"{actor['name']}: the table owner records effective Path CL {payload['effective_cl']} for this scene.")
    return True


def sync(session, aid):
    from ..canonical import canonical_sha256
    actor = session.state['actors'][aid]
    actor['bundle']['journey_path_authority'] = deepcopy(actor.get('source_states', {}).get(BLOCK, {}))
    actor['bundle'].pop('bundle_sha256', None)
    actor['bundle']['bundle_sha256'] = canonical_sha256(actor['bundle'])


@hook('journey_initialize')
@hook('journey_state_changed')
def initialize(session, aid):
    if actor_has_ruling(session, aid):
        sync(session, aid)


def actor_has_ruling(session, aid):
    actor = session.state['actors'][aid]
    return BLOCK in actor.get('source_states', {}) or 'journey_path_authority' in actor['bundle']


@hook('journey_scene_end')
def scene_end(session, previous, current):
    for aid in session.state['actors']:
        if actor_has_ruling(session, aid):
            session.state['actors'][aid].setdefault('source_states', {})[BLOCK] = {}
            sync(session, aid)


@hook('match_initialize', priority=-200)
def restore(engine):
    changed = False
    for bundle in engine.typed_bundle_documents:
        actor = engine.state.actors.get(bundle['actor_id'])
        if actor is None:
            continue
        for path, declaration in bundle.get('journey_path_authority', {}).items():
            engine._apply_condition(actor, CONDITION, 'authority:gm.path_cl', actor.entity_id,
                expires_on='UNTIL_REMOVED', data={**declaration, 'label': f"Effective Path CL {declaration['effective_cl']} (table ruling for this scene)"})
            changed = True
    return True if changed else None


@hook('journey_snapshot_actor')
def snapshot(actor, session, aid, engine):
    # Journey rulings already retain the source declaration and scene boundary.
    # Strip only their own copied encounter condition before exporting health.
    result = actor.model_copy(deep=True)
    result.conditions = {key:c for key,c in result.conditions.items()
                         if not (c.condition_id == CONDITION and c.source_definition_id == 'authority:gm.path_cl')}
    return result if len(result.conditions) != len(actor.conditions) else None


@hook('fact_admission_schema')
def world_path_schema(session,source,subject,kind):
    if source!='system:path_authority' or kind!='effective_cl' or subject not in session.state['actors']:return None
    if not bundle_levels(session.state['actors'][subject]['bundle']):return None
    return {'value_type':'document','maximum_seconds':86400,'authority':'table_owner',
        'description':'An actual sourced Realm Suppression ruling for this acquired Path and scene. Actor claims of GM authority do not suffice.'}


@hook('journey_acquired')
def acquisition_continuation(session,aid,source,acquisition_id):
    if actor_has_ruling(session,aid):sync(session,aid)
