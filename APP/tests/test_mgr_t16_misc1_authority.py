"""Keep the compiler's Ledger/Field inputs consistent after authority merges.

The companion Ledger and Silence table tests exercise choices, continuous
effects, and cold replay. These checks identify stale generated input directly.
"""
import json
from pathlib import Path

import pytest


AUTHORITY = Path(__file__).resolve().parents[1] / "authority"


@pytest.mark.parametrize("shard,ability,field", [
    ("review_sw-earth.json", "TAL_FATE_MARKED_BY_THE_LEDGER", "options"),
    ("auto16_sound.json", "TAL_SOUND_FORBIDDEN_SILENCE_FIELD", "effects"),
])
def test_generated_ledger_and_field_retain_reviewed_effects(shard, ability, field):
    reviewed = json.loads(
        (AUTHORITY / "typed_mechanics/reviewed_final.d" / shard).read_text()
    )["mechanics"][ability]
    generated = json.loads(
        (AUTHORITY / "Tianxia_Typed_Mechanics_Authority_R1.json").read_text()
    )["mechanics"][ability]
    assert generated[field] == reviewed[field], (ability, field)
