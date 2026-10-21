"""Historical card-authority comparison, used by CLARITY5 and synthetic tests.

The baseline is extracted once from the original CLARITY5 base, not from the
current authority. Only explicitly reviewed non-card field changes are projected
back to that baseline. No repository history or original prose is needed here.
"""
from hashlib import sha256
import json


def fingerprint(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def authority_fingerprints(document):
    return {key: {field: fingerprint(value) for field, value in row.items()
                  if field != "player_card"}
            for key, row in document["records"].items()}


def assert_preserved(document, baseline):
    """Reject every non-card change except exact, separately reviewed deltas."""
    projected = authority_fingerprints(document)
    for key, fields in baseline["reviewed_changes"].items():
        assert key in projected, f"Missing authority record: {key}"
        for field, change in fields.items():
            assert projected[key].get(field) == change["after"], (key, field)
            projected[key][field] = change["before"]
    assert fingerprint(projected) == baseline["records_sha256"], "Historical non-card authority changed"


def assert_generated_preserved(document, baseline):
    """Keep a generated display document historical except exact approved deltas.

    CLARITY5 uses this alongside the source-byte and non-card override audits.
    Every section, entry and schema field is fingerprinted; an absent original
    entry (such as newly reviewed evidence) is removed only after its exact
    approved replacement has been checked.
    """
    projected = {section: {key: fingerprint(value) for key, value in values.items()}
                 if isinstance(values, dict) else values
                 for section, values in document.items()}
    for section, changes in baseline["reviewed_changes"].items():
        for key, change in changes.items():
            assert projected[section].get(key) == change["after"], (section, key)
            if change["before"] is None:
                del projected[section][key]
            else:
                projected[section][key] = change["before"]
    assert fingerprint(projected) == baseline["document_sha256"], "Historical generated authority changed"
