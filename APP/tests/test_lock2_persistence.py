"""New hooks across the real table preview/commit/reload boundary, using synthetic characters."""
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.test_factory_live_match import _install, ROOT
from tests.test_lock_choices import install
from combat.prepared_actions import SOURCE, CONDITION
from tests.legacy_fight_support import legacy_zero_hp


def table_match(tmp_path):
    for side in ("left", "right"):
        _install(tmp_path, side)
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({"display_name": "Lock2 yard", "width_squares": 12, "height_squares": 8,
        "walls": [], "starts": {"team1": [[3, 4]], "team2": [[4, 4]]}})
    modes = {FACTORY_ACTOR_PREFIX + side: "MANUAL" for side in ("left", "right")}
    view = combat.create_factory_match(project_ids=["left"], opponent_actor_ids=[FACTORY_ACTOR_PREFIX + "right"],
        control_modes=modes, arena_id="battlefield:map.lock2-yard", match_seed="LOCK2-TABLE-READY")
    return combat, TabletopService(combat, tmp_path), view["match_id"]


def act(table, mid, source):
    state = table.state(mid)
    menu = state["menu"]
    if source == "end":
        cid = menu["end_turn"]
    else:
        group = next(g for g in menu["actions"] if g["source_definition_id"].startswith(source))
        cid = group["options"][0]["candidate_id"]
    from tests.iron_fist_support import answering_iron_fist  # an Iron Fist strike's damage-type question (L45)
    return answering_iron_fist(lambda answers: table.act(mid, cid, menu["decision_id"], menu["state_version"],
                                                         state["last_sequence"], answers))()


def test_ready_actual_table_use_button_and_persistent_replay(monkeypatch, tmp_path):
    install(monkeypatch, "prepare_options", lambda *a: [{"option_id": "counter", "source_id": "test:counter",
        "label": "Counterstrike", "trigger": "HOLD_POSITION_COMMITTED"}])
    install(monkeypatch, "prepared_trigger", lambda *a: True)
    def resolve(e, a, option, event, intent):
        e._grant_temp_hp(a, 3, option["source_id"], a.entity_id)
        return True
    install(monkeypatch, "prepared_action", resolve)
    combat, table, mid = table_match(tmp_path)
    actor_id = table.state(mid)["menu"]["actor_id"]
    assert act(table, mid, SOURCE)["status"] == "COMMITTED"
    assert act(table, mid, "end")["status"] == "COMMITTED"
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    first = act(table, mid, "system:combat.hold_position")
    assert first["status"] == "REACTION_REQUIRED"
    assert first["reaction"]["reaction"] == "Counterstrike"
    assert "Counterstrike" in first["reaction"]["trigger"]
    assert "Test Cultivator" in first["reaction"]["trigger"]
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    # Exactly the existing table button payload: USE, no extra option picker or forged internal data.
    answer = {**first["reaction"]["context"], "selection": "USE"}
    state, menu = first["state"], first["state"]["menu"]
    cid = next(g["options"][0]["candidate_id"] for g in menu["actions"]
               if g["source_definition_id"] == "system:combat.hold_position")
    committed = table.act(mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"], [answer])
    assert committed["status"] == "COMMITTED"
    reloaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = reloaded.engine.state.actors[actor_id]
    assert actor.temporary_hp == 3 and not actor.reaction_available
    assert not any(c.condition_id == CONDITION for c in actor.conditions.values())
    assert reloaded.mechanical.replay()["status"] == "PASS"


def test_d20_rewrite_through_service_clone_commit_reload(monkeypatch, tmp_path):
    install(monkeypatch, "d20_result", lambda *a: {"source_id": "test:fate", "operation": "reroll"})
    combat, table, mid = table_match(tmp_path)
    # A synthetic preparation provides a check during an accepted action, so preview and commit must agree.
    install(monkeypatch, "prepare_options", lambda *a: [{"option_id": "check", "source_id": "test:check",
        "label": "Check on hold", "trigger": "HOLD_POSITION_COMMITTED"}])
    install(monkeypatch, "prepared_trigger", lambda *a: True)
    def resolve(e, a, option, event, intent):
        roll = e.roller.d20(modifier=3, actor_id=a.entity_id, reason="CHECK:ready")
        e._record_roll(roll)
        e._append_event("CHECK_ROLLED", option["source_id"], actor_id=a.entity_id, payload=roll.model_dump(mode="json"))
        return True
    install(monkeypatch, "prepared_action", resolve)
    act(table, mid, SOURCE)
    act(table, mid, "end")
    first = act(table, mid, "system:combat.hold_position")
    answer = {**first["reaction"]["context"], "selection": "USE"}
    state, menu = first["state"], first["state"]["menu"]
    cid = next(g["options"][0]["candidate_id"] for g in menu["actions"] if g["source_definition_id"] == "system:combat.hold_position")
    table.act(mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"], [answer])
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert any(e.event_type == "D20_REWRITTEN" for e in loaded.engine.events)
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_dying_and_retarget_events_survive_persistent_replay(monkeypatch, tmp_path, legacy_zero_hp):
    install(monkeypatch, "prepare_options", lambda *a: [{"option_id": "strike", "source_id": "test:strike",
        "label": "Strike on hold", "trigger": "HOLD_POSITION_COMMITTED"}])
    install(monkeypatch, "prepared_trigger", lambda *a: True)
    install(monkeypatch, "retarget_attack", lambda e, a, t, *rest:
        {"source_id": "test:cover", "target_id": t.entity_id, "cover_bonus": 5})
    install(monkeypatch, "zero_hp", lambda *a: "DYING")
    def resolve(e, a, option, event, intent):
        t = e.state.actors[event.actor_id]
        e._resolve_attack_spec(a, t, {"range_ft": 500, "attack_bonus": -100}, intent,
                               source_definition_id=option["source_id"])
        e._commit_damage(t, 10000, "UNTYPED", option["source_id"], a.entity_id, None, reaction_depth=0)
        return True
    install(monkeypatch, "prepared_action", resolve)
    combat, table, mid = table_match(tmp_path)
    act(table, mid, SOURCE)
    act(table, mid, "end")
    first = act(table, mid, "system:combat.hold_position")
    state, menu = first["state"], first["state"]["menu"]
    answer = {**first["reaction"]["context"], "selection": "USE"}
    cid = next(g["options"][0]["candidate_id"] for g in menu["actions"] if g["source_definition_id"] == "system:combat.hold_position")
    table.act(mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"], [answer])
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[menu["actor_id"]].life_state == "DYING"
    shown = next(a for a in table.state(mid)["presentation"]["actors"] if a["entity_id"] == menu["actor_id"])
    assert shown["life_state"] == "DYING" and shown["active"]
    assert any(e.event_type == "ATTACK_RETARGETED" for e in loaded.engine.events)
    assert loaded.mechanical.replay()["status"] == "PASS"
