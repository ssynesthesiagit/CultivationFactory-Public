"""Commit the real creation pipeline before using Cycle at a saved table.

The submitted plan contains choices only. Production services produce and commit
the canonical acquisition events, feature occurrences and sealed owner sheet.
No acquisition event, feature row or completion receipt is constructed here.
"""
from copy import deepcopy
import json

from character_builder import CharacterBuilderService
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
    creator = CharacterCreationExecutionService(db, stage1=Stage1ClipboardService(db), provider=None, project_store=store)
    started = creator.start(pid, execution_mode="MANUAL_CHAT", idempotency_key="cycle-canonical")
    run = creator.get(started["run_id"])
    # Use the current frozen response contract, rather than the historical
    # fixture plan (which predates the required training/proficiency arrays).
    plan = deepcopy(_provider_payload(run, cue_limit=0, display_limit=0)["response_contract"]["response_template"])
    plan["selection_intent"]["by_slot"].update(selections)
    plan["selection_intent"]["by_slot"]["background_sphere_choice"] = [F.SCOUNDREL]
    plan["acquisition_intent"].update({
        "sphere_free_talent_pairs": [{"sphere_id": F.FIRE, "talent_id": F.ADVANCEMENT_TALENTS[0]}],
        "ordinary_talent_ids": [*F.ADVANCEMENT_TALENTS[1:], sixth],
        "insight_occurrences": [], "trained_choices": []})
    plan["bounded_choices"].update({
        "ability_scores": deepcopy(F.STARTING_SCORES), "background_ability": "DEX", "path_progression_by_cl": {},
        "ability_score_changes_by_milestone_id": {
            F.QI_PATH + ".feature.ability_score_improvement_or_cultivation_insight.cl4": {"deltas": {"INT": 2}}},
        "path_skill_choices_by_path_id": {F.QI_PATH: ["Arcana", "History"]},
        "origin_skill_choices_by_origin_id": {F.STREET_HARDENED: ["Deception"]},
        "background_language_choices_by_background_id": {F.ABANDONED_ORPHAN: ["Classical"]}})
    plan["owner_descriptive_fields"].update({"identity": {"name": "Canonical Cycle cultivator"},
        "concept": "Five Elements source acquisition regression"})
    submitted = creator.submit_manual(run["run_id"], response_text=json.dumps(plan), request_sha256=run["request"]["request_sha256"])
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
