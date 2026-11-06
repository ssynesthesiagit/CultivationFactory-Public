import pytest

from combat.gate5_service import CombatService
from tests.h1_support import ROOT, script
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import LEFT, HOLD, table_fight, on_hold, answer_action


@pytest.mark.parametrize("kind,roll_name", [("save", "DEX saving throw"), ("attack", "attack roll"), ("check", "ability check"), ("contest", "ability check")])
@pytest.mark.parametrize("ai_turn", [False, True])
def test_disaster_prompt_identifies_roll_creature_action_and_die_on_manual_and_ai_turns(monkeypatch, tmp_path, kind, roll_name, ai_turn):
    from combat.gate4_engine import Gate4ControllerEngine
    from tests.test_tabletop_hunt6 import RIGHT

    combat, table, mid = table_fight(tmp_path, ["TAL_FATE_REWRITE_THE_DISASTER"], ask=True)
    if ai_turn:
        while table.state(mid)["menu"]["actor_id"] != RIGHT:
            assert act(table, mid, "end")["status"] == "COMMITTED"
        combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode="LOCAL_AUTO")
    roller_id = RIGHT if ai_turn else LEFT
    observed = {}
    original = Gate4ControllerEngine._append_event

    def roll(engine, event_type, *args, **kwargs):
        result = original(engine, event_type, *args, **kwargs)
        if event_type == "INTENT_ACCEPTED" and kwargs.get("actor_id") == roller_id:
            actor = engine.state.actors[roller_id]
            source = args[0]
            action = engine.action_catalog.get(source)
            observed["action"] = action.display_name if action else source.removeprefix("system:combat.").replace("_", " ").title()
            script(engine, [2])
            if kind == "save":
                engine._roll_save(actor, "DEX", 16, source)
            elif kind == "check":
                from combat import stealth
                stealth._check(engine, actor, 3, "NORMAL", source, "Stealth", 15)
            elif kind == "contest":
                from combat.character_runtime_adapter import CharacterCombatRuntimeEngine
                target = engine.state.actors[LEFT if ai_turn else RIGHT]
                CharacterCombatRuntimeEngine._resolve_typed_check(
                    engine, actor, target, source_id=source, target_mode="CONTEST")
            else:
                target = engine.state.actors[LEFT if ai_turn else RIGHT]
                engine._resolve_attack_spec(actor, target, {"attack_bonus": 8, "range_ft": 60},
                                            engine._active_intent, source_definition_id=source, attack_index=1)
        return result

    monkeypatch.setattr(Gate4ControllerEngine, "_append_event", roll)
    first = table.auto_step(mid, 0) if ai_turn else act(table, mid, HOLD)
    assert first["status"] == "REACTION_REQUIRED"
    prompt = first["reaction"]
    assert prompt["reactor"] == "Left"
    assert prompt["reaction"] == "Rewrite the Disaster"
    for text in ("Rewrite the Disaster", "Right" if ai_turn else "Left", roll_name, observed["action"], "observed d20: 2"):
        assert text.lower() in prompt["moment"].lower()
    assert ":Stealth" not in prompt["moment"]
    assert ":actor" not in prompt["moment"].lower() and ":defender" not in prompt["moment"].lower()
    assert prompt["cost"] == "Reaction + 12 Qi"
    assert "does not charge" not in prompt["table_note"]
    # fix/prompt-ui (round22 merge f9685b35) omits descriptions repeating the label.
    assert prompt["choice"]["options"] == [
        {"id": str(value), "label": f"Natural {value}: replace the observed d20 with {value}",
         "description": ""} for value in (1, 20)]
    if ai_turn:
        result = table.auto_step(mid, 0, [{**prompt["context"], "selection": "USE", "option_ids": ["1"]}])
    else:
        result = answer_action(table, mid, HOLD, "20")
    assert result["status"] == "COMMITTED"
    assert CombatService(ROOT, tmp_path)._load_session(mid).mechanical.replay()["status"] == "PASS"


def test_disaster_skill_prompt_uses_catalog_technique_name(monkeypatch, tmp_path):
    from combat import stealth
    combat, table, mid = table_fight(
        tmp_path, ["TAL_FATE_REWRITE_THE_DISASTER", "SPEAR_BASE_SPEAR_THRUST"], ask=True)
    observed = {}

    def check(engine):
        action = next(a for a in engine.action_catalog.values()
                      if a.owner_id == LEFT and "SPEAR_BASE_SPEAR_THRUST#opt0" in a.source_definition_id)
        observed["name"], observed["id"] = action.display_name, action.source_definition_id
        script(engine, [2])
        stealth._check(engine, engine.state.actors[LEFT], 3, "NORMAL", action.source_definition_id, "Stealth", 15)

    on_hold(monkeypatch, check)
    first = act(table, mid, HOLD)
    assert first["status"] == "REACTION_REQUIRED"
    moment = first["reaction"]["moment"]
    assert observed["name"] in moment
    assert observed["id"] not in moment and ":Stealth" not in moment
    assert answer_action(table, mid, HOLD, "20")["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("natural", [1, 20])
def test_disaster_table_offers_named_dice_and_commits_the_chosen_value(monkeypatch, tmp_path, natural):
    combat, table, mid = table_fight(tmp_path, ["TAL_FATE_REWRITE_THE_DISASTER"], ask=True)
    def roll(engine):
        script(engine, [2])
        engine._roll_save(engine.state.actors[LEFT], "DEX", 16, "test:save")
    on_hold(monkeypatch, roll)
    first = act(table, mid, HOLD)
    assert first["status"] == "REACTION_REQUIRED"
    assert first["reaction"]["reaction"] == "Rewrite the Disaster"
    assert first["reaction"]["cost"] == "Reaction + 12 Qi"
    # fix/prompt-ui (round22 merge f9685b35) omits descriptions repeating the label.
    assert first["reaction"]["choice"]["options"] == [
        {"id": str(value), "label": f"Natural {value}: replace the observed d20 with {value}",
         "description": ""} for value in (1, 20)]
    assert answer_action(table, mid, HOLD, str(natural))["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    rewrites = [e for e in loaded.engine.events if e.event_type == "D20_REWRITTEN"]
    assert len(rewrites) == 1 and rewrites[0].payload["result"]["natural_result"] == natural
    assert loaded.mechanical.replay()["status"] == "PASS"
