"""Two acquired cultivators sharing one real flame through committed lifecycles."""
from copy import deepcopy
import pytest
from combat.factory_compiler import compile_character
from combat.ext.qi_hearthfire import HEARTH,hearths,retire_zone_asset
from tests import test_mgr_t14_hearthfire_native as native
from tests.test_mgr_t14_hearthfire_expiry import OID,assert_mundane
from tests.worker2_support import OWNER,ALLY,fixture,candidate,settle,turn,reload


def two_cultivators(tmp_path,monkeypatch):
    guest=native.acquired_document(tmp_path,18)
    ordinary_sheet=native.sheet
    def sheet(*args,**kwargs):
        return deepcopy(guest) if kwargs.get('name')=='guest' else ordinary_sheet(*args,**kwargs)
    monkeypatch.setattr(native,'sheet',sheet)
    return native.journey(tmp_path,monkeypatch,
        arena_objects=[{'id':91,'kind':'stone_lantern','x':5,'y':6,'weight_lb':10}])


@pytest.mark.parametrize('reverse',[False,True])
def test_journey_transfer_settles_previous_source_and_enters_combat(tmp_path,monkeypatch,reverse):
    cold,jid,act,a,b=two_cultivators(tmp_path,monkeypatch)
    first,second=(b,a) if reverse else (a,b)
    def empower(who):
        option=next(o for o in cold().journey_menu(jid,who)['options']
                    if o['kind']=='hearth_kindle' and o['payload'].get('existing')==OID)
        return act('hearth_kindle',option['payload'],who)
    state=empower(first)
    original=deepcopy(state['runtime_objects'][OID]['component']['hearth_original'])
    act('wait',{'seconds':1})
    state=empower(second)
    assert state['actors'][first]['hearthfire']['camp']['retired']==1
    obj=state['runtime_objects'][OID]
    assert obj['component']['hearth_original']==original
    assert obj['component']['asset_anchor_runtime']['owner']==second
    result=native.begin_combat(cold,jid,state['revision'],{a:'party',b:'opponents'})
    loaded=cold()._load_session(result['match_id'])
    assert loaded.mechanical.replay()['status']=='PASS'
    assert not hearths(loaded.engine,loaded.engine.state.actors[first])
    assert len(hearths(loaded.engine,loaded.engine.state.actors[second]))==1
    actual=loaded.engine.state.objects[OID].model_dump(mode='json')
    # The empowerment receipt and the real-item baseline must cross the Journey ->
    # encounter boundary unchanged. The one exception is the combat scheduler's
    # asset_actor.creator_turn: it is written on the creator's first combat turn
    # (spirit_assets.default_asset_turn, asserted in test_mgr_t14_hearthfire_assets),
    # so it is absent in the pre-turn Journey snapshot and depends on initiative
    # order here. Normalize only that runtime annotation.
    actual_component=deepcopy(actual['component']);journey_component=deepcopy(obj['component'])
    actual_component['asset_actor'].pop('creator_turn',None);journey_component['asset_actor'].pop('creator_turn',None)
    assert actual_component==journey_component
    assert actual['current_hp']==54


def test_combat_old_owner_replacement_preserves_successor_after_cold_commit(tmp_path):
    def setup(bundles):
        bundles[1]=compile_character(native.acquired_document(tmp_path,18),
            actor_id=ALLY,reaction_plan={'ask':True})
        native.controls(bundles)
    combat,table,mid=fixture(tmp_path,[],cl=18,bundle_transform=setup,
        owner_bundle=native.acquired_bundle(tmp_path,18),
        battlefield_transform=lambda b:b.update(map_objects=[
            {'id':91,'kind':'stone_lantern','x':5,'y':6,'weight_lb':10}]))
    original=reload(tmp_path,mid).state.objects[OID].model_dump(mode='json')
    choices={'choice:needle.kindled_hearth_recipients':[OWNER,ALLY]}
    def empower():
        settle(table,mid,candidate(combat,mid,
            'Kindled Hearth: empower an existing contained flame',target=OID).candidate_id,choices=choices)
    empower()
    engine=reload(tmp_path,mid)
    old=hearths(engine,engine.state.actors[OWNER])[0].zone_id
    turn(table,mid,ALLY)
    empower()
    engine=reload(tmp_path,mid)
    successor=engine.state.objects[OID].model_dump(mode='json')
    assert successor['component']['asset_anchor_runtime']['owner']==ALLY
    assert successor['component']['hearth_original']==original
    assert not engine.state.zones[old].active, 'The superseded source must end at transfer'
    # A delayed/duplicate old removal event cannot act on its successor.
    sequence=engine.state.event_sequence
    retire_zone_asset(engine,{'payload':{'zone_id':old}})
    assert engine.state.objects[OID].model_dump(mode='json')==successor
    assert engine.state.event_sequence==sequence
    turn(table,mid,OWNER)
    settle(table,mid,candidate(combat,mid,'Kindled Hearth',at=(3,7)).candidate_id,choices=choices)
    engine=reload(tmp_path,mid)
    assert engine.state.objects[OID].model_dump(mode='json')==successor
    assert len(hearths(engine,engine.state.actors[ALLY]))==1
    # Ending the actual successor restores exactly the mundane lantern.
    turn(table,mid,ALLY)
    settle(table,mid,candidate(combat,mid,'Kindled Hearth',at=(4,7)).candidate_id,choices=choices)
    engine=reload(tmp_path,mid)
    assert_mundane(engine.state.objects[OID].model_dump(mode='json'),original)
