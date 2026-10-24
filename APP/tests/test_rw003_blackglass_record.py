"""RW003 review fix: Blackglass Rampart's typed record must not keep GM riders for automated clauses.

The panel size and object stats (AC, HP, Vulnerability, Immunity) are carried by the wall object in
combat/rules/terrain.json, and the PB-Slashing traversal damage is carried by the wall's own enter
trigger. Leaving those lines as "GM:" or plain riders told the GM to rule on them by hand. The
activation effect stays "deferred": true on purpose (casting deals no damage); its notes say the
enter trigger does the work.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEY = "TAL_MAGMA_BLACKGLASS_RAMPART"
AUTOMATED_TEXT = ("GM:", "Each panel", "Slashing damage once per turn")


def _final_record() -> dict:
    data = json.loads((ROOT / "authority/typed_mechanics/reviewed_final.d/elements.json").read_text(encoding="utf-8"))
    return data["mechanics"][KEY]


def test_reviewed_record_keeps_no_gm_rider_for_automated_clauses():
    riders = _final_record()["riders"]
    assert not [line for line in riders if line.startswith("GM:") or any(text in line for text in AUTOMATED_TEXT)], riders


def test_reviewed_record_explains_the_deferred_activation_effect_in_notes():
    record = _final_record()
    effects = record["effects"]
    assert [effect.get("deferred") for effect in effects] == [True]
    notes = record.get("notes") or ""
    assert "enter trigger" in notes and "deferred: true" in notes, notes


def test_built_authority_record_has_no_gm_rider_and_keeps_the_ten_minute_duration():
    record = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text(encoding="utf-8"))["mechanics"][KEY]
    assert not [line for line in record.get("riders") or [] if any(text in line for text in AUTOMATED_TEXT)], record["riders"]
    assert not record.get("gm_decides"), record.get("gm_decides")
    assert record["duration"] == {"kind": "minutes", "amount": 10, "concentration": False}
    assert "enter trigger" in (record.get("notes") or "")
