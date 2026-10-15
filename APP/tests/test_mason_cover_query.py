from tests.mason_native_support import *

def test_barrier_cover_uses_committed_native_geometry_and_sides(tmp_path):
    positions={s.OWNER:{'x':3,'y':6},s.FOE:{'x':9,'y':6},s.SECOND:{'x':2,'y':6}}
    combat,table,mid,send,commit=fixture(tmp_path,positions=positions)
    commit(at(table,mid,'Raise Barrier: Low Wall',6,6))
    engine=cold(tmp_path,mid)
    from combat.effect_cover import query
    owner=engine.state.actors[s.OWNER];foe=engine.state.actors[s.FOE];ally=engine.state.actors[s.SECOND]
    assert query(engine,[foe.position],foe.entity_id,owner,purpose='attack')['bonus']==2
    assert query(engine,[ally.position],ally.entity_id,owner,purpose='attack')['bonus']==0
