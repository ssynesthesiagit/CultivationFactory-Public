"""Regression (MUTUALKO1RB4 finding 1): catalog tags on a typed record must not make a reviewed rider look stale.

The authority builder attaches the catalog's family tags to each mechanic. The general rider overlay checks its
exact input fingerprint against the typed record, so the tags must stay out of that fingerprint or a reviewed
conversion is skipped on the built authority.
"""
from __future__ import annotations

import copy

from factory_authoring.rider_pattern_overlay import SCHEMA, apply, coverage, digest, typing_digest


def _typed_record() -> dict:
    return {
        "source": {"text_sha256": "c" * 64},
        "effects": [{"type": "damage", "flat": 2}],
        "riders": ["Once per turn.", "Declare the affected creature."],
        "coverage": "CORE_WITH_RIDERS",
    }


def _reviewed_supplement(original: dict) -> dict:
    converted = {**copy.deepcopy(original), "riders": ["Declare the affected creature."]}
    converted["coverage"] = coverage(converted)
    row = {
        "text_sha256": original["source"]["text_sha256"],
        "input_sha256": typing_digest(original),
        "output_sha256": typing_digest(converted),
        "set": {"riders": converted["riders"]},
        "remove": [],
    }
    return {"schema": SCHEMA, "mechanics": {"TAL_TEST_TAGGED": row}}


def test_catalog_tags_do_not_change_the_reviewed_typing_fingerprint():
    original = _typed_record()
    tagged = {**copy.deepcopy(original), "tags": ["Darkness"]}
    assert typing_digest(tagged) == typing_digest(original)


def test_rider_conversion_still_applies_when_the_built_record_carries_tags():
    original = _typed_record()
    supplement = _reviewed_supplement(original)
    data = {"mechanics": {"TAL_TEST_TAGGED": {**copy.deepcopy(original), "tags": ["Darkness"]}}}
    outcomes = apply(data, supplement)
    assert outcomes == {"TAL_TEST_TAGGED": "applied"}
    assert data["mechanics"]["TAL_TEST_TAGGED"]["riders"] == ["Declare the affected creature."]
    assert data["mechanics"]["TAL_TEST_TAGGED"]["tags"] == ["Darkness"]


def test_a_real_typing_change_still_blocks_the_conversion():
    original = _typed_record()
    supplement = _reviewed_supplement(original)
    changed = {**copy.deepcopy(original), "effects": [{"type": "damage", "flat": 3}]}
    data = {"mechanics": {"TAL_TEST_TAGGED": changed}}
    assert apply(data, supplement) == {"TAL_TEST_TAGGED": "changed_typing"}
    assert digest(changed) != typing_digest(original)
