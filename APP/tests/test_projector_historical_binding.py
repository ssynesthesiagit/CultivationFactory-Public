from __future__ import annotations

import pytest

from app.core import FoundryError
from projector.reducer import EffectiveStateReducer
from projector.service import ProjectionService


RECORD_ID = "tianxia.path.qi_cultivation"
PACK_ID = "tianxia.factory.historical"
PACK_VERSION = "1.0.0"
PACK_HASH = "a" * 64
RAW_RECORD_HASH = "b" * 64
CURRENT_RECORD_HASH = "c" * 64
OWNER_PATH_ID = "tianxia.path.qi_cultivation"
OTHER_PATH_ID = "tianxia.path.body_refining"


def _project() -> dict:
    return {
        "content_lock": {
            "packs": [{"pack_id": PACK_ID, "version": PACK_VERSION, "content_hash": PACK_HASH}],
        },
    }


def _record(record_hash: str) -> dict:
    return {
        "record_id": RECORD_ID,
        "record_hash": record_hash,
        "content_binding": {
            "pack_id": PACK_ID,
            "pack_version": PACK_VERSION,
            "pack_hash": PACK_HASH,
        },
    }


def _event_binding(**overrides: str) -> dict:
    return {
        "record_hash": RAW_RECORD_HASH,
        "pack_id": PACK_ID,
        "pack_version": PACK_VERSION,
        "pack_hash": PACK_HASH,
        **overrides,
    }


def _raw_row() -> dict:
    return {
        "record_id": RECORD_ID,
        "pack_id": PACK_ID,
        "pack_version": PACK_VERSION,
        "record_hash": RAW_RECORD_HASH,
    }


def _historical_raw() -> dict:
    raw = _record(RAW_RECORD_HASH)
    raw.update({
        "content_type": "subpath",
        "dependencies": [OWNER_PATH_ID],
        "owning_path_id": None,
        "parent_path_id": None,
        "compatibility": {
            "factory": {
                "stage2_authority": {
                    "authority_complete": True,
                    "allowed_kinds": ["subpath_acquisition"],
                    "parent_path_id": OWNER_PATH_ID,
                },
            },
        },
    })
    return raw


def _historical_current() -> dict:
    current = _record(CURRENT_RECORD_HASH)
    current.update({
        "content_type": "subpath",
        "owning_path_id": OWNER_PATH_ID,
        "parent_path_id": OWNER_PATH_ID,
    })
    return current


def _subpath_event() -> dict:
    return {
        "event_id": "subpath-event-1",
        "subject": {"record_id": RECORD_ID, "content_type": "subpath"},
        "content_binding": _event_binding(),
        "advancement": {
            "kind": "subpath_acquisition",
            "calculation": {"outputs": {"record_id": RECORD_ID}},
        },
        "source_evidence": [{
            "source_id": "source.historical-subpath",
            "source_hash": "e" * 64,
            "source_path": "09_RULES/Indexes/Subpaths/index.json",
        }],
    }


def test_exact_sealed_historical_binding_uses_raw_locked_record() -> None:
    raw = _record(RAW_RECORD_HASH)
    selected = ProjectionService._select_event_bound_record(
        current_record=_record(CURRENT_RECORD_HASH),
        raw_record=raw,
        raw_row=_raw_row(),
        event_bindings=[_event_binding()],
        project=_project(),
        lock_proof_verified=True,
    )

    assert selected is raw
    assert selected["record_hash"] == RAW_RECORD_HASH


@pytest.mark.parametrize("field", ["record_hash", "pack_hash"])
def test_mismatched_event_binding_fails_closed(field: str) -> None:
    raw = _record(RAW_RECORD_HASH)
    current = _record(CURRENT_RECORD_HASH)
    binding = _event_binding(**{field: "d" * 64})
    selected = ProjectionService._select_event_bound_record(
        current_record=current,
        raw_record=raw,
        raw_row=_raw_row(),
        event_bindings=[binding],
        project=_project(),
        lock_proof_verified=True,
    )
    event = {"event_id": "event-1", "content_binding": binding}

    assert selected is current
    with pytest.raises(FoundryError) as exc:
        EffectiveStateReducer._validate_binding(event, selected, _project())
    assert exc.value.code == "PROJECTION_CONTENT_BINDING_MISMATCH"


def test_sealed_historical_subpath_owner_is_normalized_only_after_raw_fallback() -> None:
    raw = _historical_raw()
    current = _historical_current()
    event = _subpath_event()
    selected = ProjectionService._select_event_bound_record(
        current_record=current,
        raw_record=raw,
        raw_row=_raw_row(),
        event_bindings=[event["content_binding"]],
        project=_project(),
        lock_proof_verified=True,
    )

    normalized = ProjectionService._normalize_historical_subpath_owner(
        record=selected,
        current_record=current,
        raw_row=_raw_row(),
        events=[event],
        project=_project(),
        lock_proof_verified=True,
    )

    assert selected is raw
    assert normalized is not raw
    assert normalized["owning_path_id"] == OWNER_PATH_ID
    assert normalized["parent_path_id"] == OWNER_PATH_ID
    assert normalized["record_hash"] == RAW_RECORD_HASH
    assert raw.get("owning_path_id") is None
    assert raw.get("parent_path_id") is None


@pytest.mark.parametrize("mismatch", ["proof", "current", "dependency", "owner"])
def test_historical_subpath_owner_normalization_fails_closed(mismatch: str) -> None:
    raw = _historical_raw()
    current = _historical_current()
    event = _subpath_event()
    proof_verified = True
    if mismatch == "proof":
        proof_verified = False
    elif mismatch == "current":
        current["owning_path_id"] = OTHER_PATH_ID
        current["parent_path_id"] = OTHER_PATH_ID
    elif mismatch == "dependency":
        raw["dependencies"] = []
    else:
        raw["parent_path_id"] = OTHER_PATH_ID

    normalized = ProjectionService._normalize_historical_subpath_owner(
        record=raw,
        current_record=current,
        raw_row=_raw_row(),
        events=[event],
        project=_project(),
        lock_proof_verified=proof_verified,
    )

    assert normalized is raw
