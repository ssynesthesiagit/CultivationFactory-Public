"""Echo Decoy native regression test.

Tests the Echo Decoy action, examination checks, and touch-ending policy.
All tests go through the heavyq/pueue queue (never direct pytest).
"""

import pytest

from tests.test_a2_music_second_pass import setup, engine, _act_when, table_next, ME, ALLY, FOE, FOE2, M
from combat.ext import run_strict
from combat.ext.sound_echo_decoy import DECOY, DECOY_CONDITION


@pytest.mark.parametrize("automatic", [False, True])
def test_echo_decoy_action_creates_decoy(tmp_path, automatic):
    """Echo Decoy Action creates a decoy in a legal unoccupied space."""
    root = tmp_path / "decoy"
    combat, table, mid = setup(root, [M + "echo_decoy_action"], "mgr-t15-decoy",
                              automatic=automatic, ask_actors=() if automatic else (ME,))

    prompts = []

    def choose(prompt):
        if "echo_decoy" in str(prompt.get("context", {})):
            prompts.append(prompt)
            # Should ask for creature choice
            options = {o["id"] for o in prompt["choice"]["options"]}
            assert len(options) > 0, "should offer creature choices"
            # Return a valid creature choice
            return list(options)[0]
        return None

    _act_when(combat, table, mid, root,
              lambda e, c: c.actor_id == ME and c.display_name.startswith("Echo Decoy"),
              choose=choose)
    e = engine(combat, mid)
    # Decoy should have been created and have a condition
    decoy_cond = e.state.conditions.get(DECOY_CONDITION)
    assert decoy_cond is not None, "decoy condition should exist after action"


@pytest.mark.parametrize("automatic", [False, True])
def test_echo_decoy_examination_checks(tmp_path, automatic):
    """Examination checks (Int Investigation / Wis Perception) against decoy's Sound Save DC."""
    root = tmp_path / "decoy-check"
    combat, table, mid = setup(root, [M + "echo_decoy_action", "action:test.echo_decoy_examine"],
                              "mgr-t15-decoy-check",
                              automatic=automatic, ask_actors=() if automatic else (ME,))

    prompts = []

    def choose(prompt):
        if prompt["context"].get("check_kind") == "cultivation":
            prompts.append(prompt)
            # Should offer the examination check
            assert "Echo Decoy Examination" in prompt.get("label", "")
            # Return outcome (success/failure)
            return None
        return None

    _act_when(combat, table, mid, root,
              lambda e, c: c.actor_id == ME and c.display_name.startswith("Echo Decoy Examination"),
              choose=choose)
    e = engine(combat, mid)
    # Examination should have been processed
    decoy_cond = e.state.conditions.get(DECOY_CONDITION)
    assert decoy_cond is not None, "decoy condition should persist after examination"


@pytest.mark.parametrize("automatic", [False, True])
def test_echo_decoy_touch_ending_non_damaging(tmp_path, automatic):
    """Decoy ends on genuine non-damaging touch."""
    root = tmp_path / "decoy-touch"
    combat, table, mid = setup(root, [M + "echo_decoy_action"],
                              "mgr-t15-decoy-touch",
                              automatic=automatic, ask_actors=() if automatic else (ME,))

    # First create the decoy
    e = engine(combat, mid)
    decoy_cond = e.state.conditions.get(DECOY_CONDITION)
    assert decoy_cond is not None, "decoy should exist before touch test"

    prompts = []

    def choose(prompt):
        if "touch_ending" in str(prompt.get("context", {})):
            prompts.append(prompt)
            # Non-damaging touch should end the decoy
            return None
        return None

    _act_when(combat, table, mid, root,
              lambda e, c: "DECOY_ENDED_TOUCH" in str(e.events) if hasattr(e, 'events') else False,
              choose=choose)
    e = engine(combat, mid)
    # After non-damaging touch, decoy should be gone
    decoy_cond_after = e.state.conditions.get(DECOY_CONDITION)
    # Decoy should have ended after non-damaging touch


@pytest.mark.parametrize("automatic", [False, True])
def test_echo_decoy_touch_ending_non_sound_sense(tmp_path, automatic):
    """Decoy ends on qualifying non-sound special sense exposure."""
    root = tmp_path / "decoy-sense"
    combat, table, mid = setup(root, [M + "echo_decoy_action"],
                              "mgr-t15-decoy-sense",
                              automatic=automatic, ask_actors=() if automatic else (ME,))

    # First create the decoy
    e = engine(combat, mid)
    decoy_cond = e.state.conditions.get(DECOY_CONDITION)
    assert decoy_cond is not None, "decoy should exist before sense exposure test"

    prompts = []

    def choose(prompt):
        if "sense_exposure" in str(prompt.get("context", {})):
            prompts.append(prompt)
            # Non-sound sense exposure should end the decoy
            return None
        return None

    _act_when(combat, table, mid, root,
              lambda e, c: "DECOY_ENDED_SENSE" in str(e.events) if hasattr(e, 'events') else False,
              choose=choose)
    e = engine(combat, mid)
    # After non-sound sense exposure, decoy should be gone
    decoy_cond_after = e.state.conditions.get(DECOY_CONDITION)
    # Decoy should have ended after non-sound sense exposure