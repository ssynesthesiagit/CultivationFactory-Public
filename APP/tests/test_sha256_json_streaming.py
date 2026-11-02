from __future__ import annotations

import pytest

from app import core
from app.core import canonical_json, sha256_json, sha256_text


@pytest.mark.parametrize(
    "value",
    [
        {
            "zeta": [
                {
                    "unicode": "修仙 — café — 🐉",
                    "escaped": 'quote: " backslash: \\ newline:\n tab:\t',
                    "number": -0.0,
                },
                {"nested": {"β": [None, True, False, 3.141592653589793]}},
            ],
            "alpha": "keys are sorted",
            "10": "a string key",
        },
        ["scalar list", "雪", {"n": 10**30, "small": 1.25e-7}],
        None,
        True,
        False,
        'scalar — with "quotes" and \\slashes\\',
        0,
        -98765432101234567890,
        1.0,
        -0.0,
        1.25e-7,
    ],
)
def test_sha256_json_matches_canonical_json(value):
    assert sha256_json(value) == sha256_text(canonical_json(value))


def test_sha256_json_encodes_the_whole_document_once(monkeypatch):
    """Lightening plan P1-1 (docs/plans/FACTORY_LIGHTENING_PLAN_2026-09-03.md,
    c6378874): sha256_json encodes the value once with canonical_json and
    digests that one string, instead of feeding thousands of iterencode
    chunks to the hash.  The digest must stay identical."""
    value = {
        "records": [
            {
                "index": index,
                "payload": {
                    "text": f'entry-{index} — escaped "value"',
                    "values": [index, index / 10, index % 3 == 0],
                },
            }
            for index in range(10_000)
        ]
    }
    expected = sha256_text(canonical_json(value))
    calls = []
    original_canonical_json = core.canonical_json

    def counting_canonical_json(*args, **kwargs):
        calls.append(args)
        return original_canonical_json(*args, **kwargs)

    monkeypatch.setattr(core, "canonical_json", counting_canonical_json)

    digest = core.sha256_json(value)

    assert digest == expected
    assert len(calls) == 1 and calls[0][0] is value
