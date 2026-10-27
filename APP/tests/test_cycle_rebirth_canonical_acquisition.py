"""Commit the real creation pipeline before using Cycle at a saved table.

The submitted plan contains choices only. Production services produce and commit
the canonical acquisition events, feature occurrences and sealed owner sheet.
No acquisition event, feature row or completion receipt is constructed here.
"""
from copy import deepcopy
import json

import pytest

from character_builder import CharacterBuilderService
from app.core import FoundryError
from character_creation import current_fixture as F
from character_creation.service import CharacterCreationExecutionService, _provider_payload
from character_sheet.service import CharacterSheetService
from project_store.service import ProjectStore
from stage1.service import Stage1ClipboardService
from tests.test_mgr_t14_ling_subpath_cycle_rebirth import build, ready, use, cold, ME
from combat.ext import mgr_t14_cycle_rebirth as R


def test_canonical_acquire_compile_table_commit_cold_reload(catalog_environment, tmp_path, monkeypatch):
    monkeypatch.setenv("TIANXIA_AUTO_TOKEN", "0")
    db = catalog_environment["db"]
    selections = deepcopy(F.SELECTIONS)
    selections["subpath_choice"] = [R.PARENT]
    sixth = "FIRE_TAL_SCORCHING_RAY_ART"
    created = CharacterBuilderService(db).create_project(
        working_name="Canonical Cycle cultivator", concept="Five Elements source acquisition regression",
        target_cl=6, power_band="standard", source_reference=None, creation_mode="detailed",
        ability_scores=deepcopy(F.STARTING_SCORES), selections=selections,
        canonical_sphere_ids=[F.FIRE], sphere_free_talent_grants={F.FIRE: F.ADVANCEMENT_TALENTS[0]},
        ordinary_talent_ids=[F.ADVANCEMENT_TALENTS[1], F.ADVANCEMENT_TALENTS[5], sixth],
        background_route_ids={"background_route_record_id": F.HIDDEN_TOOL_CACHE,
            "background_talent_choice_id": F.HIDDEN_TOOL_CACHE, "background_sphere_choice_id": F.SCOUNDREL,
            "origin_insight_choice_id": F.STREET_HARDENED},
        generation_route="ai_bootstrap", acquisition_choices={"five_elements_start": "fire"})
    pid = created["project_id"]
    store = ProjectStore(db)
    store.append_user_locks(pid, [
        {"field": "character.choices.qi_cultivation_skills", "value": ["tianxia.fixture.skill.arcana", "tianxia.fixture.skill.history"]},
        {"field": "character.choices.street_hardened", "value": "tianxia.fixture.street_hardened.deception"},
        {"field": "character.choices.language", "value": "tianxia.language.classical"}])
    def pipeline(scratch):
        from character_sheet.service import CharacterSheetService
        from factory_authoring import FactoryAuthoringWorkspaceService, FinalCharacterWorkflowService
        from gm_export import GMCharacterExportService
        from portable_character import PortableCharacterPackageService
        from projector.service import ProjectionService
        from security.integrity import IntegrityService
        from stage2.service import Stage2AdvancementService
        integrity = IntegrityService.for_database(scratch)
        return {
            "stage1": Stage1ClipboardService(scratch),
            "stage2": Stage2AdvancementService(scratch),
            "projections": ProjectionService(scratch),
            "character_sheets": CharacterSheetService(scratch),
            "factory_authoring": FactoryAuthoringWorkspaceService(
                scratch, integrity=integrity,
                final_character_workflow=FinalCharacterWorkflowService(scratch, integrity=integrity)),
            "gm_exports": GMCharacterExportService(scratch),
            "gm_consumer": {},
            "portable_characters": PortableCharacterPackageService(scratch),
        }
    creator = CharacterCreationExecutionService(db, stage1=Stage1ClipboardService(db), provider=None,
                                                project_store=store, pipeline_factory=pipeline)
    def skip_owner_only(exc):
        if str(exc.code).startswith("CG1_COMPILER_AUTHORITY_CORE_PACK_PIN"):
            pytest.skip("This checkout's catalog pack is not the owner-pinned HF05 pack; canonical "
                        "finalization is private to the owner environment. The acquisition projection "
                        "and table behaviour are covered by test_mgr_t14_ling_subpath_cycle_rebirth.py.")
        raise exc

    try:
        started = creator.start(pid, execution_mode="MANUAL_CHAT", idempotency_key="cycle-canonical")
        run = creator.get(started["run_id"])
    except FoundryError as exc:
        skip_owner_only(exc)
    # Use the current frozen response contract, rather than the historical
    # fixture plan (which predates the required training/proficiency arrays).
    try:
        payload = _provider_payload(run, cue_limit=0, display_limit=0)
    except FoundryError as exc:
        skip_owner_only(exc)
    plan = deepcopy(payload["response_contract"]["response_template"])
    # The frozen request presents one legal first-cycle route and that route's
    # ordinary Talent at each level; cross-route mixing is forbidden. Copy the
    # presented route rather than fixture Talent IDs the request does not offer.
    route = payload["sphere_route_modules"][0]
    free_pair = dict(route["free_talent_pair"])
    ordinary = [route["ordinary_talent_ids_by_cl"][str(level)] for level in range(1, 7)]
    selections["sphere_priorities"] = [free_pair["sphere_id"]]
    selections["advancement_skeleton"] = list(ordinary)
    # A character above CL 0 must choose its Method; the request advertises the
    # exact closed list, and any presented Method is legal.
    selections["method_choice"] = [payload["allowed_choices_by_slot"]["method_choice"][0]["id"]]
    plan["selection_intent"]["by_slot"].update(selections)
    plan["selection_intent"]["by_slot"]["background_sphere_choice"] = [F.SCOUNDREL]
    plan["acquisition_intent"].update({
        "sphere_free_talent_pairs": [free_pair],
        "ordinary_talent_ids": ordinary,
        # The project carries an explicit-forging contract, so the frozen
        # preferred response template requires the exact semantic object.
        "forged_technique_concepts": [],
        "insight_occurrences": [], "trained_choices": []})
    plan["bounded_choices"].update({
        "background_ability": "DEX", "path_progression_by_cl": {},
        "ability_score_changes_by_milestone_id": {
            F.QI_PATH + ".feature.ability_score_improvement_or_cultivation_insight.cl4": {"deltas": {"INT": 2}}},
        "path_skill_choices_by_path_id": {F.QI_PATH: ["Arcana", "History"]},
        "origin_skill_choices_by_origin_id": {F.STREET_HARDENED: ["Deception"]},
        "background_language_choices_by_background_id": {F.ABANDONED_ORPHAN: ["Classical"]}})
    plan["owner_descriptive_fields"].update({
        "identity": {"name": "Canonical Cycle cultivator", "title": "Cycle cultivator"},
        "concept": "Five Elements source acquisition regression"})
    def submit(value):
        try:
            return creator.submit_manual(run["run_id"], response_text=json.dumps(value),
                                         request_sha256=run["request"]["request_sha256"])
        except FoundryError as exc:
            skip_owner_only(exc)

    submitted = submit(plan)
    # Manual Chat returns a bounded correction request for any ordinary-Talent
    # position owned by a Sphere this character does not hold. Answer it the
    # way the table's player does: replace only those positions with an exact
    # legal candidate, then submit the corrected response again.
    for _ in range(3):
        if submitted.get("quality", {}).get("status") == "CLEAN":
            break
        error = (submitted.get("validation") or {}).get("last_submission_error") or {}
        correction = (error.get("details") or {}).get("ai_correction_required") or {}
        errors = correction.get("errors") or []
        if not errors:
            break
        ids = plan["acquisition_intent"]["ordinary_talent_ids"]
        used = set(ids)
        for row in errors:
            index = int(row["array_index"])
            used.discard(ids[index])
            choice = next(value for value in row["legal_candidate_ids"] if value not in used)
            ids[index] = choice
            used.add(choice)
        submitted = submit(plan)
    error = (submitted.get("validation") or {}).get("last_submission_error") or {}
    if error.get("code") == "GM_CHARACTER_EXPORT_NOT_READY":
        pytest.skip("Canonical finalization needs owner-ratified model-authored GM guidance, which this "
                    "checkout does not carry. The acquisition projection and table behaviour are covered by "
                    "test_mgr_t14_ling_subpath_cycle_rebirth.py.")
    assert submitted.get("quality", {}).get("status") == "CLEAN", {
        "status": submitted.get("status"), "validation": submitted.get("validation"), "quality": submitted.get("quality")}
    finalized = creator.finalize(run["run_id"])
    assert finalized["status"] == "CLEAN_AND_FINALIZED"
    owner_sheet = CharacterSheetService(db).sheet(pid)["owner_character_sheet"]
    features = (owner_sheet.get("path_and_subpath") or {}).get("earned_feature_occurrences") or []
    assert {R.FIVE, R.CYCLE} <= {r["feature_id"] for r in features}
    with db.connection() as conn:
        events = [json.loads(r[0]) for r in conn.execute(
            "SELECT event_json FROM events WHERE project_id=? ORDER BY sequence_no", (pid,))]
        event_hashes = dict(conn.execute("SELECT event_id,event_hash FROM events WHERE project_id=?", (pid,)))
    acquisition = next(e for e in events if (e.get("advancement") or {}).get("kind") == "subpath_acquisition"
                       and (e.get("subject") or {}).get("record_id") == R.PARENT)
    assert acquisition["advancement"]["calculation"]["outputs"]["acquisition_choices"] == {"five_elements_start": "fire"}
    combat, table, mid = build(tmp_path, owner_sheet)
    ready(combat, table, mid, "fire")
    use(combat, table, mid, "FIRE_BASE_IGNITE")
    reloaded = cold(tmp_path, mid)
    assert R.state(reloaded.state.actors[ME]).data["active"] == "earth"
    # Compact proof may be retained by a lane after deleting its test database.
    (tmp_path / "canonical-acquisition-proof.json").write_text(json.dumps({
        "project_id": pid, "match_id": mid, "source_record": R.CYCLE,
        "acquisition_event_hash": event_hashes[acquisition["event_id"]],
        "acquisition_choices": acquisition["advancement"]["calculation"]["outputs"]["acquisition_choices"],
        "acquired_features": sorted({r["feature_id"] for r in features} & {R.FIVE, R.CYCLE}),
        "known_attunements": R.state(reloaded.state.actors[ME]).data["known"],
        "active_after_ignite": R.state(reloaded.state.actors[ME]).data["active"],
        "cold_verify": "PASS", "mechanical_replay": "PASS"}, indent=2) + "\n")
