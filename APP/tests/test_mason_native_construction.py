"""Native Mason construction regressions; real commits, reload and replay."""
from tests.mason_native_support import *

@pytest.mark.parametrize('form,hp,ac,height', [('Low Wall',72,15,3),('Tall Wall',72,15,10),('Ramp',72,15,10),('Platform',72,15,10)])
def test_raise_barrier_table_forms_reload(tmp_path,form,hp,ac,height):
    combat,table,mid,send,commit=fixture(tmp_path)
    before=cold(tmp_path,mid).state.actors[s.OWNER].resources['resource:core.qi']
    commit(at(table,mid,'Raise Barrier: '+form,6,8))
    engine=cold(tmp_path,mid)
    obj=next(o for o in engine.state.objects.values() if (o.component or {}).get('mason'))
    assert (obj.current_hp,obj.maximum_hp,obj.ac,obj.damage_threshold,obj.height_ft)==(hp,hp,ac,4,height)
    assert obj.owner_id==s.OWNER and obj.component['source_cl']==18
    assert set(obj.component['resist'])=={'BLUDGEONING','PIERCING','SLASHING'}
    assert set(obj.damage_immunities)=={'POISON','PSYCHIC'}
    assert engine.state.actors[s.OWNER].resources['resource:core.qi']==before-1
    assert obj.component['mason']['declaration']['material_source']


@pytest.mark.parametrize('form,sections',[('Great Bridge',6),('Ascending Stair',4),('Defensive Tower',6),('Gatehouse',3)])
def test_greater_structure_native_sections(tmp_path,form,sections):
    combat,table,mid,send,commit=fixture(tmp_path)
    commit(at(table,mid,'Bridge the Impossible: '+form,6,8))
    engine=cold(tmp_path,mid)
    works=[o for o in engine.state.objects.values() if (o.component or {}).get('mason')]
    assert len(works)==sections
    assert all((o.ac,o.current_hp,o.damage_threshold)==(17,144,8) for o in works)
    assert all(o.component['mason']['declaration']['legal_load'] for o in works)


def test_wrong_owner_default_inert(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,features=[])
    engine=cold(tmp_path,mid)
    assert not any(a.parameters.get('mason_build') for a in engine.action_catalog.values())
    assert not any((o.component or {}).get('mason') for o in engine.state.objects.values())


def test_barrier_occupied_cell_unreachable(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path)
    owner=cold(tmp_path,mid).state.actors[s.OWNER]
    assert not any(o.get('destination')==owner.position.model_dump(mode='json')
        for g in table.state(mid)['menu']['actions'] if g['label']=='Raise Barrier: Low Wall' for o in g['options'])


@pytest.mark.parametrize('cl,allowed',[(2,[]),(3,['raise_barrier']),(6,['raise_barrier']),(10,['raise_barrier','bridge_the_impossible']),(18,['raise_barrier','bridge_the_impossible','raise_the_imperial_bastion'])])
def test_native_effective_cl_admission(tmp_path,cl,allowed):
    combat,table,mid,send,commit=fixture(tmp_path,cl=cl)
    actual={a.parameters['mason_build'].rsplit('.',1)[1] for a in cold(tmp_path,mid).action_catalog.values() if a.parameters.get('mason_build')}
    assert actual==set(allowed)


def test_barrier_pb_cap_retires_oldest_after_native_turns(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path)
    identifiers=[]
    for x,y in [(6,8),(3,9),(1,8),(1,4),(4,3)]:
        commit(at(table,mid,'Raise Barrier: Low Wall',x,y))
        engine=cold(tmp_path,mid)
        identifiers.append(max(works(engine),key=lambda o:o.component['asset_anchor_runtime']['sequence']).object_id)
        if len(identifiers)<5:next_owner(table,mid,commit)
    engine=cold(tmp_path,mid)
    assert len(works(engine))==4 and engine.state.objects[identifiers[0]].destroyed
    assert all(not engine.state.objects[k].destroyed for k in identifiers[1:])


def test_full_geometry_failure_rolls_back_payment_and_action(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path)
    before=cold(tmp_path,mid).state.model_dump(mode='json')
    # The chosen anchor is legal; the fixed 10-foot wall extends beyond the map.
    # A square-picker selection outside range is also rejected natively.
    with pytest.raises(Exception):commit(at(table,mid,'Raise Barrier: Tall Wall',39,19))
    assert cold(tmp_path,mid).state.model_dump(mode='json')==before


def test_generic_asset_interface_rejects_unowned_or_unsupported_creation(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path)
    engine=cold(tmp_path,mid)
    # Negative guards are reached through the real action, never by injecting
    # an object, ownership marker or triggering damage receipt into state.
    from combat.ext.needle import cell_id
    from combat.gate2_runtime_models import Position
    before=engine.state.model_dump(mode='json')
    with pytest.raises(Exception):
        commit(at(table,mid,'Raise Barrier: Low Wall',4,6))
    assert cold(tmp_path,mid).state.model_dump(mode='json')==before


def test_native_open_school_acquisition_drives_table_build(catalog_environment,tmp_path):
    from character_builder import CharacterBuilderService
    from non_sphere_authority.service import NonSphereAuthorityService
    from project_store.service import ProjectStore
    db=catalog_environment['db'];parent='tianxia.subpath.qi.mason_cultivator';path='tianxia.path.qi_cultivation'
    project=CharacterBuilderService(db).create_project(working_name='Native Mason source acquisition',
        concept='Open School construction progression',target_cl=18,power_band='standard',source_reference=None,
        creation_mode='detailed',ability_scores={},selections={'path_choice':[path],'subpath_choice':[parent]})
    pid=project['project_id'];authority=NonSphereAuthorityService(db)
    state=authority.get_state(pid)
    selection=next(row for row in state['paths'] if row['path_id']==path)
    assert selection['subpath_or_tradition_id']==parent
    assert selection['attainment']==18
    assert selection['subpath_or_tradition_acquisition_provenance']['recorded'] is True
    store=ProjectStore(db)
    with db.connection() as conn:
        store.project_lock_proof(conn,pid)
        record=store._resolve_locked_record_after_proof(conn,pid,parent,authority_service=authority)
    source=record['compatibility']['factory']['stage2_authority']
    assert source['owning_path_id']==path
    # Source-bound progression is derived from the acquired parent's immutable
    # authority, rather than constructing an ability ownership receipt.
    raw=record
    def all_features(value):
        if isinstance(value,str):return [value] if value.startswith(BASE) else []
        result=[]
        if isinstance(value,dict):
            for k,v in value.items():
                result.extend(all_features(k));result.extend(all_features(v))
        elif isinstance(value,list):
            for v in value:result.extend(all_features(v))
        return result
    acquired=list(dict.fromkeys(all_features(raw)))
    assert set(acquired)==set(FEATURES)
    combat,table,mid,send,commit=fixture(tmp_path,features=acquired)
    commit(at(table,mid,'Raise Barrier: Low Wall',6,8))
    assert len(works(cold(tmp_path,mid)))==1


def test_gatehouse_action_mechanism_and_two_levels_are_native(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path)
    # Place the center gate next to the owner by extending the wall eastward.
    commit(at(table,mid,'Bridge the Impossible: Gatehouse',0,5))
    engine=cold(tmp_path,mid)
    gate=next(o for o in works(engine) if o.component.get('mechanism'))
    assert gate.component['blocks'] and gate.component['mechanism']['open']==0
    next_owner(table,mid,commit)
    commit(s.candidate(table,mid,'Open structure gate',gate.object_id))
    gate=cold(tmp_path,mid).state.objects[gate.object_id]
    assert not gate.component['blocks'] and gate.component['mechanism']['open']==1
    assert not cold(tmp_path,mid).state.actors[s.OWNER].action_available


def test_greater_replacement_asks_occupant_and_preserves_native_support(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path)
    commit(at(table,mid,'Bridge the Impossible: Great Bridge',4,4),picks={
        'choice:needle.mason_height_0':'10','choice:needle.mason_length_0':'10'})
    engine=cold(tmp_path,mid);old_ids=[o.object_id for o in works(engine)]
    candidates=combat._legal_candidates(combat._load_session(mid))
    climb=next(c for c in candidates if c.kind=='MOVE' and c.destination is not None and
        (c.destination.x,c.destination.y,c.destination.z)==(4,5,2))
    commit(climb.candidate_id)
    assert cold(tmp_path,mid).state.actors[s.OWNER].position.z==2
    next_owner(table,mid,commit)
    commit(at(table,mid,'Bridge the Impossible: Ascending Stair',7,8))
    engine=cold(tmp_path,mid)
    assert all(engine.state.objects[k].destroyed for k in old_ids)
    from combat.falling import supported
    assert supported(engine,engine.state.actors[s.OWNER])


def test_general_asset_profile_authoring_guard_and_public_default():
    from combat.tabletop import normalize_map,TabletopError
    from combat.asset_anchor_runtime import public_map_object
    doc={'display_name':'Anchor','width_squares':12,'height_squares':12,'objects':[{'id':1,'kind':'custom','x':2,'y':2,'source_cl':20}]}
    with pytest.raises(TabletopError):normalize_map(doc)
    declaration={'actor':'gm:owner','authority':'GM','source_rule':'Published Anchor profile','visibility':'gm','expiry':'source_rule'}
    doc['objects'][0]['asset_declaration']=declaration
    normalized=normalize_map(doc)['objects'][0]
    assert normalized['source_cl']==20 and normalized['asset_declaration']['object_id']==1
    assert 'source_cl' not in public_map_object(normalized)
    assert public_map_object({'id':2,'kind':'crate'})=={'id':2,'kind':'crate'}


def test_barrier_cover_uses_committed_native_geometry_and_sides(tmp_path):
    positions={s.OWNER:{'x':3,'y':6},s.FOE:{'x':9,'y':6},s.SECOND:{'x':2,'y':6}}
    combat,table,mid,send,commit=fixture(tmp_path,positions=positions)
    commit(at(table,mid,'Raise Barrier: Low Wall',6,6))
    engine=cold(tmp_path,mid)
    from combat.effect_cover import query
    owner=engine.state.actors[s.OWNER];foe=engine.state.actors[s.FOE];ally=engine.state.actors[s.SECOND]
    assert query(engine,[foe.position],foe.entity_id,owner,purpose='attack')['bonus']==2
    assert query(engine,[ally.position],ally.entity_id,owner,purpose='attack')['bonus']==0


@pytest.mark.parametrize('form,legal',[('Low Wall',True),('Tall Wall',False)])
def test_native_barrier_air_gap_and_airtight_enclosure_guard(tmp_path,form,legal):
    walls=[{'shape':'line','points':points,'height_ft':10} for points in
        ([[10,4],[14,4]],[[10,4],[10,8]],[[14,4],[14,8]],[[10,8],[11,8]],[[13,8],[14,8]])]
    positions={s.OWNER:{'x':12,'y':10},s.FOE:{'x':12,'y':6},s.SECOND:{'x':2,'y':6}}
    combat,table,mid,send,commit=fixture(tmp_path,positions=positions,scene_document={'walls':walls,'roofs':{'height_ft':10}})
    before=cold(tmp_path,mid)
    assert before.grid.roof_surfaces
    if legal:
        commit(at(table,mid,'Raise Barrier: '+form,12,8),picks={'choice:needle.mason_orientation_0':'90'})
        assert len(works(cold(tmp_path,mid)))==1
    else:
        with pytest.raises(Exception):commit(at(table,mid,'Raise Barrier: '+form,12,8),picks={'choice:needle.mason_orientation_0':'90'})
        after=cold(tmp_path,mid)
        assert after.state.model_dump(mode='json')==before.state.model_dump(mode='json')


def test_greater_can_replace_same_site_and_use_empty_native_roof_support(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path)
    commit(at(table,mid,'Raise Barrier: Platform',6,8))
    next_owner(table,mid,commit)
    cid=at(table,mid,'Bridge the Impossible: Great Bridge',6,8)[0]
    commit((cid,(6,8,2)),picks={'choice:needle.mason_length_0':'5','choice:needle.mason_width_0':'5','choice:needle.mason_height_0':'5'})
    before=cold(tmp_path,mid)
    greater=[o for o in works(before) if o.component['mason']['feature']==BASE+'bridge_the_impossible']
    assert len(greater)==1 and greater[0].position.z==2
    next_owner(table,mid,commit)
    cid=at(table,mid,'Bridge the Impossible: Great Bridge',6,8)[0]
    commit((cid,(6,8,2)),picks={'choice:needle.mason_length_0':'5','choice:needle.mason_width_0':'5','choice:needle.mason_height_0':'5'})
    after=cold(tmp_path,mid)
    assert after.state.objects[greater[0].object_id].destroyed
    live=[o for o in works(after) if o.component['mason']['feature']==BASE+'bridge_the_impossible']
    assert len(live)==1 and live[0].position.z==2


def test_barrier_cap_retirement_cannot_be_undone_by_reconstruction(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path)
    first=None
    for index,(x,y) in enumerate([(4,5),(6,8),(3,9),(1,8),(1,4)]):
        commit(at(table,mid,'Raise Barrier: Low Wall',x,y))
        engine=cold(tmp_path,mid)
        if first is None:first=works(engine)[0].object_id
        if index<4:next_owner(table,mid,commit)
    next_owner(table,mid,commit)
    engine=cold(tmp_path,mid)
    assert engine.state.objects[first].destroyed
    assert engine.state.objects[first].component['asset_anchor_runtime']['ended']
    assert not any(first in o.get('target_ids',[]) for g in table.state(mid)['menu']['actions']
        if g['label']=='Emergency Repairs: Repair Structure with sufficient material' for o in g['options'])


