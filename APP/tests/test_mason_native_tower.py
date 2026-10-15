"""The printed Tower's entrance, two floors and arrow slits in native play."""
from tests.mason_native_support import *


def test_tower_entrance_both_levels_and_three_quarters_attack_cover(tmp_path):
    declaration={'actor':'gm:review','authority':'GM','source_rule':'This stable raised deck has an ordinary ladder.',
        'visibility':'public','expiry':'source_rule'}
    combat,table,mid,send,commit=fixture(tmp_path,features=[*FEATURES,'TAL_LIGHTNING_LIGHTNING_LASH'],
        positions={s.OWNER:{'x':5,'y':9},s.FOE:{'x':12,'y':9,'z':3},s.SECOND:{'x':2,'y':6}},
        scene_objects=[{'id':1,'kind':'custom','x':12,'y':9,'height_ft':15,'blocks':False,
            'ordinary_route':'ladder','asset_declaration':declaration}])
    commit(at(table,mid,'Bridge the Impossible: Defensive Tower',6,8))
    engine=cold(tmp_path,mid)
    assert len(works(engine))==6
    entrance=next(o for o in works(engine) if o.component['mason']['declaration'].get('entrance'))
    assert not entrance.component['blocks']
    floors=[r for r in engine.grid.roof_surfaces if entrance.object_id in r.id and r.solid_at(7,9)]
    assert sorted(r.walk_ft for r in floors)==[15,30]
    def climb(destination):
        candidates=combat._legal_candidates(combat._load_session(mid))
        route=next(c for c in candidates if c.kind=='MOVE' and c.destination is not None and
            (c.destination.x,c.destination.y,c.destination.z)==destination)
        commit(route.candidate_id)
        actor=cold(tmp_path,mid).state.actors[s.OWNER]
        assert (actor.position.x,actor.position.y,actor.position.z)==destination
    climb((6,9,3))
    next_owner(table,mid,commit)
    commit(s.candidate(table,mid,'Lightning Lash',s.FOE))
    engine=cold(tmp_path,mid)
    roll=next(e for e in reversed(engine.events) if e.event_type=='ATTACK_ROLLED' and s.FOE in e.target_ids)
    assert roll.payload['cover_bonus']==5
    climb((6,9,6))
