"""CAICLANLOCK1 F8: the supplement content hash ignores version labels and raw file digests.

A pure pack_version relabel rewrites the raw source file bytes, so any digest of those bytes
(the raw_record's source_file_sha256) changes even when no content changed. The content hash
must stay the same. Synthetic projections only, so this runs on public CI.
"""
from catalog.service import supplement_content_hash


def _projection(**overrides):
    record = {
        "record_id": "tianxia.subpath.example",
        "pack_version": "1.0.0",
        "display_name": "Example Subpath",
        "source": {"path": "owner/example.json", "source_hash": "a" * 64},
        "record_hash": "b" * 64,
        "raw_record": {
            "canonical_id": "tianxia.subpath.example",
            "pack_version": "1.0.0",
            "source_provenance": {"source_file_sha256": "c" * 64},
        },
    }
    record.update(overrides)
    return record


def test_raw_file_digest_change_does_not_change_content_hash():
    before = supplement_content_hash("d" * 64, [_projection()])
    relabelled_bytes = _projection(
        raw_record={
            "canonical_id": "tianxia.subpath.example",
            "pack_version": "1.1.0",
            "source_provenance": {"source_file_sha256": "e" * 64},
        },
    )
    assert supplement_content_hash("d" * 64, [relabelled_bytes]) == before


def test_real_content_change_still_changes_content_hash():
    before = supplement_content_hash("d" * 64, [_projection()])
    edited = _projection(display_name="Edited Subpath")
    assert supplement_content_hash("d" * 64, [edited]) != before
