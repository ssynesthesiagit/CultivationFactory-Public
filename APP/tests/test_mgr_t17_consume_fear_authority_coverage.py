"""Coverage accounting for the Consume Fear held-object drop clause.

The printed clause "it drops one held mundane object if it fails a Strength saving throw" stays an explicit
unresolved rider in the reviewed override, so the authority cannot silently report the record as FULL with no riders.
"""

import json
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
AUTHORITY = APP / "authority"
KEY = "TAL_DAEMONIC_CULTIVATION_CONSUME_FEAR_REFINE_COMMAND"
DROP_CLAUSE = "it drops one held mundane object if it fails a Strength saving throw"


def _generated():
    return json.loads((AUTHORITY / "Tianxia_Typed_Mechanics_Authority_R1.json").read_text())["mechanics"][KEY]


def _reviewed():
    return json.loads((AUTHORITY / "typed_mechanics/reviewed_final.d/martial.json").read_text())["mechanics"][KEY]


def test_printed_drop_clause_is_still_in_the_source_text():
    rules = json.loads((AUTHORITY / "typed_mechanics/rules_text.json").read_text())
    assert DROP_CLAUSE in rules[KEY]


def test_generated_record_keeps_the_drop_clause_as_an_unresolved_rider_not_full():
    record = _generated()
    assert record["coverage"] == "CORE_WITH_RIDERS"
    assert record["coverage"] != "FULL"
    assert len(record["riders"]) == 1
    rider = record["riders"][0]
    assert "unresolved" in rider
    assert "held-object drop" in rider


def test_reviewed_override_states_the_unresolved_drop_and_keeps_its_modifier():
    reviewed = _reviewed()
    assert len(reviewed["riders"]) == 1
    assert "unresolved" in reviewed["riders"][0]
    # Only the rider changed: the reviewed modifier (the choose-one menu, Dread Appetite) stays intact.
    assert reviewed["modifier"]["targets"] == ["Dread Appetite"]
    assert reviewed["modifier"]["when"] == "failed_save"
    assert reviewed["modifier"]["effects"] == [{"type": "rider_consume_fear"}]
