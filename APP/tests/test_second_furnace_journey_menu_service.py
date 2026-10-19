"""Service-level regression: the Journey menu offers Engine payments after a commit and reload.

The earlier unit regression called furnace_journey.options() directly. This one
goes through CombatService: the acquired Second Furnace is admitted and saved by
the Journey store, reloaded from disk, and the player's menu is read from there.
It uses only native acquisition and a store-level Devil Qi setup; it does not
depend on the Journey end_scene path.
"""
from tests.test_second_furnace_native import game, OWNER, f


def _engine_payments(cold, jid):
    rows = cold().journey_menu(jid, OWNER)['options']
    return {row['payload'].get('payment') for row in rows if row['kind'] == 'furnace_engine'}


def test_menu_after_commit_and_reload_offers_ordinary_and_seed_payments(tmp_path, monkeypatch):
    cold, jid, _, _ = game(tmp_path, monkeypatch, cl=18, seed='journey-menu-service-seed')
    payments = _engine_payments(cold, jid)
    assert 'ordinary' in payments, payments
    assert 'seed' in payments, payments


def test_core_journey_payment_emits_spend_and_furnace_motion_survives_reload(tmp_path, monkeypatch):
    cold, jid, _, _ = game(tmp_path, monkeypatch, cl=10, seed='journey-core-spend')
    service=cold();session=service.journeys.load(jid);actor=session.state['actors'][OWNER]
    actor['resources'][f.DEVIL]=2
    service.journeys.save(session)
    menu=cold().journey_menu(jid,OWNER)
    option=next(row for row in menu['options'] if row['kind']=='furnace_engine' and row['payload']['payment']=='core:2')
    state=cold().journey_act(jid,menu['revision'],OWNER,option['kind'],option['payload'])
    assert state['actors'][OWNER]['resources'][f.DEVIL]==0
    receipt=next(row for row in reversed(state['events']) if row['kind']=='RESOURCE_SPENT')
    assert (receipt['resource_id'],receipt['amount'],receipt['source'])==(f.DEVIL,2,f.CORE)
    menu=cold().journey_menu(jid,OWNER)
    motion=next(row for row in menu['options'] if row['kind']=='furnace_core_motion')
    state=cold().journey_act(jid,menu['revision'],OWNER,motion['kind'],motion['payload'])
    reloaded=cold().journey_state(jid)
    assert reloaded['actors'][OWNER]['encounter_snapshot']['temporary_hp']==4
    assert any(row['kind']=='FURNACE_MOTION' and row['benefit']=='temp_hp' for row in reloaded['events'])


def test_menu_after_commit_and_reload_offers_core_split_when_devil_qi_is_held(tmp_path, monkeypatch):
    cold, jid, _, _ = game(tmp_path, monkeypatch, cl=18, seed='journey-menu-service-core')
    # Hold Devil Qi in the saved Journey itself, then reload it from disk.
    service = cold()
    session = service.journeys.load(jid)
    session.state['actors'][OWNER]['resources'][f.DEVIL] = 3
    service.journeys.save(session)
    payments = _engine_payments(cold, jid)
    assert {'ordinary', 'seed', 'core:1', 'core:2', 'core:3'} <= payments, payments
