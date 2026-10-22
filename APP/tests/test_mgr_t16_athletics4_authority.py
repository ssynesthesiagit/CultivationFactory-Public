"""Guard compiled Athletics inputs against losing reviewed data in a merge.

Table regressions exercise this artifact's behavior; these checks pinpoint
the integration failure when generated authority is replaced with stale data.
"""
import json
from pathlib import Path

import pytest


AUTHORITY = Path(__file__).resolve().parents[1] / "authority"


@pytest.mark.parametrize("source,ability,fields", [
    ("bodyb.json", "TAL_ATHLETICS_UNBROKEN_PURSUIT",
     ("range_scale", "subject_relation", "effects", "riders")),
    ("auto8-athletics.json", "TAL_ATHLETICS_POLEARM_VAULTER",
     ("effects", "riders")),
])
def test_generated_athletics_retains_reviewed_runtime_and_player_text(source, ability, fields):
    reviewed = json.loads(
        (AUTHORITY / "typed_mechanics/reviewed_final.d" / source).read_text()
    )["mechanics"][ability]
    generated = json.loads(
        (AUTHORITY / "Tianxia_Typed_Mechanics_Authority_R1.json").read_text()
    )["mechanics"][ability]
    for field in fields:
        assert generated.get(field) == reviewed[field], (ability, field)
    if ability == "TAL_ATHLETICS_UNBROKEN_PURSUIT":
        assert generated["range_scale"] == "speed"
        assert generated["subject_relation"] == "any"
        assert [effect["type"] for effect in generated["effects"]] == ["athletics_unbroken_pursuit"]
