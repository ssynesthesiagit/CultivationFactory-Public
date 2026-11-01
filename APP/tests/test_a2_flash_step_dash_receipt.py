"""Flash Step's Dash receipt retains its execution identity at the real table."""
import json

import pytest

from combat.gate2_runtime_models import Position
from tests.test_a2r23_athletics_map import (
    FIGHTER, FLASH_STEP, FOCUS, ROOT, act, answer_for, events, find, table_fight,
)

COORDINATED = "ATHLETICS_BASE_COORDINATED_MOVEMENT"
MERIDIAN = "TAL_ATHLETICS_MERIDIAN_THREADING_DASH"


@pytest.mark.parametrize("benefit", ["step", "check"])
def test_short_flash_step_asks_meridian_and_persists_selected_benefit(tmp_path, benefit):
    # Literal canonical input keeps the glob-loaded passives in public CI's
    # dependency closure. Compile the real rows; never synthesize the passives.
    rules = json.loads((ROOT / "combat/rules/feature_blocks.d/auto8-athletics.json").read_text())
    assert any(row["kind"] == "meridian_threading" for row in rules["features"][MERIDIAN]["rules"])
    combat, table, mid = table_fight(tmp_path, [COORDINATED, FLASH_STEP, MERIDIAN])
    before = combat._load_session(mid).engine.state.actors[FIGHTER].movement_remaining_ft
    candidate = find(table, mid, "flash_step")
    answers = []
    meridian_prompts = []
    for _ in range(12):
        result = act(table, mid, candidate, answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        choice = prompt.get("choice") or {}
        options = {row["id"] for row in choice.get("options") or []}
        if "cell:3,5" in options:
            selected = "cell:3,5"  # Five feet: walking cannot restore Focus here.
        elif {"step", "stand", "grapple", "check"} <= options:
            assert "Meridian-Threading Dash" in json.dumps(prompt)
            meridian_prompts.append(prompt)
            selected = benefit
        else:
            answers.append(answer_for(prompt))
            continue
        answers.append({**prompt["context"], "selection": "USE", "option_ids": [selected]})
    else:
        pytest.fail("Flash Step did not finish after its landing and benefit choices")
    assert result["status"] == "COMMITTED"
    assert len(meridian_prompts) == 1, "the real Meridian choice must be offered exactly once"
    engine = combat._load_session(mid).engine
    actor = engine.state.actors[FIGHTER]
    assert actor.position == Position(x=3, y=5)
    assert actor.resources[FOCUS] == 1
    gains = [event for event in events(engine, "RESOURCE_GAINED", FIGHTER)
             if event.source_definition_id == "passive:" + COORDINATED]
    assert len(gains) == 1
    assert actor.turn_flags["athletics_used:meridian_threading"] == (
        f"athletics_turn:{engine.state.round_number}:{engine.state.current_slot_index}:{FIGHTER}")
    if benefit == "step":
        assert actor.turn_flags["oa_free_ft"] == 10
        assert actor.movement_remaining_ft == before + 10
    else:
        held = [condition for condition in actor.conditions.values()
                if condition.condition_id == "condition:typed.meridian_check"]
        assert len(held) == 1
        assert held[0].expires_on == "END_OF_HOLDER_NEXT_TURN"
        assert actor.movement_remaining_ft == before
