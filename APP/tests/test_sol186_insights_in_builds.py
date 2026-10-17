"""SOL186: planning access, automatic choice, and retained Insight ownership.

The portable end-to-end check is opt-in: finalization runs browser consumers.
The lead must run it outside the sandbox; default tests never launch a GUI.
"""

from copy import deepcopy
import os
from pathlib import Path
import time
import zipfile
import json

import pytest

from catalog.coverage import Stage1CatalogCoverageService
from stage1.service import Stage1ClipboardService
from character_creation.creative_controller import seeded_picker
from character_creation.creative_controller.linear_assembly import build_response
from character_creation.creative_controller.linear_menus import (
    _committed_present_ids, _relation_satisfied, build_insight_occurrence_menu,
)
from character_creation.creative_controller.linear_prompt import build_step_prompt
from character_creation.insight_build_policy import AUTOMATIC_INSIGHT_ADVICE
from tests import test_insights_are_chosen as fixtures


def test_subpath_insights_are_plannable_without_granting_subpath_mechanics(catalog_environment):
    coverage = Stage1CatalogCoverageService(catalog_environment["db"]).build()
    subpaths = next(row for row in coverage["categories"] if row["slot_id"] == "subpath_choice")
    insights = next(row for row in coverage["categories"] if row["slot_id"] == "insight_priorities")
    targets = set(subpaths["intent_selectable_record_ids"])
    dependent = [row for row in insights["records"]
                 if row["prerequisite_coverage"]["missing_target_ids"]
                 and set(row["prerequisite_coverage"]["missing_target_ids"]) <= targets]
    assert len(dependent) == 27
    assert all(row["intent_selectable"] and not row["selectable"] for row in dependent)
    assert all(row["blocked_reasons"] and row["intent_limitations"] for row in dependent)
    # Narrative conditions and other unresolved authority remain closed.
    assert all(not row["intent_selectable"] for row in insights["records"]
               if set(row["prerequisite_coverage"]["missing_target_ids"]) - targets)


def test_invalid_subpath_authority_does_not_open_its_insight(catalog_environment, monkeypatch):
    original = Stage1CatalogCoverageService._base_evaluation

    def invalid(record, *, include_test):
        row = original(record, include_test=include_test)
        if record["record_id"] == "tianxia.subpath.body.iron_shirt":
            row["blocked_reasons"].append({"code": "RECORD_HASH_UNPROVEN"})
        return row

    monkeypatch.setattr(Stage1CatalogCoverageService, "_base_evaluation", staticmethod(invalid))
    coverage = Stage1CatalogCoverageService(catalog_environment["db"]).build()
    insights = next(row for row in coverage["categories"] if row["slot_id"] == "insight_priorities")
    row = next(row for row in insights["records"] if row["record_id"] == "insight.bell-skin-discipline")
    assert not row["intent_selectable"] and not row["selectable"]


@pytest.mark.parametrize("cl, expected", [(1, 0), (5, 1), (10, 2), (17, 4)])
def test_automatic_milestones_use_real_catalogue_prerequisites(catalog_environment, cl, expected):
    db = catalog_environment["db"]
    coverage = Stage1CatalogCoverageService(db).build()
    category = next(row for row in coverage["categories"] if row["slot_id"] == "insight_priorities")
    allowed = set(category["intent_selectable_record_ids"])
    with db.connection() as conn:
        records = [json.loads(row[0]) for row in conn.execute(
            "SELECT data_json FROM catalog_records WHERE selected_authority=1"
        )]
    choices = {record["record_id"]: {
                   **Stage1ClipboardService._choice(record),
                   "stage2_authority": deepcopy(record["compatibility"]["factory"]["stage2_authority"]),
               }
               for record in records if record["record_id"] in allowed and record["content_type"] == "cultivation_insight"}
    request, envelope = fixtures._request(cl), fixtures._envelope(cl)
    envelope["choices_by_slot"]["insight_priorities"] = choices
    state = fixtures._starting_state(cl).with_identity("Test", "Test", "A saber healer who cultivates poison")

    def chooser(menu):
        # At the point of acquisition, use the real printed typed
        # prerequisites and causal state, not a stripped test row.
        if menu.step_kind == "insight_occurrence":
            present = _committed_present_ids(request, envelope, current[0], planning=False)
            for option in menu.options:
                if option.choice_ids and option.choice_ids[0] in choices:
                    assert all(_relation_satisfied(relation, present) is True
                               for relation in choices[option.choice_ids[0]]["prerequisites"])
        return seeded_picker.step_receipt("QB-AAA111", menu)["value"]["option_id"]

    current = [state]
    from character_creation.creative_controller.linear_walk import next_step, commit_option, ACTION_AUTOCOMMITTED, ACTION_COMPLETE
    for _ in range(80):
        if fixtures._levels_answered(current[0], cl):
            break
        step = next_step(request, envelope, current[0])
        assert step.action != ACTION_COMPLETE
        if step.action == ACTION_AUTOCOMMITTED:
            current[0] = step.committed
        else:
            current[0] = commit_option(step.menu, chooser(step.menu), current[0])
    # SOL200 policy: every level resolves once; an Insight is taken when its
    # +1 gives the next ability the same modifier as +2 and its printed
    # benefit is used. The real catalogue offers such Insights from CL4.
    state = current[0]
    occurrences = state.insight_occurrences
    assert len(fixtures._resolution_by_milestone(state)) == expected
    assert (len(occurrences) >= 1) == (cl >= 4), [row["insight_id"] for row in occurrences]
    assert all(row["insight_id"] in choices for row in occurrences)
    present = _committed_present_ids(request, envelope, state, planning=False)
    from character_creation.insight_build_policy import insight_use
    assert all(insight_use(choices[row["insight_id"]], present) for row in occurrences)


@pytest.mark.parametrize("cl, expected", [(1, 0), (5, 1), (10, 2), (17, 4)])
@pytest.mark.parametrize("seed", ["QB-AAA111", "QB-BBB222", "QB-CCC333"])
def test_production_seeded_receipts_resolve_all_levels_and_assemble_occurrences(cl, expected, seed):
    # Use the production receipt called by _run_dcc_linear_walk (Quick Build
    # and seeded guided builds), not the legacy random-branch chooser.
    chooser = lambda menu: seeded_picker.step_receipt(seed, menu)["value"]["option_id"]
    request, envelope, state = fixtures._walk(cl, chooser=chooser)
    if cl == 1:
        identity = seeded_picker.identity(seed)
        state = state.with_identity(identity["name"], identity["title"], identity["concept"])
    # SOL190 owner policy supersedes unconditional Insight preference. These
    # stripped fixture rows describe only the +1, so none proves a used benefit.
    assert not state.insight_occurrences
    assert len(fixtures._resolution_by_milestone(state)) == expected
    present = _committed_present_ids(request, envelope, state, planning=False)
    for occurrence in state.insight_occurrences:
        row = envelope["choices_by_slot"]["insight_priorities"][occurrence["insight_id"]]
        assert all(_relation_satisfied(relation, present) is True for relation in row["prerequisites"])
        assert occurrence["parameters"]["ability"] in row["stage2_authority"]["ability_change"]["allowed_abilities"]
    plan = json.loads(build_response(dict(request, delegated_choice_envelope=envelope), state))
    assert {(row["insight_id"], row["milestone_id"]) for row in plan["acquisition_intent"]["insight_occurrences"]} == {
        (row["insight_id"], row["milestone_id"]) for row in state.insight_occurrences
    }
    assert len(plan["bounded_choices"].get("ability_score_changes_by_milestone_id", {})) == expected


def test_guided_prompt_prefers_insights_but_both_printed_choices_remain():
    request, envelope = fixtures._request(5), fixtures._envelope(5)
    step, state = fixtures._step_for(request, envelope, fixtures._starting_state(5),
                                    f"asi_or_insight:{fixtures._milestone_id(4)}")
    prompt = build_step_prompt(request, envelope, state, step.menu)
    assert AUTOMATIC_INSIGHT_ADVICE in prompt
    assert {option.choice_ids for option in step.menu.options} == {
        ("ability_score_increase",), ("cultivation_insight",),
    }


@pytest.mark.parametrize("cl", [1, 5, 10, 17])
def test_stage_plan_prompt_carries_the_same_insight_policy(cl):
    from character_creation.service import CharacterCreationExecutionService
    from tests.test_compact_provider_prompt import _request

    payload = json.loads(CharacterCreationExecutionService._provider_prompt({"request": _request(target_cl=cl)}))
    assert AUTOMATIC_INSIGHT_ADVICE in payload["instructions"]


def test_insight_menu_ranks_concept_fit_without_opening_an_ineligible_row():
    request, envelope = fixtures._request(5), deepcopy(fixtures._envelope(5))
    request.pop("request_sha256", None)  # independent concept, not a cached frozen request
    rows = envelope["choices_by_slot"]["insight_priorities"]
    state = fixtures._starting_state(5).with_identity("Test", "Test", "A poison healer")
    eligible = next(iter(rows))
    rows[eligible]["name"] = "Poison Healer"
    rows[eligible]["prerequisites"] = []
    menu = build_insight_occurrence_menu(request, envelope, state,
                                        milestone_id=fixtures._milestone_id(4))
    assert menu.options[0].choice_ids == (eligible,)
    rows[eligible]["prerequisites"] = [{"kind": "subpath", "operator": "requires", "target_id": "missing.subpath"}]
    menu = build_insight_occurrence_menu(request, envelope, state,
                                        milestone_id=fixtures._milestone_id(4))
    assert all(eligible not in option.choice_ids for option in menu.options)


@pytest.mark.skipif(os.environ.get("SOL186_PORTABLE_E2E") != "1",
                    reason="Lead must run portable finalization/browser consumers outside the sandbox")
@pytest.mark.parametrize("cl, expected", [(1, 0), (5, 1), (10, 2), (17, 4)])
@pytest.mark.parametrize("route", ["quick", "guided"])
def test_finalized_portable_sheet_has_eligible_insights(tmp_path, monkeypatch, cl, expected, route):
    from app.api import create_app
    from app.core import Settings
    from product_bootstrap.service import ProductBootstrapService

    monkeypatch.setenv("TIANXIA_BROWSER_EXECUTABLE", "/usr/bin/chromium")
    settings = Settings.from_env(Path(__file__).resolve().parents[1], tmp_path / "userdata")
    ProductBootstrapService(settings).run()
    app = create_app(settings)
    if route == "quick":
        batch = app.state.quick_builds.submit(items=[{"route": "seeded", "seed": "QB-AAA111"}],
                                             target_cl=cl, finalize=True)
        deadline = time.monotonic() + 3600  # finalize alone can exceed 30 min under load
        while time.monotonic() < deadline:
            # A listing can transiently miss the batch while its file is rewritten.
            row = next((row for row in app.state.quick_builds.list() if row["batch_id"] == batch["batch_id"]), None)
            item = row["items"][0] if row else {"status": "polling"}
            if item["status"] in {"failed", "finished", "needs_review", "interrupted"}:
                break
            time.sleep(0.1)
        assert item["status"] == "finished", item
    else:
        created = app.state.character_builder.create_project(
            working_name="SOL186", concept="A saber healer who cultivates poison",
            target_cl=cl, power_band="standard", source_reference=None,
            creation_mode="detailed", generation_route="ai_bootstrap",
            ability_scores={}, selections={}, autogen_seed="QB-AAA111",
        )
        app.state.character_builder.commit_normal_first_cycle_catalog_choices(created["project_id"])
        run = app.state.character_creation.start(created["project_id"], execution_mode="STANDARD_API",
                    idempotency_key=f"sol186-{cl}", controller_route="DETERMINISTIC_CREATIVE_CONTROLLER")
        assert run["status"] == "READY_FOR_REVIEW", run.get("diagnostics")
        final = app.state.character_creation.finalize(run["run_id"])
        assert final["status"] == "CLEAN_AND_FINALIZED", final.get("diagnostics")
    packages = list(settings.data_dir.glob("portable_characters/*/current.zip"))
    assert len(packages) == 1
    with zipfile.ZipFile(packages[0]) as archive:
        sheet = json.loads(archive.read("Tianxia_Owner_Character_Sheet_v1.json"))
        ledger = json.loads(archive.read("Character_Master_Ledger.json"))
    occurrences = sheet["spheres_and_talents"]["cultivation_insight_occurrences"]
    # SOL200 policy, not an unconditional count: from CL4 a real build takes
    # an Insight where its +1 matches the increase's modifier gain and its
    # benefit is used; the remaining levels stay focused increases.
    assert (len(occurrences) >= 1) == (cl >= 4), occurrences
    assert len(occurrences) <= expected
    assert len(sheet["spheres_and_talents"]["cultivation_insight_record_ids"]) == len(occurrences)
    assert len(ledger["cultivation_insight_occurrences"]) == len(occurrences)
    assert all(row["name"] and row["full_description"] and row["ability_change_applied"] for row in occurrences)
    # Every level choice records a plain reason.
    import sqlite3
    with sqlite3.connect(settings.data_dir / "foundry.sqlite3") as conn:
        commits = [json.loads(row[0])["payload"] for row in conn.execute(
            "SELECT event_json FROM dcc_controller_events WHERE event_type='STEP_COMMITTED'")]
    level = [row for row in commits if str(row.get("step_id", "")).startswith(("asi_or_insight:", "asi_milestone:", "insight_occurrence:"))]
    assert all(row.get("build_choice_reason") for row in level)
    branches = [row for row in level if row["step_id"].startswith("asi_or_insight:")]
    assert len(branches) == expected or not branches
