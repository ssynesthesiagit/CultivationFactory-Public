"""Local Auto shares its verified post-commit boundary with both response reads."""
from types import SimpleNamespace

from combat import menu_rank
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_r6_6_7_combat_presentation_architecture import ROOT, _create_service_match


def test_local_auto_response_avoids_two_replays_and_matches_cold_reads(tmp_path, monkeypatch):
    monkeypatch.setattr(menu_rank,'_CLIENT',SimpleNamespace(
        embed=lambda texts:[[1.0,0.0] for _ in texts],prefetch=lambda *a,**k:None))
    combat, mid = _create_service_match(tmp_path)
    userdata = tmp_path/'UserData'
    table = TabletopService(combat,userdata)
    loads = []
    original = combat._load_session
    def loaded(match_id):
        session = original(match_id)
        loads.append(session.engine.state.state_version)
        return session
    monkeypatch.setattr(combat,'_load_session',loaded)
    result = table.auto_step(mid,0)
    assert result['status'] == 'COMMITTED'
    assert len(loads) == 1
    cold = TabletopService(CombatService(ROOT,userdata),userdata)
    assert result['state'] == cold.state(mid)
    assert result['events'] == cold.events(mid,0)
    assert cold.combat._load_session(mid).mechanical.replay()['status'] == 'PASS'


def test_unverified_post_commit_boundary_falls_back_to_cold_load(tmp_path,monkeypatch):
    monkeypatch.setattr(menu_rank,'_CLIENT',SimpleNamespace(
        embed=lambda texts:[[1.0,0.0] for _ in texts],prefetch=lambda *a,**k:None))
    combat,mid = _create_service_match(tmp_path)
    userdata = tmp_path/'UserData'
    table = TabletopService(combat,userdata)
    loads=[]
    original=combat._load_session
    def loaded(match_id):
        value=original(match_id)
        loads.append(value.engine.state.state_version)
        return value
    monkeypatch.setattr(combat,'_load_session',loaded)
    monkeypatch.setattr(combat,'presentation_session',lambda session:None)
    result=table.auto_step(mid,0)
    assert result['status']=='COMMITTED'
    assert len(loads)==3
    cold=TabletopService(CombatService(ROOT,userdata),userdata)
    assert result['state']==cold.state(mid)
    assert result['events']==cold.events(mid,0)
