"""Coverage accounting for the Consume Fear drop clause, which the plug-in now automates."""

import json
from pathlib import Path

AUTHORITY = Path(__file__).resolve().parents[1] / "authority"
KEY = "TAL_DAEMONIC_CULTIVATION_CONSUME_FEAR_REFINE_COMMAND"


def _record():
    return json.loads((AUTHORITY / "Tianxia_Typed_Mechanics_Authority_R1.json").read_text())["mechanics"][KEY]


def test_consume_fear_drop_clause_is_automated_so_the_record_is_full():
    record = _record()
    # The drop is resolved by combat/ext/daemonic_riders.py (rider_consume_fear), so no clause remains a rider.
    assert record["riders"] == []
    assert record["coverage"] == "FULL"


def test_reviewed_record_does_not_claim_the_drop_is_unresolved():
    reviewed = json.loads((AUTHORITY / "typed_mechanics/reviewed_final.d/martial.json").read_text())["mechanics"][KEY]
    text = json.dumps(reviewed).lower()
    assert "unresolved" not in text
    assert "not automated" not in text
    assert reviewed["riders"] == []
