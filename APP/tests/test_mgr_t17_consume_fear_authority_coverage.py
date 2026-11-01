"""Coverage accounting for the Consume Fear held-object drop clause.

This checks authority accounting, not native drop behaviour.
"""

import json
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
AUTHORITY = APP / "authority"
KEY = "TAL_DAEMONIC_CULTIVATION_CONSUME_FEAR_REFINE_COMMAND"
SOURCE_HASH = "3bc927c349ca80abd334bce4792de127487a09f34109e6a652e82999b557774d"


def _generated():
    return json.loads((AUTHORITY / "Tianxia_Typed_Mechanics_Authority_R1.json").read_text())["mechanics"][KEY]


def _reviewed():
    return json.loads((AUTHORITY / "typed_mechanics/reviewed_final.d/martial.json").read_text())["mechanics"][KEY]


def test_generated_record_keeps_the_reviewed_rider_and_source():
    record = _generated()
    reviewed = _reviewed()
    assert reviewed["text_sha256"] == SOURCE_HASH
    assert record["source"]["text_sha256"] == SOURCE_HASH
    assert record["coverage"] == "CORE_WITH_RIDERS"
    assert len(reviewed["riders"]) == 1
    assert record["riders"] == reviewed["riders"]


def test_reviewed_override_keeps_its_modifier():
    reviewed = _reviewed()
    assert reviewed["modifier"]["targets"] == ["Dread Appetite"]
    assert reviewed["modifier"]["when"] == "failed_save"
    assert reviewed["modifier"]["effects"] == [{"type": "rider_consume_fear"}]
