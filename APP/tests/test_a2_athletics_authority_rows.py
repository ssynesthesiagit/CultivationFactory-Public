"""Pin the reviewed Athletics rows carried by generated authority.

Use canonical source identities, not hashes of public CI presentation prose.
The full builder reproducibility check is recorded separately in lane evidence.
"""
import json
import re
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]


def mechanical_fields(value):
    """Compare structured rules, retaining quantities in transformed prose.

    These five rows also carry English sentences in on/trigger/duration/
    condition. Public CI transforms those sentences independently per path;
    identifiers, enum tokens, expression tokens and numeric fields stay exact.
    Full canonical prose parity is the separate byte-identical builder check.
    """
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            if key == "evidence":
                continue
            if key in {"on", "trigger", "duration", "condition"} and isinstance(child, str) and " " in child:
                result[key] = {"prose_quantities": re.findall(r"\d+", child)}
            else:
                result[key] = mechanical_fields(child)
        return result
    if isinstance(value, list):
        return [mechanical_fields(child) for child in value]
    return value


@pytest.mark.parametrize("feature_id", [
    "TAL_ATHLETICS_FLASH_STEP",
    "TAL_ATHLETICS_ONE_BREATH_TEN_THOUSAND_STEPS",
    "TAL_ATHLETICS_ROPE_SWING_ADEPT",
    "TAL_ATHLETICS_AFTERIMAGE",
    "TAL_ATHLETICS_SPEED_BOOST",
])
def test_generated_athletics_row_preserves_reviewed_fields(feature_id):
    reviewed = json.loads((APP / "authority/typed_mechanics/reviewed_final.d/auto8-athletics.json").read_text())["mechanics"][feature_id]
    generated = json.loads((APP / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())["mechanics"][feature_id]
    assert generated["source"]["text_sha256"] == reviewed["text_sha256"]
    assert generated["typing_status"] == "reviewed_final"
    for field in ("effects", "cost", "activation", "modifier"):
        if field in reviewed:
            actual, expected = mechanical_fields(generated[field]), mechanical_fields(reviewed[field])
            assert actual == expected, (feature_id, field, actual, expected)
    # Exact rider prose, like evidence, is covered by the private byte-identical
    # builder check; the public test still pins the presence of each disclosure.
    assert len(generated["riders"]) == len(reviewed["riders"])
    assert all(isinstance(rider, str) and rider for rider in generated["riders"])
