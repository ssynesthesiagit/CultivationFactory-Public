"""Native Mason repairs crew regressions; real commits, reload and replay."""
from tests.mason_native_support import *

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


