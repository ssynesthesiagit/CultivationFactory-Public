"""Wax second pass through table/service commits, cold reload and replay."""
import copy

import pytest

from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate5_service import CombatService
CLINGING = "TAL_WAX_CLINGING_SEAL"
REBUKE = "TAL_WAX_MELTING_REBUKE"
TRAIL = "TAL_WAX_WAXEN_TRAIL"
TRACE = "condition:typed.wax_tracking_trace"
NO_DASH = "condition:typed.no_dash"
from combat.typed_executor import mark_condition_id
from tests.h1_support import ROOT
from tests.test_r5i_integration import (
    PLAYER, OTHER, act, answer, candidate, check_reload, fixture, mark, seed, turn, pin_ai,
)

PRESS = "TAL_WAX_PRESS_SEAL"
MOLD = "TAL_WAX_MOLD_WAX"
HUNDRED = "TAL_WAX_HUNDRED_SEAL_CONFLAGRATION"


def commit(table, mid, cid, choices=None):
    """Use real prompt transport. Unrequested optional reactions are declined."""
    choices = choices or {}
    answers = []
    for _ in range(12):
        result = act(table, mid, cid, answers)
        if result["status"] != "REACTION_REQUIRED":
            assert result["status"] == "COMMITTED", result
            return result
        prompt = result["reaction"]
        options = choices.get(prompt["reaction"])
        if options == "first":
            options = [prompt["choice"]["options"][0]["id"]]
        answers.append(answer(result, "USE" if options else "DECLINE", options or []))
    raise AssertionError("too many choices")


def owned_seal(actor, owner=PLAYER):
    return any(c.condition_id == mark_condition_id("Wax Seal", owner) for c in actor.conditions.values())


def seal(combat, table, mid, target=OTHER):
    rows = [c for c in combat._load_session(mid).engine.legal_candidates()
            if c.display_name.startswith("Press Seal") and target in c.target_ids
            and (c.display_name == "Press Seal" or "Clinging Seal" in c.display_name)]
    cid = min(rows, key=lambda c: "Clinging Seal" not in c.display_name).candidate_id
    commit(table, mid, cid, {"Clinging Seal": ["strengthen"]})


@pytest.mark.parametrize("rebuke", [False, True])
@pytest.mark.parametrize("use", [False, True])
def test_action_attempt_releases_dash_and_rebuke_consumes_exact_seal(tmp_path, rebuke, use):
    combat, table, mid = fixture(tmp_path, [PRESS, CLINGING, *([REBUKE] if rebuke else [])])
    turn(table, mid, PLAYER)
    seal(combat, table, mid)
    engine = check_reload(combat, mid, tmp_path)
    assert owned_seal(engine.state.actors[OTHER])
    assert any(c.condition_id == NO_DASH for c in engine.state.actors[OTHER].conditions.values())
    turn(table, mid, OTHER)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    hp = before["actors"][OTHER]["current_hp"]
    cid = candidate(combat, mid, "Attempt to Remove Clinging Seal")
    first = act(table, mid, cid)
    assert first["status"] == "REACTION_REQUIRED"
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    commit(table, mid, cid, {"Attempt to Remove Clinging Seal": "first", "Melting Rebuke": ["rebuke"] if use else []})
    engine = check_reload(combat, mid, tmp_path)
    target, owner = engine.state.actors[OTHER], engine.state.actors[PLAYER]
    assert not target.action_available
    assert not any(c.condition_id == NO_DASH for c in target.conditions.values())
    assert owned_seal(target) == (not (rebuke and use))
    assert target.current_hp < hp if rebuke and use else target.current_hp == hp
    if rebuke and use:
        assert not owner.reaction_available
        impressed = next(c for c in target.conditions.values() if c.condition_id == mark_condition_id("Impressed", PLAYER))
        assert impressed.expires_on == f"END_OF_TURN_AT:{OTHER}:{target.turns_started + 1}"
        assert not any(m.source_actor_id == PLAYER and m.target_field == "speed_ft" for m in target.modifiers.values())
        commit(table, mid, table.state(mid)["menu"]["end_turn"])
        assert any(c.condition_id == impressed.condition_id for c in check_reload(combat, mid, tmp_path).state.actors[OTHER].conditions.values())
        turn(table, mid, OTHER)
        commit(table, mid, table.state(mid)["menu"]["end_turn"])
        assert not any(c.condition_id == impressed.condition_id for c in check_reload(combat, mid, tmp_path).state.actors[OTHER].conditions.values())


def setup_trail(bundle, other):
    seed(bundle, "Seed Wax", [mark("Wax Seal")], target="ANY_CREATURE")
    seed(other, "Other Wax", [{**mark("Wax Seal"), "applies_to": "self"}], target="SELF")
    seed(other, "Test teleport", [{"type": "teleport", "distance_ft": 20}], target="SELF")
    other["action_catalog"][-1].update(target_kind="CELL", range_ft=20)
    other["action_catalog"][-1]["parameters"].update(any_cell=True, self_teleport=True)
    for name in ("invisible", "polymorphed", "petrified"):
        seed(other, "Test " + name, [{"type": "condition", "applies_to": "self", "condition": name}], target="SELF")
    for name, hazards in (("tracking", ["tracking", "ordinary_terrain"]), ("unrelated", []), ("magical tracking", ["tracking"])):
        seed(bundle, "Test " + name, [{"type": "contest_against", "actor_check": {"kind": "check", "ability": "WIS", "skill": "Survival", "hazards": hazards},
            "target_check": {"kind": "dc", "dc": 10}, "on_success": [], "on_fail": []}])


@pytest.mark.parametrize("change", ["teleport", "invisible", "polymorphed", "petrified"])
def test_waxen_trail_snaps_only_its_owners_seal_at_departure(tmp_path, change):
    combat, table, mid = fixture(tmp_path, [TRAIL], configure=setup_trail)
    turn(table, mid, PLAYER)
    commit(table, mid, candidate(combat, mid, "Seed Wax", OTHER))
    turn(table, mid, OTHER)
    commit(table, mid, candidate(combat, mid, "Other Wax"))
    check_reload(combat, mid, tmp_path)
    start = combat._load_session(mid).engine.state.actors[OTHER].position
    cid = next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates()
               if c.display_name.startswith("Test " + change))
    commit(table, mid, cid, {"Test teleport": "first"} if change == "teleport" else {})
    engine = check_reload(combat, mid, tmp_path)
    if change == "teleport":
        assert engine.state.actors[OTHER].position != start
    assert not owned_seal(engine.state.actors[OTHER])
    assert owned_seal(engine.state.actors[OTHER], OTHER)
    departures = [z for z in engine.state.zones.values() if z.source_definition_id == TRAIL]
    assert len(departures) == 1 and departures[0].center == start
    assert not departures[0].trigger_profile.get("difficult")


def test_trace_tracking_is_subject_and_task_scoped_after_reload(tmp_path):
    combat, table, mid = fixture(tmp_path, [TRAIL], configure=setup_trail)
    turn(table, mid, PLAYER)
    commit(table, mid, candidate(combat, mid, "Seed Wax", OTHER))
    turn(table, mid, OTHER)
    cid = next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates()
               if c.kind.value == "MOVE" and c.destination == Position(x=5, y=6))
    commit(table, mid, cid, {"Waxen Trail": ["trace"]})
    engine = check_reload(combat, mid, tmp_path)
    assert any(c.condition_id == TRACE for c in engine.state.actors[OTHER].conditions.values())
    turn(table, mid, PLAYER)
    for name, target, mode in (("tracking", OTHER, "ADVANTAGE"), ("unrelated", OTHER, "NORMAL"),
                               ("magical tracking", OTHER, "NORMAL"), ("tracking", AN, "NORMAL")):
        before = combat._load_session(mid).engine.state.event_sequence
        commit(table, mid, candidate(combat, mid, "Test " + name, target))
        engine = check_reload(combat, mid, tmp_path)
        rolled = [e for e in engine.events if e.sequence > before and e.event_type == "CHECK_ROLLED"]
        assert rolled[-1].payload["actor"]["mode"] == mode


def test_hundred_ai_never_burns_allies_in_mixed_recipient_pool(tmp_path):
    def setup(bundle, other):
        seed(bundle, "Seed Wax", [mark("Wax Seal")], target="ANY_CREATURE")
    combat, table, mid = fixture(tmp_path, [HUNDRED], allied=True, configure=setup)
    turn(table, mid, PLAYER)
    for target in (OTHER, AN):
        commit(table, mid, candidate(combat, mid, "Seed Wax", target))
    before = combat._load_session(mid).engine
    ally_hp, enemy_hp = before.state.actors[OTHER].current_hp, before.state.actors[AN].current_hp
    pin_ai(combat, mid, PLAYER, candidate(combat, mid, "Hundred-Seal Conflagration", AN))
    result = table.auto_step(mid, 0, [])
    assert result["status"] == "COMMITTED", result
    engine = check_reload(combat, mid, tmp_path)
    assert engine.state.actors[OTHER].current_hp == ally_hp
    assert engine.state.actors[PLAYER].current_hp == before.state.actors[PLAYER].current_hp
    assert engine.state.actors[AN].current_hp < enemy_hp
    assert owned_seal(engine.state.actors[OTHER])
    assert not owned_seal(engine.state.actors[AN])


@pytest.mark.parametrize("melee", [True, False])
def test_melee_wall_damage_offers_rebuke_with_rollback_and_reload(tmp_path, melee):
    def setup(bundle, other):
        seed(other, "Attack a wall section", [{"type": "wall_attack", "count": 1}], target="CELL")
        action = other["action_catalog"][-1]
        action["economy"] = "ACTION"
        action["parameters"]["wall_attack"] = True
        action["parameters"]["any_cell"] = True
        action["range_ft"] = 5 if melee else 60
        action["parameters"]["typed"]["numbers"]["attack_bonus"] = 100
        action["parameters"]["typed"]["wall_melee"] = melee
        action["parameters"]["typed"]["wall_weapon"] = {"fixed_damage": 1, "damage_type": "SLASHING"}
    combat, table, mid = fixture(tmp_path, [MOLD, "TAL_WAX_WAX_RAMPART", REBUKE], configure=setup)
    turn(table, mid, PLAYER)
    cid = next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates()
               if "Wax Rampart: Half Cover" in c.display_name and c.destination == Position(x=5, y=6))
    commit(table, mid, cid)
    check_reload(combat, mid, tmp_path)
    turn(table, mid, OTHER)
    cid = next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates()
               if c.display_name.startswith("Attack a wall section"))
    hp = combat._load_session(mid).engine.state.actors[OTHER].current_hp
    commit(table, mid, cid, {"Melting Rebuke": ["rebuke"]})
    engine = check_reload(combat, mid, tmp_path)
    assert (engine.state.actors[OTHER].current_hp < hp) == melee
    assert any(z.active and MOLD in z.source_definition_id for z in engine.state.zones.values()) == (not melee)


def test_session_attempt_is_inert_without_a_strengthened_seal(tmp_path):
    combat, table, mid = fixture(tmp_path, [PRESS])
    turn(table, mid, PLAYER)
    engine = check_reload(combat, mid, tmp_path)
    assert not any(c.display_name == "Attempt to Remove Clinging Seal" for c in engine.legal_candidates())
    # Direct session transport, then cold service load and mechanical replay.
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    c = next(c for c in session.engine.legal_candidates() if c.kind.value == "END_TURN")
    session.mechanical.execute_intent(ActionIntent(intent_id="wax-second-pass-direct", decision_id=c.decision_id,
        candidate_id=c.candidate_id, state_version=c.state_version, actor_id=c.actor_id,
        target_ids=c.target_ids, destination=c.destination, option_ids=c.option_ids))
    check_reload(combat, mid, tmp_path)


@pytest.mark.parametrize("material,ignored", [("wax", True), ("mud", True), ("snow", True),
    ("shallow water", True), ("slick stone", True), ("rubble", False), ("thorns", False)])
def test_flowing_step_prices_each_surface_and_expires_through_service(tmp_path, material, ignored):
    from combat import zones
    def setup(bundle, other):
        seed(bundle, "Test surface", [{"type": "zone"}], target="SELF")
        bundle["action_catalog"][-1]["parameters"]["typed"]["zone_spec"] = {
            "name": material, "shape": "square", "size_ft": 5, "centered_on_self": True,
            "duration": {"kind": "rounds", "amount": 10}, "difficult": "all",
            "visual": {"material": material}, "triggers": [], "inside": []}
    combat, table, mid = fixture(tmp_path, ["TAL_WAX_FLOWING_WAX_STEP"], configure=setup)
    turn(table, mid, PLAYER)
    commit(table, mid, candidate(combat, mid, "Test surface"))
    engine = check_reload(combat, mid, tmp_path)
    zone = next(z for z in zones.typed_zones(engine) if z.source_definition_id == "test:Test surface")
    assert zones.zone_is_difficult(engine, zone, engine.state.actors[PLAYER])
    commit(table, mid, candidate(combat, mid, "Flowing Wax Step"))
    engine = check_reload(combat, mid, tmp_path)
    assert zones.zone_is_difficult(engine, engine.state.zones[zone.zone_id], engine.state.actors[PLAYER]) == (not ignored)
    commit(table, mid, table.state(mid)["menu"]["end_turn"])
    engine = check_reload(combat, mid, tmp_path)
    assert zones.zone_is_difficult(engine, engine.state.zones[zone.zone_id], engine.state.actors[PLAYER])


@pytest.mark.parametrize("dc,use,extra", [(1, True, 0), (50, False, 0), (50, True, 1)])
def test_clinging_extra_cost_is_optional_and_only_after_failure(tmp_path, dc, use, extra):
    def setup(bundle, other):
        for action in bundle["action_catalog"]:
            if action["display_name"].startswith("Press Seal"):
                action["parameters"]["typed"]["numbers"]["save_dc"] = dc
    combat, table, mid = fixture(tmp_path, [PRESS, CLINGING], configure=setup)
    turn(table, mid, PLAYER)
    before = combat._load_session(mid).engine.state.actors[PLAYER].resources["resource:core.qi"]
    rows = [c for c in combat._load_session(mid).engine.legal_candidates()
            if c.display_name.startswith("Press Seal") and OTHER in c.target_ids
            and (c.display_name == "Press Seal" or "Clinging Seal" in c.display_name)]
    cid = min(rows, key=lambda c: "Clinging Seal" not in c.display_name).candidate_id
    commit(table, mid, cid, {"Clinging Seal": ["strengthen"] if use else []})
    engine = check_reload(combat, mid, tmp_path)
    assert engine.state.actors[PLAYER].resources["resource:core.qi"] == before - 1 - extra
    assert any(c.condition_id == NO_DASH for c in engine.state.actors[OTHER].conditions.values()) == bool(extra)
