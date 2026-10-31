"""Effective owning-Path CL from sealed acquisition and explicit table rulings.

Consumers: Drunken Fist activation/dormancy and future Path providers. Compilation
records known acquired Paths, never a Path guessed from an ability's flavor.
The shared fact owner records the table owner's external Realm Suppression ruling;
no AI inference supplies it. A ruling lasts until its declared expiry, scene end or replacement. Combat
uses a replayed condition. Paid states and their original Source CL are untouched.
"""
from . import hook, effect

BLOCK = 'path_authority'
CONDITION = 'condition:typed.path_effective_cl'
# docs/rules/rules_as_written.json permits characters through CL40. Standard
# Path content ending at CL20 does not cap the owner's attained/effective CL.
MAX_PATH_CL = 40


def bundle_levels(bundle):
    return {r['path_id']: r for r in bundle.get('typed_passives', []) if r.get('block') == BLOCK}


@hook('compile_passives')
def compile_levels(rows, info):
    paths = {fid.split('.feature.')[0] for fid in info['owned_ids'] if fid.startswith('tianxia.path.') and '.feature.' in fid}
    declarations = (info.get('owner_sheet', {}).get('path_and_subpath') or {}).get('paths') or []
    declared = {p['path_id']: p for p in declarations if isinstance(p, dict) and isinstance(p.get('path_id'), str)}
    result = list(rows)
    for path in sorted(paths):
        declaration = declared.get(path, {})
        attained = declaration.get('attained_cl', int(info['numbers'].get('cl') or 1))
        current = declaration.get('effective_cl', attained)
        if type(attained) is not int or type(current) is not int or not 0 <= current <= attained <= MAX_PATH_CL:
            raise ValueError(f'An acquired Path needs integer effective CL between 0 and its attained CL (at most {MAX_PATH_CL}).')
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


def managed_record(held, aid, path):
    """Validate the immutable shared-owner receipt before consuming a cached fact."""
    import json
    from ..fact_consent_admission import digest
    from ..journey import require
    record=json.loads(held['record'])
    require(record.get('authority')=='table_owner' and record.get('subject')==aid
            and record.get('source')==path and record.get('kind')=='effective_path_cl'
            and record.get('receipt_id')==digest({k:v for k,v in record.items() if k!='receipt_id'}),
            'The effective Path CL declaration failed its owner or replay commitment check.')
    return record


def journey_cl(session, aid, path_id, fallback):
    from fractions import Fraction
    actor = session.state['actors'][aid]
    row = bundle_levels(actor['bundle']).get(path_id)
    base = row['effective_cl'] if row else fallback
    held = actor.get('source_states', {}).get(BLOCK, {}).get(path_id)
    if held and Fraction(held['expiry_num'],held['expiry_den']) > session.clock():
        record=managed_record(held,aid,path_id)
        return min(base,record['value']['effective_cl'])
    return base


@effect('path_effective_cl')
def apply_level(ctx, row):
    """Rule-authored runtime suppression; expiry is the native effect duration."""
    path, value = row.get('path_id'), row.get('effective_cl')
    if not isinstance(path, str) or type(value) is not int or not 0 <= value <= MAX_PATH_CL:
        raise ValueError(f'Path suppression requires an exact Path ID and integer effective CL from 0 to {MAX_PATH_CL}.')
    from ..typed_executor import effect_expiry
    subject = ctx.target if row.get('applies_to') == 'target' else ctx.actor
    for c in list(subject.conditions.values()):
        if c.condition_id == CONDITION and c.source_definition_id == ctx.source and c.data.get('path_id') == path:
            ctx.engine._remove_condition(subject, CONDITION, ctx.source)
    ctx.engine._apply_condition(subject, CONDITION, ctx.source, ctx.actor.entity_id,
        expires_on=effect_expiry(ctx, row, subject, condition=True) or 'UNTIL_REMOVED',
        data={'path_id': path, 'effective_cl': value, 'label': f'Effective Path CL {value}'})


@hook('fact_admission_schema')
def declaration_schema(session, source, subject, kind):
    actor=session.state['actors'].get(subject)
    if kind=='effective_path_cl' and actor and source in bundle_levels(actor['bundle']):
        return {'value_type':'document','authority':'table_owner','maximum_seconds':86400,
            'description':'The table owner records the acquired Path’s current effective Cultivation Level and the sourced reason for this scene.'}
    return None


@hook('fact_admission_validate')
def validate_declaration(session, source, subject, kind, value):
    if kind!='effective_path_cl':return
    from ..journey import require
    actor=session.state['actors'].get(subject)
    known=bundle_levels(actor['bundle']).get(source) if actor else None
    if known is None:return
    require(isinstance(value,dict)
            and set(value)=={'effective_cl','reason'}
            and type(value.get('effective_cl')) is int and 0<=value['effective_cl']<=known['attained_cl']
            and type(value.get('reason')) is str and bool(value['reason'].strip()) and len(value['reason'])<=2000,
            'Use native table-owner input, an acquired Path, a bounded integer CL and a sourced reason.')


@hook('fact_admitted')
def accept_declaration(session, record):
    if record.get('kind')!='effective_path_cl':return
    from ..fact_consent_admission import canonical
    from ..journey import require
    aid,path=record['subject'],record['source']
    actor=session.state['actors'][aid]
    if path not in bundle_levels(actor['bundle']):return
    # The ruling is native table-owner input bound to this scene; the schema
    # already refuses a subject declaration of this kind.
    require(record.get('authority')=='table_owner'
            and record.get('scope')==session.state.get('scene_id',session.state['journey_id']),
            'Use native table-owner input, an acquired Path, this scene, a bounded integer CL and a sourced reason.')
    # This receipt originates in declare_world, never a self-asserted GM flag.
    actor.setdefault('source_states',{}).setdefault(BLOCK,{})[path]={
        'record':canonical(record),'expiry_num':record['expires_at'],'expiry_den':1}
    sync(session,aid)


def sync(session, aid):
    from fractions import Fraction
    from ..canonical import canonical_sha256
    actor=session.state['actors'][aid]
    managed=actor.setdefault('source_states',{}).setdefault(BLOCK,{})
    snapshot={}
    for path,held in list(managed.items()):
        record=managed_record(held,aid,path)
        remaining=max(Fraction(0),Fraction(held['expiry_num'],held['expiry_den'])-session.clock())
        if not remaining:
            del managed[path]
            continue
        held.update(remaining_num=remaining.numerator,remaining_den=remaining.denominator)
        snapshot[path]={'record':held['record'],'effective_cl':record['value']['effective_cl'],
            'remaining_num':remaining.numerator,'remaining_den':remaining.denominator}
    actor['bundle']['journey_path_authority']=snapshot
    actor['bundle'].pop('bundle_sha256',None)
    actor['bundle']['bundle_sha256']=canonical_sha256(actor['bundle'])


@hook('journey_initialize')
def initialize(session, aid):
    from fractions import Fraction
    actor=session.state['actors'][aid]
    if BLOCK not in actor.get('source_states',{}):return
    for held in actor['source_states'][BLOCK].values():
        remaining=Fraction(held['remaining_num'],held['remaining_den'])
        deadline=session.clock()+remaining
        held.update(expiry_num=deadline.numerator,expiry_den=deadline.denominator)
    sync(session,aid)


@hook('journey_state_changed')
def state_changed(session, aid):
    if BLOCK in session.state['actors'][aid].get('source_states',{}):sync(session,aid)


@hook('journey_elapsed')
def elapsed(session, aid, before, seconds, moving):
    state_changed(session,aid)


@hook('journey_scene_end')
def scene_end(session, previous, current):
    for aid,actor in session.state['actors'].items():
        if BLOCK in actor.get('source_states',{}):
            actor['source_states'][BLOCK]={}
            sync(session,aid)


@hook('match_initialize', priority=-200)
def restore(engine):
    from fractions import Fraction
    from .effect_durations import round_token
    changed=False
    for bundle in engine.typed_bundle_documents:
        actor=engine.state.actors.get(bundle['actor_id'])
        if actor is None:continue
        for path,held in bundle.get('journey_path_authority',{}).items():
            record=managed_record(held,actor.entity_id,path)
            remaining=Fraction(held['remaining_num'],held['remaining_den'])
            if not remaining:continue
            rounds=(remaining.numerator+6*remaining.denominator-1)//(6*remaining.denominator)
            engine._apply_condition(actor,CONDITION,'authority:table_owner.path_cl',actor.entity_id,
                expires_on=round_token(engine,rounds),data={'path_id':path,'effective_cl':record['value']['effective_cl'],
                    'record':held['record'],'remaining_num':remaining.numerator,'remaining_den':remaining.denominator,
                    'start_round':int(engine.state.round_number),'start_slot':int(engine.state.current_slot_index),
                    'label':'Realm Suppression: '+path.rsplit('.',1)[-1].replace('_',' ').title()})
            changed=True
    return True if changed else None


@hook('journey_snapshot_actor')
def snapshot(actor, session, aid, engine):
    result=actor.model_copy(deep=True)
    result.conditions={key:c for key,c in result.conditions.items()
                       if not (c.condition_id==CONDITION and c.source_definition_id=='authority:table_owner.path_cl')}
    return result if len(result.conditions)!=len(actor.conditions) else None


@hook('journey_encounter_settled')
def settled(session, aid, engine, creature):
    from fractions import Fraction
    managed=session.state['actors'][aid].get('source_states',{}).get(BLOCK)
    if managed is None:return
    for path,held in list(managed.items()):
        condition=next((c for c in creature.conditions.values() if c.condition_id==CONDITION
                       and c.source_definition_id=='authority:table_owner.path_cl' and c.data.get('path_id')==path),None)
        if condition is None:
            del managed[path]
            continue
        data=condition.data
        cycles=max(0,engine.state.round_number-int(data['start_round'])
                   -int(engine.state.current_slot_index<int(data['start_slot'])))
        remaining=max(Fraction(0),Fraction(data['remaining_num'],data['remaining_den'])-6*cycles)
        if not remaining:
            del managed[path]
            continue
        deadline=session.clock()+remaining
        held.update(expiry_num=deadline.numerator,expiry_den=deadline.denominator)
    sync(session,aid)
