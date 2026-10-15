"""Review regressions through committed table and elapsed journey callers."""
from tests.mason_native_support import *


def test_expired_journey_work_cannot_be_reconstructed(tmp_path):
    combat,j=journey_fixture(tmp_path);jid=j['journey_id']
    payload=journey_wall_payload()
    payload['sections'][0].update(position={'x':3,'y':5},material_source='terrain:3,5')
    # The native material wire identifier is derived from the exact placement.
    from combat.ext.needle import cell_id
    from combat.gate2_runtime_models import Position
    payload['sections'][0]['material_source']='terrain:'+cell_id(Position(x=3,y=5))
    state=combat.journey_act(jid,j['revision'],s.OWNER,'mason_build',payload)
    oid=next(iter(state['runtime_objects']))
    state=combat.journey_act(jid,state['revision'],s.OWNER,'wait',{'seconds':3600})
    with pytest.raises(ValueError):
        combat.journey_act(jid,state['revision'],s.OWNER,'mason_repair',{
            'object_id':oid,'material_source':payload['sections'][0]['material_source'],'sufficient_material':True})
    assert CombatService(ROOT,tmp_path).journey_state(jid)==state


def test_edge_reconfigure_commits_a_legal_inward_move(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,positions={
        s.OWNER:{'x':36,'y':6},s.FOE:{'x':35,'y':6},s.SECOND:{'x':34,'y':6}})
    commit(at(table,mid,'Raise the Imperial Bastion: Raise Sections',38,8))
    oid=works(cold(tmp_path,mid))[0].object_id
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id']!=s.OWNER:
        commit(table.state(mid)['menu']['end_turn'],picks={
            'choice:needle.mason_command':'Reconfigure','choice:needle.mason_command_reconfigure':'37,8,0'})
    obj=cold(tmp_path,mid).state.objects[oid]
    assert (obj.position.x,obj.position.y)==(37,8)


def test_ascending_stair_has_one_continuous_slope_after_reload(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path)
    commit(at(table,mid,'Bridge the Impossible: Ascending Stair',6,8))
    engine=cold(tmp_path,mid)
    roofs=[r for r in engine.grid.roof_surfaces if ':ramp:' in r.id]
    by_x={x:r.walk_ft for r in roofs for x in range(6,14) if r.solid_at(x,8)}
    assert [by_x[x] for x in range(6,14)]==[5,10,15,15,20,25,30,30]
