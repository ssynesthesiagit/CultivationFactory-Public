"""Real native learning and isolated service fixtures shared by the row and review tests.

No test module is imported; both consumers reuse the same acquisition/replay path.
"""
import json, zipfile
from hashlib import sha256
import pytest
from canonical_catalog.service import CanonicalCatalogAuthorityService
from combat.factory_compiler import compile_character
from factory_authoring import path_access
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT,sheet
from tests.worker2_support import settle,turn,reload

OWNER="actor:factory.aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
ALLY="actor:factory.bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
FOE="actor:factory.cccccccc-cccc-cccc-cccc-cccccccccccc"

QI='HUNGER_BASE_TASTE_THE_QI';TRACE='INK_BASE_READ_THE_TRACE';VESSEL='IMBUEMENT_BASE_READ_THE_VESSEL'
VENOM='POISON_BASE_APPRAISE_THE_VENOM';METAL='METAL_BASE_METAL_APPRAISAL';SKY='WEATHER_BASE_READ_THE_SKY'
PATH_ACCESS_SOURCE='APP/authority/Tianxia_Sphere_Path_Access_R1.json'
PATH_ACCESS_SHA256='359659f5b0388353a6604443b46b29dc8ad549044d0a8c39ff34f8e8525c9f5e'
FORGING_AUTHORITY_SOURCE='APP/authority/Tianxia_Forged_Technique_Authority_R1.json'
FORGING_AUTHORITY_SHA256='b70fe7777d46154b80ebc596ac0c668fad22a49069b7fff90879356ad4c9b38b'
SPHERES={QI:'hunger',TRACE:'ink',VESSEL:'imbuement',VENOM:'poison',METAL:'metal',SKY:'weather'}

def source(subject,values):
    return {'subject_id':subject,'facts':{k:{'value':v} for k,v in values.items() if k not in {'qi.unwilling','qi.concealing'}}}

def make(tmp_path,row,values=None,*,subject=FOE,own=True,position=None,objects=None,source_rows=None,blind=False,extra_foe=False,fragile_foe=False,talent=None,kit=None,starting_sign='wind'):
    ids=[OWNER,ALLY,FOE]+(['actor:factory.dddddddd-dddd-dddd-dddd-dddddddddddd'] if extra_foe else [])
    for aid in ids:
        doc=sheet([],cl=15,kit=kit,name={OWNER:'Wren',ALLY:'Tobin',FOE:'Mara'}.get(aid,'Guard'))
        if aid==FOE and fragile_foe:doc['ability_scores_and_statistics']['hit_points']['maximum']=1
        doc['identity']['path_ids']=['tianxia.path.qi_cultivation']
        doc['path_and_subpath']={'path_record_id':'tianxia.path.qi_cultivation','path_record_ids':['tianxia.path.qi_cultivation']}
        doc['ability_scores_and_statistics']['primary_resource']['maximum']=100
        folder=tmp_path/'portable_characters'/aid.removeprefix('actor:factory.');folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    assert sha256((ROOT.parent/PATH_ACCESS_SOURCE).read_bytes()).hexdigest()==PATH_ACCESS_SHA256
    # Native advancement returns the complete Grow menu, whose forging panel
    # verifies this real sealed authority. Declare the exact dynamic input so
    # sanitized CI exports cannot silently omit it; never replace the loader.
    assert sha256((ROOT.parent/FORGING_AUTHORITY_SOURCE).read_bytes()).hexdigest()==FORGING_AUTHORITY_SHA256
    path_access.access()  # real native learning authority, never a mocked grant
    combat=CombatService(ROOT,tmp_path);table=TabletopService(combat,tmp_path)
    table.canonical_catalog=CanonicalCatalogAuthorityService(ROOT)
    if own:table.add_advancement(OWNER.removeprefix('actor:factory.'),'sphere','tianxia.sphere.'+SPHERES[row],
        choices={'weather_starting_sign':[starting_sign]} if row==SKY else None)
    if talent:table.add_advancement(OWNER.removeprefix('actor:factory.'),'talent',talent)
    if blind:
        table.add_advancement(ALLY.removeprefix('actor:factory.'),'sphere','tianxia.sphere.dark')
        table.add_advancement(ALLY.removeprefix('actor:factory.'),'talent','TAL_DARK_BLINDFOLD')
    bundles=[compile_character(combat._factory_owner_sheet(a.removeprefix('actor:factory.')),actor_id=a,reaction_plan={'ask':True}) for a in ids]
    from copy import deepcopy
    arena=deepcopy(combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'])
    if objects:arena['map_objects']=objects
    mid=combat._finish_factory_match(bundles,ids,{a:'team:factory' if a in (OWNER,ALLY) else 'team:opponents' for a in ids},
        {OWNER:{'x':3,'y':6},ALLY:{'x':3,'y':7},FOE:position or {'x':4,'y':6},**({ids[-1]:{'x':7,'y':6}} if extra_foe else {})},arena,[OWNER,ALLY],ids[2:],
        control_modes={a:'MANUAL' for a in ids},match_seed='KNOWLEDGE',display_name='Knowledge',maximum_rounds=15,
        source_inputs=source_rows(bundles) if callable(source_rows) else source_rows if source_rows is not None else [source(subject,values)] if values else None)['match_id']
    turn(table,mid,OWNER)
    return combat,table,mid

def candidates(combat,mid,row,subject=None,suffix=None,*,count=1):
    """Select an explicit Venom fact-count mode; default to its free reading."""
    e=combat._load_session(mid).engine
    return [c for c in e.legal_candidates() if (a:=e.action_catalog.get(c.source_definition_id)) and
        (a.parameters.get('typed') or {}).get('source')==row and
        (row!=VENOM or int(a.parameters['typed'].get('reading_count',1))==count) and
        (subject is None or c.target_ids==(subject,) or c.metadata.get('object_id')==subject) and
        (suffix is None or suffix in a.display_name)]

def answers(tmp_path,mid):
    e=reload(tmp_path,mid)
    return [c.data for c in e.state.actors[OWNER].conditions.values() if c.condition_id=='condition:information.reading']

def journey_settle(combat,jid,state,aid,kind,payload):
    state=combat.journey_act(jid,state['revision'],aid,kind,payload)
    for _ in range(16):
        pending=state.get('native_scene_pending')
        if not pending:return state
        owner=pending.get('awaiting_actor_id',aid)
        current=combat.journey_state(jid,viewer_id=owner)
        request=current['native_scene_pending']['request']
        spec=request.get('extension_choice') or {}
        options=list(spec.get('option_ids') or [])
        count=spec.get('minimum_selections',0)
        chosen=options[:count]
        answer={'selection':'USE' if chosen or not spec.get('allow_decline') else 'DECLINE','option_ids':chosen}
        state=combat.journey_act(jid,state['revision'],owner,'native_scene_answer',answer)
    raise AssertionError('Native scene choices did not terminate')
