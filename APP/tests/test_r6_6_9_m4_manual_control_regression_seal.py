from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from combat.gate2_runtime_content import AN, BAI, LEE, LING
from combat.gate2_runtime_models import ConditionInstance, Position, ReactionDecision
from combat.gate5_service import CombatService

ROOT = Path(__file__).resolve().parents[1]


def _manual_payload(candidate: dict) -> dict:
    return {
        "decision_id": candidate["decision_id"],
        "state_version": candidate["state_version"],
        "candidate_id": candidate["candidate_id"],
        "actor_id": candidate["actor_id"],
        "target_ids": list(candidate.get("target_ids") or ()),
        "destination": candidate.get("destination"),
        "option_ids": list(candidate.get("option_ids") or ()),
    }


def _mixed_reaction_service(tmp_path: Path) -> tuple[CombatService, str, object]:
    service = CombatService(ROOT, tmp_path / "UserData")
    catalog = service.catalog()
    modes = {
        row["runtime_entity_id"]: "MANUAL"
        for row in catalog["projections"]
        if row.get("primary_combatant")
    }
    modes[AN] = "MANUAL"
    modes[BAI] = "LOCAL_AUTO"
    modes[LING] = "MANUAL"
    match = service.create_match(
        encounter_id=catalog["encounters"][0]["stable_id"],
        display_name="M4 mixed reaction sequence",
        match_seed="M4-REACT-1",
        control_modes=modes,
    )
    match_id = match["match_id"]
    session = service._load_session(match_id)
    engine = session.engine
    engine.state.actors[AN].position = Position(x=5, y=5)
    engine.state.actors[BAI].position = Position(x=6, y=5)
    engine.state.actors[LING].position = Position(x=6, y=6)
    engine.state.actors[LEE].position = Position(x=4, y=6)
    engine.state.current_slot_index = engine.state.initiative_order.index(AN)
    engine.state.current_actor_id = AN
    attacker = engine.state.actors[AN]
    attacker.action_available = True
    attacker.bonus_action_available = True
    attacker.movement_remaining_ft = attacker.speed_ft
    bai = engine.state.actors[BAI]
    bai.reaction_available = True
    bai.resources["resource:bai_meizhen.qi"] = max(1, bai.resources.get("resource:bai_meizhen.qi", 0))
    bai.resources["resource:bai_meizhen.moon_sea_radiance"] = 0
    ling = engine.state.actors[LING]
    ling.reaction_available = True
    ling.resources["resource:ling_qi.qi"] = max(1, ling.resources.get("resource:ling_qi.qi", 0))
    instance_id = "condition-instance:m4.keep-the-measure"
    ling.conditions[instance_id] = ConditionInstance(
        instance_id=instance_id,
        condition_id="condition:ling_qi.keep_the_measure",
        source_definition_id="action:ling_qi.keep_the_measure",
        source_actor_id=LING,
        target_id=LING,
        applied_sequence=engine.state.event_sequence,
        expires_on="UNTIL_REMOVED",
    )
    # The service public boundary is exercised while the deterministic session is
    # held in memory; no authoritative commit is performed by preview.
    service._load_session = lambda _match_id: session  # type: ignore[method-assign]
    return service, match_id, session


def test_mixed_controller_reaction_sequence_preserves_prior_exact_decisions(tmp_path: Path) -> None:
    service, match_id, session = _mixed_reaction_service(tmp_path)
    decision = service.decision(match_id)
    candidate = next(
        row
        for row in decision["context"]["legal_candidates"]
        if row["source_definition_id"] == "action:an_eui.paired_bi_shou_assault"
        and BAI in row.get("target_ids", ())
    )
    before = (
        session.engine.state.state_version,
        session.engine.state.event_sequence,
        session.engine.state.roll_counter,
    )
    first = service.preview(match_id, _manual_payload(candidate), [])
    assert first["status"] == "REACTION_REQUIRED"
    assert first["reaction_step_number"] == 2
    assert first["reaction_controller_mode"] == "MANUAL"
    assert first["reaction_context"]["reactor_id"] == LING
    assert first["reaction_context"]["reaction_source_id"] == "reaction:ling_qi.rhythmic_guard"
    assert first["reaction_context_fingerprint"].startswith("reaction-context:")
    assert first["resolved_reactions_before_prompt"] == [
        {
            "checkpoint": "DAMAGE_APPLICATION",
            "reactor_id": BAI,
            "reaction_source_id": "reaction:bai_meizhen.water_shield",
            "selection": "DECLINE",
            "spend": 0,
            "option_ids": [],
        }
    ]
    assert len(first["reaction_records_before_prompt"]) == 1
    assert first["authoritative_state_unchanged"] is True
    assert before == (
        session.engine.state.state_version,
        session.engine.state.event_sequence,
        session.engine.state.roll_counter,
    )

    decline = ReactionDecision(
        checkpoint="DAMAGE_APPLICATION",
        reactor_id=LING,
        reaction_source_id="reaction:ling_qi.rhythmic_guard",
        selection="DECLINE",
        spend=0,
        option_ids=(),
    ).model_dump(mode="json")
    complete = service.preview(match_id, _manual_payload(candidate), [decline])
    assert complete["status"] == "PREVIEW_COMPLETE"
    assert [row["reactor_id"] for row in complete["resolved_reactions"][:2]] == [BAI, LING]
    assert [row["selection"] for row in complete["resolved_reactions"][:2]] == ["DECLINE", "DECLINE"]
    assert complete["authoritative_state_unchanged"] is True
    assert before == (
        session.engine.state.state_version,
        session.engine.state.event_sequence,
        session.engine.state.roll_counter,
    )


def test_compound_map_candidate_family_is_exact_and_requires_staged_selection(tmp_path: Path) -> None:
    service = CombatService(ROOT, tmp_path / "UserData")
    session = service.persistence.create_match(match_seed="M4-COMPOUND-MAP")
    engine = session.engine
    engine.state.current_slot_index = engine.state.initiative_order.index(BAI)
    engine.state.current_actor_id = BAI
    bai = engine.state.actors[BAI]
    bai.action_available = True
    bai.bonus_action_available = True
    bai.movement_remaining_ft = bai.speed_ft
    candidates = [
        row for row in engine.legal_candidates()
        if row.source_definition_id == "action:bai_meizhen.command_cui"
        and row.target_ids and row.destination is not None
    ]
    assert candidates
    assert all(row.candidate_id.startswith("candidate:") for row in candidates)
    assert all(row.choice_authority_status == "COMPLETE" for row in candidates)
    assert len({row.candidate_id for row in candidates}) == len(candidates)

    js = (ROOT / "static/app.js").read_text(encoding="utf-8")
    assert 'selection_steps: mapChoice.steps' in js
    assert 'remaining_candidate_ids' in js
    assert 'function advanceCombatMapSelection' in js
    assert 'interaction_mode = "select_exact"' in js
    staged = js[js.index("function advanceCombatMapSelection"):js.index("function chooseCombatMapTarget")]
    assert "candidate_id" in staged
    for forbidden in ("pathfind", "lineOfSight", "Math.hypot", "radius_cells *", "movement_cost ="):
        assert forbidden not in staged


def test_manual_draft_guards_cover_refresh_history_controller_and_automatic_execution() -> None:
    js = (ROOT / "static/app.js").read_text(encoding="utf-8")
    assert "const combatPendingIntentDraftIsCurrent = () =>" in js
    guard = js[js.index("const combatPendingIntentDraftIsCurrent = () =>"):js.index("function combatSetInteractionMode")]
    for exact_pin in (
        "match_id",
        "created_for_decision_id",
        "created_for_state_version",
        "created_for_actor_id",
        "created_for_controller_mode",
        "intent",
    ):
        assert exact_pin in guard
    assert "cancelCombatPendingIntent(\"The pending manual action was canceled because combat authority advanced or the controller changed.\")" in js
    assert "function combatDraftBlocksAutomaticExecution" in js
    assert "Cancel or complete the current non-authoritative manual draft before automatic execution." in js
    assert "combatIsHistorical()" in js and "cancelCombatMapSelection" in js


def test_review_summary_exposes_exact_authoritative_facts_without_client_mechanics() -> None:
    js = (ROOT / "static/app.js").read_text(encoding="utf-8")
    start = js.index("function renderCombatIntentReview")
    end = js.index("async function continueCombatPreview", start)
    body = js[start:end]
    for expected in (
        "Candidate ID",
        "Decision",
        "Movement",
        "Area",
        "Typed action choices",
        "Resolved controller reactions",
        "Preview seal",
    ):
        assert expected in body
    for forbidden in ("Math.hypot", "pathfind", "lineOfSight", "calculateCover", "radius_cells *"):
        assert forbidden not in body


def test_m4_draft_schemas_are_closed_and_exact_id_based() -> None:
    map_schema = json.loads((ROOT / "schemas/TianxiaCombatMapSelectionDraft.v2.schema.json").read_text(encoding="utf-8"))
    pending_schema = json.loads((ROOT / "schemas/TianxiaCombatPendingIntentDraft.v1.schema.json").read_text(encoding="utf-8"))
    assert map_schema["additionalProperties"] is False
    assert pending_schema["additionalProperties"] is False
    assert map_schema["properties"]["schema"]["const"] == "TianxiaCombatMapSelectionDraft.v2"
    assert pending_schema["properties"]["schema"]["const"] == "TianxiaCombatPendingIntentDraft.v1"
    assert map_schema["properties"]["legal_candidate_ids"]["uniqueItems"] is True
    assert map_schema["properties"]["remaining_candidate_ids"]["uniqueItems"] is True
    assert set(pending_schema["required"]) == {
        "schema", "intent", "reaction_decisions", "reaction_trace",
        "created_for_match_id", "created_for_decision_id", "created_for_state_version",
        "created_for_actor_id", "created_for_controller_mode", "preview",
    }


def test_m4_draft_schema_examples_validate_and_reject_fabricated_fields() -> None:
    map_schema = json.loads((ROOT / "schemas/TianxiaCombatMapSelectionDraft.v2.schema.json").read_text(encoding="utf-8"))
    pending_schema = json.loads((ROOT / "schemas/TianxiaCombatPendingIntentDraft.v1.schema.json").read_text(encoding="utf-8"))
    map_doc = {
        "schema": "TianxiaCombatMapSelectionDraft.v2",
        "match_id": "match:test", "decision_id": "decision:test", "state_version": 3,
        "actor_id": AN, "controller_mode": "MANUAL", "interaction_mode": "select_destination",
        "selection_steps": ["select_target", "select_destination"], "step_index": 1,
        "legal_candidate_ids": ["candidate:a", "candidate:b"],
        "remaining_candidate_ids": ["candidate:b"], "preferred_candidate_id": "candidate:a",
        "selected_candidate_id": "candidate:b", "selected_target_id": BAI,
        "selected_destination": {"x": 7, "y": 8}, "selected_area_center": None,
    }
    pending_doc = {
        "schema": "TianxiaCombatPendingIntentDraft.v1",
        "intent": {"candidate_id": "candidate:b"}, "reaction_decisions": [], "reaction_trace": [],
        "created_for_match_id": "match:test", "created_for_decision_id": "decision:test",
        "created_for_state_version": 3, "created_for_actor_id": AN,
        "created_for_controller_mode": "MANUAL", "preview": None,
    }
    assert list(Draft202012Validator(map_schema).iter_errors(map_doc)) == []
    assert list(Draft202012Validator(pending_schema).iter_errors(pending_doc)) == []
    map_doc["client_computed_range"] = 30
    assert any(error.validator == "additionalProperties" for error in Draft202012Validator(map_schema).iter_errors(map_doc))
