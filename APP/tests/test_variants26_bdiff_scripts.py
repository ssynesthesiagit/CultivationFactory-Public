"""VARIANTS26F1 finding 2: bdiff setup scripts must only tweak actor fields this checkout's actor model has.

The saved scripts set a Wisdom score that the actor model does not carry, so setup failed on both arms before any
comparison ran. This test fails on the saved scripts and passes on the fixed ones.
"""
import json
from pathlib import Path

import pytest

from combat.gate2_runtime_models import ActorState

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = sorted((ROOT / "tests" / "fixtures" / "bdiff_variants26").glob("*.json"))
SUPPORTED_SCORES = {"STR", "DEX", "strength_score", "dexterity_score"}


def test_fixed_scripts_exist():
    assert len(SCRIPTS) == 2


@pytest.mark.parametrize("path", SCRIPTS, ids=lambda p: p.name)
def test_script_tweaks_use_only_supported_actor_scores(path):
    script = json.loads(path.read_text())
    for tweak in script.get("tweaks", []):
        for key in tweak.get("scores", {}):
            assert key in SUPPORTED_SCORES, f"{path.name}: unsupported score {key!r}"


def test_actor_model_has_no_wisdom_score():
    fields = set(ActorState.model_fields)
    assert "wisdom_score" not in fields
    assert {"strength_score", "dexterity_score"} <= fields
