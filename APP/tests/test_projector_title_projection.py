"""Public-safe projector identity-title authority regressions."""

from __future__ import annotations

import pytest

from app.core import FoundryError
from projector.service import _stage_aware_diagnostics
from projector.v3_bridge import _resolve_project_title


PROJECT_ID = "project.projector-title"


def _project(*locks: dict) -> dict:
    return {"project_id": PROJECT_ID, "user_locks": list(locks)}


def _raw_title(title: object) -> dict:
    return {
        "lock_id": "lock.owner.title",
        "field": "character.identity.title",
        "value": title,
        "created_revision": 3,
        "source": "owner",
    }


def _final_title(title: object, *, project_id: str = PROJECT_ID) -> dict:
    return {
        "lock_id": "lock.cg1.character-identity-final_title",
        "field": "character.identity.final_title",
        "value": {
            "value": title,
            "binding": {
                "schema": "TianxiaFoundry.ServerDerivedDescriptiveFields.v1",
                "run_id": "cg1.projector-title",
                "project_id": project_id,
                "request_sha256": "a" * 64,
                "response_sha256": "b" * 64,
                "phase": "server-derived",
            },
        },
        "created_revision": 3,
        "source": "cg1-owner-descriptive:cg1.projector-title:server-derived",
    }


def test_server_derived_title_unwraps_and_is_selected() -> None:
    title, status = _resolve_project_title(_project(_final_title("  Furnace-Bound Alchemist  ")))

    assert title == "Furnace-Bound Alchemist"
    assert status == "SELECTED"


def test_raw_owner_title_is_trimmed_and_owner_locked() -> None:
    title, status = _resolve_project_title(_project(_raw_title("  Owner's Title  ")))

    assert title == "Owner's Title"
    assert status == "OWNER_LOCKED"


def test_matching_raw_and_final_titles_are_one_projection() -> None:
    title, status = _resolve_project_title(
        _project(_raw_title("Furnace-Bound Alchemist"), _final_title(" Furnace-Bound Alchemist "))
    )

    assert (title, status) == ("Furnace-Bound Alchemist", "OWNER_LOCKED")


def test_missing_title_retains_optional_omission_marker() -> None:
    assert _resolve_project_title(_project()) == (None, "OPTIONAL_OMITTED_BY_OWNER")


@pytest.mark.parametrize(
    "locks",
    [
        (_raw_title("   "),),
        (_raw_title(17),),
        ({**_final_title("Title"), "value": "Title"},),
        ({**_final_title("Title"), "source": "caller"},),
        (
            (
                lambda lock: {
                    **lock,
                    "value": {
                        **lock["value"],
                        "binding": {**lock["value"]["binding"], "project_id": "other-project"},
                    },
                }
            )(_final_title("Title")),
        ),
    ],
    ids=["blank-raw", "non-string-raw", "missing-final-binding", "wrong-final-source", "wrong-final-project"],
)
def test_present_malformed_title_lock_fails_closed(locks: tuple[dict]) -> None:
    with pytest.raises(FoundryError) as raised:
        _resolve_project_title(_project(*locks))

    assert raised.value.code == "PROJECTION_CHARACTER_TITLE_INVALID"


def test_raw_and_final_title_conflict_fails_closed() -> None:
    with pytest.raises(FoundryError) as raised:
        _resolve_project_title(_project(_raw_title("Owner Title"), _final_title("Different Title")))

    assert raised.value.code == "PROJECTION_CHARACTER_TITLE_CONFLICT"


def test_title_projection_values_can_feed_both_reducer_destinations() -> None:
    title, status = _resolve_project_title(_project(_final_title("Sealed Title")))
    ledger = {"character": {"title": title, "title_status": status}}
    packets = {"owner_selections": {"title": title}}

    assert ledger["character"]["title"] == packets["owner_selections"]["title"] == "Sealed Title"
    assert ledger["character"]["title_status"] == "SELECTED"


def _diagnostic_reduced() -> object:
    class Reduced:
        typed_choice_snapshot = {}
        event_ids: list[str] = []
        validation_profile = {"required_semantic_nodes": []}
        provenance: dict = {}
        capability_coverage: list = []

    return Reduced()


def _title_diagnostics(title: object, status: object, packet_title: object) -> list[dict]:
    ledger = {
        "readiness": {"active_profile": "ADVANCEMENT_READY", "advancement": "ADVANCEMENT_READY"},
        "character": {"title": title, "title_status": status},
        "later_stage_readiness": {
            stage: {"status": "NOT_ATTEMPTED"}
            for stage in ("character_sheet", "gm_screen", "combat")
        },
    }
    packets = {
        "schema_version": "TianxiaFoundry.RulesSelectionPackets.v2",
        "packets": [],
        "owner_selections": {"title": packet_title},
    }
    return _stage_aware_diagnostics(ledger, packets, _diagnostic_reduced())


def test_stage_diagnostics_accept_authenticated_title_projection() -> None:
    assert _title_diagnostics("Sealed Title", "SELECTED", "Sealed Title") == []
    assert _title_diagnostics("Owner Title", "OWNER_LOCKED", "Owner Title") == []
    assert _title_diagnostics(None, "OPTIONAL_OMITTED_BY_OWNER", None) == []


@pytest.mark.parametrize(
    "title,status,packet_title",
    [
        ("Sealed Title", "OPTIONAL_OMITTED_BY_OWNER", "Sealed Title"),
        ("Sealed Title", "SELECTED", None),
        (None, "OPTIONAL_OMITTED_BY_OWNER", "Sealed Title"),
        ("Sealed Title", "UNRESOLVED", "Sealed Title"),
        ("Sealed Title", [], "Sealed Title"),
    ],
    ids=["wrong-status", "missing-packet-mirror", "unexpected-packet-title", "unknown-status", "malformed-status"],
)
def test_stage_diagnostics_reports_one_title_authority_finding(
    title: object,
    status: object,
    packet_title: object,
) -> None:
    diagnostics = _title_diagnostics(title, status, packet_title)

    assert [finding["code"] for finding in diagnostics] == [
        "PROJECTION_CHARACTER_TITLE_AUTHORITY_INVALID"
    ]
