"""Black Sun resolves child-spend damage in real manual/AI table transactions.

The test event producer models a resource-paying event rider without patching
the engine or replacing the production event subscribers.
"""
import pytest

from combat import ext
from combat.canonical import canonical_sha256
from combat.ext.daemonic_riders import BLACK_SUN_STATE
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.r1i_service_support import (
    FOE, candidate, fixture, force_ai_candidate,
)
from tests.test_riders_lane1 import BLACK_SUN


@pytest.mark.parametrize("ai", [False, True])
@pytest.mark.parametrize("dc", [50, -40, None])
@pytest.mark.parametrize("resource", ["resource:core.qi", "resource:core.stamina"])
def test_nested_first_spend_consumes_once_commit_reload_replay(monkeypatch, tmp_path, ai, dc, resource):
    ext.effects()

    def spend_inside_event(engine, kind, kwargs):
        if kind == "HOLD_POSITION_COMMITTED" and kwargs.get("actor_id") == FOE:
            subject = engine.state.actors[FOE]
            engine._spend_resource(subject, resource, 0, "test:nested-zero")
            engine._spend_resource(subject, resource, 1, "test:nested-first")
            engine._spend_resource(subject, resource, 1, "test:nested-second")

    monkeypatch.setitem(ext._HOOKS, "event", [*ext._HOOKS["event"], spend_inside_event])

    def stamina_pool(bundles):
        # This sheet has CP but no Stamina feature. Supply a declared test pool
        # in its bundle so spending/reload stays on the native recorded path.
        for bundle in bundles:
            if bundle["actor_id"] == FOE:
                bundle["actor_template"]["resources"].append({
                    "resource_id": "resource:core.stamina", "initial": 10, "maximum": 10})
                bundle.pop("bundle_sha256", None)
                bundle["bundle_sha256"] = canonical_sha256(bundle)

    combat, table, mid, send, commit = fixture(tmp_path, [BLACK_SUN] if dc is not None else [],
                                            owner_dc=dc if dc is not None else 50,
                                            bundle_transform=stamina_pool)
    if dc is not None:
        commit(candidate(table, mid, "Black Sun Over the Dantian", FOE))
    commit(table.state(mid)["menu"]["end_turn"])
    while table.state(mid)["menu"]["actor_id"] != FOE:
        commit(table.state(mid)["menu"]["end_turn"])
    session = combat._load_session(mid)
    subject = session.engine.state.actors[FOE]
    armed = [c for c in subject.conditions.values() if c.condition_id == BLACK_SUN_STATE]
    assert len(armed) == int(dc is not None)
    before_resource, before_hp = subject.resources[resource], subject.current_hp
    sequence = session.engine.state.event_sequence
    cid = next(c.candidate_id for c in session.engine.legal_candidates()
               if c.source_definition_id == "system:combat.hold_position")
    if ai:
        force_ai_candidate(combat, mid, FOE, cid)
        assert send(cid, auto=True)["status"] == "COMMITTED"
    else:
        commit(cid)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    subject = loaded.engine.state.actors[FOE]
    assert subject.resources[resource] == before_resource - 2
    assert not any(c.condition_id == BLACK_SUN_STATE for c in subject.conditions.values())
    events = [e for e in loaded.engine.events if e.sequence > sequence]
    removals = [e for e in events if e.event_type == "CONDITION_REMOVED"
                and e.payload.get("condition_id") == BLACK_SUN_STATE]
    assert len(removals) == int(dc is not None)
    if removals:
        assert removals[0].payload["reason"] == "CONSUMED"
    damage = [e for e in events if e.event_type == "DAMAGE_COMMITTED"
              and str(e.source_definition_id).endswith(BLACK_SUN) and FOE in (e.target_ids or ())]
    assert len(damage) == int(dc is not None)
    if damage:
        assert damage[0].payload["hp_damage"] + damage[0].payload.get("temporary_hp_absorbed", 0) > 0
        assert subject.current_hp < before_hp or damage[0].payload.get("temporary_hp_absorbed", 0) > 0
    assert not any(e.event_type == "GM_RIDER" and "GM resolves" in e.payload.get("rider", "")
                   for e in events)
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("ai", [False, True])
def test_black_sun_vetoes_real_qi_gain_while_condition_is_active(monkeypatch, tmp_path, ai):
    ext.effects()

    def leave_qi_room(bundles):
        for bundle in bundles:
            if bundle["actor_id"] == FOE:
                qi = next(row for row in bundle["actor_template"]["resources"]
                          if row["resource_id"] == "resource:core.qi")
                qi["initial"] -= 1
                bundle.pop("bundle_sha256", None)
                bundle["bundle_sha256"] = canonical_sha256(bundle)

    def attempt_gain(engine, kind, kwargs):
        if kind == "HOLD_POSITION_COMMITTED" and kwargs.get("actor_id") == FOE:
            engine._gain_resource(engine.state.actors[FOE], "resource:core.qi", 1,
                                  "test:black-sun-temporary-qi")

    monkeypatch.setitem(ext._HOOKS, "event", [*ext._HOOKS["event"], attempt_gain])
    combat, table, mid, send, commit = fixture(tmp_path, [BLACK_SUN], bundle_transform=leave_qi_room)
    commit(candidate(table, mid, "Black Sun Over the Dantian", FOE))
    commit(table.state(mid)["menu"]["end_turn"])
    while table.state(mid)["menu"]["actor_id"] != FOE:
        commit(table.state(mid)["menu"]["end_turn"])
    before = combat._load_session(mid).engine.state.actors[FOE].resources["resource:core.qi"]
    cid = next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates()
               if c.source_definition_id == "system:combat.hold_position")
    if ai:
        force_ai_candidate(combat, mid, FOE, cid)
        assert send(cid, auto=True)["status"] == "COMMITTED"
    else:
        commit(cid)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    subject = loaded.engine.state.actors[FOE]
    assert subject.resources["resource:core.qi"] == before
    assert any(c.condition_id == BLACK_SUN_STATE for c in subject.conditions.values())
    events = [e for e in loaded.engine.events if e.source_definition_id == "test:black-sun-temporary-qi"]
    assert len(events) == 1 and events[0].event_type == "GM_RIDER"
    assert "cannot regain Qi" in events[0].payload["rider"]
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"
