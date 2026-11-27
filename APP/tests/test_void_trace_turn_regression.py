"""Trace's recipient limit follows the initiative turn, not the recipient's turn."""
from combat import ext
from combat.authority_projection import compile_project_character
from combat.canonical import canonical_sha256
from combat.ext import void_touched_cultivator as void
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.void_family_support import acquired, bundle, owner_sheet, step_action, step_context
from tests.worker2_support import ALLY, FOE, OWNER, candidate, reload, settle


def test_trace_resets_on_next_initiative_turn(acquired, tmp_path):
    service, project = acquired
    second = compile_project_character(service, project, owner_sheet(service, project, name="Second Void"),
                                       actor_id=ALLY, reaction_plan={"ask": True})
    plain = compile_character(sheet([], cl=3, name="Target"), actor_id=FOE)
    combat = CombatService(ROOT, tmp_path)
    ids = [OWNER, ALLY, FOE]
    table = TabletopService(combat, tmp_path)
    arena = combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"]
    bundles = [bundle(service, project, OWNER), second, plain]
    # Make the two users consecutive, both before the recipient, independently
    # of the seed's initiative rolls.
    for compiled, initiative in zip(bundles, (100, 50, 0)):
        compiled["actor_template"]["initiative_bonus"] = initiative
        compiled.pop("bundle_sha256", None)
        compiled["bundle_sha256"] = canonical_sha256(compiled)
    mid = combat._finish_factory_match(
        bundles, ids,
        {OWNER: "team:factory", ALLY: "team:factory", FOE: "team:opponents"},
        {OWNER: {"x": 3, "y": 6}, ALLY: {"x": 4, "y": 6}, FOE: {"x": 6, "y": 6}},
        arena, [OWNER, ALLY], [FOE], control_modes={actor: "MANUAL" for actor in ids},
        match_seed="TRACE-TURN", display_name="TRACE-TURN", maximum_rounds=15)["match_id"]
    assert table.state(mid)["menu"]["actor_id"] == OWNER
    settle(table, mid, candidate(combat, mid, "Void Step", at=(5, 6)).candidate_id,
           picks={"choice:needle.teleport_destination": ["cell:5,6"],
                  "choice:needle.void_step_trace": [FOE]})
    # Both the mark and the recipient's initiative-turn receipt must persist.
    engine = reload(tmp_path, mid)
    target = engine.state.actors[FOE]
    assert void.mark_count(target, OWNER) == 1
    assert target.turn_flags[void.TRACE_FLAG] == void._combat_turn(engine)
    original_round = engine.state.round_number
    target_turns = target.turns_started

    # A second user's Trace in that SAME turn is still rejected after reload.
    actor = engine.state.actors[ALLY]
    context = step_context(engine, actor, step_action(engine, ALLY))
    ext.run_strict("teleport_settled", context, actor, Position(x=7, y=6), Position(x=7, y=7), False)
    assert void.mark_count(target, ALLY) == 0

    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    engine = reload(tmp_path, mid)
    assert engine.state.current_actor_id == ALLY
    assert engine.state.round_number == original_round
    assert engine.state.actors[FOE].turns_started == target_turns
    prompts = settle(table, mid, candidate(combat, mid, "Void Step", at=(7, 6)).candidate_id,
                     picks={"choice:needle.teleport_destination": ["cell:7,6"],
                            "choice:needle.void_step_trace": [FOE]})
    trace = next(p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.void_step_trace")
    assert FOE in [option["id"] for option in trace["choice"]["options"]]
    engine = reload(tmp_path, mid)
    target = engine.state.actors[FOE]
    assert target.turns_started == target_turns
    assert void.mark_count(target, ALLY) == 1
    assert target.turn_flags[void.TRACE_FLAG] == void._combat_turn(engine)
