"""Public synthetic regression controls for the generated CLARITY5 oracle."""
from copy import deepcopy

import pytest

from tools.card_preservation import assert_generated_preserved, fingerprint


def fixture():
    prior = {"schema": "player_text.v1",
             "records": {"servant": "Without orders, Dodge.", "other": "Spend 2 Qi."},
             "evidence": {"form": "The form Dodges."}}
    current = deepcopy(prior)
    current["records"]["servant"] = "Without orders, act on instinct."
    current["evidence"]["form"] = "The form acts on instinct."
    current["evidence"]["new_form"] = "The other form acts on instinct."
    changes = {section: {
        key: {"before": fingerprint(prior[section][key]) if key in prior[section] else None,
              "after": fingerprint(current[section][key])}
        for key in current[section] if prior[section].get(key) != current[section][key]}
        for section in ("records", "evidence")}
    projected = {section: {key: fingerprint(value) for key, value in values.items()}
                 if isinstance(values, dict) else values
                 for section, values in prior.items()}
    return current, {"document_sha256": fingerprint(projected), "reviewed_changes": changes}


def test_only_exact_reviewed_generated_deltas_preserve_the_historical_document():
    current, baseline = fixture()
    assert_generated_preserved(current, baseline)


@pytest.mark.parametrize("mutation", [
    "unrelated_record", "approved_record", "old_dodge_record", "approved_evidence",
    "new_evidence", "extra_evidence", "removed_record", "schema", "new_section",
])
def test_generated_oracle_rejects_changes_outside_exact_instinct_deltas(mutation):
    current, baseline = fixture()
    if mutation == "unrelated_record":
        current["records"]["other"] = "Spend 1 Qi."
    elif mutation == "approved_record":
        current["records"]["servant"] += " Gain flight."
    elif mutation == "old_dodge_record":
        current["records"]["servant"] = "Without orders, Dodge."
    elif mutation == "approved_evidence":
        current["evidence"]["form"] += " Gain flight."
    elif mutation == "new_evidence":
        current["evidence"]["new_form"] += " Gain flight."
    elif mutation == "extra_evidence":
        current["evidence"]["unapproved"] = "Free action."
    elif mutation == "removed_record":
        del current["records"]["other"]
    elif mutation == "schema":
        current["schema"] = "player_text.v2"
    else:
        current["extra"] = {"unapproved": "Free action."}
    with pytest.raises(AssertionError):
        assert_generated_preserved(current, baseline)
