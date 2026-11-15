"""Byte-for-byte parity with the pre-optimization pack identity algorithm."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from app.core import FoundryError
from catalog.service import _normalize_record
from content_packs import membership
from content_packs.identity import _normalized_record_value, normalized_record_bytes
from contracts.canonical import normalize_core_catalog_record


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _old_normalized_record_bytes(raw):
    """Frozen independent reference, including the removed JSON round trip."""
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Rules Catalog records must be JSON objects.")
    record_id = value.get("record_id")
    if not isinstance(record_id, str) or not record_id:
        raise ValueError("Rules Catalog records require record_id.")
    normalized = json.loads(_canonical(value))
    normalized.pop("record_hash", None)
    binding = normalized.get("content_binding")
    if not isinstance(binding, dict):
        raise ValueError("Rules Catalog records require content_binding.")
    binding["pack_hash"] = "<CONTENT_PACK_HASH>"
    encoded = _canonical(normalized).encode("utf-8")
    return encoded, record_id, hashlib.sha256(encoded).hexdigest()


def _old_membership_rows(records):
    rows, entries, record_set, seen = [], [], [], set()
    for path, record in sorted(records, key=lambda item: (item[1]["record_id"], item[0])):
        rid = record["record_id"]
        if rid in seen:
            raise FoundryError(
                "PACK_MEMBERSHIP_DUPLICATE_RECORD_ID",
                "A sealed pack membership may contain only one exact record per stable ID.",
                details={"record_id": rid},
            )
        seen.add(rid)
        body = json.loads(_canonical(record))
        expected_hash = _digest({key: value for key, value in body.items() if key != "record_hash"})
        if body.get("record_hash") != expected_hash:
            raise FoundryError(
                "PACK_MEMBERSHIP_RECORD_HASH_INVALID",
                "A record cannot enter immutable membership with a mismatched canonical hash.",
                details={"record_id": rid, "stored": body.get("record_hash"), "expected": expected_hash},
            )
        sem = _old_normalized_record_bytes(_canonical(body).encode("utf-8"))[2]
        semantic_bytes, _, _ = _old_normalized_record_bytes(_canonical(body).encode("utf-8"))
        rows.append({
            "record_id": rid, "record_hash": body["record_hash"], "record_path": path,
            "semantic_hash": sem, "record_json": _canonical(body),
        })
        entries.append({
            "path": path, "kind": "rules_catalog_record",
            "semantic_bytes": len(semantic_bytes), "semantic_sha256": sem,
        })
        record_set.append({"record_id": rid, "path": path, "semantic_sha256": sem})
    return rows, _digest(entries), _digest(record_set)


def _record(rid="test.record", **extras):
    value = {
        "record_id": rid, "display_name": "火 – café 🐉",
        "content_binding": {"pack_id": "test.pack", "pack_version": "1.0.0", "pack_hash": "a" * 64},
        "compatibility": {"retained": {
            "content_binding": {"pack_hash": "nested hash must remain"},
            "record_hash": "nested record hash must remain", "values": [None, True, 0, -0.0, 1.25],
        }},
        **extras,
    }
    # Membership deliberately first normalizes arbitrary Python JSON-compatible
    # inputs. Bind the hash to that same normalized body, as the old code does.
    body = json.loads(_canonical(value))
    value["record_hash"] = _digest(body)
    return value


@pytest.fixture
def real_records():
    """Small real source-bound supplemental records, without a catalog rebuild."""
    root = Path(__file__).resolve().parents[1]
    authority = json.loads((root / "catalog/typed_authority/C1A_Canonical_Typed_Authority_Pack_v1.json").read_text())
    records = []
    for rid, entry in authority["records"].items():
        supplied = entry.get("supplemental_record")
        if not supplied:
            continue
        source = entry["source"]
        projection = _normalize_record(
            record_id=rid, content_type=supplied["content_type"], display_name=supplied["display_name"],
            source_path=source["path"], source_hash=source["source_hash"], source_anchor=source["anchor"],
            raw={"compatibility": {"factory": {"stage2_authority": deepcopy(entry["stage2_authority"])}}},
            summary=supplied.get("summary", ""), dependencies=supplied.get("dependencies", []),
            acquisition_channels=entry["stage2_authority"].get("allowed_channels") or ["grant-only"],
        )
        record = normalize_core_catalog_record(projection, pack_hash="a" * 64)
        records.append((f"core-records/{rid}.json", record))
        if len(records) == 3:
            break
    assert len(records) == 3
    return records


def test_real_record_payload_bytes_hashes_membership_and_inputs_match_old_algorithm(real_records):
    before = deepcopy(real_records)
    for _, record in real_records:
        for indent, ascii_only in [(None, False), (2, True)]:
            raw = json.dumps(record, ensure_ascii=ascii_only, indent=indent).encode("utf-8")
            assert normalized_record_bytes(raw) == _old_normalized_record_bytes(raw)
    assert membership.canonical_membership_rows(reversed(real_records)) == _old_membership_rows(real_records)
    assert real_records == before


@pytest.mark.parametrize("extras", [
    {},
    {"nonfinite": [float("nan"), float("inf"), float("-inf")]},
    {"integer_keys": {2: "second", 10: "tenth"}, "tuple_values": (1, {"value": "保留"})},
])
def test_json_spelling_nested_bindings_and_non_json_input_types_keep_exact_identity(extras):
    record = _record(**extras)
    before = _canonical(record)
    raw = before.encode("utf-8")
    current = normalized_record_bytes(raw)
    assert current == _old_normalized_record_bytes(raw)
    normalized = json.loads(current[0])
    assert "record_hash" not in normalized
    assert normalized["content_binding"]["pack_hash"] == "<CONTENT_PACK_HASH>"
    assert normalized["compatibility"]["retained"]["content_binding"]["pack_hash"] == "nested hash must remain"
    assert normalized["compatibility"]["retained"]["record_hash"] == "nested record hash must remain"
    rows = [("records/one.json", record)]
    assert membership.canonical_membership_rows(rows) == _old_membership_rows(rows)
    assert _canonical(record) == before
    if "tuple_values" in extras:
        assert isinstance(record["tuple_values"], tuple)
        assert list(record["integer_keys"]) == [2, 10]


@pytest.mark.parametrize("raw", [
    b"[]", b"null", b"{}", b'{"record_id":""}', b'{"record_id":17}',
    b'{"record_id":"x"}', b'{"record_id":"x","content_binding":null}',
    b'{"record_id":"x","content_binding":[]}', b'{"record_id":', b"\xff",
])
def test_malformed_record_diagnostics_match_old_algorithm(raw):
    with pytest.raises(ValueError) as prior:
        _old_normalized_record_bytes(raw)
    with pytest.raises(type(prior.value)) as current:
        normalized_record_bytes(raw)
    assert str(current.value) == str(prior.value)


@pytest.mark.parametrize("corruption", ["hash", "body", "missing_hash", "duplicate", "binding"])
def test_membership_still_rejects_tampering_and_malformed_records(corruption):
    record = _record()
    rows = [("records/one.json", record)]
    if corruption == "hash":
        record["record_hash"] = "f" * 64
    elif corruption == "body":
        record["compatibility"]["retained"]["values"].append("unapproved")
    elif corruption == "missing_hash":
        record.pop("record_hash")
    elif corruption == "duplicate":
        rows.append(("records/duplicate.json", deepcopy(record)))
    else:
        record["content_binding"] = []
        record["record_hash"] = _digest({key: value for key, value in record.items() if key != "record_hash"})
    before = deepcopy(rows)
    with pytest.raises((FoundryError, ValueError)) as prior:
        _old_membership_rows(rows)
    with pytest.raises(type(prior.value)) as current:
        membership.canonical_membership_rows(rows)
    assert str(current.value) == str(prior.value)
    if isinstance(prior.value, FoundryError):
        assert current.value.code == prior.value.code
        assert current.value.details == prior.value.details
    assert rows == before


def test_direct_membership_normalizes_once_and_preserves_exact_byte_memo(monkeypatch):
    calls = []
    original = membership._normalized_record_value

    def normalize(value):
        calls.append(value)
        return original(value)

    monkeypatch.setattr(membership, "_SEMANTIC_HASH_MEMO", {})
    monkeypatch.setattr(membership, "_normalized_record_value", normalize)
    record = _record()
    rows, _, _ = membership.canonical_membership_rows([("records/one.json", record)])
    assert len(calls) == 1
    assert membership.semantic_hash(record) == rows[0]["semantic_hash"]
    assert len(calls) == 1  # The seal check still benefits from the existing memo.
    changed = deepcopy(record)
    changed["display_name"] += " changed"
    assert membership.semantic_hash(changed) != rows[0]["semantic_hash"]
    assert len(calls) == 1  # The public byte path normalizes its own parsed value.


def test_value_normalization_preserves_aliased_nested_bindings_and_input_identity():
    record = _record()
    # A caller can retain this object in multiple places. Normalizing the
    # top-level binding must neither mutate it nor replace nested occurrences.
    binding = record["content_binding"]
    record["compatibility"]["binding_alias"] = binding
    before = _canonical(record)
    observed = _normalized_record_value(record)
    assert observed == _old_normalized_record_bytes(before.encode("utf-8"))
    assert _canonical(record) == before
    assert record["content_binding"] is binding
    assert record["compatibility"]["binding_alias"] is binding
    normalized = json.loads(observed[0])
    assert normalized["content_binding"]["pack_hash"] == "<CONTENT_PACK_HASH>"
    assert normalized["compatibility"]["binding_alias"]["pack_hash"] == "a" * 64
