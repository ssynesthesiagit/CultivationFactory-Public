"""Run-bound immutable training/forging authority supplements.

The frozen creation-training contract can carry thousands of legal rows; the
provider prompt has a hard byte cap, so the complete authority cannot travel
inline.  Instead a *supplement* is published once per run: an exact deep copy of
the frozen ``creation_training_contract`` and ``explicit_forging_contract``,
addressed by content digest and bound to the run, request and envelope it came
from.

Design rules enforced here:

* the document is an **exact copy** of frozen envelope content - no
  normalization, no dropped fields, no silently skipped rows (a malformed
  contract is a refusal, not a partial success);
* publication is atomic and write-once: the payload is written to a unique
  temporary file, fsynced, then hard-linked into place so an existing digest can
  never be overwritten and a torn write is never visible;
* reads verify the digest, reject symlinks and malformed JSON, and refuse a
  document whose run/request binding does not match the caller;
* nothing is taken from the live catalog, and no provider, database or network
  call is made from this module.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

from app.core import FoundryError, sha256_bytes
from creation_training_authority import (
    CREATION_TRAINING_OUTCOME_SCHEMA,
    CREATION_TRAINING_SOURCE_SCHEMA,
)

SUPPLEMENT_ROOT_NAME = "creation_training_authority_supplements"
SUPPLEMENT_SCHEMA = "TianxiaFoundry.FrozenTrainingAuthoritySupplement.v2"
SUPPLEMENT_FILE_NAME = "training_authority.json"
_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")

# Exact wire templates for the two acquisition fields the supplement authorises.
# ``source``/``outcome`` are NOT provenance entries: they are the construction
# proof produced by ``creation_training_authority.constructed_source`` and
# ``constructed_outcome``.
CONSTRUCTED_SOURCE_TEMPLATE: dict[str, Any] = {
    "schema": CREATION_TRAINING_SOURCE_SCHEMA,
    "mode": "constructed",
    "route": "<row.source_route, copied exactly>",
    "choice_type": "<row.choice_type, copied exactly>",
    "source_record_id": "<row.source_record_id, copied exactly>",
    "source_provenance": "<row.source_provenance, copied exactly>",
    "rule_ids": ["Q06", "RAW-079"],
    "observed_play": False,
    "raw_081_when_new_sphere": "append \"RAW-081\" to rule_ids only when choice_type is new_sphere",
}
CONSTRUCTED_OUTCOME_TEMPLATE: dict[str, Any] = {
    "schema": CREATION_TRAINING_OUTCOME_SCHEMA,
    "result": "learned",
    "mode": "automatic_construction",
    "dice_simulated": False,
    "counts_against_limit": True,
    "slot_cost": 1,
}


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def supplement_root(db: Any) -> Path:
    return Path(os.path.abspath(os.fspath(db.settings.data_dir))) / SUPPLEMENT_ROOT_NAME / "runs"


def _run_key(run_id: str) -> str:
    return sha256_bytes(str(run_id).encode("utf-8"))


def supplement_path(db: Any, run_id: str, digest: str) -> Path:
    if not _DIGEST_PATTERN.fullmatch(str(digest)):
        raise FoundryError(
            "CG1_TRAINING_AUTHORITY_SUPPLEMENT_DIGEST_INVALID",
            "A training authority supplement digest must be a lowercase sha256 hex string.",
            details={"digest": str(digest)[:64]},
            status_code=400,
        )
    return supplement_root(db) / _run_key(run_id) / digest / SUPPLEMENT_FILE_NAME


def build_supplement(
    run_id: str,
    envelope: Mapping[str, Any],
    *,
    request_sha256: str,
    envelope_sha256: str | None = None,
) -> dict[str, Any]:
    """Copy the frozen training/forging authority exactly, with its binding."""

    training = envelope.get("creation_training_contract")
    if not isinstance(training, Mapping):
        raise FoundryError(
            "CG1_TRAINING_AUTHORITY_SUPPLEMENT_SOURCE_INVALID",
            "The frozen envelope carries no creation-training contract.",
            status_code=409,
        )
    records = training.get("records")
    if not isinstance(records, Mapping) or not records:
        raise FoundryError(
            "CG1_TRAINING_AUTHORITY_SUPPLEMENT_SOURCE_INVALID",
            "The frozen creation-training contract carries no records.",
            status_code=409,
        )
    for record_id, row in records.items():
        if not isinstance(record_id, str) or not isinstance(row, Mapping):
            raise FoundryError(
                "CG1_TRAINING_AUTHORITY_SUPPLEMENT_SOURCE_INVALID",
                "Every frozen training record must be an object keyed by record id.",
                details={"record_id": str(record_id)[:120]},
                status_code=409,
            )
    forging = envelope.get("explicit_forging_contract")
    return {
        "schema": SUPPLEMENT_SCHEMA,
        "binding": {
            "run_id": str(run_id),
            "request_sha256": str(request_sha256),
            "envelope_sha256": envelope_sha256 if isinstance(envelope_sha256, str) else envelope.get("envelope_sha256"),
            "creation_training_contract_schema": training.get("schema"),
            "creation_training_contract_version": training.get("version"),
        },
        "creation_training_contract": json.loads(json.dumps(dict(training))),
        "explicit_forging_contract": json.loads(json.dumps(dict(forging))) if isinstance(forging, Mapping) else None,
        "required_forged_design_ids": json.loads(json.dumps(envelope.get("required_forged_design_ids"))),
        "wire_templates": {
            "trained_choice_row": {
                "cl": "<1..target_cl>",
                "slot": "<1..max_choices_per_cl, contiguous from 1>",
                "choice_type": "<row.choice_type>",
                "record_id": "<row record_id>",
                "source": "constructed_source resolved for this row (see constructed_source_template)",
                "outcome": "<constructed_outcome_template, verbatim>",
                "bonus_talent_id": "<required when choice_type is new_sphere: one Talent from the same sphere>",
            },
            "constructed_source_template": CONSTRUCTED_SOURCE_TEMPLATE,
            "constructed_outcome_template": CONSTRUCTED_OUTCOME_TEMPLATE,
            "forged_technique_concepts": "<list of exact concept objects copied from explicit_forging_contract.designs[*].concept, at most one per primary talent>",
        },
    }


def supplement_digest(document: Mapping[str, Any]) -> str:
    return sha256_bytes(_canonical_bytes(dict(document)))


def publish_supplement(
    db: Any,
    run_id: str,
    envelope: Mapping[str, Any],
    *,
    request_sha256: str,
    envelope_sha256: str | None = None,
) -> dict[str, Any]:
    """Publish the supplement atomically and write-once; return its binding."""

    document = build_supplement(run_id, envelope, request_sha256=request_sha256, envelope_sha256=envelope_sha256)
    digest = supplement_digest(document)
    path = supplement_path(db, run_id, digest)
    payload = json.dumps(document, sort_keys=True, indent=1).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        existing = load_supplement(db, run_id, digest, expected_request_sha256=request_sha256)
        return _binding(run_id, digest, len(payload), existing)
    temporary = path.with_name(f".{SUPPLEMENT_FILE_NAME}.{os.getpid()}.{os.urandom(6).hex()}.tmp")
    try:
        with open(temporary, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)  # atomic, fails if the digest already exists
        except FileExistsError:
            pass
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return _binding(run_id, digest, len(payload), document)


def _binding(run_id: str, digest: str, size: int, document: Mapping[str, Any]) -> dict[str, Any]:
    training = document.get("creation_training_contract") or {}
    records = training.get("records") if isinstance(training, Mapping) else {}
    return {
        "schema": SUPPLEMENT_SCHEMA,
        "digest": digest,
        "bytes": size,
        "row_count": len(records) if isinstance(records, Mapping) else 0,
        "complete": True,
        "retrieval": {
            "kind": "run_bound_immutable_file",
            "relative_path": f"{SUPPLEMENT_ROOT_NAME}/runs/{_run_key(run_id)}/{digest}/{SUPPLEMENT_FILE_NAME}",
            "data_dir_relative": True,
            "run_id": str(run_id),
        },
    }


def load_supplement(
    db: Any,
    run_id: str,
    digest: str,
    *,
    expected_request_sha256: str | None = None,
) -> dict[str, Any]:
    """Read a published supplement, verifying address, binding and JSON shape."""

    path = supplement_path(db, run_id, digest)
    if path.is_symlink() or not path.is_file():
        raise FoundryError(
            "CG1_TRAINING_AUTHORITY_SUPPLEMENT_MISSING",
            "The declared training authority supplement is not published for this run.",
            details={"digest": digest},
            status_code=409,
        )
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FoundryError(
            "CG1_TRAINING_AUTHORITY_SUPPLEMENT_CORRUPT",
            "The training authority supplement is not readable JSON.",
            details={"digest": digest, "reason": type(exc).__name__},
            status_code=409,
        ) from exc
    if not isinstance(document, dict) or document.get("schema") != SUPPLEMENT_SCHEMA:
        raise FoundryError(
            "CG1_TRAINING_AUTHORITY_SUPPLEMENT_CORRUPT",
            "The training authority supplement does not declare the supported schema.",
            details={"digest": digest},
            status_code=409,
        )
    if supplement_digest(document) != digest:
        raise FoundryError(
            "CG1_TRAINING_AUTHORITY_SUPPLEMENT_CORRUPT",
            "The run-bound training authority supplement no longer matches its digest.",
            details={"digest": digest},
            status_code=409,
        )
    binding = document.get("binding") if isinstance(document.get("binding"), Mapping) else {}
    if binding.get("run_id") != str(run_id):
        raise FoundryError(
            "CG1_TRAINING_AUTHORITY_SUPPLEMENT_BINDING_MISMATCH",
            "The training authority supplement is bound to a different run.",
            details={"digest": digest},
            status_code=409,
        )
    if expected_request_sha256 is not None and binding.get("request_sha256") != expected_request_sha256:
        raise FoundryError(
            "CG1_TRAINING_AUTHORITY_SUPPLEMENT_BINDING_MISMATCH",
            "The training authority supplement is bound to a different request.",
            details={"digest": digest},
            status_code=409,
        )
    return document
