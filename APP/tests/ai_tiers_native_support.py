"""Native AI fight harness; requires the combat runtime's export clearance.

Only synthetic sheets are written beneath pytest's tmp_path. This module is
separate from the public, dependency-free sheet builder so public fixture tests
do not import the compiler, plug-ins, table service, or engine-heavy h1 harness.
"""
import json
import zipfile
from pathlib import Path

from combat.factory_compiler import compile_character, TYPED_AUTHORITY
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_context import build_decision_context
from combat.gate4_controller import LocalDeterministicController
from combat.gate5_service import CombatService
from tests.ai_tiers_fixtures import sheet

ROOT = Path(__file__).resolve().parents[1]

OWNER, FOE = ("actor:factory.00000000-0000-4000-8000-00000000a101",
              "actor:factory.00000000-0000-4000-8000-00000000a102")


def fight(tmp_path, talents=(), *, band=None, flight=False, foe_at=None, equal=False,
          seed="AIUP1", arena_id="battlefield:factory_pillar_arena", start_turn=True, bench_starts=False, melee=False,
          extra_items=(), foe_hp=None, maximum_rounds=8):
    items = ([{"item_id": "tianxia.mortal.weapon.jian", "quantity": 1}] if melee else []) + [
        {"item_id": item, "quantity": 1} for item in extra_items]
    kit = {"starting_kit": {"items": items}} if items else None
    mechanics = json.loads(TYPED_AUTHORITY.read_bytes())["mechanics"]
    docs = [sheet(list(talents), mechanics=mechanics, cl=10, name="Planner", kit=kit),
            sheet(list(talents) if equal else [], mechanics=mechanics, cl=10, name="Opponent",
                  kit=kit if equal else None)]
    if foe_hp is not None:
        docs[1]["ability_scores_and_statistics"]["hit_points"]["maximum"] = foe_hp
    if band is not None:
        docs[0]["advancement_history"] = {"all_owner_locks": [{"field": "power_band", "value": band}]}
    bundles = []
    for aid, doc in zip((OWNER, FOE), docs):
        folder = tmp_path / "portable_characters" / aid.removeprefix("actor:factory.")
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
        bundle = compile_character(doc, actor_id=aid)
        if flight:
            bundle["actor_template"].update(fly_speed_ft=30, hover=True)
        bundles.append(bundle)
    combat = CombatService(ROOT, tmp_path)
    arena = combat.factory_arenas(include_retired=True)[arena_id]
    positions = {OWNER: {"x": 3, "y": 6}, FOE: foe_at or {"x": 9, "y": 5}}
    if bench_starts:
        starts = list(arena["starting_positions"].values())
        positions = {OWNER: min(starts, key=lambda p: (p["x"], p["y"])),
                     FOE: max(starts, key=lambda p: (p["x"], p["y"]))}
    mid = combat._finish_factory_match(bundles, [OWNER, FOE], {OWNER: "team:a", FOE: "team:b"},
        positions, arena, [OWNER, FOE], [],
        control_modes={OWNER: "MANUAL", FOE: "MANUAL"}, match_seed=seed, display_name="Tactics",
        maximum_rounds=maximum_rounds)["match_id"]
    session = combat._load_session(mid)
    if start_turn and session.engine.state.current_actor_id != OWNER:
        end = next(c for c in session.engine.legal_candidates() if c.kind == "END_TURN")
        session.submit_intent(ActionIntent(intent_id="aiup1:end", decision_id=end.decision_id,
            candidate_id=end.candidate_id, state_version=end.state_version, actor_id=end.actor_id),
            primary_decision_record=None, reaction_provider=None)
    return combat, mid, combat._load_session(mid)


def context_for(combat, session):
    policy, _ = combat.policies.for_actor(OWNER)
    return build_decision_context(session.engine, policy, for_ai=True)


def selected(context):
    choice = LocalDeterministicController().choose_primary_action(context)
    candidate = next(c for c in context.legal_candidates if c.candidate_id == choice.intent.candidate_id)
    return choice, candidate


