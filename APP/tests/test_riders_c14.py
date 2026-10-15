"""Rider lane C14 (owner 2026-09-30: "i want everything we can automated, keep going until its only the non-combat ones
left"): the next shared systems from the blocked-line census (/var/tmp/auto-audit/fix/BLOCKED_CENSUS.md) and the lines they
unblock. Every system runs on real compiled characters on a Gate4 engine; the persistence cases commit through
Gate4Persistence and reload the saved fight. C14_OLD=1 swaps in the authority of the base commit (riders/c12, 27ef3430): the
typing cases then fail, because the base typing has none of the new rows.

Overrides: authority/typed_mechanics/reviewed_final.d/riders_c14.json (entries moved there from the files that held them).
Plug-ins: combat/ext/area_suppression.py (row 18), combat/ext/ability_lockout.py (row 21).
"""
from __future__ import annotations

import json
import os
import subprocess

import pytest

import combat.factory_compiler as compiler
from combat import zones
from combat.ext import ability_lockout, area_suppression
from combat.gate2_runtime_models import ActionIntent
from tests import test_riders_c4 as C4
from tests.h1_support import ROOT

BASE_COMMIT = "27ef3430"
ME, FOE, ALLY = C4.ME, C4.FOE, C4.ALLY
FAIL, PASS = C4.FAIL, C4.PASS
STRAIN = "resource:named.black_vein_strain"


@pytest.fixture(autouse=True, scope="session")
def base_typing(tmp_path_factory):
    if os.environ.get("C14_OLD"):
        path = tmp_path_factory.mktemp("authority") / "base.json"
        path.write_bytes(subprocess.check_output(["git", "show", f"{BASE_COMMIT}:APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json"], cwd=ROOT))
        compiler.TYPED_AUTHORITY = path


def mech(key):
    return json.loads(compiler.TYPED_AUTHORITY.read_bytes())["mechanics"][key]


def force_d20(engine, natural):
    """Every d20 rolled from now on shows ``natural``."""
    original = getattr(engine.roller, "_real_d20", None) or engine.roller.d20
    engine.roller._real_d20 = original

    def d20(**kwargs):
        while True:
            roll = original(**kwargs)
            if int(roll.natural_result) == natural:
                return roll

    engine.roller.d20 = d20


def notes(events):
    return [str((e.payload or {}).get("log") or "") for e in events if e.event_type == "PASSIVE_TRIGGERED"]


def end_turns_until(engine, actor_id):
    while True:
        engine.end_turn()
        if engine.state.current_actor_id == actor_id:
            return


# ============================================================================================ row 18: area suppression
LATTICE, LAVA_WALL = "TAL_UNMAKING_LATTICE_UNRAVELING", "TAL_MAGMA_LAVA_WALL"


def check_bonus(engine, actor_id, name):
    numbers = engine.action_catalog[C4.action_id(engine, actor_id, name)].parameters["typed"]["numbers"]
    return int(numbers["pb"]) + int(numbers["key_mod"])


def walled(wall_dc=16, me_cl=12):
    """ME (Lattice Unraveling) at (3, 6); FOE at (14, 6) raises a Lava Wall across the line at (8, 6)."""
    engine = C4.fight(C4.bundle(LATTICE, cl=me_cl), foe=C4.bundle(LAVA_WALL, actor_id=FOE, cl=10, dc=wall_dc), foe_at=(14, 6))
    C4.turn(engine, FOE)
    C4.use(engine, "Lava Wall", at=(8, 6))
    (wall,) = [z for z in zones.typed_zones(engine) if z.owner_id == FOE]
    C4.turn(engine, ME)
    return engine, wall


def test_lattice_unraveling_lines_are_typed_and_no_longer_gm_riders():
    entry = mech(LATTICE)
    assert '"suppress_area"' in json.dumps(entry["effects"])
    assert not [r for r in entry["riders"] if str(r).startswith(("Make an Unmaking Check", "Success: Suppress", "Success by 5", "###"))]


def test_lattice_unraveling_suppresses_a_foes_wall_until_the_start_of_my_next_turn():
    engine, wall = walled(wall_dc=16)
    cells = {(c.x, c.y) for c in wall.affected_cells}
    assert cells <= engine.grid.blocked
    force_d20(engine, 16 - check_bonus(engine, ME, "Lattice Unraveling") + 2)  # success by 2: not by 5
    events = C4.use(engine, "Lattice Unraveling", at=(8, 6))
    assert [p for p in C4.payloads(events, "CHECK_ROLLED") if p["dc"] == 16 and p["success"]]
    assert wall.active and not wall.affected_cells and area_suppression.suppressed(wall)
    assert not cells & engine.grid.blocked  # the wall does nothing while suppressed
    assert any("suppresses" in line and "until the start of" in line for line in notes(events))
    assert engine.state.actors[ME].resources.get(STRAIN, 0) == 0
    engine.end_turn()  # the foe's turn: still suppressed
    assert engine.state.current_actor_id == FOE and not wall.affected_cells
    end_turns_until(engine, ME)  # the start of my next turn: it comes back
    assert {(c.x, c.y) for c in wall.affected_cells} == cells and cells <= engine.grid.blocked
    assert not area_suppression.records(wall)


def test_lattice_unraveling_success_by_five_lasts_until_the_end_of_my_next_turn():
    engine, wall = walled(wall_dc=PASS)
    events = C4.use(engine, "Lattice Unraveling", at=(8, 6))
    assert any("Success by 5 or more" in line for line in notes(events))
    end_turns_until(engine, ME)
    assert not wall.affected_cells  # still suppressed through my next turn
    engine.end_turn()
    assert wall.affected_cells


def test_lattice_unraveling_failure_suppresses_nothing_and_gives_black_vein_strain():
    engine, wall = walled(wall_dc=FAIL)
    before = len(wall.affected_cells)
    C4.use(engine, "Lattice Unraveling", at=(8, 6))
    assert len(wall.affected_cells) == before and not area_suppression.records(wall)
    assert engine.state.actors[ME].resources[STRAIN] == 1


def test_lattice_unraveling_is_offered_only_on_a_square_of_an_area_and_the_ai_only_against_a_foes():
    engine = C4.fight(C4.bundle(LATTICE, LAVA_WALL, cl=12), foe=C4.bundle(LAVA_WALL, actor_id=FOE, cl=10), foe_at=(14, 6))
    C4.turn(engine, FOE)
    C4.use(engine, "Lava Wall", at=(8, 6))
    C4.turn(engine, ME)
    C4.use(engine, "Lava Wall", at=(5, 6))
    C4.turn(engine, ME)
    walls = {z.owner_id: {(c.x, c.y) for c in z.affected_cells} for z in zones.typed_zones(engine)}
    rows = [c for c in engine.legal_candidates() if c.display_name.startswith("Lattice Unraveling")]
    squares = {(c.destination.x, c.destination.y) for c in rows}
    assert squares and squares <= walls[FOE] | walls[ME] and squares & walls[ME]  # the player may pick its own too
    me = engine.state.actors[ME]
    action = engine.action_catalog[rows[0].source_definition_id]
    for c in rows:
        allowed = area_suppression.ai_only_against_foes(engine, me, c, action)
        assert allowed is ((c.destination.x, c.destination.y) in walls[FOE])


def test_a_suppressed_wall_still_ends_with_its_concentration_and_does_not_come_back():
    engine, wall = walled(wall_dc=PASS)
    C4.use(engine, "Lattice Unraveling", at=(8, 6))
    engine._end_concentration(engine.state.actors[FOE], "TEST")
    end_turns_until(engine, ME)
    engine.end_turn()
    assert not wall.active and not wall.affected_cells and not area_suppression.records(wall)


def test_a_suppressed_wall_survives_a_table_commit_and_reload_and_still_comes_back(tmp_path):
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    me, foe = C4.bundle(LATTICE, cl=12), C4.bundle(LAVA_WALL, actor_id=FOE, cl=10, dc=PASS)
    session = persistence.create_match(match_seed="C14-WALL", typed_bundles=(me, foe), roster_setup={
        "primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
        "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 14, "y": 6}}})

    def submit(actor_id, name, at=None):
        while session.engine.state.current_actor_id != actor_id:
            c = next(c for c in session.engine.legal_candidates() if c.display_name == "End turn")
            session.submit_intent(ActionIntent(intent_id=f"end-{c.state_version}", decision_id=c.decision_id, candidate_id=c.candidate_id,
                                               state_version=c.state_version, actor_id=c.actor_id, target_ids=c.target_ids),
                                  primary_decision_record=None, reaction_provider=None)
        if name is None:
            return
        c = next(c for c in session.engine.legal_candidates() if c.display_name.startswith(name)
                 and (at is None or (c.destination.x, c.destination.y) == at))
        session.submit_intent(ActionIntent(intent_id=f"{name}-{c.state_version}", decision_id=c.decision_id, candidate_id=c.candidate_id,
                                           state_version=c.state_version, actor_id=c.actor_id, target_ids=c.target_ids,
                                           destination=c.destination), primary_decision_record=None, reaction_provider=None)

    submit(FOE, "Lava Wall", (8, 6))
    submit(ME, "Lattice Unraveling", (8, 6))
    (wall,) = [z for z in session.engine.state.zones.values() if z.owner_id == FOE]
    assert not wall.affected_cells
    loaded = persistence.load_match(session.match_id)
    again = loaded.engine.state.zones[wall.zone_id]
    assert again.model_dump(mode="json") == wall.model_dump(mode="json")
    record = area_suppression.records(again)[0]
    assert all(isinstance(v, (str, int, list)) and not isinstance(v, float) for v in record.values())
    assert not {(c.x, c.y) for c in wall.affected_cells} & loaded.engine.grid.blocked
    session = loaded
    submit(FOE, None)
    submit(ME, None)  # through my next turn (success by 5) ...
    submit(FOE, None)  # ... and it is back
    again = session.engine.state.zones[wall.zone_id]
    assert again.affected_cells and {(c.x, c.y) for c in again.affected_cells} <= session.engine.grid.blocked


def beast_fight(dc_of_beast=16):
    """FOE (Ink) calls its Painted Beast (a summoned Construct) next to ME's Lattice Unraveling user."""
    engine = C4.fight(C4.bundle(LATTICE, cl=12), foe=C4.bundle("tianxia.talent.ink.painted_beast", actor_id=FOE, cl=10, dc=dc_of_beast),
                      foe_at=(9, 6))
    C4.turn(engine, FOE)
    C4.use(engine, "Painted Beast")
    (beast,) = [a for a in engine.state.actors.values() if a.summon is not None and a.active]
    beast.maximum_hp = beast.current_hp = 500
    C4.turn(engine, ME)
    return engine, beast


def test_lattice_unraveling_on_a_summoned_construct_deals_8d10_ruin_and_disadvantage_on_its_next_save():
    engine, beast = beast_fight(dc_of_beast=PASS)
    events = C4.use(engine, "Lattice Unraveling", at=(beast.position.x, beast.position.y))
    damage = [r for r in engine.rolls if r.reason.startswith("DAMAGE:") and r.expression.startswith("8d10")]
    assert damage and beast.current_hp == 500 - damage[-1].total
    assert [p for p in C4.payloads(events, "DAMAGE_COMMITTED") if p.get("damage_type") == "RUIN"]
    (mode,) = C4.held(beast, "save_against")
    assert mode.data["rule"]["save_against"]["mode"] == "DISADVANTAGE" and mode.data["rule"]["save_against"]["next"]
    assert set(mode.data["rule"]["save_against"]["abilities"]) == {"STR", "DEX", "CON", "INT", "WIS", "CHA"}


def test_lattice_unraveling_failing_against_a_construct_still_deals_4d10_and_gives_strain():
    engine, beast = beast_fight(dc_of_beast=FAIL)
    C4.use(engine, "Lattice Unraveling", at=(beast.position.x, beast.position.y))
    damage = [r for r in engine.rolls if r.reason.startswith("DAMAGE:") and r.expression.startswith("4d10")]
    assert damage and beast.current_hp == 500 - damage[-1].total
    assert engine.state.actors[ME].resources[STRAIN] == 1 and not C4.held(beast, "save_against")


def test_lattice_unraveling_is_not_offered_against_an_ordinary_creature():
    engine = C4.fight(C4.bundle(LATTICE, cl=12), foe_at=(6, 6))
    assert not [c for c in engine.legal_candidates() if c.display_name.startswith("Lattice Unraveling")]


def test_a_suppressed_aura_stays_suppressed_as_its_creator_moves_and_comes_back_around_it():
    from combat.gate2_runtime_models import Position, ZoneState

    engine, wall = walled()
    foe = engine.state.actors[FOE]
    aura = ZoneState(zone_id="zone:test:aura", source_definition_id=wall.source_definition_id, owner_id=FOE, center=foe.position,
                     radius_cells=1, affected_cells=(), concentration_link=False, duration_rounds=10, created_round=engine.state.round_number,
                     trigger_profile={"kind": zones.KIND, "name": "Aura", "follows_owner": True, "size_ft": 10, "shape": "emanation",
                                      "triggers": [], "numbers": {"save_dc": 12}})
    aura.affected_cells = zones.area_cells(engine, aura)
    engine.state.zones[aura.zone_id] = aura
    me = engine.state.actors[ME]
    area_suppression.suppress(engine, me, aura, "START_OF_TURN_AT:%s:%d" % (ME, me.turns_started + 1), "test:suppress")
    foe.position = Position(x=12, y=6)
    zones.follow(engine, foe)
    assert aura.center == foe.position and not aura.affected_cells
    end_turns_until(engine, ME)
    assert aura.affected_cells == zones.area_cells(engine, aura) and aura.affected_cells
    assert all(abs(c.x - 12) <= 2 for c in aura.affected_cells)


# ============================================================================================ row 21: ability lockout
from tests import test_riders_c2 as C2  # noqa: E402
from tests import test_riders_c5 as C5  # noqa: E402

SMOTHER, MANDATE = "TAL_SMOKE_SMOTHER_THE_BREATH", "TAL_SMOKE_SMOTHERING_MANDATE"
CLOSING, FLAW = C2.PP + "technique_closing_point", "TAL_GLASS_FLAW_WITHIN_THE_GOLDEN_TECHNIQUE"


def place_mark(engine, holder_id, name, owner_id=ME):
    from combat.typed_executor import mark_condition_id

    engine._apply_condition(engine.state.actors[holder_id], mark_condition_id(name, owner_id), "test:mark", owner_id, expires_on="UNTIL_REMOVED")


def lockouts(actor):
    return ability_lockout.records(actor)


def offered(engine, actor_id, name):
    return any(c.display_name.startswith(name) and c.actor_id == actor_id for c in engine.legal_candidates())


def test_row_21_lines_are_typed_and_no_longer_gm_riders():
    assert '"ability_lockout"' in json.dumps(mech(CLOSING)["effects"]) and \
        not [r for r in mech(CLOSING)["riders"] if str(r).startswith(("Failed Save", "Choose one non-Secret"))]
    assert '"ability_lockout"' in json.dumps(mech(MANDATE)["modifier"]) and not mech(MANDATE)["riders"]
    assert '"ability_lockout"' in json.dumps(mech(FLAW)["effects"])
    assert "the creature cannot use the same feature again until the end of its next turn" not in mech(FLAW)["riders"]


def smothered(choice):
    """FOE bears ME's Smoke Trace and uses Scouring Hand; ME's Smother the Breath answers (FOE fails the save) and ME picks
    ``choice`` of Smothering Mandate's three."""
    engine = C4.fight(C4.bundle(SMOTHER, MANDATE, dc=FAIL), foe_at=(5, 6))
    asked = C5._answers(engine, {"effect_choices": lambda options: [next(o for o in options if o.startswith(choice))]})
    place_mark(engine, FOE, "Smoke Trace")
    C4.turn(engine, FOE)
    events = C4.use(engine, "Scouring Hand: Reduce Speed", target=ME)
    return engine, events, asked


def test_smothering_mandate_can_lock_the_breath_technique_the_creature_just_used_until_the_end_of_its_next_turn():
    engine, events, asked = smothered("It cannot use this breath or voice technique again")
    foe = engine.state.actors[FOE]
    (lock,) = lockouts(foe)
    assert lock.data["mode"] == "barred" and lock.data["ability"] == "SAND_BASE_SCOURING_HAND"
    assert [r for r in asked if "effect_choices" in str(r["reaction_source_id"])]  # the player was asked which of the three
    assert any("cannot use Scouring Hand" in line for line in notes(events))
    end_turns_until(engine, FOE)  # its next turn: still locked
    assert not offered(engine, FOE, "Scouring Hand") and offered(engine, FOE, "End turn")
    engine.end_turn()  # the end of its next turn: free again
    end_turns_until(engine, FOE)
    assert offered(engine, FOE, "Scouring Hand") and not lockouts(foe)


def test_smothering_mandate_whisper_option_silences_instead():
    engine, _, _ = smothered("It cannot speak above a whisper")
    foe = engine.state.actors[FOE]
    assert C4.held(foe, "silenced") and not lockouts(foe)


def closing_fight(save):
    engine = C2._fight(C2._pp([CLOSING], dc=50), attacker=True)
    atk = C2._ready(engine, C2.ATK)
    C2._act(engine, "Calming Heart Pill", actor_id=C2.ATK)
    C2._ready(engine, C2.ME)
    C2._pick(engine, "Technique-Closing Point")
    C2._mark(engine, C2.ATK, name="Pressure Point")
    atk.saving_throws["CON"] = atk.saving_throws["WIS"] = save
    events = C2._press(engine, C2.ATK)
    return engine, atk, events


def test_technique_closing_point_failed_save_bars_an_ability_it_has_seen_used():
    engine, atk, events = closing_fight(-40)
    (lock,) = lockouts(atk)
    assert lock.data["mode"] == "barred" and lock.data["name"] == "Calming Heart Pill"
    C2._ready(engine, C2.ATK)
    names = {c.display_name for c in engine.legal_candidates() if c.actor_id == C2.ATK}
    assert "Calming Heart Pill" not in names and "End turn" in names
    # the table says what it is and who did it
    desc = ability_lockout.describe(engine, atk, {"condition_id": ability_lockout.LOCKOUT}, lock.data)
    assert "cannot use Calming Heart Pill" in desc["text"] and desc["source_ability"]


def test_technique_closing_point_non_attacking_reuse_does_not_penalize_a_later_attack():
    engine, atk, events = closing_fight(40)
    (lock,) = lockouts(atk)
    assert lock.data["mode"] == "watch"
    C2._ready(engine, C2.ATK)
    C2._act(engine, "Calming Heart Pill", actor_id=C2.ATK)
    assert not lockouts(atk)
    assert not [m for m in atk.modifiers.values() if m.target_field == "attack_mode" and m.value == "DISADVANTAGE"]
    C2._ready(engine, C2.ATK)
    attack = next(c.display_name for c in engine.legal_candidates()
                  if c.actor_id == C2.ATK and c.display_name.endswith(" attack"))
    events = C2._act(engine, attack, actor_id=C2.ATK)
    rolls = [e.payload for e in events if e.event_type == "ATTACK_ROLLED"]
    assert rolls and all(p["mode"] == "NORMAL" for p in rolls)


def test_technique_closing_point_with_nothing_seen_locks_nothing():
    engine = C2._fight(C2._pp([CLOSING], dc=50), attacker=True)
    C2._pick(engine, "Technique-Closing Point")
    C2._mark(engine, C2.ATK, name="Pressure Point")
    events = C2._press(engine, C2.ATK)
    assert not lockouts(engine.state.actors[C2.ATK])
    assert any("has used no ability it could lock" in line for line in notes(events))


def test_an_ability_lockout_survives_a_table_commit_and_reload(tmp_path):
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    me, foe = C4.bundle(SMOTHER, MANDATE, "TAL_SMOKE_CINDER_WISP", dc=FAIL), C4.bundle("SAND_BASE_SCOURING_HAND", actor_id=FOE, cl=5)
    session = persistence.create_match(match_seed="C14-LOCK", typed_bundles=(me, foe), roster_setup={
        "primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
        "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 5, "y": 6}}})
    engine = session.engine
    C5._answers(engine, {"effect_choices": lambda options: [next(o for o in options if o.startswith("It cannot use this breath"))]})
    provider = engine._gate4_reaction_provider
    while engine.state.current_actor_id != ME:
        c = next(c for c in engine.legal_candidates() if c.display_name == "End turn")
        session.submit_intent(ActionIntent(intent_id=f"end-{c.state_version}", decision_id=c.decision_id, candidate_id=c.candidate_id,
                                           state_version=c.state_version, actor_id=c.actor_id, target_ids=c.target_ids),
                              primary_decision_record=None, reaction_provider=None)
    c = next(c for c in engine.legal_candidates() if c.display_name.startswith("Cinder Wisp") and FOE in (c.target_ids or ()))
    session.submit_intent(ActionIntent(intent_id="wisp", decision_id=c.decision_id, candidate_id=c.candidate_id, state_version=c.state_version,
                                       actor_id=c.actor_id, target_ids=c.target_ids, destination=c.destination),
                          primary_decision_record=None, reaction_provider=provider)
    from combat.typed_executor import bears_mark
    assert bears_mark(session.engine.state.actors[FOE], ME, "Smoke Trace")  # ME's Cinder Wisp left its Smoke Trace
    while engine.state.current_actor_id != FOE:
        c = next(c for c in engine.legal_candidates() if c.display_name == "End turn")
        session.submit_intent(ActionIntent(intent_id=f"end-{c.state_version}", decision_id=c.decision_id, candidate_id=c.candidate_id,
                                           state_version=c.state_version, actor_id=c.actor_id, target_ids=c.target_ids),
                              primary_decision_record=None, reaction_provider=None)
    c = next(c for c in engine.legal_candidates() if c.display_name.startswith("Scouring Hand") and ME in (c.target_ids or ()))
    session.submit_intent(ActionIntent(intent_id="scour", decision_id=c.decision_id, candidate_id=c.candidate_id,
                                       state_version=c.state_version, actor_id=c.actor_id, target_ids=c.target_ids),
                          primary_decision_record=None, reaction_provider=provider)
    foe_now = session.engine.state.actors[FOE]
    rows = lockouts(foe_now)
    assert rows
    loaded = persistence.load_match(session.match_id)
    again = lockouts(loaded.engine.state.actors[FOE])
    assert [r.model_dump(mode="json") for r in again] == [r.model_dump(mode="json") for r in rows]
    assert all(isinstance(v, (str, int, list)) for v in again[0].data.values())


def test_flaw_within_the_golden_technique_can_lock_the_triggering_technique():
    engine = C4.fight(C4.bundle(FLAW, cl=15, dc=FAIL), foe_at=(6, 6))
    asked = C5._answers(engine, {"effect_choices": lambda options: [next(o for o in options if o.startswith("It cannot use the same"))]})
    place_mark(engine, FOE, "Faultline Mark")
    C4.turn(engine, FOE)
    C4.use(engine, "Scouring Hand: Reduce Speed", target=ME)
    foe = engine.state.actors[FOE]
    assert [r for r in asked if "effect_choices" in str(r["reaction_source_id"])]
    (lock,) = lockouts(foe)
    assert lock.data["ability"] == "SAND_BASE_SCOURING_HAND" and lock.data["mode"] == "barred"
    C4.turn(engine, FOE)
    assert not offered(engine, FOE, "Scouring Hand")


def test_flaw_within_the_golden_technique_default_choice_is_still_the_damage_reduction():
    engine = C4.fight(C4.bundle(FLAW, cl=15, dc=FAIL), foe_at=(6, 6))
    place_mark(engine, FOE, "Faultline Mark")
    C4.turn(engine, FOE)
    C4.use(engine, "Scouring Hand: Reduce Speed", target=ME)
    assert not lockouts(engine.state.actors[FOE])  # an unanswered choice takes the first option (4d8 less damage)


# ============================================================================================ row 19: Midnight (a radius, no light model)
def test_midnight_darkness_grows_to_the_tables_largest_area():
    engine = C4.fight(C4.bundle("TAL_DARK_MIDNIGHT", cl=15))
    names = {c.display_name.split(" at ")[0] for c in engine.legal_candidates()}
    assert "Darkness + Midnight" in names
    C4.use(engine, "Darkness + Midnight", at=(6, 6))
    (dark,) = [z for z in zones.typed_zones(engine) if z.owner_id == ME]
    cells = {(c.x, c.y) for c in dark.affected_cells}
    # 2 miles; the table caps every area at a 60-foot radius (combat/factory_compiler.py _area_size: "a battle map is about
    # 60 feet across"), so it is the largest Darkness the table draws.
    assert dark.trigger_profile["size_ft"] == 60 and len(cells) > 200 and {(0, 0), (0, engine.grid.height - 1), (12, 0)} <= cells
    assert "Increase the radius of your Darkness to 2 miles." not in mech("TAL_DARK_MIDNIGHT")["riders"]


def test_plain_darkness_keeps_its_fifteen_foot_radius():
    engine = C4.fight(C4.bundle("TAL_DARK_MIDNIGHT", cl=15))
    C4.use(engine, "Darkness", at=(6, 6))
    (dark,) = [z for z in zones.typed_zones(engine) if z.owner_id == ME]
    assert len(dark.affected_cells) < 60


# ============================================================================================ row 20: Mountain-Felling's Damage Threshold
def test_mountain_felling_axe_body_cuts_an_objects_damage_threshold_only_while_the_form_is_on():
    from tests import test_sysv2_objects as O

    bundle = O.build("tianxia.sphere.axes", ["TAL_AXES_HEWING_INTENT", "TAL_AXES_MOUNTAIN_FELLING_AXE_BODY"], axe=True)
    engine = O.fight(bundle, objects=[{"id": 1, "kind": "barrel", "x": 4, "y": 6, "threshold": 8, "hp": 999}])
    O.force_d20(engine, 13, 19)
    plain = [O.one_hit(engine, O.AXE_ATTACK, "object:map.1")[:2] for _ in range(8)]
    assert all((taken == 0) == (rolled < 8) for taken, rolled in plain)
    pb = O.proficiency_bonus(engine, "TAL_AXES_MOUNTAIN_FELLING_AXE_BODY")
    engine.state.actors[O.ME].bonus_action_available = True
    O.use(engine, "Mountain-Felling Axe Body")
    seen = []
    for _ in range(12):
        taken, rolled, events = O.one_hit(engine, O.AXE_ATTACK, "object:map.1")
        assert (taken == 0) == (rolled < 8 - pb)
        seen.append(rolled)
        if any(8 - pb <= r < 8 for r in seen):
            notes_ = O.updates(events)[0].payload["damage"]["notes"]
            assert any("Damage Threshold 8 cut to" in n for n in notes_) or taken == 0
            break


# ============================================================================================ row 26: shared Death Control Limit
from combat import summons  # noqa: E402
from combat.factory_compiler import compile_character  # noqa: E402
from tests.h1_support import sheet as h1_sheet  # noqa: E402

GRAVE, LEGION, SERVANT = "TAL_DEATH_GRAVE_FORMATION", "TAL_DEATH_LEGION_OF_THE_RESTLESS_DEAD", "TAL_DEATH_CORPSE_SERVANT"


def death_bundle(*mids, pb=4, plan=None, actor_id=ME):
    character = h1_sheet(list(mids), cl=17)
    character["identity"]["proficiency_bonus"] = pb
    return compile_character(character, actor_id=actor_id, summon_plan=plan)


def groups_of(bundle):
    out = {}
    for creature in bundle["summons"]:
        out[creature["summon"]["group"]] = out.get(creature["summon"]["group"], 0) + 1
    return out


def test_death_servants_share_the_death_control_limit():
    assert groups_of(death_bundle(SERVANT)) == {"corpse_servant": 4}  # alone: Proficiency Bonus servants, as before
    assert groups_of(death_bundle(SERVANT, GRAVE)) == {"grave_formation": 1, "corpse_servant": 1}  # 3 + 1 = PB 4
    assert groups_of(death_bundle(SERVANT, GRAVE, LEGION, pb=6)) == {"grave_formation": 1, "legion_formation": 1}  # 3 + 3 = PB 6
    # the owner's own pick comes first: four servants leave no room for a formation
    assert groups_of(death_bundle(SERVANT, GRAVE, plan={"counts": {"corpse_servant": 4}})) == {"corpse_servant": 4}
    options = death_bundle(SERVANT, GRAVE)["summon_options"]["groups"]
    assert {row["group"]: (row["load"], row["pool_limit"]) for row in options if row.get("control")}["grave_formation"] == (3, 4)


def test_a_grave_formation_is_a_large_undead_with_a_ten_foot_grave_assault_and_one_command_for_all_death_servants():
    engine = C4.fight(death_bundle(SERVANT, GRAVE), foe_at=(12, 6))
    formation = next(a for a in engine.state.actors.values() if (a.summon or {}).get("group") == "grave_formation")
    servant = next(a for a in engine.state.actors.values() if (a.summon or {}).get("group") == "corpse_servant")
    assert formation.active and formation.creature_types == ("Undead",)
    assert engine._footprint(formation.entity_id).width_cells == 2
    assert formation.maximum_hp == 10 * 17 and formation.armor_class == 12 + 4
    assault = [engine.action_catalog[a] for a in formation.action_ids if engine.action_catalog[a].display_name == "Grave Assault"]
    assert {a.range_ft for a in assault} == {10} and {a.parameters.get("hp_band") for a in assault} == {"above_half", "half_or_less"}
    commands = [c for c in engine.legal_candidates() if c.display_name.startswith("Command")]
    assert [c.display_name for c in commands] == ["Command Death servants"]
    C4.use(engine, "Command Death servants")
    assert formation.summon["commanded"] and servant.summon["commanded"]


def test_a_grave_formation_keeps_its_large_footprint_after_a_table_commit_and_reload(tmp_path):
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    me, foe = death_bundle(SERVANT, GRAVE), C4.bundle("SAND_BASE_SCOURING_HAND", actor_id=FOE, cl=5)
    session = persistence.create_match(match_seed="C14-GRAVE", typed_bundles=(me, foe), roster_setup={
        "primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
        "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 12, "y": 6}}})
    formation_id = next(a.entity_id for a in session.engine.state.actors.values() if (a.summon or {}).get("group") == "grave_formation")
    # Footprints now belong to each saved fight, never a process-wide registry.
    loaded = persistence.load_match(session.match_id)
    assert loaded.engine._footprint(formation_id).width_cells == 2
    assert loaded.engine.state.actors[formation_id].model_dump(mode="json") == session.engine.state.actors[formation_id].model_dump(mode="json")


def test_row_26_lines_are_no_longer_gm_riders():
    assert not [r for r in mech(GRAVE)["riders"] if "Control Load" in r or "commanded according" in r]
    assert not [r for r in mech(LEGION)["riders"] if "up to two Grave Formations" in r]
    assert "You may maintain any number of Corpse Servants up to your Death Control Limit." not in mech(SERVANT)["riders"]


# ============================================================================================ row 30: lengthening a push or pull
LASH, WEIGHTED = "TAL_CHAINS_CHAIN_LASH_BASE", "tianxia.talent.chains.weighted_links"
STORM, DOMAIN, GRAVITIC_PUSH = "TAL_AIR_STORM_WITHOUT_DIRECTION", "tianxia.talent.gravity.gravity_domain", "tianxia.talent.gravity.gravitic_push"


def moved_ft(engine, events, actor_id):
    rows = [e for e in events if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == actor_id and (e.payload or {}).get("forced")]
    return sum((len(e.payload["path"]) - 1) * 5 for e in rows)


def lash_push(engine, target=FOE):
    C4.turn(engine, ME)
    engine.state.actors[target].armor_class = -50
    return C4.use(engine, "Chain Lash: Push 5 Feet", target=target)


def test_weighted_links_lengthens_a_chain_lash_push_by_five_feet():
    engine = C4.fight(C4.bundle(LASH, WEIGHTED, cl=17), foe_at=(5, 6))
    assert moved_ft(engine, lash_push(engine), FOE) == 10
    plain = C4.fight(C4.bundle(LASH, cl=17), foe_at=(5, 6))
    assert moved_ft(plain, lash_push(plain), FOE) == 5


def test_storm_without_direction_no_fixed_direction_lengthens_any_push_on_a_hostile_inside():
    engine = C4.fight(C4.bundle(STORM, LASH, cl=17), foe_at=(5, 6))
    C4.use(engine, "Storm Without Direction: No Fixed Direction")
    assert moved_ft(engine, lash_push(engine), FOE) == 15
    other = C4.fight(C4.bundle(STORM, LASH, cl=17), foe_at=(5, 6))
    C4.use(other, "Storm Without Direction: No Straight Line")  # another choice: no longer push
    assert moved_ft(other, lash_push(other), FOE) == 5


def test_gravity_domain_lengthens_only_its_owners_gravity_pushes_inside_it():
    engine = C4.fight(C4.bundle(DOMAIN, GRAVITIC_PUSH, LASH, cl=4, dc=FAIL), foe_at=(5, 6))
    C4.use(engine, "Gravity Domain")
    C4.turn(engine, ME)
    events = C4.use(engine, "Gravitic Push", target=FOE)
    assert moved_ft(engine, events, FOE) == 25  # "up to 15 feet" + 10 inside the Domain
    engine.state.actors[FOE].position = engine.state.actors[FOE].position.model_copy(update={"x": 6})
    assert moved_ft(engine, lash_push(engine), FOE) == 5  # Chain Lash is not a Gravity talent


def test_row_30_lines_are_no_longer_gm_riders():
    assert not [r for r in mech(DOMAIN)["riders"] if "Forced movement caused by your Gravity talents" in r]
    # AUTO Air now executes this clause (the movement test above covers it).
    assert not [r for r in mech(STORM)["riders"] if str(r).startswith("No Fixed Direction")]
    assert not [r for r in mech(WEIGHTED)["riders"] if "increase that movement by 5 feet" in r]


# ============================================================================================ row 33: seams already in base
def test_meridian_sealing_pill_denies_every_cp_gain_including_direct_ones():
    from combat import typed_executor

    engine = C4.fight(C4.bundle("TAL_ALCHEMY_MERIDIAN_SEALING_PILL", cl=10, dc=FAIL), foe_at=(5, 6))
    source = C4.action_id(engine, ME, "Meridian-Sealing Pill")
    ctx = C4.ctx_of(engine, ME, FOE, source, dc=FAIL)
    typed_executor.run_effects(ctx, ctx.typed["effects"])
    foe = engine.state.actors[FOE]
    foe.resources["resource:core.qi"] = 10
    engine._gain_resource(foe, "resource:core.qi", 5, "test:direct")  # a plug-in's or legacy direct gain (gate2's resource_gain_allowed)
    assert foe.resources["resource:core.qi"] == 10
    assert not [r for r in mech("TAL_ALCHEMY_MERIDIAN_SEALING_PILL")["riders"] if "blocked" in str(r)]


# ============================================================================================ row 27: Concentration saves
def test_opening_phrase_adds_the_proficiency_bonus_to_the_next_concentration_save_and_is_used_up():
    from tests import test_riders_lane10 as L10

    _, e, me, foe = L10._song()
    friend = L10._friend(e, me)
    L10.SWF.cast(e, "Keep the Measure")
    me.bonus_action_available = True
    L10.SWF.cast(e, "Opening Phrase: Concentration Save", target=friend.entity_id)
    held = [c for c in friend.conditions.values() if c.condition_id == "condition:typed.music_opening_save"]
    assert held and held[0].data["concentration"] == 1 and "Concentration saving throw" in held[0].data["label"]
    before = len(e.events)
    e._concentration_check(friend, 30)  # the engine's own Concentration save (DC 15)
    rolled = [p for p in C4.payloads(e.events[before:], "SAVE_ROLLED")][0]
    assert rolled["modifier"] == int(friend.saving_throws["CON"]) + me.proficiency_bonus
    assert not [c for c in friend.conditions.values() if c.condition_id == "condition:typed.music_opening_save"]  # one save only
    before = len(e.events)
    e._concentration_check(friend, 30)
    assert C4.payloads(e.events[before:], "SAVE_ROLLED")[0]["modifier"] == int(friend.saving_throws["CON"])
    assert not [r for r in mech("MUSIC_BASE_OPENING_PHRASE")["riders"] if "typed as Advantage" in str(r)]


def test_meridian_stillness_field_takes_away_advantage_on_concentration_saves_of_marked_foes_inside():
    from combat import concentration

    engine = C2._fight(C2._pp([C2.PP + "meridian_stillness_field"], cl=17, dc=50), attacker=True, foe_at=(8, 6))
    atk = engine.state.actors[C2.ATK]
    engine._apply_condition(atk, concentration.MODE, "test:steady", C2.ATK, expires_on="UNTIL_REMOVED",
                            data={"rule": {"concentration_mode": "ADVANTAGE"}})
    assert concentration.save_mode(engine, atk) == "ADVANTAGE"
    names = sorted(n for n in C2._names(engine) if n.startswith("Meridian Stillness Field"))
    C2._act(engine, next((n for n in names if n.endswith("at 8,6")), names[0]))
    assert concentration.save_mode(engine, atk) == "ADVANTAGE"  # not marked yet
    C2._mark(engine, C2.ATK, name="Pressure Point")
    assert concentration.save_mode(engine, atk) is None
    engine._apply_condition(atk, concentration.MODE, "test:shaken", C2.ATK, expires_on="UNTIL_REMOVED",
                            data={"rule": {"concentration_mode": "DISADVANTAGE"}})
    assert concentration.save_mode(engine, atk) == "DISADVANTAGE"  # only Advantage is taken away


def test_suppressing_two_squares_of_a_wall_opens_only_those_and_they_close_again():
    engine, wall = walled()
    me = engine.state.actors[ME]
    cells = sorted(((c.x, c.y) for c in wall.affected_cells), key=lambda xy: xy[1])
    gap = [c for c in wall.affected_cells if (c.x, c.y) in set(cells[3:5])]
    record = area_suppression.suppress(engine, me, wall, "START_OF_TURN_AT:%s:%d" % (ME, me.turns_started + 1), "test:painted_gap", gap)
    assert record["all"] == 0 and sorted(map(tuple, record["cells"])) == sorted(cells[3:5])
    assert not set(cells[3:5]) & engine.grid.blocked and set(cells) - set(cells[3:5]) <= engine.grid.blocked
    assert not area_suppression.suppressed(wall)  # the rest of the wall still stands
    end_turns_until(engine, ME)
    assert sorted((c.x, c.y) for c in wall.affected_cells) == sorted(cells) and set(cells) <= engine.grid.blocked
