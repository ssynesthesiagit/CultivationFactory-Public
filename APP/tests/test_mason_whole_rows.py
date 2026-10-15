"""Printed option/category boundaries supplement the five-row native cohort."""
from tests.mason_native_support import *


@pytest.mark.parametrize('form',['Low Wall','Tall Wall','Ramp','Platform','Watchtower','Bridge Section'])
def test_all_six_bastion_forms_commit_source_profiles(tmp_path,form):
    combat,table,mid,send,commit=fixture(tmp_path)
    commit(at(table,mid,'Raise the Imperial Bastion: Raise Sections',6,8),picks={'choice:needle.mason_form_0':form})
    engine=cold(tmp_path,mid);obj=works(engine)[0]
    assert obj.component['mason']['form']==form
    assert (obj.ac,obj.current_hp,obj.maximum_hp,obj.damage_threshold)==(18,108,108,8)
    assert set(obj.component['resist'])=={'ACID','BLUDGEONING','COLD','FIRE','LIGHTNING','NECROTIC','PIERCING','POISON','RADIANT','SLASHING','THUNDER'}
    assert set(obj.damage_immunities)=={'POISON','PSYCHIC'}
    assert engine.state.actors[s.OWNER].resources['resource:core.qi']==22
    assert engine.state.actors[s.OWNER].concentration is not None


@pytest.mark.parametrize('form',['Ramp','Platform'])
def test_barrier_minimum_printed_dimensions_remain_reachable(tmp_path,form):
    combat,table,mid,send,commit=fixture(tmp_path)
    commit(at(table,mid,'Raise Barrier: '+form,6,8),picks={
        'choice:needle.mason_length_0':'1','choice:needle.mason_width_0':'1',
        'choice:needle.mason_height_0':'1','choice:needle.mason_orientation_0':'90'})
    obj=works(cold(tmp_path,mid))[0];d=obj.component['mason']['declaration']
    assert (d['length_ft'],d['width_ft'],d['height_ft'],d['rotation'])==(1,1,1,90)


def test_bastion_ignores_native_painted_rubble_for_chosen_ally(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,map_terrain=[{'terrain':'loose rubble','cells':[[4,7]]}])
    def route():
        return next(c for c in combat._legal_candidates(combat._load_session(mid))
            if c.kind=='MOVE' and c.destination is not None and
            (c.destination.x,c.destination.y,c.destination.z)==(4,7,0))
    assert route().movement_cost_ft==10
    commit(at(table,mid,'Raise the Imperial Bastion: Raise Sections',6,8))
    candidate=route();assert candidate.movement_cost_ft==5
    budget=cold(tmp_path,mid).state.actors[s.OWNER].movement_remaining_ft
    commit(candidate.candidate_id)
    assert cold(tmp_path,mid).state.actors[s.OWNER].movement_remaining_ft==budget-5


@pytest.mark.parametrize('kind',['Construct','Humanoid'])
def test_repair_creature_domain_comes_from_native_printed_identity(tmp_path,kind):
    combat,table,mid,send,commit=fixture(tmp_path,record_kinds={s.FOE:kind})
    for _ in range(6):
        engine=cold(tmp_path,mid)
        attack=next(c for c in combat._legal_candidates(combat._load_session(mid))
            if s.FOE in c.target_ids and c.kind=='ACTION' and
            engine.action_catalog[c.source_definition_id].resolution_kind=='ATTACK')
        commit(attack.candidate_id,decline=('choice:needle.mason_intervention',))
        damaged=cold(tmp_path,mid).state.actors[s.FOE]
        if damaged.current_hp<damaged.maximum_hp:break
        next_owner(table,mid,commit)
    before=cold(tmp_path,mid);hp=before.state.actors[s.FOE].current_hp
    assert hp<before.state.actors[s.FOE].maximum_hp
    next_owner(table,mid,commit)
    options=[o for g in table.state(mid)['menu']['actions'] if g['label']=='Emergency Repairs: Repair Construct (other side)' for o in g['options'] if s.FOE in o.get('target_ids',[])]
    if kind=='Humanoid':assert not options;return
    assert options
    qi=cold(tmp_path,mid).state.actors[s.OWNER].resources['resource:core.qi']
    commit(options[0]['candidate_id'])
    after=cold(tmp_path,mid)
    assert hp<after.state.actors[s.FOE].current_hp<=after.state.actors[s.FOE].maximum_hp
    assert after.state.actors[s.OWNER].resources['resource:core.qi']==qi-2
    assert after.state.actors[s.FOE].team_id==before.state.actors[s.FOE].team_id
