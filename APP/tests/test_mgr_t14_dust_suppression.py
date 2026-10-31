"""Real Internal Hammer suppression and ordinary grapple across restoration."""
import pytest
from combat import zones
from tests import r1i_service_support as s
from tests.test_mgr_t14_dust_family import P,cold
from combat.ext.qi_subpaths_dust import primordial


@pytest.mark.parametrize("with_cloud",[False,True,"replacement"])
def test_native_body_suppression_restoration_reconciles_physical_hold(tmp_path,monkeypatch,with_cloud):
    hammer='TAL_IRON_FIST_INTERNAL_HAMMER'
    original=s.sheet
    def sheet(mids,**kw):
        if hammer in mids or 'WRESTLING_BASE_RESTRAINTS_AND_UTILIZE' in mids:kw.update(dc=50,score=30)
        return original(mids,**kw)
    monkeypatch.setattr(s,'sheet',sheet)
    combat,table,mid,send,commit=s.fixture(tmp_path,[P+'primordial_dust']+([P+'dust_cloud'] if with_cloud else []),owner_cl=18,
        foe_talents=[hammer],second_talents=['WRESTLING_BASE_RESTRAINTS_AND_UTILIZE'],
        positions={s.OWNER:{'x':3,'y':6},s.FOE:{'x':4,'y':6},s.SECOND:{'x':3,'y':7}},wide=True)
    if with_cloud is True:
        from tests.test_mgr_t14_dust_family import place,advance
        place(table,mid,'Dust Cloud',3,6);advance(table,mid,commit)
    commit(s.candidate(table,mid,'Primordial Dust'))
    initial=primordial(cold(tmp_path,mid).state.actors[s.OWNER])
    identity,expiry=initial.instance_id,initial.expires_on
    if with_cloud is True:
        field=next(z for z in cold(tmp_path,mid).state.zones.values() if z.active and 'dust_cloud' in z.source_definition_id)
        field_id,field_expiry=field.zone_id,(field.created_round,field.duration_rounds)
    def turn(aid):
        while table.state(mid)['menu']['actor_id']!=aid:commit(table.state(mid)['menu']['end_turn'])
    commit(table.state(mid)['menu']['end_turn']);turn(s.FOE)
    # Iron Fist's native damaging hit supplies Opened; no prepared mark receipt.
    base=next(g for g in table.state(mid)['menu']['actions'] if g['label']=='Unarmed Strike (Iron Fist)')
    from tests.worker2_support import settle
    settle(table,mid,next(o['candidate_id'] for o in base['options'] if s.OWNER in o.get('target_ids',[])),
        picks={'choice:needle.iron_fist_step':[]})
    from combat.typed_executor import bears_mark
    assert bears_mark(cold(tmp_path,mid).state.actors[s.OWNER],s.FOE,'Opened')
    commit(table.state(mid)['menu']['end_turn']);turn(s.FOE)
    # Internal Hammer is an optional human loadout in the current table. Arm
    # it through its real setting action, then take the qualifying strike; the
    # suppression assertions themselves are unchanged.
    menu=table.state(mid)['menu']
    arm=next(o['candidate_id'] for g in menu['actions']
        if g['label']=='Internal Hammer: Internal Hammer' and g['source_definition_id'].endswith('.on.toggle')
        for o in g['options'])
    commit(arm)
    settle(table,mid,s.candidate(table,mid,'Unarmed Strike (Iron Fist) + Internal Hammer',s.OWNER),
        picks={'choice:needle.iron_fist_step':[]})
    e=cold(tmp_path,mid);actor=e.state.actors[s.OWNER]
    assert any('suppressed.dust_cultivator_primordial' in c.condition_id for c in actor.conditions.values())
    assert primordial(actor) is None
    if with_cloud is True:
        assert e.state.zones[field_id].active
        assert not zones._inside(e,actor,e.state.zones[field_id])
    turn(s.SECOND)
    # A real ordinary physical hold can now take effect while the body is suppressed.
    commit(s.candidate(table,mid,'Grapple',s.OWNER))
    e=cold(tmp_path,mid)
    assert any(c.condition_id=='condition:typed.grappled' for c in e.state.actors[s.OWNER].conditions.values())
    turn(s.OWNER)
    if with_cloud=="replacement":
        from tests.test_mgr_t14_dust_family import place
        place(table,mid,'Dust Cloud',3,6)
        e=cold(tmp_path,mid)
        field=next(z for z in e.state.zones.values() if z.active and 'dust_cloud' in z.source_definition_id)
        assert field.concentration_link and field.trigger_profile['size_ft']==10
        field_id,field_expiry=field.zone_id,(field.created_round,field.duration_rounds)
    commit(table.state(mid)['menu']['end_turn'])
    e=cold(tmp_path,mid);actor=e.state.actors[s.OWNER]
    assert primordial(actor) is not None
    assert (primordial(actor).instance_id,primordial(actor).expires_on)==(identity,expiry)
    assert actor.resources['resource:core.qi']==22-int(bool(with_cloud))
    if with_cloud:
        field=e.state.zones[field_id]
        assert not field.concentration_link and field.trigger_profile['size_ft']==20
        assert field.active and (field.created_round,field.duration_rounds)==field_expiry
        assert zones._inside(e,actor,field)
    assert not any(c.condition_id=='condition:typed.grappled' for c in actor.conditions.values())
