"""Player-visible interruption prompts from accepted attacks, rather than Hold triggers."""
import pytest
from combat.ext import force, monkey, shadow
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.test_tabletop_hunt6 import LEFT, ALLY, RIGHT, HOLD, on_hold
from tests.test_lock2_persistence import act
from tests.test_r10_consent_fix import willing_fight
from tests.r10_fixup_support import fixed_dice, cast_sender, commit


def end_sender(table, mid):
    state = table.state(mid)
    menu = state["menu"]
    return lambda answers=(): table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], state["last_sequence"], list(answers))


@pytest.mark.parametrize("slip", [False, True])
def test_monkey_base_finish_table_prompt_names_actual_attack_and_creature(monkeypatch, tmp_path, slip):
    kit = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.gun", "quantity": 1}]}}
    from tests.test_tabletop_hunt6 import table_fight
    combat, table, mid = table_fight(tmp_path, ["TAL_MONKEY_STYLE_CAPERING_FOOTWORK"], kit=kit,
                                    cl=20, ask=True, ally_talents=[])
    commit(cast_sender(combat, table, mid, "Capering Footwork"))
    on_hold(monkeypatch, lambda e: monkey.create(e, e.state.actors[LEFT], "test:opener", "test", counted=False))
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    fixed_dice(monkeypatch, [15, 15] + [1] * 40)
    send = cast_sender(combat, table, mid, "Gun (Staff) attack", target=RIGHT)
    result = send()
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert "Monkey" in prompt["moment"] and "Gun (Staff) attack" in prompt["moment"] and "Right" in prompt["moment"]
    prompts = commit(send, lambda p: ("slip", True) if slip and p["context"]["reaction_source_id"].endswith("monkey_finish") else (None, False))
    if slip:
        assert len(prompts) == 2
        assert "Slip Finish" in prompts[1]["moment"] and "Gun (Staff) attack" in prompts[1]["moment"]
        assert "Left" in prompts[1]["moment"] and "Right" in prompts[1]["moment"]
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert bool(monkey.links(loaded.engine.state.actors[LEFT])) == (not slip)
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_court_step_table_prompt_names_missed_attack_and_creature(monkeypatch, tmp_path):
    feature = force.COURT
    name = "Court of the Answering World"
    kit = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.bi_shou", "quantity": 1}]}}
    combat, table, mid = willing_fight(monkeypatch, tmp_path, [feature], kit=kit)
    commit(cast_sender(combat, table, mid, name))
    fixed_dice(monkeypatch, [1] * 40)
    while table.state(mid)["menu"]["actor_id"] != RIGHT:
        commit(end_sender(table, mid), lambda p: (None, True))
    send = cast_sender(combat, table, mid, "Bi Shou (Dagger) attack", target=ALLY)
    result = send()
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert prompt["context"]["reactor_id"] == ALLY
    assert name in prompt["moment"] and "Bi Shou (Dagger) attack" in prompt["moment"] and "Ally" in prompt["moment"]
    assert "Right" in prompt["moment"]
    commit(send)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()["status"] == "PASS"
