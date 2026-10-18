"""Welcome source lifetime through acquired Journey/table commits and reloads."""
from copy import deepcopy
import pytest
from combat.ext.qi_hearthfire_state import welcomes,hearth_identity
from combat.tabletop_service import TabletopService
from tests import test_mgr_t14_hearthfire_native as native


def enter(cold,jid,state,a,b):
    result=native.begin_combat(cold,jid,state['revision'],{a:'party',b:'opponents'},maximum_rounds=1)
    loaded=cold()._load_session(result['match_id'])
    assert loaded.mechanical.replay()['status']=='PASS'
    return result['match_id'],loaded.engine


def assert_ward(engine,a,expected):
    fields=[z for z in engine.state.zones.values() if z.active
            and (z.trigger_profile.get('profile') or {}).get('welcome')]
    assert len(fields)==int(expected)
    if fields and not fields[0].trigger_profile['profile'].get('center_actor'):
        parent=engine.state.zones[fields[0].trigger_profile['profile']['hearth_zone']]
        assert parent.active and parent.owner_id==a
    return fields


@pytest.mark.parametrize('loss',['expiry','replacement'])
@pytest.mark.parametrize('center',['hearth','self'])
def test_source_loss_ends_only_dependent_ward_and_keeps_completed_recovery(tmp_path,monkeypatch,loss,center):
    cold,jid,act,a,b=native.journey(tmp_path,monkeypatch)
    native.kindle(act,a,b)
    if loss=='expiry':act('wait',{'seconds':28770})
    act('hearth_welcome',{'center':center,'invited':[b]})
    recovered=act('hearth_recovery',{'benefit':'temp_hp'},b)
    assert recovered['actors'][b]['encounter_snapshot']['temporary_hp']==12
    assert cold().journey_menu(jid,b)['properties']['hearth_fire_resistance']==1
    if loss=='expiry':state=act('wait',{'seconds':30})
    else:
        state=act('hearth_kindle',{'position':{'x':6,'y':6},'host':a,'invited':[a,b]})
    expected=center=='self'
    assert bool(welcomes(state['actors'][a]['hearthfire']))==expected
    props=cold().journey_menu(jid,b)['properties']
    for name in ('hearth_ac_bonus','hearth_fire_resistance','hearth_cold_resistance','hearth_environmental_immune'):
        assert bool(props.get(name))==expected
    assert state['actors'][b]['hearthfire']['temporary_hp']==12
    assert state['actors'][b]['travel_uses'][native.FEATURES[1]]==state['actors'][b]['long_rests']
    # A second committed transaction cannot resurrect or retarget the old field.
    state=act('wait',{'seconds':1})
    assert cold().journey_state(jid)==state
    _,engine=enter(cold,jid,state,a,b)
    assert_ward(engine,a,expected)
    assert engine.state.actors[b].temporary_hp==12


def test_exact_parent_survives_combat_settlement_then_expires_in_journey(tmp_path,monkeypatch):
    cold,jid,act,a,b=native.journey(tmp_path,monkeypatch)
    native.kindle(act,a,b)
    act('wait',{'seconds':28770})
    state=act('hearth_welcome',{'center':'hearth','invited':[b]})
    source=deepcopy(welcomes(state['actors'][a]['hearthfire'])[0]['hearth_source'])
    act('hearth_recovery',{'benefit':'temp_hp'},b)
    mid,engine=enter(cold,jid,cold().journey_state(jid),a,b)
    assert_ward(engine,a,True)
    table=TabletopService(cold(),tmp_path)
    for _ in range(5):
        loaded=cold()._load_session(mid)
        assert loaded.mechanical.replay()['status']=='PASS'
        if loaded.engine.state.terminal_result is not None:break
        native.settle(table,mid,table.state(mid)['menu']['end_turn'])
    assert loaded.engine.state.terminal_result is not None
    state=cold().journey_state(jid)
    state=cold().journey_resume(jid,state['revision'])
    f=state['actors'][a]['hearthfire']
    assert welcomes(f)[0]['hearth_source']==source==hearth_identity(f['camp'])
    remaining=f['camp']['until']-state['seconds']
    assert 0<remaining<30
    state=act('wait',{'seconds':remaining})
    assert not welcomes(state['actors'][a]['hearthfire'])
    assert not cold().journey_menu(jid,b)['properties']
    _,engine=enter(cold,jid,state,a,b)
    assert_ward(engine,a,False)
    assert engine.state.actors[b].temporary_hp==12


def test_real_item_reempowerment_cannot_retarget_another_owners_welcome(tmp_path,monkeypatch):
    guest=native.acquired_document(tmp_path,18)
    ordinary=native.sheet
    monkeypatch.setattr(native,'sheet',lambda *args,**kwargs:
        deepcopy(guest) if kwargs.get('name')=='guest' else ordinary(*args,**kwargs))
    cold,jid,act,a,b=native.journey(tmp_path,monkeypatch,
        arena_objects=[{'id':91,'kind':'stone_lantern','x':5,'y':6,'weight_lb':10}])
    def empower(who):
        option=next(o for o in cold().journey_menu(jid,who)['options']
            if o['kind']=='hearth_kindle' and o['payload'].get('existing')=='object:map.91')
        return act('hearth_kindle',option['payload'],who)
    empower(a)
    act('hearth_welcome',{'center':'hearth','invited':[a,b]})
    act('hearth_recovery',{'benefit':'temp_hp'},a)
    act('hearth_recovery',{'benefit':'temp_hp'},b)
    state=empower(b)
    assert not welcomes(state['actors'][a]['hearthfire'])
    assert not cold().journey_menu(jid,a)['properties'].get('hearth_fire_resistance')
    state=act('wait',{'seconds':1})
    _,engine=enter(cold,jid,state,a,b)
    assert_ward(engine,a,False)
    # b's takeover shows in the empowerment receipt, not in the lantern's property
    # title: a real item's owner_id is its declared property owner (none here) and is
    # never overwritten by its cultivator (see test_empowering_real_furnace_retains_
    # physical_geometry_and_property_owner and test_existing_native_flame_expiry_...).
    obj=engine.state.objects['object:map.91']
    assert obj.component['asset_anchor_runtime']['owner']==b
    assert obj.owner_id is None
