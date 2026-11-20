"""Guarded same-run agent correction for an incomplete acquisition response.

A ``STANDARD_API`` run whose provider answer was refused *only* because the
frozen ``acquisition_intent`` was missing the validator-required
``trained_choices`` / ``forged_technique_concepts`` can be recovered without
touching the consumed request, the frozen envelope, or the original answer:

* a **new authentic mailbox request** is opened for the same run, linked
  append-only to the original request, envelope digest, retained response digest,
  prior attempt and project revision;
* the corrected answer must add **exactly** those two fields and change nothing
  else - any other semantic difference is refused;
* the original consumed row and the original response bytes stay immutable;
* initiation is idempotent per revision, and the link document records the
  attempt history so a re-drive cannot double-consume the correction budget.

Nothing here whitelists the ``agent`` provider for local correction, relaxes
manual replacement, or changes non-agent behavior.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from app.core import FoundryError, canonical_json, sha256_bytes

CORRECTION_ROOT_NAME = "agent_acquisition_corrections"
CORRECTION_LINK_NAME = "link.json"
CORRECTION_SCHEMA = "TianxiaFoundry.AgentAcquisitionCorrection.v1"
REQUIRED_ADDITIONS = ("trained_choices", "forged_technique_concepts")
_TRIGGERING_DIAGNOSTIC = "CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID"
_TERMINAL_STATUSES = {
    "CLEAN_AND_FINALIZED",
    "CANCELLED",
    "SUPERSEDED",
    "FAILED",
    "EXPIRED",
    "REJECTED",
}


def _correction_root(db: Any, run_id: str) -> Path:
    return (
        Path(os.path.abspath(os.fspath(db.settings.data_dir)))
        / CORRECTION_ROOT_NAME
        / "runs"
        / sha256_bytes(str(run_id).encode("utf-8"))
    )


def link_path(db: Any, run_id: str) -> Path:
    return _correction_root(db, run_id) / CORRECTION_LINK_NAME


def load_link(db: Any, run_id: str) -> dict[str, Any] | None:
    """Read the append-only correction link, verifying its own content address."""

    path = link_path(db, run_id)
    if path.is_symlink():
        raise FoundryError(
            "CG1_AGENT_CORRECTION_LINK_INVALID",
            "The correction link must be a regular file, not a symlink.",
            status_code=409,
        )
    if not path.is_file():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FoundryError(
            "CG1_AGENT_CORRECTION_LINK_INVALID",
            "The correction link is not readable JSON.",
            details={"reason": type(exc).__name__},
            status_code=409,
        ) from exc
    if not isinstance(document, dict) or document.get("schema") != CORRECTION_SCHEMA:
        raise FoundryError(
            "CG1_AGENT_CORRECTION_LINK_INVALID",
            "The correction link does not declare the supported schema.",
            status_code=409,
        )
    recorded = document.get("link_sha256")
    if isinstance(recorded, str) and recorded:
        body = {key: value for key, value in document.items() if key != "link_sha256"}
        if sha256_bytes(canonical_json(body).encode("utf-8")) != recorded:
            raise FoundryError(
                "CG1_AGENT_CORRECTION_LINK_INVALID",
                "The correction link no longer matches its recorded digest.",
                status_code=409,
            )
    return document


class correction_lock:
    """Process-wide advisory lock so initiation/continuation serialise.

    Concurrent callers may both observe an ANSWERED correction; the lock (plus
    the completed marker re-read under it) guarantees exactly one applies it.
    """

    def __init__(self, db: Any, run_id: str) -> None:
        self.path = _correction_root(db, run_id) / "correction.lock"
        self._handle: Any = None

    def __enter__(self) -> "correction_lock":
        import fcntl

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = open(self.path, "a+")
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc: Any) -> None:
        import fcntl

        if self._handle is not None:
            try:
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            finally:
                self._handle.close()
                self._handle = None


def _write_link(db: Any, run_id: str, document: Mapping[str, Any]) -> None:
    path = link_path(db, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {key: value for key, value in dict(document).items() if key != "link_sha256"}
    stamped = {**body, "link_sha256": sha256_bytes(canonical_json(body).encode("utf-8"))}
    payload = json.dumps(stamped, sort_keys=True, indent=1).encode("utf-8")
    temporary = path.with_name(f".{CORRECTION_LINK_NAME}.{os.getpid()}.{os.urandom(4).hex()}.tmp")
    try:
        with open(temporary, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _acquisition(plan: Mapping[str, Any]) -> Mapping[str, Any]:
    value = plan.get("acquisition_intent")
    return value if isinstance(value, Mapping) else {}


def correction_attempt_ids(link: Mapping[str, Any]) -> set[str]:
    """Every ledger attempt id this correction itself produced or is pending on."""

    ids: set[str] = set()
    for key in ("pending_attempt_id", "accepted_attempt_id", "completed_attempt_id"):
        value = link.get(key)
        if isinstance(value, str) and value:
            ids.add(value)
    for row in link.get("attempts") or []:
        if isinstance(row, Mapping):
            value = row.get("attempt_id")
            if isinstance(value, str) and value:
                ids.add(value)
    return ids


def is_correction_attempt(link: Mapping[str, Any], attempt_id: str | None) -> bool:
    return isinstance(attempt_id, str) and attempt_id in correction_attempt_ids(link)


def missing_required_additions(original: Mapping[str, Any]) -> list[str]:
    """The exact required additions this retained answer is missing, in order."""

    acquisition = _acquisition(original)
    return [key for key in REQUIRED_ADDITIONS if key not in acquisition]


def correction_adds_only_missing_fields(
    original: Mapping[str, Any],
    corrected: Mapping[str, Any],
    *,
    permitted: tuple[str, ...] | None = None,
) -> tuple[bool, str | None]:
    """True when ``corrected`` equals ``original`` plus only the permitted keys."""

    if not isinstance(original, Mapping) or not isinstance(corrected, Mapping):
        return False, "response_not_object"
    if set(corrected) != set(original):
        return False, "top_level_keys_changed"
    for key in set(original) - {"acquisition_intent"}:
        if canonical_json(original.get(key)) != canonical_json(corrected.get(key)):
            return False, f"changed:{key}"
    before = _acquisition(original)
    after = _acquisition(corrected)
    required = set(missing_required_additions(original) if permitted is None else permitted)
    added = set(after) - set(before)
    removed = set(before) - set(after)
    if removed:
        return False, "removed:" + ",".join(sorted(removed))
    # Exactly the actually-missing required keys, no more and no fewer.
    if added != required:
        extra = sorted(added - required)
        absent = sorted(required - added)
        if extra:
            return False, "unpermitted:" + ",".join(extra)
        return False, "missing:" + ",".join(absent)
    for key in set(before) & set(after):
        if canonical_json(before.get(key)) != canonical_json(after.get(key)):
            return False, f"changed:acquisition_intent.{key}"
    for key in added:
        if not isinstance(after.get(key), list):
            return False, f"not_a_list:{key}"
    return True, None


def _diagnostic(run: Mapping[str, Any]) -> Mapping[str, Any]:
    validation = run.get("validation")
    validation = validation if isinstance(validation, Mapping) else {}
    diagnostic = validation.get("last_submission_error")
    return diagnostic if isinstance(diagnostic, Mapping) else {}


def already_applied(
    run: Mapping[str, Any],
    link: Mapping[str, Any],
    *,
    latest_attempt_id: str | None,
    attempt_request_sha256: str | None,
    attempt_response_sha256: str | None = None,
) -> bool:
    """True when a prior continuation already applied this correction.

    A crash after ``_apply_response`` can leave the link incomplete.  The run's
    own attempt evidence identifies that case: a newer attempt whose request
    hash is the correction request's hash, distinct from the original attempt.
    """

    # A completion marker alone is not acceptance: it must be backed by the
    # linked correction attempt in the run's ledger.
    if isinstance(link.get("completed_response_sha256"), str) and link["completed_response_sha256"]:
        completed_attempt = link.get("completed_attempt_id") or link.get("accepted_attempt_id")
        if isinstance(completed_attempt, str) and completed_attempt:
            return latest_attempt_id == completed_attempt
    if latest_attempt_id is None or latest_attempt_id == link.get("original_attempt_id"):
        return False
    if isinstance(link.get("pending_response_sha256"), str) and link["pending_response_sha256"]:
        # The pending marker is written before the apply.  Matching bytes alone
        # are NOT proof of success: a rejected attempt is also a ledger row with
        # those bytes.  The run must additionally show a reviewable outcome and
        # the ledger attempt must be the pending one, never the original.
        if attempt_response_sha256 != link["pending_response_sha256"]:
            return False
        pending_attempt_id = link.get("pending_attempt_id")
        if isinstance(pending_attempt_id, str) and pending_attempt_id:
            if latest_attempt_id != pending_attempt_id:
                return False
        reviewable = run.get("status") in {"READY_FOR_REVIEW", "NEEDS_REVIEW"}
        quality = run.get("quality") if isinstance(run.get("quality"), Mapping) else {}
        accepted = reviewable and str(quality.get("status") or "").upper() == "CLEAN"
        return accepted
    # Request-hash equality alone is not acceptance either: require the ledger
    # row to be a correction attempt that the run records as reviewable-clean.
    correction_request_sha256 = link.get("correction_request_sha256")
    if not isinstance(correction_request_sha256, str) or not correction_request_sha256:
        return False
    if attempt_request_sha256 != correction_request_sha256:
        return False
    if not is_correction_attempt(link, latest_attempt_id):
        return False
    reviewable = run.get("status") in {"READY_FOR_REVIEW", "NEEDS_REVIEW"}
    quality = run.get("quality") if isinstance(run.get("quality"), Mapping) else {}
    return reviewable and str(quality.get("status") or "").upper() == "CLEAN"


def correction_eligibility(run: Mapping[str, Any]) -> tuple[bool, str | None]:
    """Return whether this run may open a guarded same-run correction."""

    status = run.get("status")
    if status in _TERMINAL_STATUSES:
        return False, "run_terminal"
    if status != "NEEDS_REVIEW":
        return False, "run_not_in_review"
    if run.get("execution_mode") != "STANDARD_API":
        return False, "execution_mode_not_standard_api"
    request = run.get("request") if isinstance(run.get("request"), Mapping) else {}
    envelope = request.get("delegated_choice_envelope")
    if not isinstance(envelope, Mapping):
        return False, "no_frozen_envelope"
    if not isinstance(envelope.get("creation_training_contract"), Mapping) and not isinstance(
        envelope.get("explicit_forging_contract"), Mapping
    ):
        return False, "no_training_or_forging_authority"
    diagnostic = _diagnostic(run)
    if diagnostic.get("code") != _TRIGGERING_DIAGNOSTIC:
        return False, "diagnostic_not_acquisition_contract"
    response = run.get("response") if isinstance(run.get("response"), Mapping) else {}
    text = response.get("exact_response_text")
    if not isinstance(text, str) or not text.strip():
        return False, "no_retained_response"
    try:
        plan = json.loads(text)
    except (TypeError, ValueError):
        return False, "retained_response_not_json"
    if not isinstance(plan, Mapping):
        return False, "retained_response_not_object"
    acquisition = _acquisition(plan)
    missing = [key for key in REQUIRED_ADDITIONS if key not in acquisition]
    if not missing:
        return False, "nothing_missing"
    return True, ",".join(missing)


def correction_request_key(run_id: str, *, project_revision: int, original_request_sha256: str) -> str:
    """A stable, revision-bound key so a repeated initiation cannot double-prompt."""

    return "acqcorr." + sha256_bytes(
        canonical_json({
            "run_id": run_id,
            "project_revision": project_revision,
            "original_request_sha256": original_request_sha256,
            "additions": list(REQUIRED_ADDITIONS),
        }).encode("utf-8")
    )


def build_correction_prompt(
    base_prompt: str,
    *,
    original_plan: Mapping[str, Any],
    missing: list[str],
    link: Mapping[str, Any],
) -> str:
    """Add the correction contract and the exact original answer to the wire.

    The correction prompt is the normal creation prompt plus an explicit
    correction_contract block: the retained original answer, the exact missing
    keys, and the instruction that nothing else may change.  It is serialized in
    the bridge's ordinary request-payload shape so export and answer validation
    keep working unchanged.
    """

    payload = json.loads(base_prompt) if isinstance(base_prompt, str) else None
    if not isinstance(payload, dict):
        raise FoundryError(
            "CG1_AGENT_CORRECTION_PROMPT_INVALID",
            "The correction prompt must be one JSON object.",
            status_code=409,
        )
    payload["correction_contract"] = {
        "schema": "TianxiaFoundry.AgentAcquisitionCorrectionRequest.v1",
        "kind": "add_missing_acquisition_fields",
        "run_id": link.get("run_id"),
        "project_revision": link.get("project_revision"),
        "original_request_sha256": link.get("original_request_sha256"),
        "original_response_sha256": link.get("original_response_sha256"),
        "original_attempt_id": link.get("original_attempt_id"),
        "missing_required_keys": list(missing),
        "permitted_additions": list(missing),
        "retained_original_answer": json.loads(json.dumps(dict(original_plan))),
        "instructions": [
            f"Return the retained_original_answer object unchanged, adding exactly these acquisition_intent keys: {', '.join(missing)}.",
            "Every other key and value must be byte-identical to the retained original answer, including schema, request_sha256, selection_intent, bounded_choices and owner_descriptive_fields.",
            "Do not remove, rename or reorder existing acquisition_intent entries, and do not add any other acquisition key.",
            "Read the frozen training/forging authority through training_authority_supplement.delivery before choosing trained_choices rows.",
        ],
    }
    return canonical_json(payload)


def initiate_correction(
    db: Any,
    bridge: Any,
    run: Mapping[str, Any],
    *,
    prompt_text: str,
    schema_name: str,
    max_output_tokens: int,
    provider_id: str,
    project_id: str,
    ledger_original: Mapping[str, Any] | None = None,
    declared_supplement: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Open (or return) the guarded correction mailbox request for this revision.

    The caller supplies the already-built, supplement-declaring correction
    prompt; this function owns the guards, the append-only link and the
    idempotency that prevents duplicate requests or attempts.
    """

    eligible, reason = correction_eligibility(run)
    if not eligible:
        raise FoundryError(
            "CG1_AGENT_CORRECTION_UNAVAILABLE",
            "This run cannot open a guarded same-run acquisition correction.",
            details={"reason": reason},
            status_code=409,
        )
    run_id = str(run.get("run_id"))
    request = run.get("request") if isinstance(run.get("request"), Mapping) else {}
    original_request_sha256 = request.get("request_sha256")
    if not isinstance(original_request_sha256, str) or not original_request_sha256:
        raise FoundryError(
            "CG1_AGENT_CORRECTION_UNAVAILABLE",
            "The run carries no frozen request digest to link against.",
            status_code=409,
        )
    revision = run.get("starting_revision")
    revision = revision if type(revision) is int else 0
    response = run.get("response") if isinstance(run.get("response"), Mapping) else {}
    original_response_text = response.get("exact_response_text")
    original_response_sha256 = sha256_bytes(str(original_response_text).encode("utf-8"))
    if not isinstance(original_response_text, str) or not str(original_response_text).strip():
        # The run projection may already be empty; the append-only ledger is the
        # authoritative record of the original answer in that case.
        ledger = ledger_original or {}
        original_response_sha256 = ledger.get("response_sha256") or original_response_sha256
    attempt_id = None
    validation = run.get("validation") if isinstance(run.get("validation"), Mapping) else {}
    response_state = validation.get("response_state")
    if isinstance(response_state, Mapping):
        attempt_id = response_state.get("attempt_id") if isinstance(response_state.get("attempt_id"), str) else None

    key = correction_request_key(run_id, project_revision=revision, original_request_sha256=original_request_sha256)
    existing = load_link(db, run_id)
    if existing is not None:
        if existing.get("project_revision") != revision or existing.get("original_request_sha256") != original_request_sha256:
            raise FoundryError(
                "CG1_AGENT_CORRECTION_STALE",
                "The recorded correction belongs to a different revision or request.",
                details={"planned_revision": existing.get("project_revision"), "actual_revision": revision},
                status_code=409,
            )
        if existing.get("original_response_sha256") != original_response_sha256:
            raise FoundryError(
                "CG1_AGENT_CORRECTION_ORIGINAL_CHANGED",
                "The retained original response no longer matches the recorded correction link.",
                status_code=409,
            )
        request_id = existing.get("correction_request_id")
        if isinstance(request_id, str) and request_id:
            document = bridge.get(request_id)
            attempts = list(existing.get("attempts") or [])
            latest = next(
                (row for row in reversed(attempts) if isinstance(row, Mapping) and row.get("request_id") == request_id),
                None,
            )
            if document.get("state") in {"ANSWERED", "CONSUMED"} and (
                latest is None or latest.get("state") != document.get("state")
            ):
                attempts.append({
                    "request_id": request_id,
                    "state": document.get("state"),
                    "recorded_at": __import__("app.core", fromlist=["utcnow"]).utcnow(),
                })
                existing["attempts"] = attempts
                _write_link(db, run_id, existing)
            return {"link": existing, "request": document, "created": False}

    request_payload = json.loads(prompt_text) if isinstance(prompt_text, str) else None
    if not isinstance(request_payload, dict):
        raise FoundryError(
            "CG1_AGENT_CORRECTION_PROMPT_INVALID",
            "The correction prompt must be one JSON object.",
            status_code=409,
        )
    # Match the bridge's normal provider request contract so the mailbox export
    # and the answer validator see the same wire shape the original request used.
    request_payload = {
        "model": request_payload.get("model") or "agent-authored",
        "messages": [
            {"role": "system", "content": "You are a bounded character-creation provider adapter. Return exactly one JSON object matching the contract in the user prompt."},
            {"role": "user", "content": canonical_json(request_payload)},
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": int(max_output_tokens),
        "stream": False,
    }
    document = bridge.enqueue(
        request_payload=request_payload,
        purpose=str(request.get("purpose") or "character_creation_complete_plan"),
        schema_name=schema_name,
        run_id=run_id,
        provider_id=provider_id,
        project_id=project_id,
        prompt_id=str(request.get("prompt_id") or "character_creation_complete_plan"),
        idempotency_key=key,
    )
    link = {
        "schema": CORRECTION_SCHEMA,
        "run_id": run_id,
        "project_revision": revision,
        "execution_mode": "STANDARD_API",
        "provider_id": provider_id,
        "original_request_sha256": original_request_sha256,
        "original_response_sha256": original_response_sha256,
        "original_attempt_id": attempt_id,
        "original_ledger_response_sha256": (ledger_original or {}).get("response_sha256"),
        "declared_supplement": declared_supplement,
        "envelope_sha256": (request.get("delegated_choice_envelope") or {}).get("envelope_sha256")
        if isinstance(request.get("delegated_choice_envelope"), Mapping) else None,
        "permitted_additions": list(REQUIRED_ADDITIONS),
        "correction_idempotency_key": key,
        "correction_request_id": document.get("request_id"),
        "correction_request_sha256": document.get("request_sha256"),
        "attempts": [{"request_id": document.get("request_id"), "state": document.get("state")}],
    }
    _write_link(db, run_id, link)
    return {"link": link, "request": document, "created": True}
