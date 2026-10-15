"""A visible deck permits the same native ladder descent for an automatic mover."""
from tests.mason_native_support import *


def test_automatic_mover_can_descend_visible_native_ladder(tmp_path):
    obj={'id':1,'kind':'custom','x':4,'y':5,'height_ft':10,'blocks':False,'ordinary_route':'ladder',
        'asset_declaration':{'actor':'gm:review','authority':'GM','source_rule':'A stable ladder reaches this top.',
            'visibility':'public','expiry':'source_rule'}}
    combat,table,mid,send,commit=fixture(tmp_path,features=[],scene_objects=[obj])
    candidate=next(c for c in combat._legal_candidates(combat._load_session(mid)) if c.kind=='MOVE'
        and c.destination is not None and (c.destination.x,c.destination.y,c.destination.z)==(4,5,2)
        and c.metadata.get('movement_mode')=='climb')
    commit(candidate.candidate_id)
    next_owner(table,mid,commit)
    combat.set_controller_mode(mid,actor_id=s.OWNER,controller_mode='LOCAL_AUTO')
    engine=cold(tmp_path,mid)
    from combat.senses import perceives_cell
    base_visible=perceives_cell(engine,engine.state.actors[s.OWNER],next(iter(engine.state.objects.values())).position)
    candidate=next((c for c in combat._legal_candidates(combat._load_session(mid)) if c.kind=='MOVE'
        and c.destination is not None and (c.destination.x,c.destination.y,c.destination.z)==(3,5,0)
        and c.metadata.get('movement_mode')=='climb'),None)
    assert candidate is not None,('the visible ladder deck must offer native descent',base_visible)
    s.force_ai_candidate(combat,mid,s.OWNER,candidate.candidate_id)
    result=table.auto_step(mid,0,[])
    assert result['status']=='COMMITTED',result
    actor=cold(tmp_path,mid).state.actors[s.OWNER]
    assert (actor.position.x,actor.position.y,actor.position.z)==(3,5,0)
