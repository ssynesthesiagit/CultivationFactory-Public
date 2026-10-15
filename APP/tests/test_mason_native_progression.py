"""Mason table actions, cold state and mechanical replay regressions."""
import pytest
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests import r1i_service_support as s

BASE='tianxia.subpath.qi.mason_cultivator.feature.'
FEATURES=[BASE+k for k in ('raise_barrier','emergency_repairs','bridge_the_impossible','fortress_crew','raise_the_imperial_bastion')]


def cold(tmp_path,mid):
    session=CombatService(ROOT,tmp_path)._load_session(mid)
    assert session.verify()['status']=='PASS'
    assert session.mechanical.replay()['status']=='PASS'
    return session.engine


def fixture(tmp_path,features=FEATURES,cl=18,damage=None,scene_objects=None,probe=False,positions=None,maximum_rounds=10):
    def setup(bundles):
        if damage is None and not probe:return
        from combat.canonical import canonical_sha256
        bundle=next(b for b in bundles if b['actor_id']==s.OWNER)
        action={'source_definition_id':'test:mason.native_damage','display_name':'Damage a structure',
            'owner_id':s.OWNER,'economy':'ACTION','resolution_kind':'TYPED','target_kind':'OBJECT','range_ft':60,
            'parameters':{'typed':{'source':'test:mason.native_damage','numbers':{},'duration':{'kind':'instant'},
                'effects':[{'type':'object_damage','flat':damage,'damage_types':['force']}]}}}
        if damage is not None:
            bundle['action_catalog'].append(action);bundle['actor_template']['action_ids'].append(action['source_definition_id'])
        if probe:
            for key,target,effects in [('prone','SELF',[{'type':'condition','condition':'prone','applies_to':'target'}]),
                    ('save','ANY_CREATURE',[{'type':'save','ability':'STR','dc':50,'on_fail':[{'type':'condition','condition':'prone','applies_to':'target'}],'on_success':[]}])]:
                a={'source_definition_id':'test:mason.native_'+key,'display_name':'Native '+key+' probe','owner_id':s.OWNER,
                    'economy':'ACTION','resolution_kind':'TYPED','target_kind':target,'range_ft':60,
                    'parameters':{'typed':{'source':'test:mason.native_'+key,'numbers':{},'duration':{'kind':'instant'},'effects':effects}}}
                bundle['action_catalog'].append(a);bundle['actor_template']['action_ids'].append(a['source_definition_id'])
        bundle.pop('bundle_sha256',None);bundle['bundle_sha256']=canonical_sha256(bundle)
    combat,table,mid,send,old_commit=s.fixture(tmp_path,features,owner_cl=cl,wide=True,allies=(s.SECOND,),bundle_transform=setup,positions=positions)
    if scene_objects is not None or maximum_rounds!=10:
        engine=cold(tmp_path,mid)
        saved=combat.tabletop_maps.save({'display_name':'Mason source declarations','width_squares':40,'height_squares':20,
            'walls':[],'objects':scene_objects or [],'starts':{'team1':[[3,6]],'team2':[[4,6],[5,6]]}})
        arena=combat.factory_arenas()['battlefield:map.'+saved['map_id']]
        ids=list(engine.state.actors)
        mid=combat._finish_factory_match(engine.typed_bundle_documents,ids,
            {aid:a.team_id for aid,a in engine.state.actors.items()},
            {aid:a.position.model_dump(mode='json') for aid,a in engine.state.actors.items()},arena,[s.OWNER],ids[1:],
            control_modes={aid:'MANUAL' for aid in ids},match_seed='MASON-DECLARATION',display_name='Mason native declaration',maximum_rounds=maximum_rounds)['match_id']
        def send(cid,answers=()):
            menu=table.state(mid)['menu']
            return table.act(mid,cid,menu['decision_id'],menu['state_version'],0,list(answers))
        while table.state(mid)['menu']['actor_id']!=s.OWNER:
            assert send(table.state(mid)['menu']['end_turn'])['status']=='COMMITTED'
    def commit(selection,*,picks=None,decline=()):
        from combat.placement_menu import CHOICE
        from combat.ext.needle import cell_id
        from combat.gate2_runtime_models import Position
        cid,spot=selection if isinstance(selection,tuple) else (selection,None)
        answers=[]
        for _ in range(128):
            result=send(cid,answers)
            if result['status']=='COMMITTED':return result
            assert result['status']=='REACTION_REQUIRED',result
            p=result['reaction'];answer={**p['context'],'selection':'DECLINE'}
            if p.get('choice'):
                preferred=p['choice'].get('preferred') or [p['choice']['options'][0]['id']]
                if p['context']['reaction_source_id']==CHOICE and spot is not None:
                    preferred=[cell_id(Position(x=spot[0],y=spot[1]),include_altitude=True)]
                source=p['context']['reaction_source_id']
                if source in (picks or {}):
                    preferred=(picks or {})[source]
                    preferred=[preferred] if isinstance(preferred,str) else preferred
                if source not in decline:answer.update(selection='USE',option_ids=preferred[:1])
            answers.append(answer)
        raise AssertionError('too many prompts')
    return combat,table,mid,send,commit


def at(table,mid,label,x,y):
    return (next(o['candidate_id'] for g in table.state(mid)['menu']['actions'] if g['label']==label
        for o in g['options']), (x,y))


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


def test_bastion_native_concentration_and_turn_command(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path)
    commit(at(table,mid,'Raise the Imperial Bastion: Raise Sections',6,8))
    engine=cold(tmp_path,mid)
    works=[o for o in engine.state.objects.values() if (o.component or {}).get('mason')]
    assert len(works)==1
    assert (works[0].ac,works[0].current_hp,works[0].damage_threshold)==(18,108,8)
    assert engine.state.actors[s.OWNER].concentration is not None
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id']!=s.OWNER:commit(table.state(mid)['menu']['end_turn'])
    cold(tmp_path,mid)


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


def next_owner(table,mid,commit):
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id']!=s.OWNER:commit(table.state(mid)['menu']['end_turn'])


def works(engine):
    return [o for o in engine.state.objects.values() if (o.component or {}).get('mason') and not o.destroyed]


def test_native_damage_repair_reinforcement_and_expiry(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,damage=20)
    commit(at(table,mid,'Raise Barrier: Low Wall',4,5))
    oid=works(cold(tmp_path,mid))[0].object_id
    next_owner(table,mid,commit)
    commit(s.candidate(table,mid,'Damage a structure',oid),decline=('choice:needle.mason_intervention',))
    assert cold(tmp_path,mid).state.objects[oid].current_hp==52
    next_owner(table,mid,commit)
    commit(s.candidate(table,mid,'Emergency Repairs: Repair Structure',oid))
    repaired=cold(tmp_path,mid).state.objects[oid]
    assert 52<repaired.current_hp<=72
    commit(s.candidate(table,mid,'Emergency Repairs: Reinforce Position',oid))
    reinforced=cold(tmp_path,mid).state.objects[oid]
    assert (reinforced.ac,reinforced.damage_threshold)==(17,8)
    next_owner(table,mid,commit)
    obj=cold(tmp_path,mid).state.objects[oid]
    assert (obj.ac,obj.damage_threshold)==(15,4)


def test_bastion_floor_is_one_use_per_section(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,damage=200)
    commit(at(table,mid,'Raise the Imperial Bastion: Raise Sections',4,5))
    oid=works(cold(tmp_path,mid))[0].object_id
    next_owner(table,mid,commit)
    commit(s.candidate(table,mid,'Damage a structure',oid))
    obj=cold(tmp_path,mid).state.objects[oid]
    assert obj.current_hp==1 and not obj.destroyed and obj.component['mason']['collapse_used']
    next_owner(table,mid,commit)
    commit(s.candidate(table,mid,'Damage a structure',oid))
    obj=cold(tmp_path,mid).state.objects[oid]
    assert obj.current_hp==0 and obj.destroyed


def test_intervention_native_reaction_payment_and_round_guard(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,damage=8)
    commit(at(table,mid,'Raise Barrier: Low Wall',4,5))
    oid=works(cold(tmp_path,mid))[0].object_id
    next_owner(table,mid,commit)
    before=cold(tmp_path,mid);qi=before.state.actors[s.OWNER].resources['resource:core.qi']
    commit(s.candidate(table,mid,'Damage a structure',oid),picks={'choice:needle.mason_intervention':'protect'})
    after=cold(tmp_path,mid)
    assert after.state.actors[s.OWNER].resources['resource:core.qi']==qi-2
    assert not after.state.actors[s.OWNER].reaction_available
    assert after.state.objects[oid].current_hp>64
    assert any(e.event_type=='REACTION_RESOLVED' and e.source_definition_id==BASE+'fortress_crew' for e in after.events)


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


def test_bastion_all_four_sections_and_scene_gate(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path)
    picks={'choice:needle.mason_count':'4',
        'choice:needle.mason_space_1':'cell:8,8',
        'choice:needle.mason_space_2':'cell:6,10',
        'choice:needle.mason_space_3':'cell:8,10'}
    # cell_id's actual public wire format is used, not test metadata.
    from combat.ext.needle import cell_id
    from combat.gate2_runtime_models import Position
    for i,(x,y) in enumerate([(8,8),(6,10),(8,10)],1):picks[f'choice:needle.mason_space_{i}']=cell_id(Position(x=x,y=y))
    commit(at(table,mid,'Raise the Imperial Bastion: Raise Sections',6,8),picks=picks)
    assert len(works(cold(tmp_path,mid)))==4
    next_owner(table,mid,commit)
    assert not any(g['label'].startswith('Raise the Imperial Bastion:') for g in table.state(mid)['menu']['actions'])


@pytest.mark.parametrize('operation',['Repair','Reconfigure','Raise New Work','Covered Advance','Brace the Defender'])
def test_master_builder_all_choices_reachable(tmp_path,operation):
    combat,table,mid,send,commit=fixture(tmp_path)
    commit(at(table,mid,'Raise the Imperial Bastion: Raise Sections',4,5))
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id']!=s.OWNER:
        commit(table.state(mid)['menu']['end_turn'],picks={'choice:needle.mason_command':operation})
    engine=cold(tmp_path,mid)
    if operation=='Raise New Work':assert len(works(engine))==2
    if operation=='Brace the Defender':assert any(c.condition_id=='condition:typed.mason_brace' for a in engine.state.actors.values() for c in a.conditions.values())


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


def test_destroyed_section_requires_material_declaration_and_restores_native_object(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,damage=200)
    commit(at(table,mid,'Raise Barrier: Low Wall',4,5))
    oid=works(cold(tmp_path,mid))[0].object_id
    next_owner(table,mid,commit)
    commit(s.candidate(table,mid,'Damage a structure',oid),decline=('choice:needle.mason_intervention',))
    assert cold(tmp_path,mid).state.objects[oid].destroyed
    next_owner(table,mid,commit)
    commit(s.candidate(table,mid,'Emergency Repairs: Repair Structure with sufficient material',oid))
    obj=cold(tmp_path,mid).state.objects[oid]
    assert 0<obj.current_hp<=obj.maximum_hp and not obj.destroyed
    assert obj.component['repair_declaration']['actor']==s.OWNER
    assert obj.component['repair_declaration']['sufficient_material'] is True


def journey_fixture(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path)
    engine=cold(tmp_path,mid)
    journey=combat.journeys.create(engine.typed_bundle_documents,engine.battlefield_document,
        {aid:a.position.model_dump(mode='json') for aid,a in engine.state.actors.items()},
        {aid:3000 for aid in engine.state.actors})
    return combat,journey


def journey_wall_payload():
    from combat.ext.needle import cell_id
    from combat.gate2_runtime_models import Position
    return {'source':BASE+'raise_barrier','form':'Low Wall','sections':[{
        'position':{'x':6,'y':8},'form':'Low Wall','length_ft':10,'width_ft':1,'height_ft':3,'rotation':0,
        'material_source':'terrain:'+cell_id(Position(x=6,y=8)),'legal_load':''}]}


def test_journey_native_construction_exact_hour_expiry_cold_reload(tmp_path):
    combat,j=journey_fixture(tmp_path);jid=j['journey_id']
    state=combat.journey_act(jid,j['revision'],s.OWNER,'mason_build',journey_wall_payload())
    obj=next(o for o in state['runtime_objects'].values() if not o['destroyed'])
    assert obj['current_hp']==72 and state['actors'][s.OWNER]['resources']['resource:core.qi']==29
    state=combat.journey_act(jid,state['revision'],s.OWNER,'wait',{'seconds':3599})
    loaded=CombatService(ROOT,tmp_path).journey_state(jid)
    assert not loaded['runtime_objects'][obj['object_id']]['destroyed']
    state=combat.journey_act(jid,loaded['revision'],s.OWNER,'wait',{'seconds':1})
    assert state['runtime_objects'][obj['object_id']]['destroyed']
    assert state['actors'][s.OWNER]['resources']['resource:core.qi']==29


def test_journey_objects_bind_into_native_combat_and_replay(tmp_path):
    combat,j=journey_fixture(tmp_path);jid=j['journey_id']
    state=combat.journey_act(jid,j['revision'],s.OWNER,'mason_build',journey_wall_payload())
    state=combat.journey_act(jid,state['revision'],s.OWNER,'wait',{'seconds':30})
    result=combat.journey_start_combat(jid,state['revision'],{s.OWNER:'team:a',s.FOE:'team:b',s.SECOND:'team:a'})
    engine=cold(tmp_path,result['match_id'])
    assert len(works(engine))==1 and works(engine)[0].current_hp==72
    assert engine.state.actors[s.OWNER].resources['resource:core.qi']==29


def test_journey_wrong_owner_declaration_is_atomic(tmp_path):
    combat,j=journey_fixture(tmp_path);jid=j['journey_id']
    with pytest.raises(ValueError):combat.journey_act(jid,j['revision'],s.FOE,'mason_build',journey_wall_payload())
    assert combat.journey_state(jid)==j


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


def test_master_builder_repair_restores_damaged_section_from_native_turn_start(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,damage=20)
    commit(at(table,mid,'Raise the Imperial Bastion: Raise Sections',4,5))
    oid=works(cold(tmp_path,mid))[0].object_id
    next_owner(table,mid,commit)
    commit(s.candidate(table,mid,'Damage a structure',oid),decline=('choice:needle.mason_intervention',))
    assert cold(tmp_path,mid).state.objects[oid].current_hp==88
    next_owner(table,mid,commit)
    assert 88<cold(tmp_path,mid).state.objects[oid].current_hp<=108


def test_scene_declaration_ends_concentration_and_resets_only_scene_use(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path)
    commit(at(table,mid,'Raise the Imperial Bastion: Raise Sections',4,5))
    before=cold(tmp_path,mid);qi=before.state.actors[s.OWNER].resources['resource:core.qi']
    commit(s.candidate(table,mid,'Mason: Declare the scene ended'))
    after=cold(tmp_path,mid)
    assert not works(after) and after.state.actors[s.OWNER].concentration is None
    assert not any(c.condition_id=='condition:typed.mason_scene_use' for c in after.state.actors[s.OWNER].conditions.values())
    assert after.state.actors[s.OWNER].resources['resource:core.qi']==qi


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


@pytest.mark.parametrize('restriction',['repair_allowed','specialist_reconstruction','absolute_repair_protection'])
def test_native_gm_asset_repair_restrictions_are_source_scoped(tmp_path,restriction):
    row={'id':1,'kind':'custom','name':'Cultivated support','x':4,'y':5,'hp':100,'ac':15,
         'source_cl':21,restriction:False if restriction=='repair_allowed' else True,
         'asset_declaration':{'actor':'gm:scene_owner','authority':'GM','source_rule':'Creator forbids ordinary restoration',
            'visibility':'gm','expiry':'source_rule'}}
    combat,table,mid,send,commit=fixture(tmp_path,damage=20,scene_objects=[row])
    engine=cold(tmp_path,mid);obj=next(o for o in engine.state.objects.values() if o.component.get('name')=='Cultivated support')
    commit(s.candidate(table,mid,'Damage a structure',obj.object_id),decline=('choice:needle.mason_intervention',))
    next_owner(table,mid,commit)
    before=cold(tmp_path,mid).state.objects[obj.object_id].current_hp
    commit(s.candidate(table,mid,'Emergency Repairs: Repair Structure',obj.object_id))
    after=cold(tmp_path,mid).state.objects[obj.object_id]
    assert after.current_hp==before and after.component['source_cl']==21
    public=table.state(mid)
    assert 'Creator forbids ordinary restoration' not in str(public)
    assert 'gm:scene_owner' not in str(public)


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


def commit_other_table(table,mid,cid):
    answers=[]
    for _ in range(64):
        menu=table.state(mid)['menu']
        result=table.act(mid,cid,menu['decision_id'],menu['state_version'],0,answers)
        if result['status']=='COMMITTED':return result
        assert result['status']=='REACTION_REQUIRED',result
        prompt=result['reaction'];answer={**prompt['context'],'selection':'DECLINE'}
        if prompt.get('choice'):
            answer.update(selection='USE',option_ids=(prompt['choice'].get('preferred') or [prompt['choice']['options'][0]['id']])[:1])
        answers.append(answer)
    raise AssertionError('too many native table choices')


def test_journey_return_exports_damage_and_remaining_clock_without_healing(tmp_path):
    combat,j=journey_fixture(tmp_path);jid=j['journey_id']
    state=combat.journey_act(jid,j['revision'],s.OWNER,'mason_build',journey_wall_payload())
    oid=next(iter(state['runtime_objects']))
    result=combat.journey_start_combat(jid,state['revision'],{s.OWNER:'team:a',s.FOE:'team:b',s.SECOND:'team:a'},maximum_rounds=1)
    mid=result['match_id']
    from combat.tabletop_service import TabletopService
    table=TabletopService(combat,tmp_path)
    for _ in range(12):
        engine=cold(tmp_path,mid)
        if engine.state.terminal_result is not None:break
        commit_other_table(table,mid,table.state(mid)['menu']['end_turn'])
    assert cold(tmp_path,mid).state.terminal_result is not None
    journey=combat.journey_state(jid)
    resumed=combat.journey_resume(jid,journey['revision'])
    assert not resumed['runtime_objects'][oid]['destroyed']
    assert resumed['runtime_objects'][oid]['current_hp']==cold(tmp_path,mid).state.objects[oid].current_hp
    marker=resumed['runtime_objects'][oid]['component']['asset_anchor_runtime']
    assert marker['expires_num']/marker['expires_den']<=3594
    assert CombatService(ROOT,tmp_path).journey_state(jid)==resumed
    resumed=combat.journey_act(jid,resumed['revision'],s.OWNER,'wait',{'seconds':3594})
    assert resumed['runtime_objects'][oid]['destroyed']


def test_journey_reinforcement_native_clock_and_combat_continuation(tmp_path):
    combat,j=journey_fixture(tmp_path);jid=j['journey_id'];payload=journey_wall_payload()
    payload['sections'][0]['position']={'x':4,'y':5}
    from combat.ext.needle import cell_id
    from combat.gate2_runtime_models import Position
    payload['sections'][0]['material_source']='terrain:'+cell_id(Position(x=4,y=5))
    state=combat.journey_act(jid,j['revision'],s.OWNER,'mason_build',payload)
    oid=next(iter(state['runtime_objects']))
    state=combat.journey_act(jid,state['revision'],s.OWNER,'mason_reinforce',{'object_id':oid})
    assert state['runtime_objects'][oid]['ac']==17 and state['runtime_objects'][oid]['damage_threshold']==8
    result=combat.journey_start_combat(jid,state['revision'],{s.OWNER:'team:a',s.FOE:'team:b',s.SECOND:'team:a'})
    engine=cold(tmp_path,result['match_id'])
    assert engine.state.objects[oid].ac==17
    assert any(c.condition_id=='condition:typed.mason_reinforcement' for c in engine.state.actors[s.OWNER].conditions.values())


def test_journey_bastion_requires_each_native_turn_command(tmp_path):
    combat,j=journey_fixture(tmp_path);jid=j['journey_id'];payload=journey_wall_payload()
    payload.update(source=BASE+'raise_the_imperial_bastion',form='Raise Sections',chosen_allies=[s.OWNER])
    state=combat.journey_act(jid,j['revision'],s.OWNER,'mason_build',payload)
    with pytest.raises(ValueError):combat.journey_act(jid,state['revision'],s.OWNER,'wait',{'seconds':60})
    state=combat.journey_act(jid,state['revision'],s.OWNER,'wait',{'seconds':6})
    choices=combat.journey_menu(jid,s.OWNER)['options']
    assert {o['payload']['command'] for o in choices if o['kind']=='mason_command'}=={'Repair','Reconfigure','Raise New Work','Covered Advance','Brace the Defender'}
    state=combat.journey_act(jid,state['revision'],s.OWNER,'mason_command',{'command':'Brace the Defender','ally_id':s.OWNER})
    assert state['actors'][s.OWNER]['mason_command_due']==[12,1]
    assert CombatService(ROOT,tmp_path).journey_state(jid)==state


@pytest.mark.parametrize('explicit_destroyer',[False,True])
def test_native_artifact_source_exception_is_gm_declared_and_replayed(tmp_path,explicit_destroyer):
    row={'id':1,'kind':'custom','name':'Source-bound artifact support','x':4,'y':5,'hp':100,'artifact':True,
        'artifact_destruction_sources':['test:mason.native_damage'] if explicit_destroyer else [],
        'asset_declaration':{'actor':'gm:scene_owner','authority':'GM','source_rule':'This exact source explicitly destroys this artifact' if explicit_destroyer else 'Ordinary artifact damage',
            'visibility':'gm','expiry':'source_rule'}}
    combat,table,mid,send,commit=fixture(tmp_path,damage=20,scene_objects=[row])
    before=cold(tmp_path,mid);oid=next(o.object_id for o in before.state.objects.values() if o.component.get('artifact'))
    qi=before.state.actors[s.OWNER].resources['resource:core.qi']
    commit(s.candidate(table,mid,'Damage a structure',oid))
    after=cold(tmp_path,mid)
    assert after.state.actors[s.OWNER].resources['resource:core.qi']==qi-(0 if explicit_destroyer else 2)
    if explicit_destroyer:assert after.state.objects[oid].current_hp==80
    else:
        reduction=next(e.payload['reduction'] for e in after.events if e.event_type=='REACTION_RESOLVED' and e.source_definition_id==BASE+'fortress_crew')
        assert after.state.objects[oid].current_hp==80+reduction



def test_fortress_crew_native_save_advantage_and_five_foot_stand(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,probe=True)
    commit(at(table,mid,'Raise Barrier: Low Wall',4,5))
    next_owner(table,mid,commit)
    commit(s.candidate(table,mid,'Native save probe',s.OWNER))
    engine=cold(tmp_path,mid)
    save=next(e for e in reversed(engine.events) if e.event_type=='SAVE_ROLLED' and e.actor_id==s.OWNER)
    assert save.payload['mode']=='ADVANTAGE'
    menu=table.state(mid)['menu']
    stand=next(o['candidate_id'] for g in menu['actions'] if 'Stand up' in g['label'] for o in g['options'])
    movement=engine.state.actors[s.OWNER].movement_remaining_ft
    commit(stand)
    assert cold(tmp_path,mid).state.actors[s.OWNER].movement_remaining_ft==movement-5


def test_barrier_cover_uses_committed_native_geometry_and_sides(tmp_path):
    positions={s.OWNER:{'x':3,'y':6},s.FOE:{'x':9,'y':6},s.SECOND:{'x':2,'y':6}}
    combat,table,mid,send,commit=fixture(tmp_path,positions=positions)
    commit(at(table,mid,'Raise Barrier: Low Wall',6,6))
    engine=cold(tmp_path,mid)
    from combat.effect_cover import query
    owner=engine.state.actors[s.OWNER];foe=engine.state.actors[s.FOE];ally=engine.state.actors[s.SECOND]
    assert query(engine,[foe.position],foe.entity_id,owner,purpose='attack')['bonus']==2
    assert query(engine,[ally.position],ally.entity_id,owner,purpose='attack')['bonus']==0



def test_bastion_exact_minute_expiry_releases_concentration_and_sections(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,maximum_rounds=12)
    commit(at(table,mid,'Raise the Imperial Bastion: Raise Sections',4,5))
    start=cold(tmp_path,mid);initial_round=start.state.round_number
    for _ in range(40):
        session=combat._load_session(mid)
        if session.engine.state.round_number>=initial_round+10 and session.engine.state.current_actor_id==s.OWNER:break
        commit(table.state(mid)['menu']['end_turn'])
    engine=cold(tmp_path,mid)
    assert engine.state.round_number==initial_round+10
    assert not works(engine) and engine.state.actors[s.OWNER].concentration is None
    assert engine.state.actors[s.OWNER].resources['resource:core.qi']==22
