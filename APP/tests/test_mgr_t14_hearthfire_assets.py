"""Source acquisition -> native object actions/areas -> commit/cold replay."""
import pytest
from combat.gate5_service import CombatService
from tests.h1_support import ROOT,sheet
from tests.worker2_support import OWNER,ALLY,FOE,fixture,candidate,settle,turn,reload
from tests.test_mgr_t14_hearthfire_native import acquired_bundle


def resilient(bundles):
    from combat.canonical import canonical_sha256
    for bundle in bundles:
        bundle['actor_template']['maximum_hp']=500
        bundle.pop('bundle_sha256',None)
        bundle['bundle_sha256']=canonical_sha256(bundle)


def game(tmp_path,*,dc=9):
    foe=sheet(['STARS_TAL_FALLING_STAR'],cl=18,dc=dc)
    combat,table,mid=fixture(tmp_path,[],cl=18,owner_pb=6,owner_bundle=acquired_bundle(tmp_path,18),
        foe_sheet=foe,bundle_transform=resilient,seed='HEARTH-ASSET-'+str(dc),
        battlefield_transform=lambda a:a.update(map_objects=[{'id':91,'kind':'wooden_crate','x':5,'y':7}]))
    settle(table,mid,candidate(combat,mid,'Kindled Hearth',at=(5,6)).candidate_id,
        choices={'choice:needle.kindled_hearth_recipients':[OWNER,ALLY]})
    e=reload(tmp_path,mid)
    obj=next(o for o in e.state.objects.values() if o.component.get('name')=='Kindled Hearth')
    turn(table,mid,FOE)
    return combat,table,mid,obj.object_id


def test_native_asset_defaults_to_dodge_on_its_creators_turn(tmp_path):
    combat,table,mid,oid=game(tmp_path)
    e=reload(tmp_path,mid)
    rows=[c for c in e.legal_candidates() if c.target_ids==(oid,) and
        e.action_catalog[c.source_definition_id].parameters.get('object_attack')]
    assert rows
    settle(table,mid,rows[0].candidate_id)
    e=reload(tmp_path,mid)
    rolls=[r for r in e.rolls if r.reason.startswith('ATTACK:') and ':object:' in r.reason]
    assert rolls and rolls[-1].mode=='DISADVANTAGE'
    before=e.state.objects[oid].position
    turn(table,mid,OWNER)
    e=reload(tmp_path,mid)
    profile=e.state.objects[oid].component['asset_actor']
    assert profile['creator_turn']==e.state.actors[OWNER].turns_started
    assert e.state.objects[oid].position==before
    assert not any(a.entity_id==oid for a in e.state.actors.values())
    turn(table,mid,FOE)
    e=reload(tmp_path,mid)
    rows=[c for c in e.legal_candidates() if c.target_ids==('object:map.91',) and
        e.action_catalog[c.source_definition_id].parameters.get('object_attack')]
    assert rows
    settle(table,mid,rows[0].candidate_id)
    e=reload(tmp_path,mid)
    assert [r for r in e.rolls if r.reason.startswith('ATTACK:') and ':object:' in r.reason][-1].mode=='NORMAL'


@pytest.mark.parametrize('dc,success',[(9,True),(100,False)])
def test_native_asset_uses_creator_save_bonus_and_exact_half_branch(tmp_path,dc,success):
    combat,table,mid,oid=game(tmp_path,dc=dc)
    before=reload(tmp_path,mid);count=len(before.rolls)
    initial=before.state.objects[oid].current_hp
    settle(table,mid,candidate(combat,mid,'Falling Star',at=(5,6)).candidate_id)
    e=reload(tmp_path,mid)
    saves=[r for r in e.rolls[count:] if r.actor_id==oid and r.reason.startswith('SAVE:')]
    assert len(saves)==1 and saves[0].modifier==8
    assert saves[0].mode=='ADVANTAGE' and (saves[0].total>=dc)==success
    damage=[r for r in e.rolls[count:] if r.reason.startswith('DAMAGE:')]
    assert damage
    amount=damage[0].total//(2 if success else 1)
    assert e.state.objects[oid].current_hp==max(0,initial-amount)
    # A mundane crate gains neither the source actor profile nor its save.
    assert 'asset_actor' not in e.state.objects['object:map.91'].component
    assert not any(r.actor_id=='object:map.91' and r.reason.startswith('SAVE:') for r in e.rolls)


def test_native_map_property_declaration_round_trips_without_rebinding(tmp_path):
    document={'map_id':'asset-roundtrip','display_name':'A real lantern',
        'width_squares':20,'height_squares':14,'objects':[{'id':91,'kind':'stone_lantern','x':5,'y':6,
            'property_owner_id':'actor:factory.guest','asset_declaration':{'actor':'table-owner','authority':'GM',
                'source_rule':'The guest owns this lantern.','visibility':'public','expiry':'source_rule'}}]}
    service=CombatService(ROOT,tmp_path)
    saved=service.tabletop_maps.save(document)
    cold=CombatService(ROOT,tmp_path).tabletop_maps.get(saved['map_id'])
    assert cold['objects']==saved['objects']
    saved['objects'][0]['id']=92
    with pytest.raises(Exception,match='declaration'):
        service.tabletop_maps.save(saved)


@pytest.mark.parametrize('name',['Hearth','Campfire','Stove','Cooking fire'])
def test_declared_real_contained_fire_uses_native_map_and_retains_identity(tmp_path,monkeypatch,name):
    from tests.test_mgr_t14_hearthfire_native import journey
    saved=CombatService(ROOT,tmp_path).tabletop_maps.save({'map_id':'contained-fire','display_name':name,
        'width_squares':25,'height_squares':15,'objects':[{'id':91,'kind':'custom','name':name,
            'x':5,'y':6,'blocks':False,'contained_flame':True,'asset_declaration':{
                'actor':'table-owner','authority':'GM','source_rule':'This real '+name.lower()+' contains an actual burning fire.',
                'visibility':'public','expiry':'source_rule'}}]})
    saved=CombatService(ROOT,tmp_path).tabletop_maps.get(saved['map_id'])
    cold,jid,act,a,b=journey(tmp_path,monkeypatch,arena_objects=saved['objects'])
    option=next(o for o in cold().journey_menu(jid,a)['options'] if o['payload'].get('existing')=='object:map.91')
    state=act('hearth_kindle',option['payload'])
    assert state['actors'][a]['resources']['resource:core.qi']==99
    obj=state['runtime_objects']['object:map.91']
    assert obj['component']['hearth_original']['component']['name']==name
    assert obj['component']['contained_flame'] is True
    result=cold().journey_start_combat(jid,state['revision'],{a:'team:a',b:'team:b'})
    loaded=cold()._load_session(result['match_id'])
    assert loaded.mechanical.replay()['status']=='PASS'
    assert loaded.engine.state.objects['object:map.91'].component['hearth_original']['component']['name']==name


def test_unlit_or_undeclared_custom_objects_do_not_offer_empowerment(tmp_path,monkeypatch):
    from tests.test_mgr_t14_hearthfire_native import journey
    rows=[{'id':91,'kind':'stone_lantern','x':5,'y':6,'contained_flame':False,
        'asset_declaration':{'actor':'table-owner','authority':'GM','source_rule':'This lantern is unlit.',
                            'visibility':'public','expiry':'source_rule'}},
          {'id':92,'kind':'custom','name':'Something called a campfire','x':5,'y':7}]
    saved=CombatService(ROOT,tmp_path).tabletop_maps.save({'map_id':'unlit-fire','display_name':'Unlit fire',
        'width_squares':25,'height_squares':15,'objects':rows})
    cold,jid,act,a,b=journey(tmp_path,monkeypatch,arena_objects=saved['objects'])
    assert not any(o['payload'].get('existing') in ('object:map.91','object:map.92') for o in cold().journey_menu(jid,a)['options'])
