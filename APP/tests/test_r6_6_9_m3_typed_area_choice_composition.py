from __future__ import annotations

import json
from pathlib import Path

import pytest

from combat.choice_authority import canonicalize_option_selection, expand_option_selections, validate_option_selection
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_content import AN, BAI, LING
from combat.gate2_runtime_models import CandidateKind, LegalCandidate, Position, ReactionDecision
from combat.gate4_context import build_reaction_context
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate4_policy import PolicyLibrary

ROOT = Path(__file__).resolve().parents[1]


def _set_turn(engine: Gate2Engine, actor_id: str) -> None:
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    engine.state.current_actor_id = actor_id
    actor = engine.state.actors[actor_id]
    actor.action_available = True
    actor.bonus_action_available = True
    actor.movement_remaining_ft = actor.speed_ft


def _candidate(source: str, options: tuple[str, ...]) -> LegalCandidate:
    engine = Gate2Engine(ROOT, match_seed="R669-M3-CANDIDATE")
    actor = engine.state.actors[AN]
    return engine._candidate(
        CandidateKind.ACTION,
        actor,
        source,
        source,
        target_ids=(LING,),
        option_ids=options,
    )


def test_area_candidate_contains_exact_server_issued_center_radius_and_cells() -> None:
    engine = Gate2Engine(ROOT, match_seed="R669-M3-AREA")
    _set_turn(engine, LING)
    candidate = next(
        row for row in engine.legal_candidates()
        if row.source_definition_id == "action:ling_qi.forgotten_vale_nocturne"
    )
    assert candidate.area is not None
    assert candidate.area.center == candidate.destination
    assert candidate.area.radius_cells == 4
    assert candidate.area.affected_cells == engine.grid.cells_in_radius(candidate.destination, 4)
    assert candidate.candidate_id.startswith("candidate:")


def test_scouring_blast_exposes_two_independent_typed_choice_domains() -> None:
    candidate = _candidate(
        "action:an_eui.scouring_destruction_blast",
        ("DEEPEN", "AC_MINUS_1", "NEXT_ATTACK_ADVANTAGE", "NO_HALF_COVER"),
    )
    assert candidate.choice_authority_status == "COMPLETE"
    assert [row.domain_id for row in candidate.choice_domains] == ["break_guard", "modifier:deepen"]
    assert validate_option_selection(candidate, ("DEEPEN", "AC_MINUS_1")) == ()
    assert "domain_maximum_exceeded:break_guard" in validate_option_selection(
        candidate, ("AC_MINUS_1", "NEXT_ATTACK_ADVANTAGE")
    )
    expanded = expand_option_selections(candidate)
    assert ("AC_MINUS_1", "DEEPEN") in expanded
    assert ("NEXT_ATTACK_ADVANTAGE", "DEEPEN") in expanded
    assert ("AC_MINUS_1",) in expanded
    assert () in expanded
    assert canonicalize_option_selection(candidate, ("DEEPEN", "AC_MINUS_1")) == ("AC_MINUS_1", "DEEPEN")


def test_unknown_multi_option_semantics_fail_closed_for_owner_composition() -> None:
    candidate = _candidate("action:test.unknown_multi_option", ("A", "B"))
    assert candidate.choice_authority_status == "GAP"
    assert candidate.choice_domains == ()
    assert "choice_authority_gap" in validate_option_selection(candidate, ("A",))


def test_reaction_context_exposes_exact_legal_option_ids() -> None:
    engine = Gate4ControllerEngine(ROOT, match_seed="R669-M3-REACTION")
    policy, _ = PolicyLibrary(ROOT).for_actor(BAI)
    request = {
        "checkpoint": "ALLY_OR_COMPANION_ATTACKED",
        "reactor_id": BAI,
        "reaction_source_id": "reaction:bai_meizhen.spirit_intercession",
        "protected_target_id": "bai_cui_companion_cl5",
        "legal_reaction_ids": ["reaction:bai_meizhen.spirit_intercession"],
        "legal_option_ids": ["SPEND_QI"],
        "spend_options": [],
    }
    context = build_reaction_context(engine, policy, request)
    assert context.legal_option_ids == ("SPEND_QI",)
    use = ReactionDecision(
        checkpoint=context.checkpoint,
        reactor_id=context.reactor_id,
        reaction_source_id=context.reaction_source_id,
        selection="USE",
        spend=0,
        option_ids=("SPEND_QI",),
    )
    assert use.option_ids == context.legal_option_ids


def test_ui_uses_exact_area_projection_and_typed_domains_without_client_radius_math() -> None:
    js = (ROOT / "static/app.js").read_text(encoding="utf-8")
    assert 'return {mode: "select_area", candidates: areaCandidates}' in js
    assert "candidate.area?.affected_cells" in js or "selectedAreaCandidate?.area?.affected_cells" in js
    assert "chooseCombatMapArea" in js
    assert "chooseCombatAreaTechnical" in js
    assert "Choose Area on Map" in js
    assert "combatRenderChoiceDomains" in js
    assert 'candidate.choice_authority_status === "GAP"' in js
    area_start = js.index("function renderCombatBoard")
    area_end = js.index("function combatSheetButton", area_start)
    area_body = js[area_start:area_end]
    for forbidden in ("Math.hypot", "radius_ft", "radius_cells *", "lineOfSight", "pathfind"):
        assert forbidden not in area_body


def test_choice_composition_schema_is_closed() -> None:
    schema = json.loads((ROOT / "schemas/TianxiaCombatChoiceComposition.v1.schema.json").read_text(encoding="utf-8"))
    assert schema["$id"] == "TianxiaCombatChoiceComposition.v1"
    assert schema["additionalProperties"] is False
    assert schema["properties"]["schema"]["const"] == "TianxiaCombatChoiceComposition.v1"
    assert schema["properties"]["selected_option_ids"]["uniqueItems"] is True


def test_m3_gap_report_explicitly_defers_absent_primary_spend_and_multitarget_domains() -> None:
    report = (ROOT / "R6_6_9_M3_AUTHORITY_GAP_REPORT.md").read_text(encoding="utf-8")
    assert "No current primary-action variable-spend domain" in report
    assert "No current composable multi-target domain" in report
    assert "does not infer" in report
