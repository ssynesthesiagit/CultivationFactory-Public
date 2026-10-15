"""An off-turn Furnace Mantle choice identifies its source and target duration."""
import pytest

from tests.hunt14_support import ME, ALLY, FOE, act, advance, fight, reload


@pytest.mark.parametrize("auto_turn", [False, True])
def test_offturn_heat_pressure_prompt_names_feature_owner_and_duration(tmp_path, auto_turn):
    # Seed 7 orders Tester -> Ally -> Target: the outer turn's actor is
    # different from Furnace Mantle's owner when its consequence fires.
    combat, table, mid = fight(tmp_path, mantle=True, seed=7)
    act(table, mid, "TAL_MAGMA_FURNACE_MANTLE")
    # The owner stays manual with Ask me. An ally's turn ends as the hostile
    # creature starts; the Heat Pressure choice still belongs to the owner.
    if auto_turn:
        combat.set_controller_mode(mid, actor_id=ALLY, controller_mode="LOCAL_AUTO")
        combat.set_controller_mode(mid, actor_id=FOE, controller_mode="LOCAL_AUTO")
    prompts = act(table, mid, "end", option="reactions", auto=False)
    # An ally can precede the hostile turn in initiative.
    for _ in range(20):
        if prompts:
            break
        current = table.state(mid)["menu"]["actor_id"]
        prompts = act(table, mid, "end", option="reactions", auto=auto_turn and current == ALLY)
    prompt = next(p for p in prompts if p.get("choice"))
    assert prompt["action"] == "Furnace Mantle"
    assert prompt["trigger_actor"] == "Tester"
    assert prompt["affected"] == "Target"
    assert "Furnace Mantle" in prompt["moment"]
    assert "Target" in prompt["moment"]
    assert "next turn starts" in next(o["label"] for o in prompt["choice"]["options"] if o["id"] == "reactions")
    assert "extra cost" in prompt["moment"]
    engine = reload(tmp_path, mid)
    assert any("reaction_denied" in c.condition_id for c in engine.state.actors[FOE].conditions.values())


def test_ai_mantle_owner_selects_heat_pressure_automatically(tmp_path):
    combat, table, mid = fight(tmp_path, mantle=True, seed=7)
    act(table, mid, "TAL_MAGMA_FURNACE_MANTLE")
    combat.set_controller_mode(mid, actor_id=ME, controller_mode="LOCAL_AUTO")
    assert act(table, mid, "end", auto=True, selected=True) == []
    assert table.state(mid)["menu"]["actor_id"] == ALLY
    assert act(table, mid, "end") == []
    engine = reload(tmp_path, mid)
    assert engine.state.current_actor_id == FOE
    assert any(m.target_field == "speed_ft" and m.value == -10 for m in engine.state.actors[FOE].modifiers.values())
