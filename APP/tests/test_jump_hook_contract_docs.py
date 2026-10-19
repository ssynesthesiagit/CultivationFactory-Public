"""Keep the shared jump extension contracts discoverable and explicit."""
from pathlib import Path


def test_new_jump_hook_contracts_are_documented():
    docs = (Path(__file__).parents[1] / "combat" / "ext" / "__init__.py").read_text()
    assert "jump_run_start_free(engine, actor) -> None or bool" in docs
    assert "jump_steps_multiplier(engine, actor) -> positive integer" in docs
    assert "Default inert" in docs
    assert "before grid rounding or any separate fixed-distance grant" in docs
