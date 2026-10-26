"""VARIANTS26F1 finding 2: bdiff setup scripts must only tweak actor fields this checkout's actor model has.

The saved scripts set a Wisdom score that the actor model does not carry, so setup failed on both arms before any
comparison ran. This test fails on the saved scripts and passes on the fixed ones.
"""
import pytest

from combat.gate2_runtime_models import ActorState

SUPPORTED_SCORES = {"STR", "DEX", "strength_score", "dexterity_score"}
# Public-safe synthetic equivalents of the two behavior-diff scripts. Keep their score-tweak
# validation independent of private fixture export/clearance.
SCRIPTS = {
    "meld-darkvision-persistent": {
        "seed": "BDIFF-meld-darkvision-persistent",
        "owner_talents": ["TAL_DARK_DARKVISION", "TAL_DARK_BLINDFOLD"],
        "steps": [{"use": "Meld: Darkvision (Persistent)", "target": "FOE"}],
        "tweaks": [],
    },
    "meld-blindfold-persistent-enhanced": {
        "seed": "BDIFF-meld-blindfold-persistent-enhanced",
        "owner_talents": ["TAL_DARK_BLINDFOLD", "TAL_DARK_DARKVISION"],
        "steps": [{"use": "Meld: Blindfold (Persistent) (2 CP)", "target": "FOE"}],
        "tweaks": [],
    },
}


def test_fixed_scripts_exist():
    assert len(SCRIPTS) == 2


@pytest.mark.parametrize("name,script", SCRIPTS.items(), ids=SCRIPTS.keys())
def test_script_tweaks_use_only_supported_actor_scores(name, script):
    for tweak in script.get("tweaks", []):
        for key in tweak.get("scores", {}):
            assert key in SUPPORTED_SCORES, f"{name}: unsupported score {key!r}"


def test_actor_model_has_no_wisdom_score():
    fields = set(ActorState.model_fields)
    assert "wisdom_score" not in fields
    assert {"strength_score", "dexterity_score"} <= fields
