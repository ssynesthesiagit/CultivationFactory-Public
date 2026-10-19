"""Composite Playbook proposals are a request-scoped display overlay on the sheet.

The authored ``Composite_Playbook.json`` only carries a locator row.  The sheet
proposes validated playbooks from the sealed snapshot's own printed action
records (plus the 5.5e baseline) and appends them after the archive rows, with
an honest ``proposals`` note when nothing can be proposed.  The sealed snapshot
is never rewritten and nothing is kept on the shared service instance.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import tests.test_character_sheet_complete_character as sheet_fixture
from character_sheet.service import CharacterSheetService

REFERENCE = sheet_fixture.PROJECT_ID
LEDGER = "Character_Master_Ledger.json"
PRIMARY = "RES_TEST_PRIMARY"


def _talent(record_id: str, name: str, action_type: str, cost: str = "None") -> dict:
    return {"record_id": record_id, "display_name": name, "section": "talents",
            "full_description": f"#### {name}\nAction Type: {action_type}\nCost: {cost}\nA synthetic test rule."}


def _sealed_snapshot(*, talents: list[dict]) -> dict:
    return {
        "sheet_id": "sheet.composite-overlay",
        "identity": {"display_name": "Overlay Fixture"},
        "readiness": {"advancement": "ADVANCEMENT_READY", "character_sheet": "CHARACTER_SHEET_READY"},
        "selected_record_sections": {"talents": talents, "insights": []},
        "ability_scores_and_statistics": {"primary_resource": {"definitions": [
            {"resource_id": PRIMARY, "name": "Test Points", "current": 8, "max": 8}]}},
    }


def _service_with_snapshot(tmp_path: Path, snapshot: dict) -> CharacterSheetService:
    service = sheet_fixture._service(tmp_path)
    service.db.migrate()
    sheet_fixture._sheet_stubs(service)
    ledger = {"character": {}, "readiness": {"advancement": "ADVANCEMENT_READY"}}
    service._compiled_artifacts = lambda _project_id: (
        {LEDGER: ledger},
        {"status": "READY", "projection_id": sheet_fixture.PROJECTION_ID, "eligible_for_command5": False},
    )
    service._cached_snapshot = lambda project_id, **_kwargs: (snapshot, {"sheet_id": "sheet.composite-overlay"})
    sheet_fixture._write_candidate(service.db.settings.data_dir)
    return service


def test_sheet_appends_validated_proposals_after_the_archive_rows(tmp_path: Path) -> None:
    snapshot = _sealed_snapshot(talents=[
        _talent("TAL_TEST_STRIKE", "Test Strike", "Action", "1 CP"),
        _talent("TAL_TEST_STEP", "Test Step", "Bonus Action"),
        _talent("TAL_TEST_GUARD", "Test Guard", "Reaction"),
    ])
    sealed = deepcopy(snapshot)
    service = _service_with_snapshot(tmp_path, snapshot)

    result = service.sheet(REFERENCE)

    data = result["complete_character"]["surfaces"]["composite_playbooks"]["data"]
    rows = data["composites"]
    assert rows[0]["playbook_id"] == "playbook.test"  # the archive's row stays first and untouched
    proposed = [row for row in rows[1:] if row.get("capability_status") == "SERVER_VALIDATED_PROPOSAL"]
    assert proposed and len(proposed) == data["proposals"]["proposed_count"] == len(rows) - 1
    assert data["proposals"]["status"] == "proposed"
    assert data["proposals"]["generator"]["kind"] == "deterministic_template_proposer"
    assert data["proposals"]["registry"]["own_actions"] == 3
    assert data["execution_authority"] is False
    ids = [row["composite_id"] for row in proposed]
    assert len(ids) == len(set(ids)) and all(i.startswith("gm.playbook.proposed.") for i in ids)
    for row in proposed:
        assert row["validation"]["ok"] is True and len(row["sequence"]) >= 2
        assert all({"step", "action_id", "round_offset", "economy"} <= set(step) for step in row["sequence"])
    assert any("TAL_TEST_STRIKE" in [step["action_id"] for step in row["sequence"]] for row in proposed)
    assert snapshot == sealed  # the sealed snapshot is never rewritten
    assert not hasattr(service, "_composite_proposals")


def test_sheet_reports_an_honest_empty_state_when_nothing_can_be_proposed(tmp_path: Path) -> None:
    # No printed action records: the 5.5e baseline alone must not become a playbook (min_own_steps).
    service = _service_with_snapshot(tmp_path, _sealed_snapshot(talents=[]))

    data = service.sheet(REFERENCE)["complete_character"]["surfaces"]["composite_playbooks"]["data"]

    assert [row["playbook_id"] for row in data["composites"]] == ["playbook.test"]
    assert data["proposals"]["status"] == "none_proposed" and data["proposals"]["proposed_count"] == 0
    skipped = data["proposals"]["generator"]["skipped_templates"]
    assert len(skipped) == 5 and any("min_own_steps" in item["reason"] for item in skipped)
    assert any(item["template_id"] == "forged_signature" and "no eligible action" in item["reason"] for item in skipped)
    assert data["proposals"]["registry"]["own_actions"] == 0


def test_sheet_reports_unavailable_when_the_proposer_fails(tmp_path: Path, monkeypatch) -> None:
    import factory_authoring.composite_playbook as package

    def boom(_snapshot, **_kwargs):
        raise RuntimeError("synthetic proposer failure")

    monkeypatch.setattr(package, "propose_from_sheet", boom)
    service = _service_with_snapshot(tmp_path, _sealed_snapshot(talents=[]))

    data = service.sheet(REFERENCE)["complete_character"]["surfaces"]["composite_playbooks"]["data"]

    assert [row["playbook_id"] for row in data["composites"]] == ["playbook.test"]
    assert data["proposals"]["status"] == "unavailable" and data["proposals"]["proposed_count"] == 0
    assert "synthetic proposer failure" in data["proposals"]["reason"]


def test_authored_dao_and_i_ching_themes_lead_the_hooks(tmp_path: Path, monkeypatch) -> None:
    original = sheet_fixture._surface_document

    def with_authored_themes(member: str, *, display_name: str) -> dict:
        if member == "Dao_IChing_Combat_Profile.json":
            return {"schema_version": "test-dao", "classification": "GM_GUIDANCE_ONLY", "execution_authority": False,
                    "dao": {"authoring_id": "gm.dao.actual.test", "display_name": "Banked Furnace",
                            "core_theme": "Measure the flame before release.", "mechanical_effects": []},
                    "i_ching": {"authoring_id": "gm.iching.actual.test", "display_name": "Fire over Mountain",
                                "core_theme": "Restraint before release.", "mechanical_effects": []}}
        return original(member, display_name=display_name)

    monkeypatch.setattr(sheet_fixture, "_surface_document", with_authored_themes)
    service = _service_with_snapshot(tmp_path, _sealed_snapshot(talents=[
        _talent("TAL_TEST_STRIKE", "Test Strike", "Action", "1 CP"),
        _talent("TAL_TEST_STEP", "Test Step", "Bonus Action"),
    ]))

    data = service.sheet(REFERENCE)["complete_character"]["surfaces"]["composite_playbooks"]["data"]

    proposed = [row for row in data["composites"] if row.get("capability_status") == "SERVER_VALIDATED_PROPOSAL"]
    assert proposed and data["proposals"]["themes"]["dao"]["source"] == "gm.dao.actual.test"
    assert all(row["dao_hook"].startswith("Dao: Banked Furnace: Measure the flame before release.") for row in proposed)
    assert all(row["i_ching_hook"].startswith("I Ching: Fire over Mountain: Restraint before release.") for row in proposed)
    assert all(row["validation"]["ok"] is True for row in proposed)
    assert all(row["i_ching_shift"]["kind"] in ("resource_low", "resource_recovered", "step_denied") for row in proposed)
    assert all(isinstance(row["dao_aspects"], list) for row in proposed)
