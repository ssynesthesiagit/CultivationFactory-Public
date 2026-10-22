"""Real-item expiry through committed Journey calls and cold service reloads."""
from copy import deepcopy
import pytest
from combat.journey_assets import JourneyAssetContext
from tests import test_mgr_t14_hearthfire_native as native


OID='object:map.91'


def empower(cold,jid,act,actor):
    option=next(o for o in cold().journey_menu(jid,actor)['options']
                if o['kind']=='hearth_kindle' and o['payload'].get('existing')==OID)
    return act('hearth_kindle',option['payload'])


def assert_mundane(obj,original):
    assert not obj['destroyed'], 'Expiry must leave the real item intact on every later transaction'
    assert obj['current_hp']==original['current_hp']
    assert obj['maximum_hp']==original['maximum_hp']
    assert obj['ac']==original['ac']
    assert obj['damage_immunities']==original['damage_immunities']
    assert obj['component']==original['component']
    assert 'hearth_original' not in obj['component']
    assert 'asset_anchor_runtime' not in obj['component']


def test_expiry_is_once_only_after_reload_and_can_renew_real_lantern(tmp_path,monkeypatch):
    cold,jid,act,a,b=native.journey(tmp_path,monkeypatch,
        arena_objects=[{'id':91,'kind':'stone_lantern','x':5,'y':6,'weight_lb':10}])
    state=empower(cold,jid,act,a)
    original=deepcopy(state['actors'][a]['hearthfire']['camp']['native_object']['component']['hearth_original'])
    state=act('wait',{'seconds':28800})
    assert_mundane(state['runtime_objects'][OID],original)
    count=sum(e['kind']=='OBJECT_UPDATED' and e.get('object',{}).get('object_id')==OID for e in state['events'])
    state=act('wait',{'seconds':1})
    assert_mundane(state['runtime_objects'][OID],original)
    assert sum(e['kind']=='OBJECT_UPDATED' and e.get('object',{}).get('object_id')==OID for e in state['events'])==count
    # Renewal must not run retirement a second time, or nest the old blessing.
    state=empower(cold,jid,act,a)
    renewed=state['runtime_objects'][OID]
    assert renewed['component']['hearth_original']==original
    assert not renewed['destroyed'] and renewed['current_hp']==54
    assert state['actors'][a]['resources']['resource:core.qi']==98
    state=act('wait',{'seconds':28801})
    assert_mundane(state['runtime_objects'][OID],original)
    state=act('wait',{'seconds':1})
    assert_mundane(state['runtime_objects'][OID],original)
    result=native.begin_combat(cold,jid,state['revision'],{a:'party',b:'opponents'})
    loaded=cold()._load_session(result['match_id'])
    assert loaded.mechanical.replay()['status']=='PASS'
    assert_mundane(loaded.engine.state.objects[OID].model_dump(mode='json'),original)


@pytest.mark.parametrize('other_kind',['crate','stone_lantern'])
def test_offscene_expiry_never_retires_same_local_id_on_another_map(tmp_path,monkeypatch,other_kind):
    cold,jid,act,a,b=native.journey(tmp_path,monkeypatch,
        arena_objects=[{'id':91,'kind':'stone_lantern','x':5,'y':6,'weight_lb':10}])
    state=empower(cold,jid,act,a)
    old=deepcopy(state['actors'][a]['hearthfire']['camp'])
    original=old['native_object']['component']['hearth_original']
    first_map=deepcopy(state['battlefield'])
    act('wait',{'seconds':100});act('finish')
    second_map={**deepcopy(first_map),'stable_id':'hearth:other-map',
                'map_objects':[{'id':91,'kind':other_kind,'x':5,'y':6,'weight_lb':10}]}
    monkeypatch.setattr(native.CombatService,'factory_arenas',lambda self:{'scene':second_map})
    state=cold().create_journey(project_ids=['hearth','guest'],arena_id='scene',
        positions={a:{'x':3,'y':6},b:{'x':4,'y':6}},base_paces={a:18000,b:18000})
    second=state['journey_id']
    untouched=JourneyAssetContext(cold().journeys.load(second)).state.objects[OID].model_dump(mode='json')
    state=cold().journey_act(second,state['revision'],a,'wait',{'seconds':28700})
    actual=JourneyAssetContext(cold().journeys.load(second)).state.objects[OID].model_dump(mode='json')
    assert actual==untouched, 'An expired Hearth on another map must never change this map’s matching local ID'
    assert OID not in state.get('runtime_objects',{})
    f=state['actors'][a]['hearthfire']
    assert_mundane(f['objects'][old['scene']+'|'+OID]['object'],original)
    assert cold().journey_state(second)==state
    state=cold().journey_act(second,state['revision'],a,'wait',{'seconds':1})
    state=cold().journey_act(second,state['revision'],a,'finish',{})
    monkeypatch.setattr(native.CombatService,'factory_arenas',lambda self:{'scene':first_map})
    state=cold().create_journey(project_ids=['hearth','guest'],arena_id='scene',
        positions={a:{'x':3,'y':6},b:{'x':4,'y':6}},base_paces={a:18000,b:18000})
    third=state['journey_id']
    result=native.begin_combat(cold,third,state['revision'],{a:'party',b:'opponents'})
    loaded=cold()._load_session(result['match_id'])
    assert loaded.mechanical.replay()['status']=='PASS'
    assert_mundane(loaded.engine.state.objects[OID].model_dump(mode='json'),original)


def test_hardship_option_explains_penalty_and_table_owner_declaration(tmp_path,monkeypatch):
    cold,jid,act,a,b=native.journey(tmp_path,monkeypatch)
    native.kindle(act,a,b)
    option=next(o for o in cold().journey_menu(jid,b)['options'] if o['kind']=='hearth_hardship')
    assert option['label']=='Record this creature’s environmental Exhaustion or reduced speed and when it ends; the table owner must declare the cause, penalty and duration. Requires a live native table-owner declaration; no action or Qi cost.'


def test_expiry_does_not_remove_another_cultivators_new_empowerment(tmp_path,monkeypatch):
    # Both cultivators acquire the real progression; the guest uses the same
    # public Journey command rather than an injected runtime object/profile.
    guest=native.acquired_document(tmp_path,18)
    ordinary_sheet=native.sheet
    def sheet(*args,**kwargs):
        return deepcopy(guest) if kwargs.get('name')=='guest' else ordinary_sheet(*args,**kwargs)
    monkeypatch.setattr(native,'sheet',sheet)
    cold,jid,act,a,b=native.journey(tmp_path,monkeypatch,
        arena_objects=[{'id':91,'kind':'stone_lantern','x':5,'y':6,'weight_lb':10}])
    state=empower(cold,jid,act,a)
    original=deepcopy(state['runtime_objects'][OID]['component']['hearth_original'])
    act('wait',{'seconds':1})
    option=next(o for o in cold().journey_menu(jid,b)['options']
                if o['kind']=='hearth_kindle' and o['payload'].get('existing')==OID)
    state=act('hearth_kindle',option['payload'],b)
    other=deepcopy(state['runtime_objects'][OID])
    state=act('wait',{'seconds':28799})
    assert state['runtime_objects'][OID]==other, 'Expiry must match the exact empowerment, including its cultivator'
    assert cold().journey_state(jid)==state
    state=act('wait',{'seconds':1})
    assert_mundane(state['runtime_objects'][OID],original)
    state=act('wait',{'seconds':1})
    assert_mundane(state['runtime_objects'][OID],original)
    assert cold().journey_state(jid)==state
    result=native.begin_combat(cold,jid,state['revision'],{a:'party',b:'opponents'})
    loaded=cold()._load_session(result['match_id'])
    assert loaded.mechanical.replay()['status']=='PASS'
    assert_mundane(loaded.engine.state.objects[OID].model_dump(mode='json'),original)
