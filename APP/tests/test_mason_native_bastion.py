"""Native Mason bastion regressions; real commits, reload and replay."""
from tests.mason_native_support import *

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


def test_master_builder_repairs_another_native_sources_allied_asset(tmp_path):
    hearth='tianxia.subpath.qi.hearthfire_cultivator.feature.kindled_hearth'
    combat,table,mid,send,commit=fixture(tmp_path,damage=20,second_features=[hearth])
    commit(at(table,mid,'Raise the Imperial Bastion: Raise Sections',4,5))
    for _ in range(6):
        if table.state(mid)['menu']['actor_id']==s.SECOND:break
        commit(table.state(mid)['menu']['end_turn'])
    candidates=combat._legal_candidates(combat._load_session(mid))
    c=next(c for c in candidates if c.display_name=='Kindled Hearth' and c.destination is not None and
        (c.destination.x,c.destination.y)==(6,5))
    commit(c.candidate_id)
    engine=cold(tmp_path,mid);asset=next(o for o in engine.state.objects.values() if o.object_kind=='cultivation_asset')
    assert asset.owner_id==s.SECOND and asset.component['source_cl']==17
    next_owner(table,mid,commit)
    commit(s.candidate(table,mid,'Damage a structure',asset.object_id),decline=('choice:needle.mason_intervention',))
    damaged=cold(tmp_path,mid).state.objects[asset.object_id]
    assert damaged.current_hp==31
    next_owner(table,mid,commit)
    after=cold(tmp_path,mid).state.objects[asset.object_id]
    assert 31<after.current_hp<=51
    assert after.owner_id==s.SECOND and after.component['created_by']==asset.component['created_by']


def test_bastion_later_section_can_use_earlier_section_support_atomically(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path)
    from combat.ext.needle import cell_id
    from combat.gate2_runtime_models import Position
    commit(at(table,mid,'Raise the Imperial Bastion: Raise Sections',6,8),picks={
        'choice:needle.mason_count':'2','choice:needle.mason_form_0':'Platform',
        'choice:needle.mason_form_1':'Low Wall','choice:needle.mason_space_1':cell_id(Position(x=6,y=8,z=2))})
    engine=cold(tmp_path,mid);objects=works(engine)
    assert len(objects)==2 and sorted(o.position.z for o in objects)==[0,2]
    assert engine.state.actors[s.OWNER].resources['resource:core.qi']==22


