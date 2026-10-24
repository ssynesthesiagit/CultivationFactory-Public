"""Restricted Hundred-Venom scripture acquisition through the source owner's API.

The installed native sheet must already own the Body Path and its actual Path
attainment. World-owner access is separate from that mechanical fact. Neither
caller payloads nor access declarations contain earned feature IDs or sheets.
The provider derives the five progression rows, commits the real acquisition,
persists its source overlay and preserves existing resource balances. Other
Subpath progressions on the same Body Path cannot coexist with this choice.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from . import hook
from .hundred_venom_sources import FAMILY
from .hundred_venom import PREFIX
from ..journey import require,integer
from ..fact_consent_admission import read,canonical,digest

BODY='tianxia.path.body_refining'
LEVELS=(3,6,10,14,18)
FEATURES=tuple(PREFIX+s for s in ('venom_furnace','swallow_the_poison','three_sovereign_venoms',
                                 'poisoned_body_poisoned_world','myriad_venom_immortal'))


def body_level(sheet):
    paths=sheet.get('path_and_subpath') or {}
    ids=set(paths.get('path_record_ids') or ())|set(sheet.get('identity',{}).get('path_ids') or ())
    if paths.get('path_record_id'):ids.add(paths['path_record_id'])
    if BODY not in ids:return None
    level=next((p.get('attainment',p.get('owning_path_level',p.get('effective_cl')))
                for p in paths.get('paths',()) if p.get('path_id')==BODY),None)
    return level if integer(level,1) and level<=int(sheet['identity']['cultivation_level']) else None


def stored(actor):
    return actor.get('source_states',{}).get(FAMILY,{}).get('acquisition')


@hook('fact_admission_schema')
def scripture_access(session, source, subject, kind):
    if (source,kind)!=(FAMILY,'source_access') or subject not in session.state['actors']:
        return None
    return {'value_type':'document','authority':'table_owner','maximum_seconds':2592000,
        'description':'The world owner records actual access to the restricted Hundred-Venom scripture; Path attainment and earned features are validated separately.',
        'document_schema':{'type':'object','additionalProperties':False,
            'required':['scripture','source_rule'],
            'properties':{'scripture':{'const':FAMILY},'source_rule':{'type':'string','minLength':1,'maxLength':2000}}}}


def require_compatible_progression(sheet):
    """A cold installed build cannot silently combine replacement progressions."""
    paths=sheet.get('path_and_subpath') or {}
    ids=set(paths.get('subpath_record_ids') or ())
    if paths.get('subpath_record_id'):ids.add(paths['subpath_record_id'])
    ids.update(r.get('subpath_id') for r in paths.get('bindings',()) if r.get('path_id')==BODY)
    ids.update(r.get('subpath_id') for r in paths.get('subpaths',()) if r.get('owning_path_id')==BODY)
    for key in ('path_feature_record_ids','source_granted_subpath_feature_record_ids'):
        ids.update(paths.get(key) or ())
    ids.update(r.get('feature_id') for r in paths.get('earned_feature_occurrences',()))
    require(not any(isinstance(f,str) and f.startswith('tianxia.subpath.body.') and f!=FAMILY and not f.startswith(PREFIX) for f in ids),
            'The installed Body build has another Subpath progression; the acquired scripture cannot grant both base and replacement progressions.')


def overlay(sheet, acquisition):
    require(acquisition['receipt_id']==digest({k:v for k,v in acquisition.items() if k!='receipt_id'}),
            'The saved scripture acquisition failed its native commitment.')
    level=body_level(sheet)
    require(level is not None,'The acquired scripture requires the installed Body Path and its committed attainment.')
    require_compatible_progression(sheet)
    result=deepcopy(sheet);paths=result.setdefault('path_and_subpath',{})
    earned=[f for f,minimum in zip(FEATURES,LEVELS) if level>=minimum]
    for key in ('path_feature_record_ids','source_granted_subpath_feature_record_ids'):
        paths[key]=list(dict.fromkeys([f for f in paths.get(key,[]) if f not in FEATURES]+earned))
    paths['subpath_record_ids']=list(dict.fromkeys([*paths.get('subpath_record_ids',[]),FAMILY]))
    if not paths.get('subpath_record_id'):paths['subpath_record_id']=FAMILY
    subpath={'subpath_id':FAMILY,'display_name':'Hundred-Venom Body','owning_path_id':BODY,
             'source_packet_ids':[acquisition['access_receipt']]}
    paths['subpaths']=[r for r in paths.get('subpaths',[]) if r.get('owning_path_id')!=BODY]+[subpath]
    paths['bindings']=[r for r in paths.get('bindings',[]) if r.get('path_id')!=BODY]+[
        {'path_id':BODY,'subpath_id':FAMILY,'source_packet_ids':[acquisition['access_receipt']]}]
    paths['hundred_venom_acquisition']=deepcopy(acquisition)
    return result


@hook('journey_source_sheet')
def source_sheet(sheet,session,aid):
    acquired=stored(session.state['actors'][aid])
    if acquired:
        require(acquired['subject']==aid and acquired['source']==FAMILY,'The saved scripture belongs to another creature or source.')
        return overlay(sheet,acquired)
    return None


def _receipt_path(userdata_root, actor_id):
    return Path(userdata_root) / 'Combat' / 'SourceAcquisitions' / (
        hashlib.sha256(actor_id.encode()).hexdigest() + '.json')


@hook('installed_source_sheet')
def installed_sheet(sheet, userdata_root, actor_id):
    """Project committed source-owned acquisitions into every installed build."""
    path = _receipt_path(userdata_root, actor_id)
    if not path.is_file():
        return None
    document = json.loads(path.read_text())
    require(document.get('actor_id') == actor_id and document.get('source') == FAMILY,
            'The saved scripture acquisition belongs to another creature or source.')
    return overlay(sheet, document['acquisition'])


@hook('journey_acquired')
def persist_acquisition(session, aid, source, receipt_id, userdata_root):
    if source != FAMILY:
        return None
    receipt = stored(session.state['actors'][aid])
    require(receipt and receipt['receipt_id'] == receipt_id and receipt['subject'] == aid,
            'The committed scripture acquisition does not match this creature.')
    from ..gate3_storage import atomic_write_bytes, LocalMatchWriterLock
    path = _receipt_path(userdata_root, aid)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with LocalMatchWriterLock(path.with_suffix('.lock'), 'source-acquisition:' + aid):
        atomic_write_bytes(path, json.dumps({'actor_id':aid,'source':FAMILY,'acquisition':receipt},
            sort_keys=True,separators=(',',':')).encode())
    return None


@hook('journey_acquisition')
def acquire(session,aid,source,payload,sheet):
    if source!=FAMILY:return None
    require(set(payload)=={'access_scope'} and type(payload['access_scope']) is str and payload['access_scope'],
            'Choose the current world-owner scripture access record.')
    actor=session.state['actors'][aid]
    require(not actor['incapacitated'] and not stored(actor),'This scripture is already acquired or the creature cannot complete acquisition.')
    level=body_level(sheet)
    require(level is not None and level>=3,'Hundred-Venom Body requires actual Body Path attainment of at least 3; overall CL alone grants no progression.')
    access=read(session,FAMILY,aid,'source_access',payload['access_scope'],aid)
    require(access is not None and access['authority']=='table_owner','The native world owner must grant actual restricted-scripture access first.')
    require(access['value']['scripture']==FAMILY and access['value']['source_rule'].strip(), 'Name the actual scripture and its source permission.')
    paths=sheet.get('path_and_subpath') or {}
    selected=set(paths.get('subpath_record_ids') or ())
    if paths.get('subpath_record_id'):selected.add(paths['subpath_record_id'])
    selected.update(r.get('subpath_id') for r in paths.get('bindings',()) if r.get('path_id')==BODY)
    ids=set(paths.get('path_feature_record_ids') or ())|set(paths.get('source_granted_subpath_feature_record_ids') or ())
    ids.update(r.get('feature_id') for r in paths.get('earned_feature_occurrences',()))
    require(not any(isinstance(s,str) and s.startswith('tianxia.subpath.body.') for s in selected|ids),
            'This Body Path already has a Subpath progression; a second or replacement progression needs its printed source procedure.')
    receipt={'source':FAMILY,'subject':aid,'owning_path':BODY,'path_attainment':level,
             'access_receipt':access['receipt_id'],'source_rule':access['value']['source_rule'],
             'journey_id':session.state['journey_id'],'revision':session.state['revision'],
             'event_sequence':len(session.state['events'])+1,'clock_num':session.clock().numerator,'clock_den':session.clock().denominator}
    receipt['receipt_id']=digest(receipt)
    actor.setdefault('source_states',{}).setdefault(FAMILY,{})['acquisition']=receipt
    earned=[f for f,minimum in zip(FEATURES,LEVELS) if level>=minimum]
    session.emit('HUNDRED_VENOM_SOURCE_ACQUIRED',aid,source=FAMILY,receipt_id=receipt['receipt_id'],
                 access_receipt=access['receipt_id'],path_attainment=level,earned_features=earned)
    return {'sheet':overlay(sheet,receipt),'acquisition_id':receipt['receipt_id']}


@hook('compile_bundle')
def bind_body_numbers(bundle,info):
    """Consume the installed native owning-Path profile for family numbers.

    Multi-Path overall CL/key ability never substitutes for Body effective CL
    or Constitution. Legacy sheets without an explicit Body row keep their
    historical compiled representation. This adds no suppression declaration
    or competing generic Realm-state schema.
    """
    family_rows=[r for key in ('typed_passives','typed_reactions') for r in bundle.get(key,())
                 if str(r.get('feature_id') or '').startswith(PREFIX)]
    if not family_rows:return None
    paths=(info['owner_sheet'].get('path_and_subpath') or {}).get('paths') or ()
    body=next((r for r in paths if isinstance(r,dict) and r.get('path_id')==BODY),None)
    if body is None:return None
    level=body.get('effective_cl')
    if level is None:level=body.get('attainment',body.get('owning_path_level'))
    require(integer(level),'The installed Body effective cultivation level must be a nonnegative integer.')
    numbers=info['numbers'];pb=int(numbers['pb']);con=int(numbers['con_mod'])
    result=deepcopy(bundle)
    result['hundred_venom_body_cl']=level
    result['hundred_venom_body_attainment']=int(body.get('attainment',body.get('owning_path_level',level)))
    for key in ('typed_passives','typed_reactions'):
        for row in result.get(key,()):
            if not str(row.get('feature_id') or '').startswith(PREFIX):continue
            row.update(cl=level,pb=pb,save_dc=8+pb+con)
            if 'numbers' in row:
                row['numbers']={**row['numbers'],'cl':level,'pb':pb,'key_mod':con,'con_mod':con,'save_dc':8+pb+con}
    return result


@hook('body_mode_profiles')
def body_profile(bundle):
    """Enroll the family with the named Body modes/scene-resources owner.

    The public profile carries only actually compiled ownership and progression
    thresholds. The shared owner retains its single suppression/input/state
    contract; no source-specific replacement for that producer is created here.
    """
    owned={r.get('feature_id') for key in ('typed_passives','typed_reactions') for r in bundle.get(key,())}
    levels={feature:level for feature,level in zip(FEATURES,LEVELS) if feature in owned}
    return [{'source':FAMILY,'name':'Hundred-Venom Body','feature_levels':levels,
             **({'body_attainment':bundle['hundred_venom_body_attainment']} if 'hundred_venom_body_attainment' in bundle else {}),
             'separate_effect_sources':list(FEATURES),
             'dormancy_exclusions':['condition:typed.swallowed_poison','condition:typed.swallowed_poison_continuation']}] if levels else None


@hook('cultivation_effective_cl')
def native_body_attainment(engine,actor,path):
    if path!=BODY:return None
    bundle=next((b for b in engine.typed_bundle_documents if b.get('actor_id')==actor.entity_id),{})
    return bundle.get('hundred_venom_body_cl')
