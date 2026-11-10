"""MGR-T17 armor-ally review: Armor Knows Its Owner's owner-facing records must match the behaviour.

The trigger "wearing armor or carrying a shield" is enforced by the recipient_allowed hook in
combat/ext/ironclad_blacksmith.py. The three records that describe the clause (feature_blocks, feature_status and the
reviewed_final note) and the generated typed authority must say so, not claim the clause is unchecked.
"""
from __future__ import annotations

import json
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
STALE = ("Unfinished printed clause", "Remaining printed clause", "REMAINING CLAUSE", "is not checked")
RECORDS = [
    ("combat/rules/feature_blocks.d/blacksmith.json", "tianxia.talent.blacksmith.armor_knows_its_owner", "why"),
    ("combat/rules/feature_status.d/blacksmith.json", "tianxia.talent.blacksmith.armor_knows_its_owner", "why"),
    ("authority/typed_mechanics/reviewed_final.d/mgr_t17_armor_owner.json",
     "tianxia.talent.blacksmith.armor_knows_its_owner", "notes"),
]


def _text(path: str, key: str, field: str) -> str:
    data = json.loads((APP / path).read_text(encoding="utf-8"))
    for section in ("mechanics", "rules", "features", "records"):
        if isinstance(data.get(section), dict) and key in data[section]:
            return str(data[section][key][field])
    return str(data[key][field])


def test_armor_knows_records_say_the_armor_or_shield_trigger_is_enforced():
    for path, key, field in RECORDS:
        text = _text(path, key, field)
        assert not any(phrase in text for phrase in STALE), path
        assert "recipient_allowed" in text, path
        assert "carrying" in text and "shield" in text, path


def test_generated_authority_carries_the_enforced_trigger_text():
    authority = (APP / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text(encoding="utf-8")
    assert "wearing armor or carrying a shield' is enforced" in authority
    assert "wearing armor or carrying a shield' is not checked" not in authority
