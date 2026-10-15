"""The general physical-route seam has a second, native GM-authored producer."""
from tests.mason_native_support import *


@pytest.mark.parametrize('declared',[False,True])
def test_native_gm_ladder_without_mason_is_scoped_and_replayed(tmp_path,declared):
    obj={'id':1,'kind':'custom','name':'A wooden ladder','x':4,'y':5,'height_ft':10,'blocks':False,
        'source_cl':1,'asset_declaration':{'actor':'gm:review','authority':'GM',
            'source_rule':'This object has an ordinary ladder to its ten-foot top.',
            'visibility':'public','expiry':'source_rule'}}
    if declared:obj['ordinary_route']='ladder'
    combat,table,mid,send,commit=fixture(tmp_path,features=[],scene_objects=[obj])
    engine=cold(tmp_path,mid)
    assert not any(a.parameters.get('mason_build') for a in engine.action_catalog.values())
    candidates=combat._legal_candidates(combat._load_session(mid))
    destination=lambda c,xyz:c.kind=='MOVE' and c.destination is not None and (c.destination.x,c.destination.y,c.destination.z)==xyz
    assert not any(destination(c,(1,6,2)) for c in candidates), 'a ladder never grants free-air climbing'
    climbs=[c for c in candidates if destination(c,(4,5,2))]
    if not declared:assert not climbs;return
    assert climbs
    commit(climbs[0].candidate_id)
    actor=cold(tmp_path,mid).state.actors[s.OWNER]
    assert (actor.position.x,actor.position.y,actor.position.z)==(4,5,2)


def test_native_route_input_rejects_unknown_geometry(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,features=[])
    with pytest.raises(ValueError):
        combat.tabletop_maps.save({'display_name':'Invalid route','width_squares':10,'height_squares':10,'walls':[],
            'objects':[{'id':1,'kind':'custom','x':4,'y':5,'height_ft':10,'ordinary_route':'free flight',
                'asset_declaration':{'actor':'gm:review','authority':'GM','source_rule':'No route supplied.',
                    'visibility':'public','expiry':'source_rule'}}]})


def test_native_gm_route_continues_in_journey_without_mason(tmp_path):
    obj={'id':1,'kind':'custom','x':4,'y':5,'height_ft':10,'blocks':False,'ordinary_route':'ladder',
        'asset_declaration':{'actor':'gm:review','authority':'GM','source_rule':'A stable ladder reaches this top.',
            'visibility':'public','expiry':'source_rule'}}
    combat,table,mid,send,commit=fixture(tmp_path,features=[],scene_objects=[obj])
    engine=cold(tmp_path,mid)
    j=combat.journeys.create(engine.typed_bundle_documents,engine.battlefield_document,
        {aid:a.position.model_dump(mode='json') for aid,a in engine.state.actors.items()},
        {aid:3000 for aid in engine.state.actors})
    jid=j['journey_id']
    state=combat.journey_act(jid,j['revision'],s.OWNER,'move',{'path':[
        {'x':3,'y':5,'z':1},{'x':3,'y':5,'z':2},{'x':4,'y':5,'z':2}]})
    assert state['actors'][s.OWNER]['position']=={'x':4,'y':5,'z':2}
    assert CombatService(ROOT,tmp_path).journey_state(jid)==state


def test_native_asset_declaration_cold_map_binding_is_idempotent(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,features=[])
    obj={'id':1,'kind':'custom','x':4,'y':5,'source_cl':21,'repair_allowed':False,
        'asset_declaration':{'actor':'gm:review','authority':'GM','source_rule':'Creator forbids repair.',
            'visibility':'gm','expiry':'source_rule'}}
    saved=combat.tabletop_maps.save({'display_name':'Bound declaration','width_squares':10,'height_squares':10,
        'walls':[],'objects':[obj]})
    loaded=CombatService(ROOT,tmp_path).tabletop_maps.get(saved['map_id'])
    assert loaded['objects'][0]['source_cl']==21 and loaded['objects'][0]['repair_allowed'] is False
    assert loaded['objects'][0]['asset_declaration']['object_id']==1
    imported={**saved,'display_name':'Wrong binding','objects':[{**loaded['objects'][0],'id':2}]}
    with pytest.raises(ValueError,match='bound to its actual map object'):
        combat.tabletop_maps.save(imported)
