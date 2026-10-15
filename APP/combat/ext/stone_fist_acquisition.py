"""Stone Fist's native Open School producer for the shared acquisition API.

The service supplies the actual installed sheet. The controller chooses only
the school; earned IDs, levels, source commitment and receipt are derived here.
No source provider, school access, extra Path or replacement is inferred from a
display name. Existing acquisitions persist in the native source-state registry.
"""
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
import hashlib
import json

from . import hook
from .stone_fist import PREFIX
from ..fact_consent_admission import digest
from ..journey import require

BODY='tianxia.path.body_refining'
PARENT='tianxia.subpath.body.stone_fist'
KEY=PARENT+'.acquisition'


@lru_cache(maxsize=1)
def source_record():
    """Read the same sealed P2B progression used by native NS1R selection."""
    root=Path(__file__).resolve().parents[2]/'non_sphere_authority'/'authority'
    name='Tianxia_Subpath_Tradition_Index_Master_P2B.json'
    raw=(root/name).read_bytes()
    identity=json.loads((root/'NS1R_AUTHORITY_IDENTITIES.json').read_bytes())['files'][name]
    require(identity['size']==len(raw) and identity['sha256']==hashlib.sha256(raw).hexdigest(),
            'The native Subpath source commitment does not match its authority.')
    rows=[row for row in json.loads(raw)['entries'] if row['canonical_id']==PARENT]
    require(len(rows)==1,'Stone Fist must resolve to one native source.')
    row=rows[0]
    require(row['owning_path_id']==BODY and row['access']['canonical_category']=='Open School'
            and not row['access']['access_source_record_required'] and row['parent_variant_relationship'] is None,
            'This procedure admits only the printed independent Open School.')
    return row,identity['sha256']


def body_level(sheet):
    paths=sheet.get('path_and_subpath') or {}
    ids=set(paths.get('path_record_ids') or ())|{paths.get('path_record_id')}
    body=next((row for row in paths.get('paths') or () if row.get('path_id')==BODY),None)
    require(BODY in ids and body is not None,'Stone Fist requires an actually acquired Body Refining Path.')
    level=next((body[key] for key in ('attainment','owning_path_level','effective_cl')
                if type(body.get(key)) is int),None)
    require(type(level) is int and 0<=level<=20,'The native Body Path must supply its actual level.')
    return level


def body_parents(paths):
    parents={row.get('subpath_id') for row in paths.get('subpaths') or ()
             if row.get('owning_path_id')==BODY}
    parents.update(row.get('subpath_id') for row in paths.get('bindings') or () if row.get('path_id')==BODY)
    parents.update(row.get('subpath_or_tradition_id') for row in paths.get('paths') or () if row.get('path_id')==BODY)
    legacy=paths.get('subpath_record_id')
    if isinstance(legacy,str) and legacy.startswith('tianxia.subpath.body.'):
        parents.add(legacy)
    return parents-{None,''}


def publish(sheet,record):
    row,commitment=source_record()
    require(record.get('schema')=='StoneFistSourceAcquisition.v1' and record['source']==PARENT and record['source_sha256']==commitment
            and record['acquisition_id']==digest({k:v for k,v in record.items() if k!='acquisition_id'}),
            'The retained Stone Fist acquisition failed its source commitment.')
    level=body_level(sheet)
    paths=deepcopy(sheet.get('path_and_subpath') or {})
    # A later native retraining to another Body school owns that slot. Retain
    # the old receipt for audit without silently granting both progressions.
    if body_parents(paths)-{PARENT}:
        return deepcopy(sheet)
    earned=list(dict.fromkeys([*record['earned_features'],
        *(feature['canonical_id'] for feature in row['feature_progression'] if feature['granted_at_cl']<=level)]))
    for field in ('path_feature_record_ids','source_granted_subpath_feature_record_ids'):
        paths[field]=list(dict.fromkeys([*(fid for fid in paths.get(field,()) if not fid.startswith(PREFIX)),*earned]))
    school={'subpath_id':PARENT,'display_name':'Stone Fist','owning_path_id':BODY,
            'source_packet_ids':[record['acquisition_id']]}
    paths['subpaths']=[r for r in paths.get('subpaths',()) if r.get('owning_path_id')!=BODY]+[school]
    paths['bindings']=[r for r in paths.get('bindings',()) if r.get('path_id')!=BODY]+[
        {'path_id':BODY,'subpath_id':PARENT,'source_packet_ids':[record['acquisition_id']]}]
    paths['subpath_record_ids']=list(dict.fromkeys([*paths.get('subpath_record_ids',()),PARENT]))
    if paths.get('path_record_id')==BODY or len(paths.get('path_record_ids',()))==1:
        paths['subpath_record_id']=PARENT;paths['subpath']=school
    result=deepcopy(sheet);result['path_and_subpath']=paths
    return result


@hook('journey_acquisition')
def acquire_stone_fist(session,actor_id,source,payload,sheet):
    if source!=PARENT:
        return None
    require(not payload,'Choose Stone Fist itself; this Open School has no printed acquisition cost or training-time payload.')
    actor=session.state['actors'][actor_id]
    row,commitment=source_record();level=body_level(sheet)
    require(level>=row['prerequisites']['minimum_cl'],'Stone Fist selection requires Body Refining level 3.')
    require(not body_parents(sheet.get('path_and_subpath') or {}),'The Body Subpath slot is already selected; this is not a retraining or replacement procedure.')
    require(KEY not in actor.get('source_states',{}),'Stone Fist has already been acquired through this procedure.')
    record={'schema':'StoneFistSourceAcquisition.v1','source':PARENT,'actor':actor_id,'authority':actor_id,
        'expiry':'native_source_rule','source_sha256':commitment,
        'clock':int(session.clock()),'sequence':len(session.state['events'])+1,'path_level':level,
        'earned_features':[f['canonical_id'] for f in row['feature_progression'] if f['granted_at_cl']<=level]}
    record['acquisition_id']=digest(record)
    updated=publish(sheet,record)
    actor.setdefault('source_states',{})[KEY]=record
    session.emit('STONE_FIST_SOURCE_ACQUIRED',actor_id,**record)
    return {'sheet':updated,'acquisition_id':record['acquisition_id']}


@hook('journey_source_sheet')
def retained_stone_fist(sheet,session,actor_id):
    record=session.state['actors'][actor_id].get('source_states',{}).get(KEY)
    if not record:
        return None
    require(record.get('actor')==actor_id and record.get('authority')==actor_id
            and record.get('expiry')=='native_source_rule','The Stone Fist acquisition belongs to another controller or source scope.')
    paths=sheet.get('path_and_subpath') or {}
    # The current native build owns later retraining/Path loss and its own
    # provenance. Overlays bridge the original installed pre-acquisition sheet.
    if body_parents(paths) or BODY not in (set(paths.get('path_record_ids') or ())|{paths.get('path_record_id')}):
        return None
    return publish(sheet,record)
