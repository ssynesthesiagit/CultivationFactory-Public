"""Relevant-only: reviewed record IDs, not writer filenames, own execution."""
import copy
import json

import pytest

from tools import typed_mechanics_helpers as reviews


@pytest.fixture
def review_inputs(tmp_path, monkeypatch):
    base = tmp_path / "reviewed_final.json"
    shards = tmp_path / "reviewed_final.d"
    shards.mkdir()
    monkeypatch.setattr(reviews, "REVIEWED_FINAL", base)
    return base, shards


def write_reviews(path, mechanics):
    path.write_text(json.dumps({"mechanics": mechanics}), encoding="utf-8")


@pytest.mark.parametrize("in_base", [False, True])
@pytest.mark.parametrize("identical", [False, True])
def test_duplicate_record_ownership_is_an_error(review_inputs, in_base, identical):
    base, shards = review_inputs
    first = base if in_base else shards / "a_family.json"
    second = shards / "z_writer.json"
    row = {"text_sha256": "a" * 64, "effects": [], "riders": []}
    write_reviews(first, {"record:A": row})
    write_reviews(second, {"record:A": row if identical else {**row, "riders": ["Different review."]}})

    with pytest.raises(ValueError) as raised:
        reviews.load_finals()
    message = str(raised.value)
    assert "record:A" in message
    assert first.name in message and second.name in message


@pytest.mark.parametrize("in_base", [False, True])
@pytest.mark.parametrize("mechanics, key", [
    ('"record:A": {}, "record:A": {}', "record:A"),
    ('"record:A": {"effects": [], "effects": [{"type": "damage"}]}', "effects"),
])
def test_duplicate_json_keys_cannot_hide_a_review(review_inputs, in_base, mechanics, key):
    base, shards = review_inputs
    path = base if in_base else shards / "record_a.json"
    path.write_text('{"mechanics": {' + mechanics + '}}', encoding="utf-8")

    with pytest.raises(ValueError) as raised:
        reviews.load_finals()
    assert key in str(raised.value) and path.name in str(raised.value)


def test_record_owner_edits_and_renames_preserve_unrelated_reviews(review_inputs):
    base, shards = review_inputs
    assert reviews.load_finals() == {}
    legacy = {"text_sha256": "a" * 64, "riders": ["Legacy review."]}
    owned = {"text_sha256": "b" * 64, "options": [
        {"label": "First", "effects": [{"type": "damage", "flat": 2}]},
        {"label": "Second", "effects": [{"type": "healing", "flat": 3}]},
    ]}
    other = {"text_sha256": "c" * 64, "effects": [], "riders": []}
    write_reviews(base, {"record:A": legacy})
    owner = shards / "record:B.json"
    write_reviews(owner, {"record:B": owned})
    write_reviews(shards / "unrelated_family.json", {"record:C": other})
    write_reviews(shards / "empty_family.json", {})

    before = reviews.load_finals()
    assert before == {"record:A": legacy, "record:B": owned, "record:C": other}
    renamed = shards / "zz_record_b.json"
    owner.rename(renamed)
    assert reviews.load_finals() == before
    changed = copy.deepcopy(owned)
    changed["options"][0]["effects"][0]["flat"] = 5
    write_reviews(renamed, {"record:B": changed})
    after = reviews.load_finals()
    assert after == {**before, "record:B": changed}
    assert {key for key in before if before[key] != after[key]} == {"record:B"}
