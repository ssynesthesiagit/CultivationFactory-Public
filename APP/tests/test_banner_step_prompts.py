from pathlib import Path


def test_banner_step_prompts_match_deferred_turn_start_delivery():
    source = (Path(__file__).parents[1] / "combat/ext/banner.py").read_text()
    assert "Rally the Line: choose allies to gain Temporary Hit Points and move 5 feet at the start of their next turn without provoking" in source
    assert "Follow the Victor: choose a different ally to move 5 feet at the start of its next turn without provoking" in source
    assert "may step now" not in source
    assert "to step now" not in source
