"""Exact-source replay of conversion receipts and stale-owner-edit protection."""
from __future__ import annotations

import copy
import hashlib
import json

import pytest

from factory_authoring.rider_pattern_overlay import SCHEMA, apply, apply_file, coverage, digest
from factory_authoring.rider_pattern_conversions import conversions


def _case():
    original = {"mechanic_id": "synthetic", "source": {"text_sha256": "a" * 64},
                "effects": [{"type": "damage", "flat": 2}], "riders": ["A bounded printed rider."],
                "coverage": "CORE_WITH_RIDERS"}
    revised = {**copy.deepcopy(original), "riders": [],
               "effects": [{"type": "damage", "flat": 2}, {"type": "speed", "flat": 5}]}
    revised["coverage"] = coverage(revised)
    row = {"text_sha256": original["source"]["text_sha256"], "input_sha256": digest(original),
           "output_sha256": digest(revised), "set": {"effects": revised["effects"], "riders": []}, "remove": []}
    return {"mechanics": {"synthetic": original}}, {"schema": SCHEMA, "mechanics": {"synthetic": row}}, revised


def test_receipt_replays_only_the_complete_input_it_was_built_from():
    data, receipt, revised = _case()
    assert apply(data, receipt) == {"synthetic": "applied"}
    assert data["mechanics"]["synthetic"] == revised
    once = copy.deepcopy(data)
    assert apply(data, receipt) == {"synthetic": "changed_typing"}
    assert data == once, "a second application cannot duplicate effects or consume its own output"


@pytest.mark.parametrize("change,expected", [
    ("owner_text", "stale_text"), ("reviewed_effect", "changed_typing"),
    ("unrelated_new_rider", "changed_typing"), ("new_cost", "changed_typing"),
])
def test_owner_text_or_other_lane_changes_keep_the_original_riders(change, expected):
    data, receipt, _ = _case()
    record = data["mechanics"]["synthetic"]
    if change == "owner_text":
        record["source"]["text_sha256"] = "b" * 64
    elif change == "reviewed_effect":
        record["effects"][0]["flat"] = 9
    elif change == "unrelated_new_rider":
        record["riders"].append("A later review still needs this condition.")
    else:
        record["cost"] = [[{"resource": "qi", "amount": 3}]]
    preserved = copy.deepcopy(data)
    assert apply(data, receipt) == {"synthetic": expected}
    assert data == preserved


def test_missing_supplement_is_byte_inert_for_historical_builds(tmp_path):
    data, _, _ = _case()
    before = json.dumps(data)
    assert apply_file(data, tmp_path / "absent.json") == {}
    assert json.dumps(data) == before


@pytest.mark.parametrize("field", ["source", "mechanic_id", "provenance", "schema", "coverage"])
def test_receipts_cannot_rewrite_source_identity_or_forge_coverage(field):
    data, receipt, _ = _case()
    receipt["mechanics"]["synthetic"]["set"][field] = "forged"
    preserved = copy.deepcopy(data)
    with pytest.raises(ValueError, match="Unsupported general rider override"):
        apply(data, receipt)
    assert data == preserved


def test_corrupt_output_digest_fails_before_publishing_the_changed_record():
    data, receipt, _ = _case()
    receipt["mechanics"]["synthetic"]["output_sha256"] = "0" * 64
    preserved = copy.deepcopy(data)
    with pytest.raises(ValueError, match="output fingerprint mismatch"):
        apply(data, receipt)
    assert data == preserved


def test_multiple_recipes_keep_receipts_bound_to_original_rider_locations():
    flight = "Gain Fly Speed 30 feet and Hover."
    repeat = "The target repeats the saving throw at the end of each of its turns, ending the effect on a success."
    text = "For the duration, gain:\n" + flight + "\n" + repeat
    original = {"mechanic_id": "synthetic_composite", "name": "Synthetic composite", "coverage": "CORE_WITH_RIDERS",
                "source": {"text_sha256": hashlib.sha256(text.encode()).hexdigest()}, "activation": {"economy": "action"},
                "duration": {"kind": "minutes", "amount": 1}, "riders": [flight, repeat],
                "effects": [{"type": "save", "ability": "WIS",
                             "on_fail": [{"type": "condition", "condition": "Frightened"}]}]}
    result = conversions({"mechanics": {"synthetic_composite": original}}, {"synthetic_composite": text})
    receipts = result["mechanics"]["synthetic_composite"]["matches"]
    assert [(row["pattern"], row["path"], row["rider"]) for row in receipts] == [
        ("fixed_flight_hover", "/riders/0", flight),
        ("repeat_save_end_turn", "/riders/1", repeat),
    ]
    assert original["riders"] == [flight, repeat]


def test_refresh_never_binds_changed_owner_text_to_a_retained_old_source_hash(capsys):
    old_text = "Gain Expertise in Wisdom (Animal Handling)."
    current_text = old_text + "\nOnly while training an animal."
    original = {"mechanic_id": "synthetic_expertise", "coverage": "RIDERS_ONLY", "typing_status": "owner_edit_not_carried",
                "source": {"text_sha256": hashlib.sha256(old_text.encode()).hexdigest()},
                "activation": {"economy": "passive"}, "effects": [], "riders": [old_text]}
    baseline = {"mechanics": {"synthetic_expertise": original}}
    before = copy.deepcopy(baseline)
    assert not conversions(baseline, {"synthetic_expertise": current_text})["mechanics"]
    assert baseline == before
    assert "printed text differs from the typed source" in capsys.readouterr().err
