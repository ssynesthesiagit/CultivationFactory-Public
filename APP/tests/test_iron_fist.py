"""The Iron Fist sphere (owner 2026-09-28, "automate every aspect"): the Iron Fist Die, talents that change the Unarmed
Strike, Openings and Open the Gate; and a Meld that grants its own action (Step Through Darkness)."""

from pathlib import Path

from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate4_engine import Gate4ControllerEngine
from combat.typed_executor import bears_mark
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.fist"
IRON_FIST = ["TAL_IRON_FIST_IRON_FIST_TRAINING", "TAL_IRON_FIST_BREAKING_KNUCKLE"]


def _bundle(talents, sphere="tianxia.sphere.iron_fist"):
    return compile_character({**SHEET, "equipment": [], "spheres_and_talents": {"sphere_record_ids": [sphere], "learned_talent_record_ids": talents}},
                             actor_id=ME)


def _engine(bundle, foe_at=(4, 6)):
    engine = Gate4ControllerEngine(ROOT, match_seed="FIST", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": foe_at[0], "y": foe_at[1]}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine


def test_the_iron_fist_die_and_its_talents_on_the_unarmed_strike():
    bundle = _bundle(IRON_FIST)
    strike = next(row for row in bundle["action_catalog"] if row["display_name"] == "Unarmed Strike (Iron Fist)")
    damage = strike["parameters"]["typed"]["weapon"]["damage"]
    assert (damage["count"], damage["sides"]) == (1, 10)  # CL 5-10, both hands free
    knuckle = next(row for row in bundle["modifiers"] if row["name"] == "Breaking Knuckle")
    assert knuckle["status"] == "applied" and "Unarmed Strike (Iron Fist)" in knuckle["applied"]
    assert any(row["display_name"] == "Open the Gate: Hooking Step" for row in bundle["action_catalog"])


def test_a_damaging_unarmed_strike_opens_the_target_and_opens_the_gate_once_a_turn():
    engine = _engine(_bundle(IRON_FIST))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    hits = 0
    for attempt in range(6):  # until a hit lands (the dice decide)
        strike = next((c for c in engine.legal_candidates() if c.display_name == "Unarmed Strike (Iron Fist)"), None)
        if strike is None:
            break
        engine.execute_intent(ActionIntent(intent_id=f"s{attempt}", decision_id=strike.decision_id, candidate_id=strike.candidate_id,
                                           state_version=strike.state_version, actor_id=ME, target_ids=strike.target_ids))
        if bears_mark(foe, ME, "Opened"):
            hits += 1
            break
        engine.state.current_actor_id = ME
        me.action_available = True
    assert hits == 1 and me.turn_flags.get("open_the_gate")
    assert any(e.event_type == "GM_RIDER" and "Open the Gate: Centerline Impact" in str((e.payload or {}).get("rider")) for e in engine.events)


def test_step_through_darkness_is_a_bonus_action_teleport_from_darkness_into_darkness():
    bundle = _bundle(["DARK_BASE_DARKNESS", "TAL_DARK_STEP_THROUGH_DARKNESS"], sphere="tianxia.sphere.dark")
    step = next(row for row in bundle["action_catalog"] if row["display_name"] == "Step Through Darkness")
    assert step["economy"] == "BONUS_ACTION" and step["parameters"]["typed"]["teleport_where"] == "darkness"
    engine = _engine(bundle, foe_at=(14, 6))
    assert not [c for c in engine.legal_candidates() if c.display_name.startswith("Step Through Darkness")]  # not in darkness
    darkness = next(c for c in engine.legal_candidates() if c.display_name.startswith("Darkness") and c.destination == Position(x=5, y=6))
    engine.execute_intent(ActionIntent(intent_id="dark", decision_id=darkness.decision_id, candidate_id=darkness.candidate_id,
                                       state_version=darkness.state_version, actor_id=ME, target_ids=darkness.target_ids, destination=darkness.destination))
    steps = [c for c in engine.legal_candidates() if c.display_name.startswith("Step Through Darkness to")]
    assert steps and all(abs(c.destination.x - 5) <= 3 and abs(c.destination.y - 6) <= 3 for c in steps)
