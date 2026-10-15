"""Bell-Tower's Open School selection through the native source boundary.

Qi Player Path Chapter R19: the first Qi subpath choice grants its progression
at Qi attainment 3/6/10/14/18. Open School selection has no printed extra Qi or
ritual price. It cannot replace another school or duplicate an existing choice.
Only this provider publishes earned Bell IDs; callers supply no sheet or IDs.
"""
from copy import deepcopy
from . import hook
from ..canonical import canonical_sha256
from ..journey import require

PARENT='tianxia.subpath.qi.bell_tower_cultivator'
PREFIX=PARENT+'.feature.'
QI='tianxia.path.qi_cultivation'
PROGRESSION=dict(zip((3,6,10,14,18),('watch_bell','alarm_resonance','purifying_peal','bell_tower_formation','ninefold_heavenly_bell')))
FEATURE_FIELDS=('path_feature_record_ids','source_granted_subpath_feature_record_ids','advancement_feature_record_ids')


def path_data(sheet):
    paths=sheet.get('path_and_subpath') or {}
    ids=set(paths.get('path_record_ids') or [])|set((sheet.get('identity') or {}).get('path_ids') or [])
    if paths.get('path_record_id'):ids.add(paths['path_record_id'])
    rows=[r for r in paths.get('paths',[]) if isinstance(r,dict) and r.get('path_id')==QI]
    levels=[r[k] for r in rows for k in ('attainment','owning_path_level')
        if type(r.get(k)) is int and r[k]>0]
    require(QI in ids and levels and len(set(levels))==1,
        'Bell-Tower selection requires the installed character’s actual Qi Path attainment.')
    level=levels[0];cl=(sheet.get('identity') or {}).get('cultivation_level')
    require(type(cl) is int and 1<=level<=cl,'Qi attainment must be within the character’s actual cultivation level.')
    effective=[r['effective_cl'] for r in rows if type(r.get('effective_cl')) is int and r['effective_cl']>=0]
    return paths,level,min([cl,level,*effective])


def qi_selections(paths):
    selected={s for s in paths.get('subpath_record_ids',[]) if isinstance(s,str) and s.startswith('tianxia.subpath.qi.')}
    single=paths.get('subpath_record_id')
    if isinstance(single,str) and single.startswith('tianxia.subpath.qi.'):selected.add(single)
    for row in [*paths.get('bindings',[]),*paths.get('paths',[]),*paths.get('subpaths',[])]:
        if not isinstance(row,dict) or (row.get('path_id') or row.get('owning_path_id'))!=QI:continue
        for key in ('subpath_id','subpath_record_id','subpath_or_tradition_id'):
            if row.get(key):selected.add(row[key])
    return selected


def feature_ids(paths):
    result={sid for field in FEATURE_FIELDS for sid in paths.get(field,[])}
    result.update(r['feature_id'] for r in paths.get('earned_feature_occurrences',[]) if isinstance(r,dict) and r.get('feature_id'))
    return result


def acquired_paths(sheet,receipt):
    result=deepcopy(sheet);paths,level,effective=path_data(result)
    require(not (qi_selections(paths)-{PARENT}),
        'The current native sheet selects another Qi school; Bell-Tower cannot overwrite it.')
    require(not any(s.startswith('tianxia.subpath.qi.') and not s.startswith(PREFIX) for s in feature_ids(paths)),
        'Bell-Tower cannot coexist with another Qi subpath progression.')
    earned=[PREFIX+name for minimum,name in PROGRESSION.items() if minimum<=level]
    paths=deepcopy(paths)
    for field in FEATURE_FIELDS:
        paths[field]=list(dict.fromkeys([s for s in paths.get(field,[]) if not s.startswith(PREFIX)]+earned))
    paths['subpath_record_ids']=list(dict.fromkeys([s for s in paths.get('subpath_record_ids',[]) if not s.startswith('tianxia.subpath.qi.')]+[PARENT]))
    if paths.get('path_record_id') in (None,QI) and not paths.get('subpath_record_id'):
        paths['subpath_record_id']=PARENT
    entry={'subpath_id':PARENT,'owning_path_id':QI,'display_name':'Bell-Tower Cultivator','source_packet_ids':[receipt['receipt_id']]}
    paths['subpaths']=[r for r in paths.get('subpaths',[]) if r.get('owning_path_id')!=QI]+[entry]
    if not paths.get('subpath'):paths['subpath']=deepcopy(entry)
    paths['bindings']=[r for r in paths.get('bindings',[]) if r.get('path_id')!=QI]+[
        {'path_id':QI,'subpath_id':PARENT,'source_packet_ids':[receipt['receipt_id']]}]
    for row in paths.get('paths',[]):
        if row.get('path_id')==QI:row['subpath_id']=PARENT
    paths['bell_tower_acquisition']={**deepcopy(receipt),'earned_features':earned,'current_path_attainment':level}
    result['path_and_subpath']=paths
    return result


def overlay(sheet,record):
    receipt=record.get('source_states',{}).get(PARENT,{}).get('acquisition')
    if receipt is None:return None
    body={k:v for k,v in receipt.items() if k!='receipt_id'}
    require(receipt.get('receipt_id')==canonical_sha256(body) and receipt.get('source')==PARENT,
        'The Bell-Tower acquisition failed its native commitment check.')
    return acquired_paths(sheet,receipt)


@hook('installed_source_sheet')
def installed_school(sheet,actor_record,actor_id):
    return overlay(sheet,actor_record)


@hook('journey_source_sheet')
def journey_school(sheet,session,actor_id):
    return overlay(sheet,session.state['actors'][actor_id])


@hook('journey_acquisition')
def select_school(session,actor_id,source,payload,sheet):
    if source!=PARENT:return None
    require(payload=={'procedure':'select'},'Choose Bell-Tower Cultivator as the first Qi school; do not submit earned IDs or a sheet.')
    actor=session.state['actors'][actor_id]
    require(not actor.get('source_states',{}).get(PARENT,{}).get('acquisition'),
        'Bell-Tower is already acquired; selecting it again cannot renew its limits.')
    paths,level,effective=path_data(sheet)
    require(level>=3,'The first Qi subpath choice requires Qi Path attainment 3.')
    require(not qi_selections(paths) and not any(s.startswith('tianxia.subpath.qi.') for s in feature_ids(paths)),
        'Choose only the first Qi subpath. Bell-Tower is not an additional or replacement progression.')
    body={'source':PARENT,'actor_id':actor_id,'path_id':QI,'path_attainment':level,
        'clock':int(session.clock()),'sequence':len(session.state['events'])+1,
        'route':'Open School first selection','sheet_sha256':canonical_sha256(sheet)}
    receipt={**body,'receipt_id':canonical_sha256(body)}
    updated=acquired_paths(sheet,receipt)
    actor.setdefault('source_states',{}).setdefault(PARENT,{})['acquisition']=receipt
    session.emit('BELL_TOWER_SOURCE_ACQUIRED',actor_id,source=PARENT,acquisition_id=receipt['receipt_id'],
        path_attainment=level,earned_features=updated['path_and_subpath']['bell_tower_acquisition']['earned_features'],
        text=f"{actor['name']} selects Bell-Tower Cultivator as its Open School; no additional Qi cost.")
    return {'sheet':updated,'acquisition_id':receipt['receipt_id']}


@hook('journey_acquired')
def bind_acquired_school(session,actor_id,source,acquisition_id):
    if source==PARENT:
        from .mgr_reserve_bell_tower_cultivator_watch_bell import bind_journey_scene
        bind_journey_scene(session,actor_id)


@hook('compile_bundle')
def owning_path_level(bundle,info):
    rows=[r for r in bundle.get('typed_passives',[]) if r.get('block')=='bell_tower']
    if not rows:return None
    sheet=info['owner_sheet'];paths=sheet.get('path_and_subpath') or {}
    if not any(r.get('path_id')==QI for r in paths.get('paths',[]) if isinstance(r,dict)):return None
    paths,level,effective=path_data(sheet)
    result=deepcopy(bundle)
    for row in result['typed_passives']:
        if row.get('block')=='bell_tower':row['numbers']={**row['numbers'],'cl':effective}
    for action in result['action_catalog']:
        typed=action.get('parameters',{}).get('typed') or {}
        if typed.get('source','').startswith(PREFIX):typed['numbers']={**typed['numbers'],'cl':effective}
    return result
