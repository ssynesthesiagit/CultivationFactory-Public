"""End-to-end coverage for the owner-wins wording rule (LOCKWORD, finding 2).

Owner rule 2026-10-10: owner-written name/concept/title always win; the AI may
only ADD whole words to them.  Unlike ``test_locked_wording_whitespace.py``
(which only calls the ``_owner_wins`` helper) these tests exercise both real
boundaries:

* the REAL validator, ``validate_delegated_choice_plan``, on a real sealed
  envelope; and
* the REAL acceptance service, ``accept_descriptive_fields``, against a real
  migrated SQLite database, followed by a real reload (``service.get`` and a
  direct ``accepted_descriptive_fields_json`` read).

The real 2026-10-10 build blocker was a locked concept whose only difference
from the AI/browser copy was whitespace (two spaces after a period).  Every
case asserts the exact persisted text, not a ``repr`` substring.
"""
from __future__ import annotations

import json

import pytest

import character_creation.delegated_choice_authority as delegated_authority
from app.core import canonical_json, sha256_json
from tests.test_cg1_character_creation_modes import make
from tests.test_delegated_title_authority import (
    _isolate_title_validator,
    _sealed_title_validation_case,
)

NAME_OWNER = "Kai"
# The real 2026-10-10 case: two spaces after the first period and a newline.
CONCEPT_OWNER = (
    "This is an evil demonic cultivator.  He comes from the jungle.\n"
    "He wields a blowgun."
)
CONCEPT_COLLAPSED = (
    "This is an evil demonic cultivator. He comes from the jungle. "
    "He wields a blowgun."
)
TITLE_OWNER = "Furnace-Bound Alchemist"


def _rehash(envelope: dict) -> None:
    envelope["envelope_sha256"] = sha256_json({
        key: value for key, value in envelope.items() if key != "envelope_sha256"
    })


def _locked_case(
    *,
    name: str = NAME_OWNER,
    concept: str = CONCEPT_OWNER,
    title: str = TITLE_OWNER,
) -> tuple[dict, dict, dict]:
    """A real sealed envelope whose name, concept and title are owner-locked."""
    project, run, plan = _sealed_title_validation_case(title_lock=title)
    envelope = run["request"]["delegated_choice_envelope"]
    for field, owner_value in (("identity.name", name), ("concept", concept)):
        authority = envelope["delegated_fields"][field]
        authority["state"] = "owner_locked"
        authority["owner_value"] = owner_value
        if "positive_delegation" in authority:
            authority["positive_delegation"] = False
    _rehash(envelope)
    return project, run, plan


def _delegated_control_case() -> tuple[dict, dict, dict]:
    """A real sealed envelope whose name, concept and title are all delegated."""
    project, run, plan = _sealed_title_validation_case(title_lock=None)
    envelope = run["request"]["delegated_choice_envelope"]
    for field in ("identity.name", "concept", "identity.title"):
        authority = envelope["delegated_fields"][field]
        authority["state"] = "delegated"
        authority["owner_value"] = None
        if "positive_delegation" in authority:
            authority["positive_delegation"] = True
    _rehash(envelope)
    return project, run, plan


def _propose(plan: dict, *, name: str, concept: str, title: str) -> None:
    plan["owner_descriptive_fields"] = {
        "identity": {"name": name, "title": title},
        "concept": concept,
    }


def _validator_resolved(monkeypatch, plan, project, run) -> dict:
    _isolate_title_validator(monkeypatch)
    final_plan = delegated_authority.validate_delegated_choice_plan(run, project, plan)
    assert final_plan is not None
    return final_plan["descriptive_fields"]


# (field, owner wording, AI wording, exact resolved wording)
_VALIDATOR_CASES = [
    # (a) whitespace-only difference keeps the owner's exact text
    ("name", "Li  Wei", "Li Wei", "Li  Wei"),
    ("concept", CONCEPT_OWNER, CONCEPT_COLLAPSED, CONCEPT_OWNER),
    ("title", "Owner  Title", "Owner Title", "Owner  Title"),
    # (b) an AI addition containing the owner's whole wording is kept
    ("name", "Kai", "Kai the Rotbloom", "Kai the Rotbloom"),
    (
        "concept",
        CONCEPT_OWNER,
        CONCEPT_COLLAPSED + " His darts carry spores.",
        CONCEPT_COLLAPSED + " His darts carry spores.",
    ),
    ("title", TITLE_OWNER, TITLE_OWNER + " of Ash", TITLE_OWNER + " of Ash"),
    # (c) a replacement (incl. the embedded word Kai -> Kaiden) is replaced
    ("name", "Kai", "Kaiden", "Kai"),
    ("name", "Kai", "Kael", "Kai"),
    (
        "concept",
        CONCEPT_OWNER,
        CONCEPT_COLLAPSED.replace("blowgun", "spear"),
        CONCEPT_OWNER,
    ),
    ("title", TITLE_OWNER, "Different Title", TITLE_OWNER),
]


@pytest.mark.parametrize(
    "field,owner,ai,expected",
    _VALIDATOR_CASES,
    ids=[f"{case[0]}-{case[3][:14]!r}" for case in _VALIDATOR_CASES],
)
def test_validator_owner_lock_matrix(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    owner: str,
    ai: str,
    expected: str,
) -> None:
    owners = {"name": NAME_OWNER, "concept": CONCEPT_OWNER, "title": TITLE_OWNER}
    owners[field] = owner
    project, run, plan = _locked_case(
        name=owners["name"], concept=owners["concept"], title=owners["title"]
    )

    proposals = dict(owners)
    proposals[field] = ai
    _propose(
        plan,
        name=proposals["name"],
        concept=proposals["concept"],
        title=proposals["title"],
    )

    resolved = _validator_resolved(monkeypatch, plan, project, run)

    expected_values = dict(owners)
    expected_values[field] = expected
    assert resolved["identity"]["name"] == expected_values["name"]
    assert resolved["concept"] == expected_values["concept"]
    assert resolved["identity"]["title"] == expected_values["title"]


def test_validator_delegated_control_is_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # (d) a delegated (not locked) field keeps the AI's exact wording.
    project, run, plan = _delegated_control_case()
    _propose(plan, name="AI Name", concept="AI concept", title="AI Title")

    resolved = _validator_resolved(monkeypatch, plan, project, run)

    assert resolved["identity"]["name"] == "AI Name"
    assert resolved["concept"] == "AI concept"
    assert resolved["identity"]["title"] == "AI Title"


def _seed_run(service, db, envelope: dict, proposed: dict) -> str:
    run_id = "cg1.locked-wording"
    request = {"delegated_choice_envelope": envelope, "request_sha256": "r" * 64}
    with db.transaction() as conn:
        conn.execute(
            """INSERT INTO character_creation_runs(
                   run_id, project_id, starting_revision, execution_mode,
                   idempotency_key, request_json, response_json,
                   owner_descriptive_fields_json, status, created_at, updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                run_id,
                "p",
                0,
                "STANDARD_API",
                "locked-wording",
                canonical_json(request),
                "{}",
                canonical_json(proposed),
                "READY_FOR_REVIEW",
                "n",
                "n",
            ),
        )
    return run_id


def _accept_and_reload(
    tmp_path,
    envelope: dict,
    proposed: dict,
    *,
    name: str,
    concept: str,
    title: str,
) -> tuple[dict, dict]:
    service, _provider, db = make(tmp_path)
    run_id = _seed_run(service, db, envelope, proposed)
    service.accept_descriptive_fields(
        run_id, name=name, concept=concept, title=title
    )
    reloaded = service.get(run_id)
    with db.connection() as conn:
        row = conn.execute(
            "SELECT accepted_descriptive_fields_json FROM character_creation_runs WHERE run_id=?",
            (run_id,),
        ).fetchone()
    return reloaded, json.loads(row["accepted_descriptive_fields_json"])


def test_acceptance_whitespace_only_difference_keeps_owner_exact_text(
    tmp_path,
) -> None:
    # (a) The exact persisted concept keeps the owner's two spaces and newline.
    envelope = _locked_case()[1]["request"]["delegated_choice_envelope"]
    reloaded, persisted = _accept_and_reload(
        tmp_path / "ws",
        envelope,
        {
            "identity": {"name": NAME_OWNER, "title": TITLE_OWNER},
            "concept": CONCEPT_COLLAPSED,
        },
        name=NAME_OWNER,
        concept=CONCEPT_COLLAPSED,
        title=TITLE_OWNER,
    )

    assert persisted["concept"] == CONCEPT_OWNER
    assert reloaded["owner_descriptive_fields"]["resolved"]["concept"] == CONCEPT_OWNER
    assert persisted == {
        "identity": {"name": NAME_OWNER, "title": TITLE_OWNER},
        "concept": CONCEPT_OWNER,
    }


def test_acceptance_addition_containing_owner_wording_is_kept(tmp_path) -> None:
    # (b) The AI addition is persisted verbatim for a locked name.
    added = "Kai the Rotbloom"
    envelope = _locked_case()[1]["request"]["delegated_choice_envelope"]
    reloaded, persisted = _accept_and_reload(
        tmp_path / "addition",
        envelope,
        {
            "identity": {"name": added, "title": TITLE_OWNER},
            "concept": CONCEPT_OWNER,
        },
        name=added,
        concept=CONCEPT_OWNER,
        title=TITLE_OWNER,
    )

    assert persisted["identity"]["name"] == added
    assert reloaded["owner_descriptive_fields"]["resolved"]["identity"]["name"] == added
    assert persisted["concept"] == CONCEPT_OWNER
    assert persisted["identity"]["title"] == TITLE_OWNER


def test_acceptance_embedded_replacement_is_replaced_by_owner_text(
    tmp_path,
) -> None:
    # (c) 'Kai' -> 'Kaiden' is a replacement, so the owner's exact name is saved.
    envelope = _locked_case()[1]["request"]["delegated_choice_envelope"]
    reloaded, persisted = _accept_and_reload(
        tmp_path / "replacement",
        envelope,
        {
            "identity": {"name": "Kaiden", "title": TITLE_OWNER},
            "concept": CONCEPT_OWNER,
        },
        name="Kaiden",
        concept=CONCEPT_OWNER,
        title=TITLE_OWNER,
    )

    assert persisted["identity"]["name"] == NAME_OWNER
    assert reloaded["owner_descriptive_fields"]["resolved"]["identity"]["name"] == NAME_OWNER
    assert persisted == {
        "identity": {"name": NAME_OWNER, "title": TITLE_OWNER},
        "concept": CONCEPT_OWNER,
    }


def test_acceptance_delegated_control_is_untouched(tmp_path) -> None:
    # (d) A delegated field is not overwritten by the lock policy.
    envelope = _delegated_control_case()[1]["request"]["delegated_choice_envelope"]
    reloaded, persisted = _accept_and_reload(
        tmp_path / "control",
        envelope,
        {
            "identity": {"name": "AI Name", "title": "AI Title"},
            "concept": "AI concept",
        },
        name="AI Name",
        concept="AI concept",
        title="AI Title",
    )

    assert persisted == {
        "identity": {"name": "AI Name", "title": "AI Title"},
        "concept": "AI concept",
    }
    resolved = reloaded["owner_descriptive_fields"]["resolved"]
    assert resolved["identity"]["name"] == "AI Name"
    assert resolved["concept"] == "AI concept"
    assert resolved["identity"]["title"] == "AI Title"
