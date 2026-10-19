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


def test_menu_after_commit_and_reload_offers_core_split_when_devil_qi_is_held(tmp_path, monkeypatch):
    cold, jid, _, _ = game(tmp_path, monkeypatch, cl=18, seed='journey-menu-service-core')
    # Hold Devil Qi in the saved Journey itself, then reload it from disk.
    service = cold()
    session = service.journeys.load(jid)
    session.state['actors'][OWNER]['resources'][f.DEVIL] = 3
    service.journeys.save(session)
    payments = _engine_payments(cold, jid)
    assert {'ordinary', 'seed', 'core:1', 'core:2', 'core:3'} <= payments, payments
