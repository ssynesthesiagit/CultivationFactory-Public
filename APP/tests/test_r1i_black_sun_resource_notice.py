"""Black Sun's GM fallback must not impose failed-save restrictions on success."""
import pytest

from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.r1i_service_support import fixture, candidate, force_ai_candidate, OWNER, FOE
from tests.test_riders_lane1 import BLACK_SUN, _rider_engine, _rider_use


def restriction_notice(events):
    return "\n".join(str(e.payload.get("rider", "")) for e in events
                     if e.event_type == "GM_RIDER")


def assert_scoped(notice):
    assert "Failed save only, until the end of the caster's next turn" in notice
    assert "does not apply on a successful save" in notice
    # Round 24 automates the three represented pools. Only unsupported pools
    # and temporary-CP provenance remain GM work; preserve that distinction.
    assert "prevent recovery of cultivation resources other than Qi, Stamina and Resonance" in notice
    assert "those three pools are blocked automatically" in notice
    assert "no benefit from temporary CP" in notice
    assert "temporary CP provenance/benefit hook" in notice


@pytest.mark.parametrize("dc", [50, -40])
def test_compiled_black_sun_gm_restrictions_name_save_branch_and_duration(dc):
    assert_scoped(restriction_notice(_rider_use(_rider_engine(BLACK_SUN, dc=dc), BLACK_SUN)))


@pytest.mark.parametrize("ai_owner", [False, True])
def test_black_sun_resource_fallback_table_commit_reload_replay(tmp_path, ai_owner):
    combat, table, mid, send, commit = fixture(tmp_path, [BLACK_SUN])
    cid = candidate(table, mid, "Black Sun Over the Dantian", FOE)
    if ai_owner:
        force_ai_candidate(combat, mid, OWNER, cid)
        result = send(cid, auto=True)
        assert result["status"] == "COMMITTED", result
    else:
        commit(cid)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    events = [e for e in loaded.engine.events
              if e.actor_id == OWNER and FOE in e.target_ids]
    assert_scoped(restriction_notice(events))
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize('dc,regains', [(50, False), (-40, True)])
def test_black_sun_gain_denial_uses_failed_save_condition_after_spend(tmp_path, monkeypatch, dc, regains):
    from tests.test_lock_choices import install
    combat, table, mid, send, commit = fixture(tmp_path, [BLACK_SUN], owner_dc=dc)
    commit(candidate(table, mid, 'Black Sun Over the Dantian', FOE))
    def recover(engine, kind, kwargs):
        if kind != 'HOLD_POSITION_COMMITTED' or kwargs.get('actor_id') != OWNER:
            return
        actor = engine.state.actors[FOE]
        engine._spend_resource(actor, 'resource:core.qi', 1, 'test:spend')
        engine._gain_resource(actor, 'resource:core.qi', 1, 'test:recovery')
    install(monkeypatch, 'event', recover)
    before = combat._load_session(mid).engine.state.actors[FOE].resources['resource:core.qi']
    commit(candidate(table, mid, 'Hold position'))
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[FOE]
    assert actor.resources['resource:core.qi'] == before - (0 if regains else 1)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
