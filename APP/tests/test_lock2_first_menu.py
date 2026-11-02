from combat import ext
from combat.gate2_engine import Gate2Engine
from combat.gate5_service import FACTORY_ACTOR_PREFIX, CombatService
from combat.tabletop_service import TabletopService
from tests.test_factory_live_match import _install
from tests.test_tabletop import MAP, ROOT


def test_match_start_runs_after_genesis_setup_and_no_hook_is_inert(monkeypatch):
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "match_start", [])
    baseline = Gate2Engine(ROOT, match_seed="LOCK2-START")
    seen = []
    monkeypatch.setitem(ext._HOOKS, "match_start", [lambda e: seen.append(e.state.model_dump(mode="json"))])
    hooked = Gate2Engine(ROOT, match_seed="LOCK2-START")
    assert seen == [baseline.state.model_dump(mode="json")]
    assert hooked.events == baseline.events and hooked.rolls == baseline.rolls


def test_first_table_menu_has_objects_without_any_move_and_reload_keeps_genesis(tmp_path):
    _install(tmp_path, "left")
    _install(tmp_path, "right")
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({**MAP, "walls": [], "objects": [
        {"id": 1, "kind": "crate", "x": 2, "y": 4}, {"id": 2, "kind": "crate", "x": 13, "y": 4}]})
    modes = {FACTORY_ACTOR_PREFIX + side: "MANUAL" for side in ("left", "right")}
    view = combat.create_factory_match(project_ids=["left"], opponent_actor_ids=[FACTORY_ACTOR_PREFIX + "right"],
        control_modes=modes, arena_id="battlefield:map.courtyard", match_seed="LOCK2-FIRST-MENU")
    mid = view["match_id"]
    table = TabletopService(combat, tmp_path)
    state = table.state(mid)
    assert len(state["objects"]) == 2
    assert state["menu"]["manual"] and "error" not in state["menu"]
    session = combat._load_session(mid)
    assert not any(e.event_type == "INTENT_ACCEPTED" for e in session.engine.events)
    assert any(c.target_ids and c.target_ids[0].startswith("object:map.") for c in session.engine.legal_candidates())
    # The presentation itself must contain the object-target button, not only the engine candidates.
    import json
    assert "object:map." in json.dumps(state["menu"])
    assert session.mechanical.replay()["status"] == "PASS"
    original = {k: o.model_dump(mode="json") for k, o in session.engine.state.objects.items()}
    reloaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert {k: o.model_dump(mode="json") for k, o in reloaded.engine.state.objects.items()} == original
    assert reloaded.mechanical.replay()["status"] == "PASS"
