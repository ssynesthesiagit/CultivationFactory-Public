"""Pressure-Point Strike decisions happen after a failed save, through the real table."""
import pytest

from combat.ext.tabik_ninpo import STAMINA
from tests.test_lock2_persistence import act
from tests.test_log1_pressure_expiry import (
    PLAYER, FOE, SOURCE, pressure_fight, pressure_effects, reload, pressure_act, pressure_call,
)
from tests.test_r4_integration import auto_candidate


def attack_candidate(combat, table, mid):
    action = next(a for a in combat._load_session(mid).engine.action_catalog.values()
                  if a.owner_id == PLAYER and a.display_name == "Iron Fist attack")
    state = table.state(mid)
    menu = state["menu"]
    group = next(g for g in menu["actions"] if g["source_definition_id"] == action.source_definition_id)
    return (mid, group["options"][0]["candidate_id"], menu["decision_id"],
            menu["state_version"], state["last_sequence"])


def failed_choice(result, chosen, triggering_action="Iron Fist"):
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert prompt["context"]["reactor_id"] == PLAYER
    assert prompt["choice"]["minimum"] == prompt["choice"]["maximum"] == 1
    assert not prompt["choice"]["allow_decline"]
    assert {o["id"] for o in prompt["choice"]["options"]} == {
        "reactions", "speed", "attack", "concentration", "whisper"}
    for text in ("Pressure-Point Strike", "failed its Constitution save", triggering_action, "Pressure Target", "1 Stamina"):
        assert text in prompt["moment"]
    assert prompt["trigger_actor"] and prompt["affected"]
    for option in prompt["choice"]["options"]:
        assert "next turn" in option["label"]
    return {**prompt["context"], "selection": "USE", "option_ids": [chosen]}


@pytest.mark.parametrize("choice", ["reactions", "speed", "attack", "concentration", "whisper"])
def test_manual_pressure_chooses_after_failure_not_standing_preference(tmp_path, monkeypatch, choice):
    combat, table, mid = pressure_fight(tmp_path, monkeypatch, "attack" if choice == "reactions" else "reactions", True)
    args = attack_candidate(combat, table, mid)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    result = pressure_act(table, *args)
    answer = failed_choice(result, choice)
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    assert pressure_act(table, *args)["reaction"] == result["reaction"]
    assert pressure_act(table, *args, [answer])["status"] == "COMMITTED"
    combat, _, loaded = reload(tmp_path, mid)
    target = loaded.engine.state.actors[FOE]
    effects = pressure_effects(target)
    assert len(effects) == 1
    effect = effects[0]
    if choice in {"speed", "attack"}:
        assert effect.target_field == ("speed_ft" if choice == "speed" else "attack_mode")
        assert effect.value == (-10 if choice == "speed" else "DISADVANTAGE")
    else:
        assert effect.condition_id == "condition:typed." + {
            "reactions": "reaction_denied", "concentration": "concentration_mode", "whisper": "silenced"}[choice]
    events = loaded.engine.events
    saves = [e for e in events if e.event_type == "SAVE_ROLLED" and e.source_definition_id == SOURCE]
    assert len(saves) == 1
    assert loaded.engine.state.actors[PLAYER].resources[STAMINA] == 29
    assert loaded.engine.state.actors[PLAYER].reaction_available
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("legacy_pressure", [False, True])
def test_manual_pressure_asks_during_opportunity_attack_on_manual_or_ai_turn(tmp_path, monkeypatch, auto_turn, legacy_pressure):
    combat, table, mid = pressure_fight(tmp_path, monkeypatch, "reactions", True, legacy_pressure=legacy_pressure)
    bundles = next(tmp_path.rglob("Typed_Character_Bundles.json"))
    saved_bundle_bytes = bundles.read_bytes()
    assert act(table, mid, "end")["status"] == "COMMITTED"
    state = table.state(mid)
    menu = state["menu"]
    assert menu["actor_id"] == FOE
    move = next(m for m in menu["moves"] if m["destination"] == {"x": 6, "y": 6})
    args = (mid, move["candidate_id"], menu["decision_id"], menu["state_version"], state["last_sequence"])
    if auto_turn:
        auto_candidate(combat, mid, FOE, move["candidate_id"])
    call = lambda answers=(): pressure_call(lambda paid: table.auto_step(mid, 0, paid), list(answers)) if auto_turn else pressure_act(table, *args, list(answers))
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    first = call()
    answers = []
    if legacy_pressure:
        # The old bundle's Opportunity Attack is automatic; its failed-save choice still belongs to the player.
        result = first
    else:
        assert first["reaction"]["reaction"] == "Opportunity Attack"
        answers = [{**first["reaction"]["context"], "selection": "USE"}]
        result = call(answers)
    answer = failed_choice(result, "speed", "Opportunity Attack")
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    assert call(answers)["reaction"] == result["reaction"]
    assert call([*answers, answer])["status"] == "COMMITTED"
    _, _, loaded = reload(tmp_path, mid)
    assert loaded.engine.state.actors[PLAYER].resources[STAMINA] == 29
    assert len(pressure_effects(loaded.engine.state.actors[FOE])) == 1
    assert loaded.engine._effective_speed(loaded.engine.state.actors[FOE]) == 20
    assert bundles.read_bytes() == saved_bundle_bytes
    if legacy_pressure:
        original_row = next(row for bundle in loaded.engine.typed_bundle_documents for row in bundle["typed_passives"]
                            if row.get("kind") == "pressure_point")
        assert "choice_owner" not in original_row
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("failed,enabled", [(False, True), (True, False)])
def test_pressure_success_or_disabled_does_not_ask(tmp_path, monkeypatch, failed, enabled):
    combat, table, mid = pressure_fight(tmp_path, monkeypatch, "attack" if enabled else "off", failed)
    assert pressure_act(table, *attack_candidate(combat, table, mid))["status"] == "COMMITTED"
    _, _, loaded = reload(tmp_path, mid)
    effects = pressure_effects(loaded.engine.state.actors[FOE])
    assert len(effects) == int(enabled)
    if enabled:
        assert effects[0].condition_id == "condition:typed.reaction_denied"
    assert loaded.engine.state.actors[PLAYER].resources[STAMINA] == (29 if enabled else 30)
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("failed", [False, True])
def test_ai_pressure_selects_automatically(tmp_path, monkeypatch, failed):
    combat, table, mid = pressure_fight(tmp_path, monkeypatch, "attack", failed)
    args = attack_candidate(combat, table, mid)
    auto_candidate(combat, mid, PLAYER, args[1])
    assert table.auto_step(mid, 0)["status"] == "COMMITTED"
    _, _, loaded = reload(tmp_path, mid)
    effects = pressure_effects(loaded.engine.state.actors[FOE])
    assert len(effects) == 1
    if failed:
        assert effects[0].target_field == "attack_mode" and effects[0].value == "DISADVANTAGE"
    else:
        assert effects[0].condition_id == "condition:typed.reaction_denied"
    assert loaded.engine.state.actors[PLAYER].resources[STAMINA] == 29
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("options", [{"owns_pressure": False}, {"miss": True}, {"stamina": 0}])
def test_pressure_is_inert_without_ownership_hit_or_stamina(tmp_path, monkeypatch, options):
    combat, table, mid = pressure_fight(tmp_path, monkeypatch, "reactions", True, **options)
    before = combat._load_session(mid).engine.state.actors[PLAYER].resources.get(STAMINA, 0)
    assert pressure_act(table, *attack_candidate(combat, table, mid))["status"] == "COMMITTED"
    _, _, loaded = reload(tmp_path, mid)
    assert loaded.engine.state.actors[PLAYER].resources.get(STAMINA, 0) == before
    assert not pressure_effects(loaded.engine.state.actors[FOE])
    assert not [e for e in loaded.engine.events if e.event_type == "SAVE_ROLLED" and e.source_definition_id == SOURCE]
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_ai_pressure_owner_selects_automatically_on_opportunity_attack(tmp_path, monkeypatch):
    combat, table, mid = pressure_fight(tmp_path, monkeypatch, "attack", True)
    assert act(table, mid, "end")["status"] == "COMMITTED"
    combat.set_controller_mode(mid, actor_id=PLAYER, controller_mode="LOCAL_AUTO")
    state = table.state(mid)
    menu = state["menu"]
    move = next(m for m in menu["moves"] if m["destination"] == {"x": 6, "y": 6})
    result = pressure_act(table, mid, move["candidate_id"], menu["decision_id"], menu["state_version"], state["last_sequence"])
    assert result["status"] == "COMMITTED"
    _, _, loaded = reload(tmp_path, mid)
    effects = pressure_effects(loaded.engine.state.actors[FOE])
    assert len(effects) == 1
    assert effects[0].target_field == "attack_mode" and effects[0].value == "DISADVANTAGE"
    assert loaded.engine.state.actors[PLAYER].resources[STAMINA] == 29
    assert loaded.mechanical.replay()["status"] == "PASS"
