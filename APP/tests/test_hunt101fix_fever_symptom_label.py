"""Fever Symptom's reviewed text is free of developer notes, and its Sickened rider still applies."""
import json
from pathlib import Path

from combat.ext.paid_hit import effect_text

ROOT = Path(__file__).resolve().parents[1]
AUTHORITY = ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json"
DEVELOPER_NOTE = "no Sickened condition defined"


def _fever_effects():
    record = json.loads(AUTHORITY.read_text())["mechanics"]["tianxia.talent.disease.fever_symptom"]
    return record["effects"]


def test_fever_symptom_label_has_no_developer_note():
    text = effect_text(_fever_effects())
    assert DEVELOPER_NOTE not in text
    assert "combat/rules" not in text
    assert "becomes Sickened until the start of your next turn." in text


def test_fever_symptom_failed_save_applies_sickened():
    save = _fever_effects()[0]
    conditions = [row for row in save["on_fail"] if row.get("type") == "condition"]
    assert [(row["condition"], row["duration"]) for row in conditions] == [("sickened", "until_start_of_next_turn")]
