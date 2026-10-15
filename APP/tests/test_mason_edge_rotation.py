"""Invalid edge rotations cannot hide inward movement or later legal rotation."""
from tests.mason_native_support import *


def test_last_row_reconfigure_skips_invalid_rotation_then_rotates_inward(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,positions={
        s.OWNER:{'x':36,'y':17},s.FOE:{'x':35,'y':17},s.SECOND:{'x':34,'y':17}})
    commit(at(table,mid,'Raise the Imperial Bastion: Raise Sections',38,19))
    oid=works(cold(tmp_path,mid))[0].object_id
    def command(destination):
        commit(table.state(mid)['menu']['end_turn'])
        while table.state(mid)['menu']['actor_id']!=s.OWNER:
            commit(table.state(mid)['menu']['end_turn'],picks={
                'choice:needle.mason_command':'Reconfigure',
                'choice:needle.mason_command_reconfigure':destination})
    command('37,18,0')
    obj=cold(tmp_path,mid).state.objects[oid]
    assert (obj.position.x,obj.position.y,obj.component['rotation'])==(37,18,0)
    command('37,18,90')
    engine=cold(tmp_path,mid);obj=engine.state.objects[oid]
    assert obj.component['rotation']==obj.component['mason']['declaration']['rotation']==90
    from combat.object_geometry import target_cells
    assert {(p.x,p.y) for p in target_cells(engine,obj)}=={(37,18),(37,19)}
    assert engine.grid.terrain_at((37,19,0),'BLOCKED')
    assert not engine.grid.terrain_at((38,18,0),'BLOCKED')
    assert obj.current_hp==108 and engine.state.actors[s.OWNER].resources['resource:core.qi']==22
