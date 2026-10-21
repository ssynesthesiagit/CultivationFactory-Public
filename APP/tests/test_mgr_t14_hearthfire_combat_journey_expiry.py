"""Combat delivery receipts survive native encounter settlement and travel expiry."""
from copy import deepcopy

import pytest

from combat.asset_anchor_runtime import KEY
from combat.ext.qi_hearthfire import HEARTH
from combat.ext.qi_hearthfire_camp import camp_owns_hearth,retire_camp
from combat.gate2_runtime_models import RuntimeObjectState
from combat.journey_assets import JourneyAssetContext
from combat.tabletop_service import TabletopService
from tests import test_mgr_t14_hearthfire_native as native
from tests.test_mgr_t14_hearthfire_expiry import OID,assert_mundane
from tests.test_mgr_t14_hearthfire_source_transfer import two_cultivators
from tests.worker2_support import candidate,settle,turn


def combat_cast_and_resume(cold,jid,tmp_path,a,b):
    state=cold().journey_state(jid)
    result=native.begin_combat(cold,jid,state['revision'],{a:'party',b:'opponents'},maximum_rounds=2)
    mid=result['match_id'];table=TabletopService(cold(),tmp_path)
    loaded=cold()._load_session(mid)
    original=loaded.engine.state.objects[OID].model_dump(mode='json')
    turn(table,mid,a)
    cast=candidate(cold(),mid,'Kindled Hearth: empower an existing contained flame',target=OID)
    settle(table,mid,cast.candidate_id,choices={'choice:needle.kindled_hearth_recipients':[a]})
    for _ in range(6):
        loaded=cold()._load_session(mid)
        assert loaded.mechanical.replay()['status']=='PASS'
        if loaded.engine.state.terminal_result is not None:break
        settle(table,mid,table.state(mid)['menu']['end_turn'])
    assert loaded.engine.state.terminal_result is not None
    state=cold().journey_state(jid)
    state=cold().journey_resume(jid,state['revision'])
    assert cold().journey_state(jid)==state
    camp=state['actors'][a]['hearthfire']['camp']
    binding=camp['native_object']['component'][KEY]
    assert binding['source'].endswith('.empower_existing') and binding['source']!=HEARTH
    assert binding['owner']==a
    assert camp['until']>state['seconds']
    return state,original


@pytest.mark.parametrize('offscene',[False,True])
def test_combat_real_item_expires_after_settlement_and_cold_encounter_entry(tmp_path,monkeypatch,offscene):
    cold,jid,act,a,b=native.journey(tmp_path,monkeypatch,
        arena_objects=[{'id':91,'kind':'stone_lantern','x':5,'y':6,'weight_lb':10}])
    state,original=combat_cast_and_resume(cold,jid,tmp_path,a,b)
    camp=deepcopy(state['actors'][a]['hearthfire']['camp'])
    remaining=camp['until']-state['seconds']
    first_map=deepcopy(state['battlefield'])
    if offscene:
        act('finish')
        other_map={**deepcopy(first_map),'stable_id':'hearth:combat-expiry-other',
                   'map_objects':[{'id':91,'kind':'crate','x':5,'y':6,'weight_lb':10}]}
        monkeypatch.setattr(native.CombatService,'factory_arenas',lambda self:{'scene':other_map})
        state=cold().create_journey(project_ids=['hearth','guest'],arena_id='scene',
            positions={a:{'x':3,'y':6},b:{'x':4,'y':6}},base_paces={a:18000,b:18000})
        jid=state['journey_id']
        untouched=JourneyAssetContext(cold().journeys.load(jid)).state.objects[OID].model_dump(mode='json')
    state=cold().journey_act(jid,state['revision'],a,'wait',{'seconds':remaining})
    assert state['actors'][a]['hearthfire']['camp']['retired']==1
    if offscene:
        actual=JourneyAssetContext(cold().journeys.load(jid)).state.objects[OID].model_dump(mode='json')
        assert actual==untouched
        assert_mundane(state['actors'][a]['hearthfire']['objects'][camp['scene']+'|'+OID]['object'],original)
    else:
        assert_mundane(state['runtime_objects'][OID],original)
    state=cold().journey_act(jid,state['revision'],a,'wait',{'seconds':1})
    assert cold().journey_state(jid)==state
    if offscene:
        cold().journey_act(jid,state['revision'],a,'finish',{})
        monkeypatch.setattr(native.CombatService,'factory_arenas',lambda self:{'scene':first_map})
        state=cold().create_journey(project_ids=['hearth','guest'],arena_id='scene',
            positions={a:{'x':3,'y':6},b:{'x':4,'y':6}},base_paces={a:18000,b:18000})
        jid=state['journey_id']
    result=native.begin_combat(cold,jid,state['revision'],{a:'party',b:'opponents'})
    loaded=cold()._load_session(result['match_id'])
    assert loaded.mechanical.replay()['status']=='PASS'
    assert_mundane(loaded.engine.state.objects[OID].model_dump(mode='json'),original)


def test_journey_transfer_settles_combat_origin_source(tmp_path,monkeypatch):
    cold,jid,act,a,b=two_cultivators(tmp_path,monkeypatch)
    state,original=combat_cast_and_resume(cold,jid,tmp_path,a,b)
    state=act('hearth_carry',{'center':a,'damage_type':'FIRE'})
    assert state['runtime_objects'][OID]['position']==state['actors'][a]['position']
    state=act('move',{'path':[{'x':3,'y':7}]})
    assert state['runtime_objects'][OID]['position']==state['actors'][a]['position']
    option=next(o for o in cold().journey_menu(jid,b)['options']
                if o['kind']=='hearth_kindle' and o['payload'].get('existing')==OID)
    state=act('hearth_kindle',option['payload'],b)
    assert state['actors'][a]['hearthfire']['camp']['retired']==1
    assert state['runtime_objects'][OID]['component'][KEY]['owner']==b
    assert_mundane(state['runtime_objects'][OID]['component']['hearth_original'],original)
    result=native.begin_combat(cold,jid,state['revision'],{a:'party',b:'opponents'})
    loaded=cold()._load_session(result['match_id'])
    assert loaded.mechanical.replay()['status']=='PASS'
    assert loaded.engine.state.objects[OID].component[KEY]['owner']==b


def test_unmatched_retirement_keeps_receipt_and_can_retry(tmp_path,monkeypatch):
    cold,jid,act,a,b=native.journey(tmp_path,monkeypatch,
        arena_objects=[{'id':91,'kind':'stone_lantern','x':5,'y':6,'weight_lb':10}])
    state,original=combat_cast_and_resume(cold,jid,tmp_path,a,b)
    session=cold().journeys.load(jid)
    camp=session.state['actors'][a]['hearthfire']['camp']
    receipt=deepcopy(camp['native_object'])
    current=session.state['runtime_objects'][OID]
    current['component'][KEY]['sequence']+=1
    successor=deepcopy(current)
    retire_camp(session,a,camp)
    assert not camp.get('retired'), 'An unmatched receipt must remain retryable'
    assert camp['native_object']==receipt
    assert session.state['runtime_objects'][OID]==successor
    current['component'][KEY]=deepcopy(receipt['component'][KEY])
    retire_camp(session,a,camp)
    assert camp['retired']==1
    assert_mundane(session.state['runtime_objects'][OID],original)


def test_delivery_authentication_preserves_exact_identity(tmp_path,monkeypatch):
    cold,jid,act,a,b=native.journey(tmp_path,monkeypatch,
        arena_objects=[{'id':91,'kind':'stone_lantern','x':5,'y':6,'weight_lb':10}])
    state,original=combat_cast_and_resume(cold,jid,tmp_path,a,b)
    session=cold().journeys.load(jid)
    receipt=state['actors'][a]['hearthfire']['camp']['native_object']
    for mismatch in ('source','owner','object','sequence','wrong_ability'):
        snapshot=deepcopy(receipt)
        # Pydantic retains nested component dictionaries. Keep the live object
        # independent, or mutating the expected sequence mutates both sides.
        obj=RuntimeObjectState.model_validate(deepcopy(receipt))
        if mismatch=='source':
            snapshot['component'][KEY]['source']+=':unregistered'
            obj=RuntimeObjectState.model_validate(snapshot)
        elif mismatch=='owner':snapshot['component'][KEY]['owner']=b
        elif mismatch=='object':snapshot['object_id']='object:map.92'
        elif mismatch=='sequence':snapshot['component'][KEY]['sequence']+=1
        else:
            for action in session.state['actors'][a]['bundle']['action_catalog']:
                if action['source_definition_id']==snapshot['component'][KEY]['source']:
                    action['parameters']['typed']['source']=native.FEATURES[1]
        assert not camp_owns_hearth(session,a,obj,snapshot),mismatch
