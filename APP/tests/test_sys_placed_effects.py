"""Automation push 2026-09-29, system "placed effects": things a creature puts on the map that act later (owner: "i want everything
we can automated, keep going until its only the non-combat ones left").  Section 1: Traps (combat/ext/trap.py on the shared
placement store combat/ext/placed.py).  Section 2: Blossoms of the Flowers sphere (combat/ext/blossom.py, same store).
Section 3: Puppet vessels of the Puppetry sphere (combat/ext/vessel.py, same store).  Section 4: Figments of the Illusion sphere
(combat/ext/figment.py, same store).  Section 5: the Banner Cultivator's Command Banner (combat/ext/banner.py, same store).  Section 6: Cut the Road Behind You of the Space sphere (combat/ext/seal.py, same store).  Section 7: Safe Return Mark of the Space sphere (combat/ext/return_mark.py, same store).

Every test compiles a real Trap character, runs its buttons through the engine and reads what the printed rules say happens
(rule text in authority/typed_mechanics/rules_text.json, sphere "Trap"); each fails without the plug-in (there was no Set Trap
button: the sphere was a rider line only).  Foe saves are forced with a -50/+50 Dexterity save bonus, attacks always hit (foe AC -50);
a walk is a committed move (MOVEMENT_COMMITTED with its path, then zones.on_moved) -- the engine's own move loop is not needed to
show what a trap does to the mover.
"""

from __future__ import annotations

import pytest

from types import SimpleNamespace

from combat import condition_text, ext, typed_executor, zones
from combat.factory_compiler import compile_character
from combat.ext import banner, blossom, placed, return_mark, seal, trap
from combat.gate2_rolls import DeterministicRollAuthority
from combat.tabletop_service import TabletopService
from combat.typed_executor import bears_mark
from combat.gate2_runtime_models import ActionIntent, Position
from combat import typed_reactions
from tests.test_auto_lane1 import ALLY, AN, ME, _ally_bundle, _engine, _held, _payloads, _ready, _sheet

FOCUS = "resource:core.martial_focus"


# ------------------------------------------------------------------------------------------------------- harness


SHIELD = {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.armor.shield', 'name': 'Shield', 'quantity': 1}]}}


def _trapper(*talents, cl=10, dc=16, kit=None):
    sheet = _sheet("TAL_TRAP_TRAPPED_SHIELD", cl=cl, dc=dc)  # any Trap talent: gives the sphere and its base abilities
    sheet["spheres_and_talents"]["learned_talent_record_ids"] = list(talents)
    if kit:
        sheet["equipment"] = [kit]
    return compile_character(sheet, actor_id=ME)


def _pick(engine, name, at=None, target=None, actor=ME):
    """Use a legal button by name (a Set Trap / Disarm Trap button also by the square it points at, or the creature it targets);
    ``actor`` presses it on that creature's turn."""
    cands = [c for c in engine.legal_candidates() if c.display_name == name or c.display_name.startswith(name + " at")
             or c.metadata.get('effect_origin') and engine.action_catalog[c.source_definition_id].display_name==name]
    if target is not None:
        cands = [c for c in cands if tuple(c.target_ids or ()) == (target,)]
    if at is not None:
        cands = [c for c in cands if c.destination is not None and (c.destination.x, c.destination.y) == at]
    assert cands, f"{name!r} at {at} is not legal; legal: {sorted({c.display_name for c in engine.legal_candidates()})[:50]}"
    cand, before = cands[0], len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"i-{name}-{before}", decision_id=cand.decision_id, candidate_id=cand.candidate_id,
                                       state_version=cand.state_version, actor_id=actor, target_ids=cand.target_ids or (), destination=cand.destination))
    return engine.events[before:]


def _scene(*talents, picks=(), cl=10, foe_dex_save=-50, kit=None):
    """The trapper on (3,6), the foe two squares away on (2,5) so it can walk over (3,5) to (4,5); its Dexterity saves forced."""
    engine = _engine(_trapper(*talents, cl=cl, kit=kit))
    for name in picks:
        _pick(engine, name)
    foe = engine.state.actors[AN]
    foe.saving_throws["DEX"] = foe_dex_save
    foe.position = Position(x=2, y=5)
    return engine


def _walk(engine, actor_id, cells):
    """A committed move over ``cells`` (the squares entered, in order)."""
    actor = engine.state.actors[actor_id]
    start = actor.position
    path = [{"x": start.x, "y": start.y}, *[{"x": x, "y": y} for x, y in cells]]
    actor.position = Position(x=cells[-1][0], y=cells[-1][1])
    engine.state.current_actor_id = actor_id
    before = len(engine.events)
    engine._append_event("MOVEMENT_COMMITTED", "test:walk", actor_id=actor_id, payload={"path": path, "destination": path[-1]})
    zones.on_moved(engine, actor, start, actor.position)
    engine.state.current_actor_id = ME
    return engine.events[before:]


def _traps(engine):
    return placed.of(engine, "trap")


def _lines(events):
    return [p["text"] for p in _payloads(events, "PASSIVE_TRIGGERED") if p.get("text")]


def _foe(engine):
    return engine.state.actors[AN]


def _conditions(actor):
    return sorted(c.condition_id.split(".")[-1] for c in actor.conditions.values() if c.condition_id != trap.SETUP)  # the setup marker is the picks


def _damage_dice(events):
    return [p["expression"] for p in _payloads(events, "DAMAGE_ROLLED")]


# ----------------------------------------------------------------------------------------------- the Trap sphere is a system now


def test_the_trap_sphere_compiles_to_set_trap_and_its_setup_buttons_not_a_gm_line():
    bundle = _trapper("TAL_TRAP_NOOSE", "TAL_TRAP_FALSE_TRIGGER", "TAL_TRAP_TRAP_WIELDER")
    names = {row["display_name"] for row in bundle["action_catalog"]}
    assert {"Set Trap", "Trap form: Dart Mechanism", "Trap form: Tripwire", "Trap form: Noose", "Trap trigger: False Trigger",
            "Trap deployment: Trap Wielder", "Trap aim: east", "Disarm Trap", "Escape the net"} <= names
    assert "Trap form: Flash Trap" not in names  # a form is offered only to a character that owns its talent
    assert "Trap trigger: False Trigger" in names and "Trap trigger: Warning Trigger" not in names
    skipped = {row.get("id") if isinstance(row, dict) else row for row in bundle.get("skipped", ())}
    assert not {"TAL_TRAP_NOOSE", "TAL_TRAP_FALSE_TRIGGER", "TAL_TRAP_TRAP_WIELDER"} & skipped


def test_set_trap_costs_one_martial_focus_and_puts_a_trap_within_reach_only():
    engine = _engine(_trapper())
    me = engine.state.actors[ME]
    assert me.resources[FOCUS] == 1
    squares = {(c.destination.x, c.destination.y) for c in engine.legal_candidates() if c.display_name.startswith("Set Trap") and c.destination}
    assert (3, 5) in squares and (3, 6) not in squares  # not the space you stand on: "an unoccupied space within your reach"
    assert (3, 8) not in squares and (3, 10) not in squares  # beyond 5 feet
    events = _pick(engine, "Set Trap", at=(3, 5))
    assert me.resources[FOCUS] == 0
    assert [(z.center.x, z.center.y) for z in _traps(engine)] == [(3, 5)]
    assert any("set a trap" in line for line in _lines(events))
    assert "Set Trap" not in {c.display_name for c in engine.legal_candidates()}  # Martial Focus spent, none to set another


def test_a_trap_is_recorded_on_the_map_so_a_saved_fight_replays_it():
    engine = _scene()
    events = _pick(engine, "Set Trap", at=(3, 5))
    created = _payloads(events, "ZONE_CREATED")
    assert len(created) == 1 and created[0]["zone"]["trigger_profile"]["placed"]["tag"] == "trap"
    assert created[0]["zone"]["duration_rounds"] == 10  # "lasts for 1 minute"


# ------------------------------------------------------------------------------------------------------------ Dart Mechanism


@pytest.mark.parametrize("cl, dice", [(4, "1d6"), (5, "2d6"), (10, "2d6"), (11, "3d6"), (17, "4d6")])
def test_dart_mechanism_damage_dice_follow_the_cultivation_level_table(cl, dice):
    engine = _scene(picks=("Trap aim: east",), cl=cl)
    _pick(engine, "Set Trap", at=(3, 5))
    foe = _foe(engine)
    hp = foe.current_hp
    events = _walk(engine, AN, [(3, 5), (4, 5)])
    assert _damage_dice(events) == [dice + "+0"]  # "CL 1-4: 1d6, CL 5-10: 2d6, CL 11-16: 3d6, CL 17-20: 4d6"
    assert foe.current_hp < hp
    assert not _traps(engine)  # "a trap is destroyed after it triggers"
    assert engine.state.actors[ME].resources[FOCUS] == 0


def test_a_dart_flies_along_its_line_and_hits_only_what_stands_in_it():
    engine = _scene(picks=("Trap aim: west",))  # away from where the foe walks to
    _pick(engine, "Set Trap", at=(3, 5))
    events = _walk(engine, AN, [(3, 5), (4, 5)])
    assert _damage_dice(events) == []
    assert any("strikes nothing" in line for line in _lines(events))


def test_aimed_shot_fires_at_the_creature_that_triggered_it_with_a_d8():
    engine = _scene("TAL_TRAP_AIMED_SHOT", picks=("Trap form: Dart Mechanism + Aimed Shot", "Trap aim: west"))
    _pick(engine, "Set Trap", at=(3, 5))
    events = _walk(engine, AN, [(3, 5), (4, 5)])
    assert _damage_dice(events) == ["2d8+0"]  # the aim square is ignored: "target the creature that triggers the trap"


def test_a_creature_that_only_crosses_the_trap_still_triggers_it():
    """Default Trigger: "even if that creature crosses several spaces occupied by the same trap" -- the trap is sprung by a square in
    the middle of a path, not only the one the mover stops on."""
    engine = _scene("TAL_TRAP_AIMED_SHOT", picks=("Trap form: Dart Mechanism + Aimed Shot",))
    _pick(engine, "Set Trap", at=(3, 5))
    events = _walk(engine, AN, [(3, 5), (4, 5), (5, 5), (6, 5)])
    assert _damage_dice(events) == ["2d8+0"] and not _traps(engine)


def test_a_trap_does_not_trigger_on_the_creature_that_set_it_or_a_creature_that_never_enters_it():
    engine = _scene("TAL_TRAP_AIMED_SHOT", picks=("Trap form: Dart Mechanism + Aimed Shot",))
    _pick(engine, "Set Trap", at=(3, 5))
    assert _damage_dice(_walk(engine, AN, [(2, 4), (2, 3)])) == []
    assert len(_traps(engine)) == 1


def test_damage_type_forms_use_their_own_dice_and_type():
    for talent, pick, sides, dtype in (("TAL_TRAP_BLUNT_DART", "Trap form: Dart Mechanism + Blunt Dart", 10, "BLUDGEONING"),
                                       ("TAL_TRAP_DEADLY_DART", "Trap form: Dart Mechanism + Deadly Dart (Slashing)", 10, "SLASHING")):
        engine = _scene(talent, picks=(pick, "Trap aim: east"))
        _pick(engine, "Set Trap", at=(3, 5))
        events = _walk(engine, AN, [(3, 5), (4, 5)])
        assert _damage_dice(events) == [f"2d{sides}+0"], talent
        assert _payloads(events, "DAMAGE_COMMITTED")[0].get("damage_type", dtype).upper() == dtype


# --------------------------------------------------------------------------------------------- Tripwire, Net, Noose, Flash


def test_tripwire_knocks_a_creature_prone_and_stays_set_but_a_prone_creature_does_not_trigger_it():
    engine = _scene(picks=("Trap form: Tripwire",))
    _pick(engine, "Set Trap", at=(3, 5))
    _walk(engine, AN, [(3, 5), (4, 5)])
    assert _conditions(_foe(engine)) == ["prone"]
    assert len(_traps(engine)) == 1  # "A Tripwire is not destroyed when it triggers"
    _foe(engine).position = Position(x=2, y=5)
    events = _walk(engine, AN, [(3, 5)])  # still Prone: does not trigger it again
    assert not any("sprang" in line for line in _lines(events))


def test_a_creature_that_saves_against_a_tripwire_learns_where_it_is_and_saves_with_advantage_next_time():
    engine = _scene(picks=("Trap form: Tripwire",), foe_dex_save=50)
    _pick(engine, "Set Trap", at=(3, 5))
    assert AN in placed.data(_traps(engine)[0])["aware"]  # it watched the trap being set: "aware" from the start
    placed.update(engine, _traps(engine)[0], aware=[])  # (say it looked away)
    _walk(engine, AN, [(3, 5)])
    assert _conditions(_foe(engine)) == []
    zone = _traps(engine)[0]
    assert AN in placed.data(zone)["aware"]  # "Successful Save: ... becomes aware of the trap"
    ctx = trap._ctx_for(engine, engine.state.actors[ME], zone)
    ctx.typed["source"] = f"trap:{zone.zone_id}"
    assert trap.trap_save_modes(ctx, _foe(engine), "DEX", set()) == {"modes": ["ADVANTAGE"]}


def test_noose_restrains_and_the_creature_can_try_to_escape_against_the_save_dc():
    engine = _scene("TAL_TRAP_NOOSE", picks=("Trap form: Noose",))
    _pick(engine, "Set Trap", at=(3, 5))
    _walk(engine, AN, [(3, 5)])
    foe = _foe(engine)
    # Rider lane C4 2026-09-30: "While Restrained by this noose, it also cannot speak, supply Verbal components" -- Silenced now
    # (combat/speech.py exists), linked to the noose's Restrained and released with it below.
    assert _conditions(foe) == ["netted", "restrained", "silenced"]
    assert not _traps(engine)
    # the netted creature has an "Escape the net" button of its own only when it has compiled one; the escape effect is the rule under test
    action = next(a for a in engine.action_catalog.values() if a.display_name == "Escape the net")
    typed_ctx = typed_executor.Context(engine, foe, action, None, {"numbers": {"save_dc": 16}}, [foe], foe, {})
    foe.saving_throws["DEX"] = 0
    trap.trap_escape(typed_ctx, {"bonus": 100})  # +100: the check beats DC 16
    assert _conditions(foe) == []


def test_net_snare_and_net_dart_are_two_uses_of_the_same_talent():
    engine = _scene("tianxia.talent.trap.net", picks=("Trap form: Net (Snare use)",))
    _pick(engine, "Set Trap", at=(3, 5))
    _walk(engine, AN, [(3, 5)])
    assert _conditions(_foe(engine)) == ["netted", "restrained"]
    engine = _scene("tianxia.talent.trap.net", picks=("Trap form: Net (Dart use)", "Trap aim: east"))
    _pick(engine, "Set Trap", at=(3, 5))
    _walk(engine, AN, [(3, 5), (4, 5)])
    assert _conditions(_foe(engine)) == ["netted", "restrained"]


def test_flash_trap_blinds_every_creature_within_five_feet_including_its_setter():
    engine = _scene("TAL_TRAP_FLASH_TRAP", picks=("Trap form: Flash Trap",))
    me = engine.state.actors[ME]
    me.saving_throws["DEX"] = -50
    _pick(engine, "Set Trap", at=(3, 5))
    _walk(engine, AN, [(3, 5)])
    assert _conditions(_foe(engine)) == ["blinded"]
    assert _conditions(me) == ["blinded"]  # (3,6) is within 5 feet of (3,5): "each creature within 5 feet of the trap"


def test_razor_wire_adds_slashing_damage_to_the_tripwire():
    engine = _scene("TAL_TRAP_RAZOR_WIRE", picks=("Trap form: Tripwire + Razor Wire",))
    _pick(engine, "Set Trap", at=(3, 5))
    events = _walk(engine, AN, [(3, 5)])
    assert _damage_dice(events) == ["2d6+0"] and _conditions(_foe(engine)) == ["prone"]


def test_alarm_trap_only_makes_a_noise_and_is_used_up():
    engine = _scene("TAL_TRAP_ALARM_TRAP", picks=("Trap form: Alarm Trap",))
    _pick(engine, "Set Trap", at=(3, 5))
    events = _walk(engine, AN, [(3, 5)])
    assert any("300 feet" in line for line in _lines(events)) and not _traps(engine)


def test_terrain_trap_makes_twelve_squares_of_difficult_terrain_for_ten_rounds():
    engine = _scene("TAL_TRAP_TERRAIN_TRAP", picks=("Trap form: Terrain Trap",))
    _pick(engine, "Set Trap", at=(3, 5))
    _walk(engine, AN, [(3, 5)])
    fields = placed.of(engine, "terrain_trap")
    assert len(fields) == 1 and len(fields[0].affected_cells) == 12  # "a 10-foot-radius area" of 5-foot squares
    assert fields[0].duration_rounds == 10 and fields[0].trigger_profile["difficult"] == "all"
    assert engine.state.zones.get(fields[0].zone_id) is not None


def test_terrain_trap_sprung_at_once_needs_no_creature_to_step_on_it():
    engine = _scene("TAL_TRAP_TERRAIN_TRAP", picks=("Trap form: Terrain Trap (sprung at once)",))
    events = _pick(engine, "Set Trap", at=(3, 5))
    assert len(placed.of(engine, "terrain_trap")) == 1 and any("at once" in line for line in _lines(events))


# ---------------------------------------------------------------------------------------- triggers and ways of setting it


def test_false_trigger_clicks_the_first_time_and_fires_the_second_with_disadvantage_on_the_save():
    engine = _scene("TAL_TRAP_FALSE_TRIGGER", picks=("Trap form: Tripwire", "Trap trigger: False Trigger"))
    _pick(engine, "Set Trap", at=(3, 5))
    placed.update(engine, _traps(engine)[0], aware=[])  # the foe did not see it set
    events = _walk(engine, AN, [(3, 5)])
    assert any("only clicks" in line for line in _lines(events)) and _conditions(_foe(engine)) == []
    zone = _traps(engine)[0]
    assert placed.data(zone)["false_used"] is True
    ctx = trap._ctx_for(engine, engine.state.actors[ME], zone)
    ctx.typed["source"] = f"trap:{zone.zone_id}"
    assert trap.trap_save_modes(ctx, _foe(engine), "DEX", set()) == {"modes": ["DISADVANTAGE"]}
    engine.state.round_number += 1  # a trap triggers "the first time on a turn": the next turn it is dangerous
    _foe(engine).position = Position(x=2, y=5)
    _walk(engine, AN, [(3, 5)])
    assert _conditions(_foe(engine)) == ["prone"]


def test_warning_trigger_lets_the_warned_pass_but_not_the_others():
    engine = _scene("TAL_TRAP_WARNING_TRIGGER", picks=("Trap form: Tripwire", "Trap trigger: Warning Trigger"))
    _pick(engine, "Set Trap", at=(3, 5))
    assert ME in placed.data(_traps(engine)[0])["warned"]
    _walk(engine, AN, [(3, 5)])  # the foe was not warned
    assert _conditions(_foe(engine)) == ["prone"]
    me = engine.state.actors[ME]
    me.saving_throws["DEX"] = -50
    _walk(engine, ME, [(3, 5)])
    assert _conditions(me) == []


def test_trap_wielder_springs_the_trap_at_once_in_a_creatures_own_space():
    engine = _scene("TAL_TRAP_TRAP_WIELDER", picks=("Trap form: Tripwire", "Trap deployment: Trap Wielder"))
    _foe(engine).position = Position(x=4, y=6)
    squares = {(c.destination.x, c.destination.y) for c in engine.legal_candidates() if c.display_name.startswith("Set Trap") and c.destination}
    assert squares == {(4, 6)}  # only the space of a creature within reach
    events = _pick(engine, "Set Trap", at=(4, 6))
    assert _conditions(_foe(engine)) == ["prone"] and not _traps(engine)  # sprung, then a Tripwire set this way falls apart
    assert any("at once" in line for line in _lines(events))


def test_chained_mechanism_springs_a_second_trap_after_the_first():
    engine = _scene("TAL_TRAP_CHAINED_MECHANISM", "TAL_TRAP_AIMED_SHOT",
                    picks=("Trap form: Dart Mechanism + Aimed Shot", "Trap trigger: Chained Mechanism"))
    me = engine.state.actors[ME]
    _pick(engine, "Set Trap", at=(3, 5))
    me.resources[FOCUS], me.action_available = 1, True
    _pick(engine, "Set Trap", at=(2, 6))
    assert len(_traps(engine)) == 2
    events = _walk(engine, AN, [(3, 5)])
    assert len(_damage_dice(events)) == 2 and not _traps(engine)  # the chained one fired at the same creature, then both fell apart


def test_the_trap_limit_is_the_proficiency_bonus_and_the_oldest_falls_apart():
    engine = _scene()
    me = engine.state.actors[ME]
    pb = 4  # the sheet's proficiency bonus
    squares = [(2, 6), (2, 7), (3, 7), (4, 7), (4, 5)]
    for square in squares:
        me.resources[FOCUS] = 1
        me.action_available = True
        _pick(engine, "Set Trap", at=square)
    assert len(_traps(engine)) == pb  # PB 4 at this sheet: the fifth set made the first fall apart
    assert (2, 6) not in {(z.center.x, z.center.y) for z in _traps(engine)}


def test_trapped_shield_darts_the_creature_that_misses_the_shield_bearer_in_melee():
    engine = _scene("TAL_TRAP_TRAPPED_SHIELD", picks=("Trap deployment: Trapped Shield", "Trap aim: east"), kit=SHIELD)
    _pick(engine, "Set Trap", at=(3, 5))
    zone = _traps(engine)[0]
    assert (zone.center.x, zone.center.y) == (3, 6) and placed.data(zone)["shield"]  # it rides its bearer
    foe, me = _foe(engine), engine.state.actors[ME]
    foe.position = Position(x=4, y=6)
    me.reaction_available = True
    action = next(iter(engine.action_catalog.values()))
    typed_ctx = typed_executor.Context(engine, foe, action, None, {"numbers": {"pb": 4}, "range_ft": None}, [me], me, {})
    before = len(engine.events)
    ext.run("attack_resolved", typed_ctx, me, False, {})  # a melee attack of the foe that missed the bearer
    events = engine.events[before:]
    assert _damage_dice(events) == ["2d6+0"] and not me.reaction_available and not _traps(engine)  # the Dart Mechanism's own dice
    # a hit, or a ranged miss, does nothing
    engine2 = _scene("TAL_TRAP_TRAPPED_SHIELD", picks=("Trap deployment: Trapped Shield",), kit=SHIELD)
    _pick(engine2, "Set Trap", at=(3, 5))
    me2, foe2 = engine2.state.actors[ME], _foe(engine2)
    foe2.position = Position(x=4, y=6)
    me2.reaction_available = True
    action = next(iter(engine2.action_catalog.values()))
    for hit, rng in ((True, None), (False, 60)):
        ctx = typed_executor.Context(engine2, foe2, action, None, {"numbers": {"pb": 4}, "range_ft": rng}, [me2], me2, {})
        ext.run("attack_resolved", ctx, me2, hit, {})
    assert _traps(engine2) and me2.reaction_available


def test_trappers_recovery_regains_martial_focus_once_when_a_creature_fails_a_save_against_the_trap():
    engine = _scene("TAL_TRAP_TRAPPER_S_RECOVERY", picks=("Trap form: Tripwire",))
    me = engine.state.actors[ME]
    _pick(engine, "Set Trap", at=(3, 5))
    assert me.resources[FOCUS] == 0
    _ready(engine)
    events = _walk(engine, AN, [(3, 5)])
    assert me.resources[FOCUS] == 1 and not me.reaction_available
    gained = [p for p in _payloads(events, "RESOURCE_GAINED") if p["resource_id"] == FOCUS]
    assert len(gained) == 1  # the generic reaction row is gone: the plug-in's is the only one


# --------------------------------------------------------------------------------------- finding and disarming a trap


def test_a_search_finds_a_hidden_trap_and_the_finder_can_then_disarm_it():
    engine = _scene(picks=("Trap aim: east",))
    _pick(engine, "Set Trap", at=(3, 5))
    zone = _traps(engine)[0]
    foe = _foe(engine)
    placed.update(engine, zone, aware=[e for e in placed.data(zone)["aware"] if e != AN])  # the foe did not see it set
    action = next(iter(engine.action_catalog.values()))
    ctx = typed_executor.Context(engine, foe, action, None, {"numbers": {"pb": 4}}, [foe], foe, {})
    ext.run("after_search", ctx, {"bonus": 100})  # a Perception check that beats the DC
    assert AN in placed.data(_traps(engine)[0])["aware"]
    assert any("noticed a trap" in line for line in _lines(engine.events[-6:]))


def test_the_trapper_disarms_its_own_trap_without_a_roll():
    engine = _scene(picks=("Trap aim: east",))
    _pick(engine, "Set Trap", at=(3, 5))
    engine.state.actors[ME].action_available = True
    events = _pick(engine, "Disarm Trap", at=(3, 5))
    assert not _traps(engine) and not _payloads(events, "CHECK_ROLLED")
    assert any("disarmed" in line for line in _lines(events))


def test_a_failed_disarm_by_five_or_more_sets_the_trap_off_on_the_one_who_tried():
    engine = _scene("TAL_TRAP_AIMED_SHOT", picks=("Trap form: Dart Mechanism + Aimed Shot",))
    _pick(engine, "Set Trap", at=(3, 5))
    zone = _traps(engine)[0]
    foe = _foe(engine)
    placed.update(engine, zone, aware=[*placed.data(zone)["aware"], AN])
    foe.position = Position(x=3, y=4)
    action = next(a for a in engine.action_catalog.values() if a.display_name == "Disarm Trap")
    ctx = typed_executor.Context(engine, foe, action, ActionIntent(intent_id="x", decision_id="d", candidate_id="c", state_version=0, actor_id=AN,
                                                                 destination=Position(x=3, y=5)),
                                 {"numbers": {"pb": 4}}, [foe], foe, {})
    hp = foe.current_hp
    trap.trap_disarm(ctx, {"bonus": -100})  # fails by far more than 5
    assert foe.current_hp < hp and not _traps(engine)
    engine2 = _scene("TAL_TRAP_AIMED_SHOT", picks=("Trap form: Dart Mechanism + Aimed Shot",))
    _pick(engine2, "Set Trap", at=(3, 5))
    zone2, foe2 = _traps(engine2)[0], _foe(engine2)
    placed.update(engine2, zone2, aware=[*placed.data(zone2)["aware"], AN])
    ctx2 = typed_executor.Context(engine2, foe2, action, ActionIntent(intent_id="x", decision_id="d", candidate_id="c", state_version=0, actor_id=AN,
                                                                     destination=Position(x=3, y=5)),
                                  {"numbers": {"pb": 4}}, [foe2], foe2, {})
    trap.trap_disarm(ctx2, {"bonus": 100})  # succeeds
    assert not _traps(engine2) and _damage_dice(engine2.events[-8:]) == []


# =============================================================================================================== Blossoms (Flowers)
# Rule text: authority/typed_mechanics/rules_text.json, TAL_FLOWERS_* and tianxia.talent.flowers.* (Sphere Compendium, "Core Flower
# Rules").  Without combat/ext/blossom.py the sphere compiled a Cultivate Blossom action with no effects and every Blossom talent
# was a rider line.  The gardener stands on (3,6) with an ally on (3,7) and the foe on (4,6).

CP = "resource:core.qi"
KNOWN = ["TAL_FLOWERS_MEDICINAL_BLOSSOM", "TAL_FLOWERS_THORNED_BLOOM", "TAL_FLOWERS_EXPLODING_SEED", "TAL_FLOWERS_SCENTED_TRACE",
         "TAL_FLOWERS_TRAVELING_GARDEN", "TAL_FLOWERS_FLOWER_OF_FALSE_DEATH", "tianxia.talent.flowers.spirit_lotus",
         "tianxia.talent.flowers.corpse_blooming_flower", "tianxia.talent.flowers.ten_thousand_bloom_scripture", "TAL_FLOWERS_DELAYED_BLOOM",
         "TAL_FLOWERS_IMMEDIATE_BLOOM", "TAL_FLOWERS_UNWILLING_CREATURE", "TAL_FLOWERS_CULTIVATE_BLOSSOM"]


def _gardener(*talents, cl=17, dc=16):
    sheet = _sheet("TAL_FLOWERS_MEDICINAL_BLOSSOM", cl=cl, dc=dc)
    sheet["spheres_and_talents"]["learned_talent_record_ids"] = list(talents or KNOWN)
    return compile_character(sheet, actor_id=ME)


def _bed(*talents, picks=(), cl=17):
    """The gardener with an ally (wounded to 20 HP) beside it; the foe's saves forced to fail."""
    engine = _engine(_gardener(*talents, cl=cl), allies=(_ally_bundle(),))
    for name in picks:
        _pick(engine, name)
    engine.state.actors[ALLY].current_hp = 20
    engine.state.actors[AN].saving_throws["DEX"] = -50
    engine.state.actors[AN].saving_throws["WIS"] = -50
    engine.state.actors[AN].saving_throws["CON"] = -50
    return engine


def _me(engine):
    return engine.state.actors[ME]


def _blossoms(engine):
    return placed.of(engine, "blossom")


def _dice(events):
    return [d.removesuffix("+0") for d in _damage_dice(events)]


def _turn(engine, actor_id, boundary):
    engine._append_event(boundary, "test:turn", actor_id=actor_id)


def _refresh(engine):
    _ready(engine)
    _me(engine).resources[CP] = 30


def _plant(engine, at, name="Cultivate Blossom"):
    _refresh(engine)
    return _pick(engine, name, at=at)


def _bloom(engine, at, name="Delayed Bloom"):
    _refresh(engine)
    return _pick(engine, name, at=at)


def _hp(engine, actor_id):
    return engine.state.actors[actor_id].current_hp


def test_the_flowers_sphere_compiles_to_cultivate_delayed_bloom_and_its_pickers_not_an_effectless_action():
    bundle = _gardener()
    names = {row["display_name"] for row in bundle["action_catalog"]}
    assert {"Cultivate Blossom", "Cultivate Blossom (bloom at once)", "Delayed Bloom", "Remove Blossom", "Blossom: Thorned Bloom (2 CP)",
            "Seed damage: Poison", "Lotus: Piercing Petals", "Corpse flower: Funeral Medicine", "Traveling Garden: leave the field where it blooms",
            "Delayed Bloom (Scripture, no action)", "Ten-Thousand Bloom Scripture"} <= names
    assert not [row for row in bundle["action_catalog"] if row["source_definition_id"].endswith((".TAL_FLOWERS_CULTIVATE_BLOSSOM", ".TAL_FLOWERS_DELAYED_BLOOM"))]
    assert not any("Traveling Garden" in n and n.startswith("Cultivate") for n in names)  # its augment button is gone: the plug-in owns the Garden
    plain = {row["display_name"] for row in _gardener("TAL_FLOWERS_MEDICINAL_BLOSSOM")["action_catalog"]}
    assert "Cultivate Blossom" in plain and "Blossom: Thorned Bloom (2 CP)" not in plain and "Delayed Bloom (Scripture, no action)" not in plain
    assert "Remove Blossom" in {row["display_name"] for row in _gardener("TAL_FLOWERS_MEDICINAL_BLOSSOM")["action_catalog"]}


def test_a_blossom_is_planted_on_an_ally_within_sixty_feet_and_shows_on_the_map_and_the_bearer():
    engine = _bed()
    events = _plant(engine, (3, 7))
    (zone,) = _blossoms(engine)
    assert (zone.center.x, zone.center.y) == (3, 7) and placed.data(zone)["state"] == "dormant" and zone.duration_rounds == 600  # 1 hour
    assert [c.condition_id for c in engine.state.actors[ALLY].conditions.values()] == [blossom.CARRIED]
    assert any("cultivated a Blossom" in line for line in _lines(events))
    assert created_tag(events) == "blossom"
    _ready(engine)
    squares = {(c.destination.x, c.destination.y) for c in engine.legal_candidates() if c.display_name.startswith("Cultivate Blossom at") and c.destination}
    assert (3, 8) in squares and (3, 7) in squares and (4, 6) in squares  # an unoccupied square, a creature: an ally or a foe
    assert (3, 6) in squares  # yourself: a willing creature


def created_tag(events):
    return _payloads(events, "ZONE_CREATED")[0]["zone"]["trigger_profile"]["placed"]["tag"]


@pytest.mark.parametrize("cl, dice", [(5, "1d8"), (10, "1d8"), (11, "2d8"), (16, "2d8"), (17, "3d8")])
def test_medicinal_blossom_heals_by_cultivation_level_and_costs_one_cp(cl, dice):
    engine = _bed(cl=cl)
    _plant(engine, (3, 7))
    events = _bloom(engine, (3, 7))
    assert _dice(events)[0].startswith(dice)
    assert _payloads(events, "RESOURCE_SPENT")[0]["amount"] == 1  # "1 CP"
    assert _hp(engine, ALLY) > 20 and not _blossoms(engine) and not _held(engine.state.actors[ALLY], blossom.CARRIED)  # withers after blooming


def test_medicinal_blossom_heals_a_creature_only_once_per_short_rest():
    engine = _bed()
    _plant(engine, (3, 7))
    _bloom(engine, (3, 7))
    healed = _hp(engine, ALLY)
    engine.state.actors[ALLY].current_hp = 20
    _plant(engine, (3, 7))
    events = _bloom(engine, (3, 7))
    assert _hp(engine, ALLY) == 20 and healed > 20  # "only once per short rest": nobody left to heal
    assert any("withers" in line for line in _lines(events)) and not _blossoms(engine)


def test_cultivate_with_an_immediate_bloom_blooms_in_the_same_action_and_pays_the_cp():
    engine = _bed()
    events = _plant(engine, (3, 7), "Cultivate Blossom (bloom at once)")
    assert _hp(engine, ALLY) > 20 and not _blossoms(engine) and _payloads(events, "RESOURCE_SPENT")[0]["amount"] == 1
    _me(engine).resources[CP] = 0
    _ready(engine)
    assert not [c for c in engine.legal_candidates() if c.display_name.startswith("Cultivate Blossom (bloom at once)")]  # no CP: not offered


def test_a_delayed_bloom_needs_a_dormant_blossom_of_yours_at_that_square_and_a_bonus_action():
    engine = _bed()
    _refresh(engine)
    assert not [c for c in engine.legal_candidates() if c.display_name.startswith("Delayed Bloom")]
    _plant(engine, (3, 7))
    _refresh(engine)
    _me(engine).bonus_action_available = False
    assert not [c for c in engine.legal_candidates() if c.display_name.startswith("Delayed Bloom at")]
    _me(engine).bonus_action_available = True
    assert [c.destination for c in engine.legal_candidates() if c.display_name.startswith("Delayed Bloom at")] == [Position(x=3, y=7)]


def test_the_dormant_limit_is_the_proficiency_bonus_and_the_oldest_withers():
    engine = _bed()
    for square in [(2, 7), (2, 8), (3, 8), (4, 8), (5, 8)]:
        _plant(engine, square)
    cells = [(z.center.x, z.center.y) for z in _blossoms(engine)]
    assert len(cells) == 4 and (2, 7) not in cells  # PB 4 on this sheet: the fifth made the first wither


def test_an_unwilling_creature_is_cultivated_by_a_ranged_cultivation_attack_and_a_miss_does_nothing():
    engine = _bed()
    events = _plant(engine, (4, 6))
    assert _payloads(events, "ATTACK_ROLLED") and [(z.center.x, z.center.y) for z in _blossoms(engine)] == [(4, 6)]
    assert placed.data(_blossoms(engine)[0])["willing"] is False
    engine = _bed()
    engine.state.actors[AN].armor_class = 500  # only a natural 20 can hit this
    hits = 0
    for _ in range(3):
        _plant(engine, (4, 6))
        hits = len(_blossoms(engine))
    assert hits <= 1  # "Miss: No effect" (a natural 20 may hit)


def test_remove_blossom_lets_the_bearer_throw_a_visible_blossom_away_with_an_action():
    engine = _bed()
    _plant(engine, (4, 6))
    foe = _foe(engine)
    assert _held(foe, blossom.CARRIED)
    engine.state.current_actor_id = AN
    foe.action_available = True
    action = next(a for a in engine.action_catalog.values() if a.display_name == "Remove Blossom" and a.owner_id == ME)
    ctx = typed_executor.Context(engine, foe, action, None, {"numbers": {"pb": 4}}, [foe], foe, {})
    assert blossom.blossom_candidates(engine, foe, type("C", (), {"destination": None})(), action) is True
    blossom.remove(ctx, {"type": "blossom_remove"})
    assert not _held(foe, blossom.CARRIED) and not _blossoms(engine)
    assert blossom.blossom_candidates(engine, foe, type("C", (), {"destination": None})(), action) is False


def test_thorned_bloom_is_a_ten_foot_field_of_difficult_terrain_that_hurts_a_creature_that_enters_it():
    engine = _bed(picks=("Blossom: Thorned Bloom (2 CP)",))
    _plant(engine, (6, 6))
    events = _bloom(engine, (6, 6))
    (zone,) = _blossoms(engine)
    assert len(zone.affected_cells) == 13 and zone.trigger_profile["difficult"] == "all" and (zone.center.x, zone.center.y) == (6, 6)
    assert _payloads(events, "RESOURCE_SPENT")[0]["amount"] == 2 and _me(engine).concentration is not None
    assert _me(engine).concentration.zone_id == zone.zone_id
    foe = _foe(engine)
    foe.position = Position(x=6, y=3)  # the field is every square within 2 of (6,6): 10 feet
    hp = foe.current_hp
    events = _walk(engine, AN, [(6, 4)])
    assert _dice(events) == ["6d6"] and foe.current_hp < hp  # CL 17: 6d6 Piercing, Dexterity save failed
    assert _dice(_walk(engine, AN, [(6, 5)])) == []  # "only once per turn"
    engine.state.round_number += 1
    before = len(engine.events)
    zones.on_turn_start(engine, foe)  # "or starts its turn inside": it is still there
    assert _dice(engine.events[before:]) == ["6d6"]


def test_thorned_bloom_dice_follow_the_level_and_a_successful_save_takes_half():
    for cl, dice in ((5, "2d6"), (11, "4d6")):
        engine = _bed(picks=("Blossom: Thorned Bloom (2 CP)",), cl=cl)
        _plant(engine, (6, 6))
        _bloom(engine, (6, 6))
        _foe(engine).position = Position(x=6, y=3)
        assert _dice(_walk(engine, AN, [(6, 4)])) == [dice]
    engine = _bed(picks=("Blossom: Thorned Bloom (2 CP)",))
    _plant(engine, (6, 6))
    _bloom(engine, (6, 6))
    foe = _foe(engine)
    foe.saving_throws["DEX"] = 50
    foe.position = Position(x=6, y=3)
    events = _walk(engine, AN, [(6, 4)])
    dealt = sum(p["hp_damage"] for p in _payloads(events, "DAMAGE_COMMITTED"))
    assert 0 < dealt <= 18  # a saved 6d6: half of at most 36


def test_traveling_garden_anchors_the_field_to_an_unwilling_bearer_that_fails_its_wisdom_save_and_costs_one_more():
    engine = _bed(picks=("Blossom: Thorned Bloom (2 CP)",))
    _plant(engine, (4, 6))
    events = _bloom(engine, (4, 6))
    (zone,) = _blossoms(engine)
    assert _payloads(events, "RESOURCE_SPENT")[0]["amount"] == 3  # "+1 CP"
    assert zone.trigger_profile["anchor_id"] == AN and placed.data(zone)["garden"] is True
    (anchor,) = _held(_foe(engine), blossom.ANCHORED)
    assert anchor.data["repeat_save"] == {"ability": "WIS", "dc": 16, "when": "end"}
    _foe(engine).position = Position(x=8, y=6)
    zones.follow(engine, _foe(engine))
    assert (zone.center.x, zone.center.y) == (8, 6)  # the area moves with the bearer


def test_traveling_garden_stays_put_when_the_bearer_saves_or_the_garden_is_switched_off():
    engine = _bed(picks=("Blossom: Thorned Bloom (2 CP)",))
    _foe(engine).saving_throws["WIS"] = 50
    _plant(engine, (4, 6))
    events = _bloom(engine, (4, 6))
    (zone,) = _blossoms(engine)
    assert _payloads(events, "RESOURCE_SPENT")[0]["amount"] == 3 and not zone.trigger_profile.get("anchor_id") and not _held(_foe(engine), blossom.ANCHORED)
    assert any("resisted" in line for line in _lines(events))
    engine = _bed(picks=("Blossom: Thorned Bloom (2 CP)", "Traveling Garden: leave the field where it blooms"))
    _plant(engine, (4, 6))
    events = _bloom(engine, (4, 6))
    assert _payloads(events, "RESOURCE_SPENT")[0]["amount"] == 2 and not _blossoms(engine)[0].trigger_profile.get("anchor_id")


def test_the_garden_anchor_ends_when_the_bearer_makes_its_repeat_save():
    engine = _bed(picks=("Blossom: Thorned Bloom (2 CP)",))
    _plant(engine, (4, 6))
    _bloom(engine, (4, 6))
    (zone,) = _blossoms(engine)
    foe = _foe(engine)
    foe.saving_throws["WIS"] = 50
    engine._expire_typed_for_checkpoint("END_OF_TURN", AN)  # the engine's own repeat save at the end of the bearer's turn
    assert not _held(foe, blossom.ANCHORED) and not zone.trigger_profile.get("anchor_id")


def test_exploding_seed_explodes_at_the_end_of_the_casters_next_turn_in_a_ten_foot_radius():
    engine = _bed(picks=("Blossom: Exploding Seed (3 CP)",))
    _plant(engine, (6, 6))
    events = _bloom(engine, (6, 6))
    assert _payloads(events, "RESOURCE_SPENT")[0]["amount"] == 3
    assert placed.data(_blossoms(engine)[0])["state"] == "seed"
    foe = _foe(engine)
    foe.position = Position(x=6, y=8)  # 10 feet from the seed
    _turn(engine, ME, "TURN_ENDED")
    assert _blossoms(engine) and foe.current_hp == foe.maximum_hp  # not yet: "until the end of your next turn"
    engine.state.round_number += 1
    events = _walk_none(engine)
    assert not _blossoms(engine) and foe.current_hp < foe.maximum_hp
    assert "8d6" in _dice(events) and any("explodes" in line for line in _lines(events))
    assert _hp(engine, ALLY) == 20  # the ally on (3,7) is outside the 10-foot radius of (6,6)


def _walk_none(engine):
    before = len(engine.events)
    _turn(engine, ME, "TURN_ENDED")
    return engine.events[before:]


def test_exploding_seed_can_be_poison_and_a_carrier_can_remove_it_before_it_goes_off():
    engine = _bed(picks=("Blossom: Exploding Seed (3 CP)", "Seed damage: Poison"))
    _plant(engine, (4, 6))
    _bloom(engine, (4, 6))
    foe = _foe(engine)
    assert placed.data(_blossoms(engine)[0])["damage"] == "poison" and _held(foe, blossom.CARRIED)  # a seed stays on its carrier
    engine.state.round_number += 1
    events = _walk_none(engine)
    types = [p["damage_type"] for p in _payloads(events, "DAMAGE_COMMITTED")]
    assert types == ["POISON"] * 3 and not _held(foe, blossom.CARRIED)  # "Creatures inside": the gardener and its ally stand within 10 feet too
    engine = _bed(picks=("Blossom: Exploding Seed (3 CP)",))
    _plant(engine, (4, 6))
    _bloom(engine, (4, 6))
    foe = _foe(engine)
    action = next(a for a in engine.action_catalog.values() if a.display_name == "Remove Blossom" and a.owner_id == ME)
    blossom.remove(typed_executor.Context(engine, foe, action, None, {"numbers": {"pb": 4}}, [foe], foe, {}), {})
    engine.state.round_number += 1
    _walk_none(engine)
    assert foe.current_hp == foe.maximum_hp and not _blossoms(engine)  # removed before it detonates


def test_scented_trace_marks_a_creature_and_an_unwilling_one_can_shake_it_off():
    engine = _bed(picks=("Blossom: Scented Trace (1 CP)",))
    _plant(engine, (4, 6))
    events = _bloom(engine, (4, 6))
    assert len(_held(_foe(engine), blossom.TRACE_ON)) == 1 and any("direction" in line and "miles" in line for line in _lines(events))
    assert _payloads(events, "RESOURCE_SPENT")[0]["amount"] == 1 and not _blossoms(engine)
    engine = _bed(picks=("Blossom: Scented Trace (1 CP)",))
    _foe(engine).saving_throws["DEX"] = 50
    _plant(engine, (4, 6))
    events = _bloom(engine, (4, 6))
    assert not _held(_foe(engine), blossom.TRACE_ON) and any("shook off" in line for line in _lines(events))
    engine = _bed(picks=("Blossom: Scented Trace (1 CP)",))
    _plant(engine, (3, 7))
    _bloom(engine, (3, 7))
    assert len(_held(engine.state.actors[ALLY], blossom.TRACE_ON)) == 1  # a willing creature has no save


def test_spirit_lotus_restores_the_most_wounded_ally_at_the_end_of_the_casters_turn():
    engine = _bed(picks=("Blossom: Spirit Lotus (6 CP)",))
    _plant(engine, (3, 8))
    events = _bloom(engine, (3, 8))
    (zone,) = _blossoms(engine)
    assert placed.data(zone)["state"] == "lotus" and _payloads(events, "RESOURCE_SPENT")[0]["amount"] == 6 and _me(engine).concentration is not None
    events = _walk_none(engine)
    assert _hp(engine, ALLY) > 20 and _dice(events)[0].startswith("2d8")
    assert _held(engine.state.actors[ALLY], blossom.LOTUS_USED)


def test_spirit_lotus_flings_petals_when_nobody_is_hurt_and_purifies_a_frightened_ally():
    engine = _bed(picks=("Blossom: Spirit Lotus (6 CP)", "Lotus: Piercing Petals"))
    _plant(engine, (3, 8))
    _bloom(engine, (3, 8))
    foe = _foe(engine)
    events = _walk_none(engine)
    assert foe.current_hp < foe.maximum_hp and "3d8" in _dice(events)
    engine = _bed(picks=("Blossom: Spirit Lotus (6 CP)", "Lotus: Purifying Pollen"))
    _plant(engine, (3, 8))
    _bloom(engine, (3, 8))
    ally = engine.state.actors[ALLY]
    engine._apply_condition(ally, "condition:typed.frightened", "test", AN, expires_on="UNTIL_REMOVED", data={"repeat_save": {"ability": "WIS", "dc": 1, "when": "end"}})
    events = _walk_none(engine)
    assert any("Purifying Pollen" in line for line in _lines(events)) and not _held(ally, "condition:typed.frightened")


def test_flower_of_false_death_keeps_an_ally_with_your_blossom_at_one_hp_and_hides_it():
    engine = _bed()
    ally = engine.state.actors[ALLY]
    _plant(engine, (3, 7))
    _refresh(engine)
    ally.current_hp = 8
    left = typed_reactions._offer_drop_to_zero_or_bloodied(engine, ally, engine.state.actors[AN], 30, 0, AN)
    assert ally.current_hp - left == 1 or left == 7  # "drops to 1 HP instead"
    assert _me(engine).resources[CP] == 24 and not _me(engine).reaction_available  # 6 CP and the Reaction
    assert _held(ally, "condition:typed.invisible") and _held(ally, blossom.FALSE_DEATH_USED)
    (zone,) = _blossoms(engine)  # the attached Blossom bloomed; "a blossom appears where the creature would have fallen"
    assert (zone.center.x, zone.center.y) == (3, 7) and placed.data(zone)["state"] == "dormant" and placed.data(zone)["bearer"] is None
    _ready(engine)
    ally.current_hp = 8
    _plant(engine, (3, 7))  # a second Blossom on the same creature: once per long rest per creature
    _refresh(engine)
    assert typed_reactions._offer_drop_to_zero_or_bloodied(engine, ally, engine.state.actors[AN], 30, 0, AN) == 30


def test_flower_of_false_death_needs_one_of_your_blossoms_attached_to_the_creature():
    engine = _bed()
    ally = engine.state.actors[ALLY]
    _refresh(engine)
    ally.current_hp = 8
    assert typed_reactions._offer_drop_to_zero_or_bloodied(engine, ally, engine.state.actors[AN], 30, 0, AN) == 30
    assert _me(engine).reaction_available and _me(engine).resources[CP] == 30


def test_flower_of_false_death_also_saves_the_caster_with_its_own_blossom():
    engine = _bed()
    me = _me(engine)
    _plant(engine, (3, 6))
    _refresh(engine)
    me.current_hp = 8
    typed_reactions._offer_drop_to_zero_or_bloodied(engine, me, engine.state.actors[AN], 30, 0, AN)
    assert _held(me, "condition:typed.invisible") and _held(me, blossom.FALSE_DEATH_USED)


def test_corpse_blooming_flower_grows_where_a_creature_died_and_heals_an_ally_at_the_start_of_the_casters_turn():
    engine = _bed()
    foe = _foe(engine)
    _refresh(engine)
    typed_reactions.on_creature_event(engine, foe, "any_drop_to_zero")
    (zone,) = _blossoms(engine)
    assert placed.data(zone)["state"] == "corpse" and (zone.center.x, zone.center.y) == (4, 6) and _me(engine).resources[CP] == 26  # 4 CP
    engine.state.actors[ALLY].position = Position(x=4, y=7)
    events = _walk_none_start(engine)
    assert _hp(engine, ALLY) > 20 and "2d8" in "".join(_dice(events)) and any("Funeral Medicine" in line for line in _lines(events))
    _refresh(engine)
    typed_reactions.on_creature_event(engine, foe, "any_drop_to_zero")
    assert len(_blossoms(engine)) == 1  # "Only one may exist at a time"


def _walk_none_start(engine):
    before = len(engine.events)
    _turn(engine, ME, "TURN_STARTED")
    return engine.events[before:]


def test_corpse_blooming_flower_lets_grave_pollen_hurt_an_enemy_when_chosen_and_ignores_a_summon():
    engine = _bed(picks=("Corpse flower: Grave Pollen (Necrotic)",))
    engine.state.actors[ALLY].position = Position(x=9, y=9)
    _refresh(engine)
    dying = engine.state.actors[ALLY]
    dying.summon = {"kind": "summon"}
    typed_reactions.on_creature_event(engine, dying, "any_drop_to_zero")
    assert not _blossoms(engine)  # "cannot be created from ... temporary summons"
    dying.summon = None
    engine.state.actors[ALLY].position = Position(x=4, y=7)
    typed_reactions.on_creature_event(engine, dying, "any_drop_to_zero")
    foe = _foe(engine)
    events = _walk_none_start(engine)
    assert foe.current_hp < foe.maximum_hp and "3d8" in _dice(events)


def test_ten_thousand_bloom_scripture_doubles_the_limit_and_makes_two_blossoms_per_cultivate():
    engine = _bed()
    _refresh(engine)
    _pick(engine, "Ten-Thousand Bloom Scripture")
    assert _held(_me(engine), blossom.SCRIPTURE_ON) and blossom._limit(blossom._kit(engine, _me(engine)), _me(engine)) == 8  # twice PB
    _plant(engine, (2, 7))
    assert len(_blossoms(engine)) == 2  # "Cultivate Blossom may create two"
    for square in [(2, 8), (3, 8), (4, 8), (5, 8)]:
        _plant(engine, square)
    assert len(_blossoms(engine)) == 8  # ten made, eight kept
    engine = _bed()
    _plant(engine, (2, 7))
    assert len(_blossoms(engine)) == 1


def test_the_scripture_makes_the_first_blossom_talent_each_turn_cost_one_less_but_never_below_one():
    engine = _bed(picks=("Blossom: Thorned Bloom (2 CP)",))
    _refresh(engine)
    _pick(engine, "Ten-Thousand Bloom Scripture")
    _plant(engine, (6, 6))
    first = _bloom(engine, (6, 6))
    assert _payloads(first, "RESOURCE_SPENT")[0]["amount"] == 1  # Thorned Bloom is 2 CP: "1 fewer"
    _refresh(engine)
    _me(engine).turn_flags["blossom_discount_used"] = True
    assert blossom._cost(engine, _me(engine), blossom._kit(engine, _me(engine)), "thorned", False) == 2  # only the first each turn
    assert blossom._cost(engine, _me(engine), blossom._kit(engine, _me(engine)), "medicinal", False) == 1  # minimum 1 (flag set: no discount either way)
    _me(engine).turn_flags.clear()
    assert blossom._cost(engine, _me(engine), blossom._kit(engine, _me(engine)), "medicinal", False) == 1  # 1 - 1, minimum 1


def test_remove_blossom_button_lets_the_caster_throw_a_blossom_off_itself():
    engine = _bed()
    me = _me(engine)
    assert "Remove Blossom" not in {c.display_name for c in engine.legal_candidates()}  # nothing rides it
    _plant(engine, (3, 6))
    assert _held(me, blossom.CARRIED)
    _ready(engine)
    events = _pick(engine, "Remove Blossom")
    assert not _held(me, blossom.CARRIED) and not _blossoms(engine) and any("removed a Blossom" in line for line in _lines(events))


def test_the_scriptures_free_delayed_bloom_needs_no_bonus_action_and_works_once_a_turn():
    engine = _bed(picks=("Blossom: Thorned Bloom (2 CP)",))
    _refresh(engine)
    _pick(engine, "Ten-Thousand Bloom Scripture")
    _plant(engine, (6, 6))
    _refresh(engine)
    _me(engine).bonus_action_available = False
    events = _pick(engine, "Delayed Bloom (Scripture, no action)", at=(6, 6))
    assert _payloads(events, "RESOURCE_SPENT")[0]["amount"] == 1  # Thorned Bloom 2 CP, "1 fewer"
    assert not _me(engine).bonus_action_available  # (still spent: nothing was taken from it)
    assert not [c for c in engine.legal_candidates() if c.display_name.startswith("Delayed Bloom (Scripture")]  # once per turn


def test_without_the_cp_a_blossom_stays_dormant_and_the_bloom_is_not_offered():
    engine = _bed(picks=("Blossom: Spirit Lotus (6 CP)",))
    _plant(engine, (3, 8))
    _refresh(engine)
    _me(engine).resources[CP] = 5
    assert not [c for c in engine.legal_candidates() if c.display_name.startswith("Delayed Bloom at")]


def test_a_blossom_is_recorded_so_a_saved_fight_replays_it():
    engine = _bed()
    events = _plant(engine, (3, 7))
    zone = _payloads(events, "ZONE_CREATED")[0]["zone"]
    assert zone["duration_rounds"] == 600 and zone["trigger_profile"]["placed"]["state"] == "dormant" and zone["trigger_profile"]["anchor_id"] == ALLY


# ============================================================================================================ 3. Puppet vessels
# Puppetry (combat/ext/vessel.py; owner text: the sphere compendium "Puppetry" section, rules_text.json PUPPETRY_BASE_* and
# tianxia.talent.puppetry.*).  A vessel is a placement; the puppeteer is ME on (3,6), the foe on (4,6).

PUPPET = ["PUPPETRY_BASE_RAISE_THE_VESSEL", "PUPPETRY_BASE_PUPPET_STRIKE", "tianxia.talent.puppetry.needle_rain_marionette",
          "tianxia.talent.puppetry.substitute_harm_body", "tianxia.talent.puppetry.marionette_substitution_body",
          "tianxia.talent.puppetry.ironwood_practice_body", "tianxia.talent.puppetry.heaven_s_spare_body"]
TWO_BODY, LONG_SILK = "tianxia.talent.puppetry.two_body_control", "tianxia.talent.puppetry.long_silk_thread"
QI = "resource:core.qi"


def _puppeteer(*talents, cl=17, dc=16):
    sheet = _sheet("tianxia.talent.puppetry.substitute_harm_body", cl=cl, dc=dc)
    sheet["spheres_and_talents"]["learned_talent_record_ids"] = list(talents or PUPPET)
    return compile_character(sheet, actor_id=ME)


def _stage(*talents, cl=17, at=(4, 7), raise_it=True, picks=(), legacy=False):
    """The puppeteer (30 CP) and its ally; the foe's Strength and Dexterity saves forced to fail; a vessel raised on ``at`` and a fresh turn."""
    bundle = _puppeteer(*talents,cl=cl)
    if legacy:
        from combat.canonical import canonical_sha256
        for action in bundle['action_catalog']:
            params=action.get('parameters',{})
            if params.get('vessel_kit'):params['vessel_native']=False
            params.pop('vessel_native_origin',None)
            if params.get('vessel_strike'):params['player_only']=True
        bundle.pop('bundle_sha256',None)
        bundle['bundle_sha256']=canonical_sha256(bundle)
    engine = _engine(bundle, allies=(_ally_bundle(),))
    foe = engine.state.actors[AN]
    foe.saving_throws["STR"] = foe.saving_throws["DEX"] = -50
    _me(engine).resources[QI] = 30
    for name in picks:
        _pick(engine, name)
    if raise_it:
        _pick(engine, "Raise the Vessel (1 CP)", at=at)
    _ready(engine)
    _me(engine).resources[QI] = 30
    return engine


def _vessels(engine, states=("active",)):
    return [zone for zone in placed.of(engine, "vessel") if placed.data(zone)["state"] in states]


def _names(engine):
    candidates=engine.legal_candidates()
    return {c.display_name for c in candidates} | {engine.action_catalog[c.source_definition_id].display_name
        for c in candidates if c.metadata.get('effect_origin')}


def _marked(engine):
    return any(c.condition_id.startswith("condition:typed.mark.tension_mark") for c in _foe(engine).conditions.values())


def test_the_puppetry_sphere_compiles_to_vessel_buttons_and_the_plain_raise_action_is_gone():
    bundle = _puppeteer()
    names = {row["display_name"] for row in bundle["action_catalog"]}
    assert {"Raise the Vessel (1 CP)", "Move Vessel", "Dismiss Vessel", "Tension Response: Tug the Joint", "Tension Response: Snap the Thread",
            "Vessel form: Slashing", "Vessel construction: Guard Body (+2 AC)", "Puppet Strike (from the vessel)"} <= names
    assert "Raise the Vessel" not in names  # the compiled effect-less action was a button that did nothing
    assert "Puppet Strike + Ironwood Practice Body" not in names  # Ironwood is a construction choice, not a strike variant
    by_id = {row["source_definition_id"]: row for row in bundle["action_catalog"]}
    for sid, row in by_id.items():
        if '.vessel' in sid:
            params = row['parameters']
            native_ai = bool(params.get('vessel_strike') or
                             (params.get('vessel_native') and params.get('vessel_raise')) or
                             (params.get('vessel_move') and params.get('cell_placement') == {}))
            assert bool(params.get('player_only')) is (not native_ai), row['display_name']


def test_raise_the_vessel_costs_one_cp_and_claims_a_square_within_thirty_feet_in_sight():
    engine = _stage(raise_it=False)
    assert ("Raise the Vessel (1 CP) at 9,6" in {c.display_name for c in engine.legal_candidates()}
            and "Raise the Vessel (1 CP) at 10,6" not in _names(engine))  # 30 feet, not 35
    events = _pick(engine, "Raise the Vessel (1 CP)", at=(4, 7))
    assert _payloads(events, "RESOURCE_SPENT")[0]["amount"] == 1 and _me(engine).resources[QI] == 29
    (zone,) = _vessels(engine)
    assert (zone.center.x, zone.center.y) == (4, 7) and zone.duration_rounds == 10  # "Duration: 1 minute"
    assert any("raises a puppet vessel" in line for line in _lines(events))


@pytest.mark.parametrize("cl,ac,hp,speed", [(1, 13, 12, 25), (5, 14, 30, 30), (11, 15, 64, 30), (17, 16, 110, 35)])
def test_vessel_statistics_follow_the_cultivation_level_table(cl, ac, hp, speed):
    engine = _stage(cl=cl)
    data = placed.data(_vessels(engine)[0])
    assert (data["ac"], data["hp"], data["speed"]) == (ac, hp, speed)  # AC 13/14/15/16; HP 10+2CL, 15+3CL, 20+4CL, 25+5CL; Speed 25/30/30/35


def test_a_vessel_is_recorded_drawn_and_difficult_terrain_for_everyone():
    engine = _stage(raise_it=False)
    events = _pick(engine, "Raise the Vessel (1 CP)", at=(4, 7))
    zone = _payloads(events, "ZONE_CREATED")[0]["zone"]
    assert zone["trigger_profile"]["placed"]["tag"] == "vessel" and "puppet vessel" in zone["trigger_profile"]["name"]  # a saved fight replays it
    assert (4, 7) in zones.difficult_cells(engine, _foe(engine)) and (4, 7) in zones.difficult_cells(engine, _me(engine))


def test_listing_the_buttons_with_a_vessel_up_writes_no_events_and_gives_the_same_ids_each_time():
    # A plug-in hook that raises is logged as a GM_RIDER event; the vessel's path check once did (engine._occupied_cells_except("") raises
    # KeyError once mounts look up the actor "" for a rider/mount pair), so every listing changed the event sequence, hence every candidate id,
    # and the engine refused each button as stale.
    engine = _stage()
    before = len(engine.events)
    first = {c.display_name: c.candidate_id for c in engine.legal_candidates()}
    second = {c.display_name: c.candidate_id for c in engine.legal_candidates()}
    assert len(engine.events) == before and first == second
    assert not [e for e in engine.events if e.event_type == "GM_RIDER" and "failed" in str(e.payload.get("rider"))]


def test_a_second_vessel_makes_the_first_inactive_unless_two_body_control_allows_two():
    engine = _stage()
    _pick(engine, "Raise the Vessel (1 CP)", at=(5, 7))
    assert [(z.center.x, z.center.y) for z in _vessels(engine)] == [(5, 7)]
    assert [(z.center.x, z.center.y) for z in _vessels(engine, ("inactive",))] == [(4, 7)]  # stays where it is, with no thread
    engine = _stage(*PUPPET, TWO_BODY)
    _pick(engine, "Raise the Vessel (1 CP)", at=(5, 7))
    assert len(_vessels(engine)) == 2


def test_legacy_catalog_may_move_the_vessel_once_on_the_raising_turn_then_a_bonus_action_later():
    engine = _stage(raise_it=False,legacy=True)
    _pick(engine, "Raise the Vessel (1 CP)", at=(4, 7))
    events = _pick(engine, "Move Vessel (as you raise it)", at=(9, 7))  # 5 squares = 25 feet, Speed 35
    assert any("walks from (4, 7) to (9, 7)" in line for line in _lines(events))
    assert not [n for n in _names(engine) if n.startswith("Move Vessel (as you raise it)")]  # only when you activate it
    _ready(engine)
    assert _pick(engine, "Move Vessel", at=(8, 7)) and (_vessels(engine)[0].center.x, _vessels(engine)[0].center.y) == (8, 7)
    assert not _me(engine).bonus_action_available  # a Bonus Action on later turns


def test_a_vessel_walks_no_farther_than_its_speed_nor_out_of_the_control_range():
    engine = _stage()
    _me(engine).position = Position(x=0, y=6)
    _ready(engine)
    assert "Move Vessel at 11,7" in _names(engine)  # 7 squares = 35 feet, and 55 feet from the puppeteer
    assert "Move Vessel at 12,7" not in _names(engine)  # 8 squares: past its Speed
    _me(engine).position = Position(x=0, y=6)
    _pick(engine, "Move Vessel", at=(11, 7))
    _ready(engine)
    assert "Move Vessel at 13,7" not in _names(engine)  # 65 feet from the puppeteer: beyond the 60-foot control range


def test_the_puppeteer_dismisses_the_vessel_without_an_action():
    engine = _stage()
    events = _pick(engine, "Dismiss Vessel")
    assert not _vessels(engine, ("active", "inactive")) and _me(engine).action_available
    assert any("dismisses the puppet vessel" in line for line in _lines(events))


def test_puppet_strike_is_made_from_the_vessel_marks_the_target_and_replaces_the_strike_from_your_own_square():
    engine = _stage()
    names = _names(engine)
    assert "Puppet Strike" not in names and "Puppet Strike (from the vessel)" in names  # the vessel is beside the foe (4,6)
    events = _pick(engine, "Puppet Strike (from the vessel)")
    assert any("puppet vessel at (4, 7) strikes" in line for line in _lines(events)) and _marked(engine)
    assert _foe(engine).current_hp < _foe(engine).maximum_hp


def test_puppet_strike_needs_a_vessel_within_reach_of_the_target_and_needle_rain_gives_thirty_feet():
    engine = _stage(at=(9, 7))  # 25 feet from the foe
    assert "Puppet Strike (from the vessel)" not in _names(engine) and "Puppet Strike + Needle Rain Marionette (from the vessel)" in _names(engine)
    assert "Puppet Strike" not in _names(engine)  # not from the puppeteer's own square while a vessel is up
    engine = _stage(raise_it=False,legacy=True)
    assert "Puppet Strike" in _names(engine)  # with no vessel up the compiled strike stays (the built-in AI never raises one)


def test_puppet_strike_damage_type_is_the_vessels_form():
    engine = _stage(picks=("Vessel form: Slashing",))
    events = _pick(engine, "Puppet Strike (from the vessel)")
    assert [p["damage_type"].lower() for p in _payloads(events, "DAMAGE_COMMITTED")][:1] == ["slashing"]


def test_a_tension_mark_lasts_until_the_end_of_the_puppeteers_next_turn():
    from combat.typed_executor import expire_marks

    engine = _stage()
    _pick(engine, "Puppet Strike (from the vessel)")
    mark = next(c for c in _foe(engine).conditions.values() if c.condition_id.startswith("condition:typed.mark.tension_mark"))
    assert mark.expires_on == "END_OF_MARKER_NEXT_TURN"  # "A Tension Mark lasts until the end of your next turn" (typed_conditions.json mark_durations)
    expire_marks(engine)
    assert _marked(engine)  # still the turn it was made
    _me(engine).turns_started += 1  # the puppeteer's next turn begins ...
    expire_marks(engine)
    assert _marked(engine)  # ... and is not over yet
    engine.state.current_actor_id = AN
    expire_marks(engine)
    assert not _marked(engine)


def _marked_stage(*args, **kwargs):
    engine = _stage(*args, **kwargs)
    _pick(engine, "Puppet Strike (from the vessel)")
    _ready(engine)
    _me(engine).resources[QI] = 30
    return engine


def test_tug_the_joint_moves_a_marked_creature_five_feet_toward_the_vessel_on_a_failed_strength_save_and_spends_the_mark():
    engine = _marked_stage()
    events = _pick(engine, "Tension Response: Tug the Joint")
    assert (_foe(engine).position.x, _foe(engine).position.y) in {(5, 6), (5, 7)}  # 5 feet to a free square beside the vessel (4,7), not into the vessel itself
    assert not _marked(engine) and any("is tugged to" in line for line in _lines(events))
    assert [p for p in _payloads(events, "MOVEMENT_COMMITTED") if p.get("forced")]  # forced movement: no opportunity attack


def test_tug_the_joint_does_nothing_to_a_creature_that_saves_and_tension_is_one_response_a_round():
    engine = _marked_stage()
    _foe(engine).saving_throws["STR"] = 50
    _pick(engine, "Tension Response: Tug the Joint")
    assert _foe(engine).position == Position(x=4, y=6) and not _marked(engine)  # the mark is spent either way
    _pick(engine, "Puppet Strike (from the vessel)") if "Puppet Strike (from the vessel)" in _names(engine) else None
    assert not [n for n in _names(engine) if n.startswith("Tension Response")]  # "one Tension Response per turn"


def test_a_tension_response_needs_a_mark_a_live_thread_and_a_creature_in_control_range():
    engine = _stage()
    assert not [n for n in _names(engine) if n.startswith("Tension Response")]  # no Tension Mark yet
    engine = _marked_stage()
    _me(engine).position = Position(x=0, y=0)  # the foe is now 20 feet away, the vessel 25: still threaded
    assert "Tension Response: Cross the Limb" in _names(engine)
    _foe(engine).position = Position(x=19, y=13)  # ...but a creature beyond the 60-foot control range cannot be answered
    assert not [n for n in _names(engine) if n.startswith("Tension Response")]


def test_cross_the_limb_gives_the_creature_disadvantage_on_its_next_attack_roll():
    engine = _marked_stage()
    _pick(engine, "Tension Response: Cross the Limb")
    foe = _foe(engine)
    assert [m for m in foe.modifiers.values() if m.target_field == "attack_mode" and m.value == "DISADVANTAGE"] and not _marked(engine)


def test_guarding_vessel_gives_a_creature_beside_the_vessel_two_ac_against_the_next_attack_only():
    engine = _marked_stage()
    ally = engine.state.actors[ALLY]
    ally.position = Position(x=5, y=7)  # beside the vessel (4,7)
    _pick(engine, "Tension Response: Guarding Vessel", target=ALLY)
    assert sum(ext.run("ac", engine, ally)) == 2
    engine._append_event("ATTACK_ROLLED", "test:attack", actor_id=AN, target_ids=(ALLY,), payload={})
    assert sum(ext.run("ac", engine, ally)) == 0  # "against the next attack roll"


@pytest.mark.parametrize("cl,dice", [(1, 1), (5, 2), (11, 3), (17, 4)])
def test_snap_the_thread_deals_force_damage_by_level(cl, dice):
    engine = _marked_stage(cl=cl)
    events = _pick(engine, "Tension Response: Snap the Thread")
    assert _damage_dice(events) == [f"{dice}d6+0"]
    assert [p["damage_type"].lower() for p in _payloads(events, "DAMAGE_COMMITTED")][:1] == ["force"]


def test_snap_the_thread_may_take_the_type_of_the_vessels_last_puppetry_attack_instead():
    engine = _marked_stage()
    events = _pick(engine, "Tension Response: Snap the Thread (the vessel's last damage type)")
    assert [p["damage_type"].lower() for p in _payloads(events, "DAMAGE_COMMITTED")][:1] == ["bludgeoning"]  # the default form of the strike that marked it


def test_the_thread_ends_when_the_vessel_is_outside_the_control_range_at_the_end_of_the_turn():
    engine = _stage()
    zone = _vessels(engine)[0]
    _me(engine).position = Position(x=0, y=0)
    placed.reshape(engine, zone, cells=Position(x=13, y=0))  # 65 feet
    events = engine.events[-1:]
    _turn(engine, ME, "TURN_ENDED")
    assert not _vessels(engine) and _vessels(engine, ("inactive",))  # inactive: no thread, no strike
    assert any("control range" in line for line in [p.get("text", "") for p in _payloads(engine.events, "PASSIVE_TRIGGERED")])
    engine = _stage(*PUPPET, LONG_SILK)  # +120 feet at CL 11+ "instead"
    _me(engine).position = Position(x=0, y=0)
    placed.reshape(engine, _vessels(engine)[0], cells=Position(x=19, y=0))  # 95 feet
    _turn(engine, ME, "TURN_ENDED")
    assert len(_vessels(engine)) == 1


@pytest.mark.parametrize("cl,low,high", [(5, 4, 18), (11, 5, 26), (17, 6, 34)])
def test_substitute_harm_body_reduces_the_damage_by_the_level_dice_and_the_vessel_takes_the_same(cl, low, high):
    engine = _stage(cl=cl)
    zone = _vessels(engine)[0]
    hp = placed.data(zone)["hp"]
    reduced = typed_reactions.on_damage(engine, _me(engine), 60, 0, source_definition_id="action:test.attack", source_actor_id=AN)
    took = hp - placed.data(zone)["hp"]
    assert low <= 60 - reduced <= high and took == 60 - reduced  # 2d8+2 / 3d8+2 / 4d8+2: "the same amount of damage that was reduced"
    assert _me(engine).resources[QI] == 29 and not _me(engine).reaction_available  # 1 CP and the Reaction


def test_substitute_harm_body_needs_an_active_vessel_within_thirty_feet_and_a_broken_vessel_is_gone():
    engine = _stage(at=(9, 6))
    _me(engine).position = Position(x=2, y=6)  # 35 feet from the vessel: "within 30 feet"
    assert typed_reactions.on_damage(engine, _me(engine), 40, 0, source_definition_id="action:test.attack", source_actor_id=AN) == 40
    engine = _stage()
    zone = _vessels(engine)[0]
    placed.update(engine, zone, hp=3)
    typed_reactions.on_damage(engine, _me(engine), 40, 0, source_definition_id="action:test.attack", source_actor_id=AN)
    assert not _vessels(engine, ("active", "inactive")) and any("is broken" in p.get("text", "") for p in _payloads(engine.events, "PASSIVE_TRIGGERED"))


def test_marionette_substitution_body_swaps_places_with_the_vessel_for_three_cp():
    # (with Substitute Harm Body too the Auto arbitration keeps the Reaction for the damage soak: typed_reactions.on_attacked)
    swap = [t for t in PUPPET if t != "tianxia.talent.puppetry.substitute_harm_body"]
    engine = _stage(*swap, at=(8, 6))  # 25 feet
    typed_reactions.on_attacked(engine, _foe(engine), _me(engine), {"attack_bonus": 5, "range_ft": None}, None)
    assert (_me(engine).position.x, _me(engine).position.y) == (8, 6)
    assert (_vessels(engine)[0].center.x, _vessels(engine)[0].center.y) == (3, 6) and _me(engine).resources[QI] == 27
    engine = _stage(*swap, at=(9, 6))
    _me(engine).position = Position(x=0, y=6)
    placed.reshape(engine, _vessels(engine)[0], cells=Position(x=13, y=6))  # 65 feet: "within 60 feet"
    typed_reactions.on_attacked(engine, _foe(engine), _me(engine), {"attack_bonus": 5, "range_ft": None}, None)
    assert _me(engine).position == Position(x=0, y=6) and _me(engine).resources[QI] == 30


def test_heavens_spare_body_destroys_the_vessel_holds_you_at_one_hp_and_moves_you_into_its_square_once_a_long_rest():
    engine = _stage()
    _me(engine).current_hp = 5
    left = typed_reactions._offer_drop_to_zero_or_bloodied(engine, _me(engine), _foe(engine), 60, 0, AN)
    assert left == 4  # 5 HP, held at 1
    assert not _vessels(engine, ("active", "inactive")) and _me(engine).position == Position(x=4, y=7) and _me(engine).resources[QI] == 22
    _pick(engine, "Raise the Vessel (1 CP)", at=(5, 7))
    _me(engine).resources[QI] = 30
    assert typed_reactions._offer_drop_to_zero_or_bloodied(engine, _me(engine), _foe(engine), 60, 0, AN) == 60  # once per long rest


def test_ironwood_guard_and_running_bodies_change_the_vessels_armor_and_speed():
    engine = _stage(raise_it=False, picks=("Vessel construction: Guard Body (+2 AC)",))
    _pick(engine, "Raise the Vessel (1 CP)", at=(4, 7))
    assert placed.data(_vessels(engine)[0])["ac"] == 18  # 16 + 2
    engine = _stage(raise_it=False, picks=("Vessel construction: Running Body (+10 ft Speed)",))
    _pick(engine, "Raise the Vessel (1 CP)", at=(4, 7))
    assert placed.data(_vessels(engine)[0])["speed"] == 45  # 35 + 10


def test_needle_body_lets_the_vessel_strike_from_ten_feet_in_piercing_damage():
    engine = _stage(raise_it=False, picks=("Vessel construction: Needle Body (reach 10 ft, Piercing)",), at=(4, 8))
    _pick(engine, "Raise the Vessel (1 CP)", at=(4, 8))  # 10 feet from the foe on (4,6)
    _ready(engine)
    events = _pick(engine, "Puppet Strike (from the vessel)")
    assert [p["damage_type"].lower() for p in _payloads(events, "DAMAGE_COMMITTED")][:1] == ["piercing"]


def test_the_tension_mark_has_its_own_deadline_in_the_rules_table_not_in_every_talent():
    assert typed_executor.rules()["mark_durations"]["tension mark"] == "until_end_of_your_next_turn"



# ----------------------------------------------------------------------------------------------------------------- Figments
# Illusion (combat/ext/figment.py; owner text: the sphere compendium "Illusion" section, rules_text.json TAL_ILLUSION_* and
# tianxia.talent.illusion.*).  A figment is a placement (a cube of squares); the illusionist is ME on (3,6), the foe on (4,6), the
# ally on (3,7).  The foe's Wisdom and Intelligence saves are forced to fail unless a test says otherwise.

FIG = ["TAL_ILLUSION_CREATE_FIGMENT", "TAL_ILLUSION_CONTROL_FIGMENT", "TAL_ILLUSION_SELECTIVE_PREMISE", "TAL_ILLUSION_POTENT_PHANTASM",
       "TAL_ILLUSION_GREATER_ILLUSION", "TAL_ILLUSION_VEILED_ILLUSION", "TAL_ILLUSION_MISDIRECTION_RESPONSES"]
PREMISE = "False Premise"


def _illusionist(*talents, cl=10, dc=16, actor=ME):
    sheet = _sheet("TAL_ILLUSION_CREATE_FIGMENT", cl=cl, dc=dc)
    sheet["spheres_and_talents"]["learned_talent_record_ids"] = list(talents or FIG)
    return compile_character(sheet, actor_id=actor)


def _fig_stage(*picks, cl=10, talents=(), at=None):
    """The illusionist (30 CP) and its ally against the foe (Wisdom and Intelligence saves forced to fail); the free setup buttons in
    ``picks`` pressed, a figment made on ``at``, and a fresh turn."""
    engine = _engine(_illusionist(*talents, cl=cl), allies=(_ally_bundle(),))
    for actor_id in (AN, ALLY):
        engine.state.actors[actor_id].saving_throws["WIS"] = engine.state.actors[actor_id].saving_throws["INT"] = -50
    _me(engine).resources[QI] = 30
    for name in picks:
        _pick(engine, name)
    if at is not None:
        _pick(engine, "Create Figment", at=at)
    _refresh(engine)
    return engine


def _figs(engine):
    return placed.of(engine, "figment")


def _can(engine, name, at=None, target=None):
    return any(c.display_name == name or c.display_name.startswith(name + " at") for c in engine.legal_candidates()
               if (at is None or (c.destination is not None and (c.destination.x, c.destination.y) == at))
               and (target is None or tuple(c.target_ids or ()) == (target,)))


def _premised(engine):
    return bears_mark(_foe(engine), ME, PREMISE)


def _plant_premise(engine, save=-50):
    _foe(engine).saving_throws["WIS"] = save
    _refresh(engine)
    return _pick(engine, "Plant False Premise", target=AN)


def test_the_illusion_sphere_compiles_to_figment_buttons_and_the_effectless_talent_actions_are_gone():
    catalog = _illusionist()["action_catalog"]
    names = {row["display_name"] for row in catalog}
    assert {"Create Figment", "Move Figment", "Dismiss Figment", "Control Figment (1 CP)", "Keep a figment without Concentration (2 CP)", "Plant False Premise",
            "False Premise (a creature acts on the figment)", "Figment: Selective Premise (choose creatures when created)", "Figment: sight and sound (1 CP)",
            "Figment: larger cube (1 CP)", "Figment: no Concentration (2 CP)", "Figment: Potent Phantasm, Blinded (3 CP)",
            "Misdirection Response: False Opening", "Misdirection Response: Wrong Angle", "Misdirection Response: Lost Timing",
            "Misdirection Response: Stolen Step"} <= names
    ids = [row["source_definition_id"] for row in catalog]
    assert not [i for i in ids if i.endswith((".TAL_ILLUSION_CREATE_FIGMENT", ".TAL_ILLUSION_CONTROL_FIGMENT", ".TAL_ILLUSION_SELECTIVE_PREMISE",
                                              ".TAL_ILLUSION_POTENT_PHANTASM", ".TAL_ILLUSION_MISDIRECTION_RESPONSES"))]  # the effect-less copies did nothing
    assert [row["display_name"] for row in catalog].count("Create Figment") == 1


def test_the_options_a_figment_offers_follow_the_talents_its_maker_owns():
    bare = {row["display_name"] for row in _illusionist("TAL_ILLUSION_CREATE_FIGMENT")["action_catalog"]}
    assert {"Create Figment", "Move Figment", "Plant False Premise", "Misdirection Response: Wrong Angle"} <= bare  # base abilities of the sphere
    assert not [n for n in bare if n.startswith(("Figment: Potent", "Figment: Selective", "Control Figment"))]
    potent = {row["display_name"] for row in _illusionist("TAL_ILLUSION_CREATE_FIGMENT", "TAL_ILLUSION_POTENT_PHANTASM")["action_catalog"]}
    assert {"Figment: Potent Phantasm, Deafened (1 CP)", "Figment: Potent Phantasm, Blinded (3 CP)"} <= potent
    assert not {"Figment: Potent Phantasm, Psychic damage (2 CP)", "Figment: Potent Phantasm, Poisoned (2 CP)", "Figment: Potent Phantasm, Frightened (2 CP)"} & potent


@pytest.mark.parametrize("cl,cells", [(3, 4), (10, 9), (12, 16), (17, 25)])
def test_a_figment_is_a_cube_as_big_as_the_cultivation_level_table_allows(cl, cells):
    engine = _fig_stage(cl=cl)
    events = _pick(engine, "Create Figment", at=(9, 7))
    zone = _figs(engine)[0]
    assert len(zone.affected_cells) == cells and (zone.center.x, zone.center.y) == (9, 7)
    assert _me(engine).resources[QI] == 30  # "Cost: None"
    assert any("makes a figment" in line for line in _lines(events))


def test_the_paid_augments_make_the_cube_bigger_add_sound_and_free_the_maker_of_concentration():
    engine = _fig_stage("Figment: larger cube (1 CP)", "Figment: sight and sound (1 CP)", "Figment: no Concentration (2 CP)")
    _pick(engine, "Create Figment", at=(8, 7))
    zone = _figs(engine)[0]
    assert len(zone.affected_cells) == 36 and placed.data(zone)["senses"] and placed.data(zone)["free"]  # 15 -> 30 ft at CL 10
    assert _me(engine).resources[QI] == 26 and _me(engine).concentration is None and zone.active


def test_a_figment_lasts_as_long_as_its_makers_concentration():
    engine = _fig_stage(at=(7, 6))
    zone = _figs(engine)[0]
    assert _me(engine).concentration.zone_id == zone.zone_id
    engine._end_concentration(_me(engine), "TEST")
    assert not zone.active and not _figs(engine)


def test_keeping_a_figment_without_concentration_costs_two_cp_and_no_action():
    engine = _fig_stage(at=(7, 6))
    zone = _figs(engine)[0]
    events = _pick(engine, "Keep a figment without Concentration (2 CP)", at=(7, 6))
    assert _me(engine).resources[QI] == 28 and _me(engine).concentration is None and zone.active and placed.data(zone)["free"]
    assert _me(engine).action_available  # "without using an Action"
    assert any("without Concentration" in line for line in _lines(events)) and not _can(engine, "Keep a figment without Concentration (2 CP)")


def test_move_figment_uses_the_action_and_only_reaches_squares_in_range_and_sight():
    engine = _fig_stage(at=(7, 6))
    zone = _figs(engine)[0]
    assert not _can(engine, "Move Figment", at=(17, 6))  # 70 feet away
    events = _pick(engine, "Move Figment", at=(9, 5))
    assert (zone.center.x, zone.center.y) == (9, 5) and len(zone.affected_cells) == 9 and not _me(engine).action_available
    assert any("moves the figment" in line for line in _lines(events))


def test_dismiss_figment_ends_it_and_its_concentration_without_an_action():
    engine = _fig_stage(at=(7, 6))
    zone = _figs(engine)[0]
    events = _pick(engine, "Dismiss Figment", at=(7, 6))
    assert not zone.active and _me(engine).concentration is None and _me(engine).action_available
    assert any("fade" in line for line in _lines(events))


def test_a_failed_wisdom_save_puts_a_false_premise_on_the_target_until_the_start_of_the_illusionists_next_turn():
    engine = _fig_stage(at=(7, 6))
    events = _plant_premise(engine)
    (row,) = [c for c in _foe(engine).conditions.values() if c.condition_id == typed_executor.mark_condition_id(PREMISE, ME)]
    assert row.expires_on == "START_OF_SOURCE_NEXT_TURN" and _premised(engine)
    assert any("gains a False Premise" in line for line in _lines(events))
    _refresh(engine)
    assert not _can(engine, "Plant False Premise", target=AN) and not _can(engine, "False Premise (a creature acts on the figment)", target=AN)  # only one from you at a time
    engine.state.current_actor_id = AN
    engine._system_start_turn()
    assert _premised(engine)  # the foe's turn is not the illusionist's
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    assert not _premised(engine)


def test_a_passed_wisdom_save_leaves_no_false_premise():
    engine = _fig_stage(at=(7, 6))
    _plant_premise(engine, save=50)
    assert not _premised(engine)


def test_false_premise_on_a_creature_acting_on_the_figment_needs_a_figment_the_creature_can_see():
    engine = _fig_stage()
    assert not _can(engine, "False Premise (a creature acts on the figment)", target=AN)  # nothing to act on
    engine = _fig_stage(at=(7, 6))
    _pick(engine, "False Premise (a creature acts on the figment)", target=AN)
    assert _premised(engine)


@pytest.mark.parametrize("pick,field,value", [("False Opening", "incoming_attack_mode", "ADVANTAGE"), ("Wrong Angle", "attack_mode", "DISADVANTAGE"),
                                              ("Stolen Step", "speed_ft", -10)])
def test_a_misdirection_response_ends_the_premise_and_changes_the_targets_next_rolls_or_speed(pick, field, value):
    engine = _fig_stage(at=(7, 6))
    _plant_premise(engine)
    speed = engine._effective_speed(_foe(engine))
    events = _pick(engine, f"Misdirection Response: {pick}", target=AN)
    assert not _premised(engine)  # "a False Premise ends immediately after you trigger a Misdirection Response from it"
    mods = {(m.target_field, m.value, m.expires_on) for m in _foe(engine).modifiers.values()}
    assert (field, value, "START_OF_SOURCE_NEXT_TURN") in mods
    if pick == "Stolen Step":
        assert engine._effective_speed(_foe(engine)) == speed - 10
    assert any(f"triggers {pick}" in line for line in _lines(events))


def test_lost_timing_takes_the_targets_reactions_and_only_one_response_can_be_triggered_a_round():
    engine = _fig_stage(at=(7, 6))
    _plant_premise(engine)
    _pick(engine, "Misdirection Response: Lost Timing", target=AN)
    assert "reaction_denied" in {c.condition_id.split(".")[-1] for c in _foe(engine).conditions.values()}
    _plant_premise(engine)  # a second premise on the same turn: a response is still not allowed
    assert _premised(engine) and not _can(engine, "Misdirection Response: Wrong Angle", target=AN)
    engine.state.round_number += 1
    _refresh(engine)
    assert _can(engine, "Misdirection Response: Wrong Angle", target=AN)


def test_a_response_needs_a_creature_that_carries_a_false_premise_from_the_illusionist():
    engine = _fig_stage(at=(7, 6))
    assert not [n for n in _names(engine) if n.startswith("Misdirection Response")]
    _plant_premise(engine)
    assert {"Misdirection Response: False Opening", "Misdirection Response: Wrong Angle", "Misdirection Response: Lost Timing",
            "Misdirection Response: Stolen Step"} <= {c.display_name for c in engine.legal_candidates()}


@pytest.mark.parametrize("pick,condition", [("Blinded (3 CP)", "blinded"), ("Deafened (1 CP)", "deafened"), ("Poisoned (2 CP)", "poisoned"),
                                            ("Frightened (2 CP)", "frightened")])
def test_potent_phantasm_makes_a_creature_that_starts_its_turn_in_the_figment_save_or_suffer_the_chosen_condition(pick, condition):
    engine = _fig_stage(f"Figment: Potent Phantasm, {pick}", at=(4, 6))
    foe, before = _foe(engine), len(engine.events)
    zones.on_turn_start(engine, foe)
    assert condition in {c.condition_id.split(".")[-1] for c in foe.conditions.values()}
    assert any("Potent Phantasm" in line for line in _lines(engine.events[before:]))


def test_a_potent_phantasm_is_paid_for_when_the_figment_is_made():
    engine = _fig_stage("Figment: Potent Phantasm, Blinded (3 CP)")
    _pick(engine, "Create Figment", at=(7, 6))
    assert _me(engine).resources[QI] == 27 and placed.data(_figs(engine)[0])["phantasm"] == "blind"


def test_a_creature_that_passes_the_intelligence_save_shrugs_the_phantasm_off():
    engine = _fig_stage("Figment: Potent Phantasm, Blinded (3 CP)", at=(4, 6))
    foe = _foe(engine)
    foe.saving_throws["INT"] = 50
    zones.on_turn_start(engine, foe)
    assert "blinded" not in {c.condition_id.split(".")[-1] for c in foe.conditions.values()}


@pytest.mark.parametrize("cl,dice", [(10, "1d4"), (12, "2d4"), (17, "3d4")])
def test_the_psychic_phantasm_deals_one_four_sided_die_a_tier_of_cultivation_level(cl, dice):
    engine = _fig_stage("Figment: Potent Phantasm, Psychic damage (2 CP)", cl=cl, at=(4, 6))
    foe, before = _foe(engine), len(engine.events)
    hp = foe.current_hp
    zones.on_turn_start(engine, foe)
    assert _dice(engine.events[before:]) == [dice] and foe.current_hp < hp


def test_the_maker_and_the_creatures_chosen_by_selective_premise_are_not_touched_by_the_phantasm():
    """Selective Premise is chosen per creature while the illusion is created ("Embedded; no separate action"), and its
    two printed modes differ against Potent Phantasm: "immune to that harmless or hindering effect" stops the condition,
    while merely "recognizes that specific illusion as false" does not -- the phantasm "continues after recognition"."""
    engine = _fig_stage("Figment: Potent Phantasm, Blinded (3 CP)", at=(3, 7))
    zone, = _figs(engine)
    placed.update(engine, zone, immune=[ALLY])  # Selective Premise: ALLY chose immunity to this hindering effect
    for who in (ME, ALLY, AN):
        zones.on_turn_start(engine, engine.state.actors[who])
    blinded = {who for who in (ME, ALLY, AN) if "blinded" in {c.condition_id.split(".")[-1] for c in engine.state.actors[who].conditions.values()}}
    assert blinded == {AN}
    plain = _fig_stage("Figment: Potent Phantasm, Blinded (3 CP)", at=(3, 7))
    placed.update(plain, _figs(plain)[0], recognized=[ALLY])  # recognized, not immune: still fooled
    for who in (ME, ALLY, AN):
        zones.on_turn_start(plain, plain.state.actors[who])
    blinded = {who for who in (ME, ALLY, AN) if "blinded" in {c.condition_id.split(".")[-1] for c in plain.state.actors[who].conditions.values()}}
    assert blinded == {ALLY, AN}  # the illusion fools whoever was not told, an ally too; only its maker sees through it


def _two_illusionists():
    """ME and an allied illusionist; the ally makes a figment on (7,6) on its own turn, then it is ME's turn."""
    engine = _engine(_illusionist(), allies=(_illusionist(actor=ALLY),))
    engine.state.current_actor_id = ALLY
    ally = engine.state.actors[ALLY]
    ally.action_available = ally.bonus_action_available = ally.reaction_available = True
    for actor_id in (ME, ALLY):
        engine.state.actors[actor_id].resources[QI] = 30
    _pick(engine, "Create Figment", at=(7, 6), actor=ALLY)
    engine.state.current_actor_id = ME
    _refresh(engine)
    return engine


def test_control_figment_takes_another_illusionists_figment_on_a_cultivation_check_and_costs_one_cp_either_way():
    engine = _two_illusionists()
    zone = _figs(engine)[0]
    assert not _can(engine, "Move Figment", at=(9, 6))  # it is not mine yet
    placed.update(engine, zone, save_dc=99)  # a Cultivation Save DC no check reaches
    events = _pick(engine, "Control Figment (1 CP)", at=(7, 6))
    assert _me(engine).resources[QI] == 29 and placed.data(zone)["controller"] == ALLY and any("fails to seize" in line for line in _lines(events))
    _refresh(engine)
    placed.update(engine, zone, save_dc=1)
    events = _pick(engine, "Control Figment (1 CP)", at=(7, 6))
    assert placed.data(zone)["controller"] == ME and any("seizes the figment" in line for line in _lines(events))
    assert _me(engine).concentration.source_definition_id.endswith(".figment.control")  # "you must assume Concentration over it"
    _refresh(engine)
    _pick(engine, "Move Figment", at=(9, 6))
    assert (zone.center.x, zone.center.y) == (9, 6)


def _control_check_dice(events):
    """How many dice the recorded Control Figment Cultivation Check actually rolled."""
    for event in events:
        payload = event.payload or {}
        if event.event_type == "CHECK_ROLLED" and str(payload.get("check") or "").endswith("(Control Figment)"):
            return len(payload["actor"]["dice"])
    raise AssertionError("Control Figment recorded no Cultivation Check")


def _control_check_total(events):
    for event in events:
        payload = event.payload or {}
        if event.event_type == "CHECK_ROLLED" and str(payload.get("check") or "").endswith("(Control Figment)"):
            return int(payload["actor"]["total"])
    raise AssertionError("Control Figment recorded no Cultivation Check")


def _seize_with_mode(mode, dc=1):
    """ME seizes ALLY's figment while carrying a scoped check mode; returns the dice the check rolled and its total."""
    engine = _two_illusionists()
    zone = _figs(engine)[0]
    placed.update(engine, zone, save_dc=dc)
    if mode:
        engine._apply_condition(_me(engine), typed_executor.CONDITION_PREFIX + "check_mode", "test:control-mode", ME,
                                expires_on="UNTIL_REMOVED", data={"rule": {"check_mode": {"ALL": mode}}})
    _refresh(engine)
    events = _pick(engine, "Control Figment (1 CP)", at=(7, 6))
    return _control_check_dice(events), _control_check_total(events)


def test_control_figments_cultivation_check_honours_the_printers_advantage_and_disadvantage():
    """Control Figment's rider: "The Cultivation Check must use all applicable Advantage, Disadvantage, bonuses and
    check floors." The check resolves through the shared Cultivation Check resolver, so scoped modes roll two dice."""
    assert _seize_with_mode(None)[0] == 1, "an unencumbered Cultivation Check rolls one die"
    assert _seize_with_mode("DISADVANTAGE")[0] == 2, "Disadvantage on ability checks must roll the lower of two dice"
    assert _seize_with_mode("ADVANTAGE")[0] == 2, "Advantage on ability checks must roll the higher of two dice"
    # Both together cancel, exactly as an ordinary check does.
    engine = _two_illusionists()
    zone = _figs(engine)[0]
    placed.update(engine, zone, save_dc=1)
    for mode in ("DISADVANTAGE", "ADVANTAGE"):
        engine._apply_condition(_me(engine), typed_executor.CONDITION_PREFIX + "check_mode", f"test:both-{mode}", ME,
                                expires_on="UNTIL_REMOVED", data={"rule": {"check_mode": {"ALL": mode}}})
    _refresh(engine)
    assert _control_check_dice(_pick(engine, "Control Figment (1 CP)", at=(7, 6))) == 1


def test_control_figments_cultivation_check_uses_a_d20_floor_and_reports_its_total():
    """The same printed rider: a check floor the actor carries raises the check it just rolled."""
    engine = _two_illusionists()
    zone = _figs(engine)[0]
    placed.update(engine, zone, save_dc=10)
    _refresh(engine)
    events = _pick(engine, "Control Figment (1 CP)", at=(7, 6))
    natural = _control_check_total(events)
    assert placed.data(zone)["controller"] in (ME, ALLY)
    # Raise the floor above anything this die can reach: the check must succeed and take the figment.
    engine = _two_illusionists()
    zone = _figs(engine)[0]
    placed.update(engine, zone, save_dc=1)
    engine._apply_condition(_me(engine), "condition:typed.d20_floor", "test:control-floor", ME,
                            expires_on="UNTIL_REMOVED", data={"rule": {"d20_floor": {"floor": 30}}})
    _refresh(engine)
    events = _pick(engine, "Control Figment (1 CP)", at=(7, 6))
    assert _control_check_total(events) >= 30, "the d20 floor raises the total it applies to"
    assert placed.data(zone)["controller"] == ME and any("seizes the figment" in line for line in _lines(events))


def test_a_controlled_figment_goes_back_to_its_maker_when_the_controllers_concentration_ends():
    engine = _two_illusionists()
    zone = _figs(engine)[0]
    placed.update(engine, zone, save_dc=1)
    _pick(engine, "Control Figment (1 CP)", at=(7, 6))
    engine._end_concentration(_me(engine), "TEST")
    assert placed.data(zone)["controller"] == ALLY and zone.active
    assert any("returns to its creator" in line for line in _lines(engine.events[-4:]))


def test_the_controllers_concentration_goes_with_the_figment_when_its_maker_lets_it_end():
    engine = _two_illusionists()
    zone = _figs(engine)[0]
    placed.update(engine, zone, save_dc=1)
    _pick(engine, "Control Figment (1 CP)", at=(7, 6))
    assert _me(engine).concentration is not None
    engine._end_concentration(engine.state.actors[ALLY], "TEST")
    assert not zone.active and _me(engine).concentration is None


def test_the_setup_marker_and_the_false_premise_mark_read_out_on_the_table():
    assert "Potent Phantasm" in condition_text.all_conditions()["figment_setup"]["reading"]
    row = {"condition_id": typed_executor.mark_condition_id(PREMISE, ME), "source_definition_id": "action:typed.x.figment.plant", "expires_on": "START_OF_SOURCE_NEXT_TURN", "detail": None}
    engine = SimpleNamespace(action_catalog={})
    TabletopService._explain_marks(TabletopService, {"actors": [{"conditions": [row]}]}, engine, {ME: "Mei Jiang"}, {"action:typed.x.figment.plant": "Plant False Premise"})
    assert row["detail"].startswith("False Premise mark from Mei Jiang (Plant False Premise), until the start of its placer's next turn.")
    assert "Misdirection Response" in row["detail"]



# -------------------------------------------------------------------------------------------------------- Command Banner
# Banner Cultivator (combat/ext/banner.py; owner text: the Qi subpath compendium, Banner Cultivator).  ME (3,6) is the cultivator, the ally
# (3,7) and the foe (4,6); the banner is raised on (4,7): the foe is five feet from it, the aura (15 feet) holds ME and the ally.

BAN = "tianxia.subpath.qi.banner_cultivator.feature."
RAISE, RALLY, ADVANCING, FOURFOLD, IMPERIAL = (BAN + name for name in ("raise_the_standard", "rally_the_line", "advancing_standard", "fourfold_formation",
                                                                    "imperial_standard_of_heaven"))
BANNER_FULL = [RAISE, RALLY, ADVANCING, FOURFOLD, IMPERIAL]
STEP = "condition:typed.banner_step"
MANIFEST = "Manifest Command Banner (1 Qi)"
ORDER_INDEX = {"auto": 0, "reposition": 1, "seize": 2, "brace": 3, "rise": 4, "courage": 5, "shift": 6}


def _banner_bundle(ids=BANNER_FULL, cl=18, order="auto"):
    sheet = _sheet(ids[0], cl=cl)
    sheet["path_and_subpath"] = {"path_feature_record_ids": list(ids)}
    return compile_character(sheet, actor_id=ME, reaction_plan={"options": {FOURFOLD: ORDER_INDEX[order]}})


def _bn_stage(*, at=(4, 7), ids=BANNER_FULL, cl=18, order="auto", raised=True):
    engine = _engine(_banner_bundle(ids, cl, order), allies=(_ally_bundle(),))
    _me(engine).resources[QI] = 30
    if raised:
        _pick(engine, MANIFEST, at=at)
        _ready(engine)
    return engine


def _standard(engine):
    return placed.of(engine, "standard")[0]


def _ally(engine):
    return engine.state.actors[ALLY]


def _bn_save(engine, actor_id, total, condition="frightened", ability="WIS"):
    """Force the coming save of ``actor_id`` to total ``total`` (the roller is a counter: peek at the die it will roll) and make it."""
    roller = engine.roller
    natural = DeterministicRollAuthority(roller.seed, roller.counter).d20(modifier=0, actor_id="peek", reason="peek").total
    engine.state.actors[actor_id].saving_throws[ability] = total - natural
    from tests.test_auto_lane1 import _foe_forces_save

    dc = _foe_forces_save(engine, actor_id, ability, condition=condition)
    rolled = [p for p in _payloads(engine.events, "SAVE_ROLLED")][-1]
    assert rolled["total"] == total, rolled
    return dc


def _bn_hit(engine, dealer=ALLY, amount=5):
    engine._commit_damage(_foe(engine), amount, "SLASHING", "test:blow", dealer, None, reaction_depth=0)


def _bn_turn_of(engine, actor_id):
    engine.state.current_actor_id = actor_id
    _turn(engine, actor_id, "TURN_STARTED")


def test_the_banner_cultivator_has_a_button_for_each_part_it_owns_and_a_lone_raise_the_standard_only_the_first():
    engine = _bn_stage(raised=False)
    assert _can(engine, MANIFEST) and _can(engine, "Empower a Real Banner you carry (1 Qi)")
    assert not _can(engine, "Rally the Line (2 Qi)")  # nothing to rally without a banner
    _pick(engine, MANIFEST, at=(4, 7))
    _ready(engine)
    assert all(_can(engine, name) for name in ("Rally the Line (2 Qi)", "Advancing Standard (4 Qi)", "Imperial Standard of Heaven (8 Qi, once per scene)",
                                               "Banner Stance: Steady + Clear Signal", "Dismiss Command Banner"))
    lone = _bn_stage(ids=[RAISE], cl=3, raised=False)
    assert _can(lone, MANIFEST) and _can(lone, "Banner Stance: Steady") and not _can(lone, "Banner Stance: Steady + Clear Signal")
    _pick(lone, MANIFEST, at=(4, 7))
    _ready(lone)
    assert not any(_can(lone, name) for name in ("Rally the Line (2 Qi)", "Advancing Standard (4 Qi)", "Imperial Standard of Heaven (8 Qi, once per scene)"))


def test_manifesting_the_banner_costs_a_qi_and_a_bonus_action_and_needs_a_free_square_within_thirty_feet():
    engine = _bn_stage(raised=False)
    assert not _can(engine, MANIFEST, at=(3, 7))  # the ally's square
    assert not _can(engine, MANIFEST, at=(12, 6))  # forty-five feet
    events = _pick(engine, MANIFEST, at=(4, 7))
    me, zone = _me(engine), _standard(engine)
    assert me.resources[QI] == 29 and not me.bonus_action_available
    assert (zone.center.x, zone.center.y) == (4, 7) and zone.owner_id == ME and "aura 15 ft" in zone.trigger_profile["name"]
    assert banner._covers(engine, zone, me) and banner._covers(engine, zone, _ally(engine)) and not banner._covers(engine, zone, _foe(engine))
    assert any("plants a Command Banner" in line for line in _lines(events))


def test_a_second_banner_replaces_the_first_and_dismissing_it_lets_the_aura_go():
    engine = _bn_stage()
    _pick(engine, MANIFEST, at=(5, 7))
    assert [(z.center.x, z.center.y) for z in placed.of(engine, "standard")] == [(5, 7)]
    events = _pick(engine, "Dismiss Command Banner")
    assert not placed.of(engine, "standard") and any("lets the Command Banner go" in line for line in _lines(events))


def test_a_real_banner_the_cultivator_carries_keeps_its_aura_on_the_bearer():
    engine = _bn_stage(raised=False)
    _pick(engine, "Empower a Real Banner you carry (1 Qi)")
    zone = _standard(engine)
    assert (zone.center.x, zone.center.y) == (3, 6) and placed.data(zone)["carried"]
    _walk(engine, ME, [(3, 5)])
    assert (zone.center.x, zone.center.y) == (3, 5)


def test_stances_are_chosen_free_once_a_turn_and_the_fourfold_formation_gives_two():
    engine = _bn_stage()
    zone = _standard(engine)
    assert placed.data(zone)["stances"] == ["forward", "guarded"]
    _pick(engine, "Banner Stance: Steady + Clear Signal")
    assert placed.data(zone)["stances"] == ["steady", "signal"] and "Steady, Clear Signal" in zone.trigger_profile["name"]
    assert not _can(engine, "Banner Stance: Forward + Guarded")  # once each turn
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    assert _can(engine, "Banner Stance: Forward + Guarded")
    assert _held(_me(engine), banner.SETUP)[0].data["label"].startswith("Command Banner Stance: Steady, Clear Signal")


def test_forward_gives_five_feet_of_speed_inside_the_aura_only():
    engine = _bn_stage()
    ally = _ally(engine)
    inside = engine._effective_speed(ally)
    ally.position = Position(x=12, y=7)  # forty feet from the banner
    assert engine._effective_speed(ally) == inside - 5
    ally.position = Position(x=3, y=7)
    _pick(engine, "Banner Stance: Guarded + Steady")
    assert engine._effective_speed(ally) == inside - 5  # Forward is not chosen


def test_guarded_gives_one_armor_class_against_opportunity_attacks_only():
    engine = _bn_stage()
    ally = _ally(engine)
    plain = engine._ac_modifier(ally)
    engine._typed_oa_attacker = AN
    assert engine._ac_modifier(ally) == plain + 1
    _pick(engine, "Banner Stance: Steady + Clear Signal")
    assert engine._ac_modifier(ally) == plain  # not chosen
    engine._typed_oa_attacker = None


def test_steady_gives_advantage_on_saves_against_frightened_and_prone_not_others():
    engine = _bn_stage()
    _bn_save(engine, ALLY, 10)
    assert _payloads(engine.events, "SAVE_ROLLED")[-1]["mode"] == "NORMAL"  # Forward and Guarded are the Stances
    _pick(engine, "Banner Stance: Guarded + Steady")
    _bn_save(engine, ALLY, 10, condition="prone")
    assert _payloads(engine.events, "SAVE_ROLLED")[-1]["mode"] == "ADVANTAGE"
    from tests.test_auto_lane1 import _foe_forces_save

    _foe_forces_save(engine, ALLY, "WIS", condition="charmed")
    assert _payloads(engine.events, "SAVE_ROLLED")[-1]["mode"] == "NORMAL"
    _ally(engine).position = Position(x=12, y=7)
    _foe_forces_save(engine, ALLY, "WIS", condition="frightened")
    assert _payloads(engine.events, "SAVE_ROLLED")[-1]["mode"] == "NORMAL"  # outside the aura


def test_rally_the_line_gives_temporary_hit_points_and_a_free_step_once_per_creature_per_round():
    engine = _bn_stage()
    me, ally = _me(engine), _ally(engine)
    events = _pick(engine, "Rally the Line (2 Qi)")
    assert me.resources[QI] == 27 and (me.temporary_hp, ally.temporary_hp) == (6, 6)  # Proficiency Bonus 4 + key modifier 2
    assert me.turn_flags["oa_free_ft"] == 5  # the rallying cultivator steps at once
    assert _held(ally, STEP)[0].data["feet"] == 5  # the ally on its own turn
    assert any("Rally the Line" in line for line in _lines(events))
    _ready(engine)
    assert not _can(engine, "Rally the Line (2 Qi)")  # everyone in the aura was rallied this round
    engine.state.round_number += 1
    _ready(engine)
    assert _can(engine, "Rally the Line (2 Qi)")


def test_a_rally_leaves_out_an_ally_outside_the_aura_and_the_step_comes_at_the_start_of_its_turn():
    engine = _bn_stage()
    ally = _ally(engine)
    ally.position = Position(x=12, y=7)
    _pick(engine, "Rally the Line (2 Qi)")
    assert ally.temporary_hp == 0 and not _held(ally, STEP)
    ally.position = Position(x=3, y=7)
    engine.state.round_number += 1
    _ready(engine)
    _pick(engine, "Rally the Line (2 Qi)")
    before = ally.movement_remaining_ft
    _bn_turn_of(engine, ALLY)
    assert not _held(ally, STEP) and ally.movement_remaining_ft == before + 5 and ally.turn_flags["oa_free_ft"] == 5


def test_hold_formation_adds_the_proficiency_bonus_to_a_failed_save_against_frightened_for_a_reaction_and_a_qi():
    engine = _bn_stage()
    me, ally = _me(engine), _ally(engine)
    _bn_save(engine, ALLY, 5)  # 5 + 4 is short of 16: not helped
    assert me.resources[QI] == 29 and me.reaction_available and _held(ally, "condition:typed.frightened")
    engine._remove_condition(ally, "condition:typed.frightened", "test")
    _bn_save(engine, ALLY, 14)  # 14 + 4 turns it
    assert not _held(ally, "condition:typed.frightened")
    assert me.resources[QI] == 28 and not me.reaction_available
    assert any(e.event_type == "REACTION_RESOLVED" and e.payload.get("checkpoint") == "SAVE_FAILED" for e in engine.events)
    assert any("Hold Formation" in line for line in _lines(engine.events))
    _ready(engine)
    _bn_save(engine, ALLY, 14)  # once per round
    assert me.resources[QI] == 29 - 1 and _held(ally, "condition:typed.frightened")


def test_advancing_standard_widens_the_aura_moves_the_banner_free_and_steps_allies_at_their_turn_start():
    engine = _bn_stage()
    me, ally, zone = _me(engine), _ally(engine), _standard(engine)
    assert not _can(engine, "Move the Banner (up to 30 feet, free)")
    ally.position = Position(x=8, y=7)  # twenty feet from the banner
    assert not banner._covers(engine, zone, ally)
    _pick(engine, "Advancing Standard (4 Qi)")
    assert me.resources[QI] == 25 and banner._covers(engine, zone, ally) and "aura 20 ft" in zone.trigger_profile["name"]
    before = ally.movement_remaining_ft
    _bn_turn_of(engine, ALLY)
    assert ally.movement_remaining_ft == before + 5 and ally.turn_flags["oa_free_ft"] == 5  # Advance Together
    engine.state.current_actor_id = ME
    events = _pick(engine, "Move the Banner (up to 30 feet, free)", at=(8, 9))
    assert (zone.center.x, zone.center.y) == (8, 9) and me.action_available  # free: it took no action
    assert not _can(engine, "Move the Banner (up to 30 feet, free)", at=(7, 9))  # once each turn
    assert any("moves the Command Banner" in line for line in _lines(events))
    assert not _can(engine, "Advancing Standard (4 Qi)")  # it is running


def test_the_advancing_standard_runs_for_a_minute_then_the_aura_shrinks_back():
    engine = _bn_stage()
    zone = _standard(engine)
    _pick(engine, "Advancing Standard (4 Qi)")
    assert banner._aura(engine, zone) == 20
    engine.state.round_number += 10
    assert banner._aura(engine, zone) == 15


def test_a_formation_maneuver_follows_the_first_damage_an_ally_deals_each_turn():
    engine = _bn_stage()
    ally, foe = _ally(engine), _foe(engine)
    _pick(engine, "Advancing Standard (4 Qi)")
    _ready(engine)
    _pick(engine, "Formation Maneuver: Temporary Hit Points")
    engine.state.current_actor_id = ALLY
    _bn_hit(engine)
    assert ally.temporary_hp == 4 and any("Formation Maneuver (Temporary Hit Points)" in line for line in _lines(engine.events))
    _bn_hit(engine)
    assert ally.temporary_hp == 4  # once per turn
    _ready(engine)
    _pick(engine, "Formation Maneuver: no Reactions for the damaged creature")
    engine.state.current_actor_id = ALLY
    engine.state.round_number += 1
    _bn_hit(engine)
    assert any(c.condition_id.endswith("reaction_denied") for c in foe.conditions.values())


def test_formation_maneuver_automatic_heals_a_wounded_ally_and_otherwise_denies_the_foe_its_reaction():
    engine = _bn_stage()
    ally, foe = _ally(engine), _foe(engine)
    _pick(engine, "Advancing Standard (4 Qi)")
    engine.state.current_actor_id = ALLY
    ally.current_hp = ally.maximum_hp // 2
    _bn_hit(engine)
    assert ally.temporary_hp == 4
    engine.state.round_number += 1
    ally.current_hp = ally.maximum_hp
    _bn_hit(engine)
    assert any(c.condition_id.endswith("reaction_denied") for c in foe.conditions.values())


def test_a_formation_maneuver_can_push_the_damaged_creature_or_move_the_banner():
    engine = _bn_stage()
    foe, zone = _foe(engine), _standard(engine)
    _pick(engine, "Advancing Standard (4 Qi)")
    _ready(engine)
    _pick(engine, "Formation Maneuver: push the damaged creature 5 feet")
    engine.state.current_actor_id = ALLY
    _bn_hit(engine)
    assert (foe.position.x, foe.position.y) != (4, 6) and engine.grid.distance_ft(Position(x=4, y=6), foe.position) == 5
    engine.state.current_actor_id = ME
    _pick(engine, "Formation Maneuver: move the banner up to 10 feet")
    engine.state.current_actor_id = ALLY
    engine.state.round_number += 1
    at = (zone.center.x, zone.center.y)
    _bn_hit(engine)
    assert (zone.center.x, zone.center.y) != at and engine.grid.distance_ft(Position(x=at[0], y=at[1]), zone.center) <= 10


def _officer(order="auto", **stage):
    """The ally begins its turn inside the aura and the cultivator answers (Officer's Command)."""
    engine = _bn_stage(order=order, **stage)
    engine.state.current_actor_id = ALLY
    return engine


def test_officers_command_is_a_reaction_row_with_an_order_menu_and_no_range_of_its_own():
    engine = _bn_stage()
    row = next(r for r in engine.typed_reaction_rows[ME] if r["name"] == "Fourfold Formation")
    assert row["option_labels"] == ["Best fit", "Reposition", "Seize the Opening", "Brace", "Rise", "Remember Courage", "Shift the Standard"]
    assert row["range_ft"] is None and row["costs"] == [{"resource_id": QI, "amount": 2}]


def test_officers_command_best_fit_gives_seize_the_opening_to_an_ally_that_begins_its_turn_in_the_aura():
    engine = _officer()
    n = len(engine.events)
    typed_reactions.on_turn_start(engine, _ally(engine))
    me = _me(engine)
    assert me.resources[QI] == 27 and not me.reaction_available
    assert any(e.event_type == "MODIFIER_APPLIED" and e.payload["target_field"] == "attack_mode" and e.payload["value"] == "ADVANTAGE" for e in engine.events[n:])
    assert any("Officer's Command (Seize the Opening)" in line for line in _lines(engine.events[n:]))


def test_officers_command_needs_the_ally_inside_the_aura():
    engine = _officer()
    _ally(engine).position = Position(x=12, y=7)
    typed_reactions.on_turn_start(engine, _ally(engine))
    assert _me(engine).resources[QI] == 29 and _me(engine).reaction_available


def test_officers_command_best_fit_stands_a_prone_ally_and_reminds_a_frightened_one_of_courage():
    engine = _officer()
    engine._apply_condition(_ally(engine), "condition:typed.prone", "test", AN, expires_on="UNTIL_REMOVED")
    typed_reactions.on_turn_start(engine, _ally(engine))
    assert not _held(_ally(engine), "condition:typed.prone")  # Rise
    engine = _officer()
    engine._apply_condition(_ally(engine), "condition:typed.frightened", "test", ME, expires_on="UNTIL_REMOVED")  # from a source of its own Cultivation Level
    typed_reactions.on_turn_start(engine, _ally(engine))
    assert not _held(_ally(engine), "condition:typed.frightened")  # Remember Courage


def test_officers_command_reposition_gives_ten_feet_free_brace_gives_advantage_on_its_next_save_and_shift_moves_the_banner():
    engine = _officer("reposition")
    before = _ally(engine).movement_remaining_ft
    typed_reactions.on_turn_start(engine, _ally(engine))
    assert _ally(engine).movement_remaining_ft == before + 10 and _ally(engine).turn_flags["oa_free_ft"] == 10
    engine = _officer("brace")
    typed_reactions.on_turn_start(engine, _ally(engine))
    assert _held(_ally(engine), banner.BRACE)
    from tests.test_auto_lane1 import _foe_forces_save

    _foe_forces_save(engine, ALLY, "DEX")
    assert _payloads(engine.events, "SAVE_ROLLED")[-1]["mode"] == "ADVANTAGE" and not _held(_ally(engine), banner.BRACE)  # used up by the save
    _foe_forces_save(engine, ALLY, "DEX")
    assert _payloads(engine.events, "SAVE_ROLLED")[-1]["mode"] == "NORMAL"
    engine = _officer("shift")
    _ally(engine).position = Position(x=3, y=9)
    zone = _standard(engine)
    typed_reactions.on_turn_start(engine, _ally(engine))
    assert engine.grid.distance_ft(zone.center, Position(x=3, y=9)) < engine.grid.distance_ft(Position(x=4, y=7), Position(x=3, y=9))


def test_imperial_standard_of_heaven_widens_the_aura_to_forty_feet_gives_every_stance_and_is_once_per_scene():
    engine = _bn_stage()
    me, ally, zone = _me(engine), _ally(engine), _standard(engine)
    ally.position = Position(x=12, y=7)  # forty feet away
    plain = engine._ac_modifier(ally)
    events = _pick(engine, "Imperial Standard of Heaven (8 Qi, once per scene)")
    assert me.resources[QI] == 21 and banner._aura(engine, zone) == 40 and banner._covers(engine, zone, ally)
    assert banner._stances(engine, zone) == list(banner.STANCES) and "Imperial Standard of Heaven" in zone.trigger_profile["name"]
    assert engine._ac_modifier(ally) == plain + 1  # +1 Armor Class for the allies in it
    assert any("Imperial Standard of Heaven" in line for line in _lines(events)) and _held(me, banner.SPENT)
    _ready(engine)
    assert not _can(engine, "Imperial Standard of Heaven (8 Qi, once per scene)") and not _can(engine, "Advancing Standard (4 Qi)")
    engine.state.round_number += 10  # the minute ends: the aura and its Stances go
    assert banner._aura(engine, zone) == 15 and banner._stances(engine, zone) == ["forward", "guarded"]
    assert not _can(engine, "Imperial Standard of Heaven (8 Qi, once per scene)")  # once per scene: not again this fight


def test_imperial_standard_gives_advantage_on_saves_against_forced_movement_and_makes_rally_free_once_a_round():
    engine = _bn_stage()
    _pick(engine, "Imperial Standard of Heaven (8 Qi, once per scene)")
    _ready(engine)
    from tests.test_auto_lane1 import _foe_forces_save

    _foe_forces_save(engine, ALLY, "STR", condition="forced_movement")
    assert _payloads(engine.events, "SAVE_ROLLED")[-1]["mode"] == "ADVANTAGE"
    assert _pick(engine, "Rally the Line (2 Qi)") and _me(engine).resources[QI] == 21  # free the first time
    engine.state.round_number += 1
    _ready(engine)
    _pick(engine, "Rally the Line (2 Qi)")
    assert _me(engine).resources[QI] == 21  # free once each round


def test_imperial_advance_steps_two_allies_at_the_start_of_the_cultivators_turns_and_follow_the_victor_steps_another():
    engine = _bn_stage(ids=BANNER_FULL)
    _pick(engine, "Imperial Standard of Heaven (8 Qi, once per scene)")
    ally = _ally(engine)
    _bn_turn_of(engine, ME)
    assert _held(ally, STEP)[0].data["feet"] == 10
    ctx = SimpleNamespace(engine=engine, actor=_me(engine))
    engine.state.round_number += 1
    banner.follow_the_victor(ctx, _foe(engine), "attack")
    assert _held(ally, STEP)[0].data["feet"] == 15 and any("Follow the Victor" in line for line in _lines(engine.events))
    banner.follow_the_victor(ctx, _foe(engine), "attack")
    assert _held(ally, STEP)[0].data["feet"] == 15  # once each round


def test_standard_cannot_fall_keeps_an_ally_at_one_hit_point_the_first_time_but_not_when_killed_outright():
    engine = _bn_stage()
    ally = _ally(engine)
    ally.current_hp, ally.temporary_hp = 5, 0
    assert typed_reactions.on_damage(engine, ally, 9, 0, "test:blow", AN) == 9  # no Imperial Standard: the blow lands whole
    _pick(engine, "Imperial Standard of Heaven (8 Qi, once per scene)")
    assert typed_reactions.on_damage(engine, ally, 9, 0, "test:blow", AN) == 4  # left at 1
    assert _held(ally, STEP)[0].data["feet"] == 5 and any("Standard Cannot Fall" in line for line in _lines(engine.events))
    assert typed_reactions.on_damage(engine, ally, 9, 0, "test:blow", AN) == 9  # once each activation
    other = _me(engine)
    other.current_hp = 5
    assert typed_reactions.on_damage(engine, other, 5 + other.maximum_hp, 0, "test:blow", AN) == 5 + other.maximum_hp  # killed outright


def test_the_banner_conditions_read_out_on_the_table_and_the_would_drop_hook_is_documented():
    conditions = condition_text.all_conditions()
    for key in ("banner_orders", "banner_step", "banner_brace", "banner_imperial_spent"):
        assert conditions[key]["reading"]
    assert "would_drop" in ext.__doc__


# ------------------------------------------------------------------------------------------- 6. Cut the Road Behind You (Space)

CUT = "tianxia.talent.space.cut_the_road_behind_you"
SEALER = ME
FOLLOWER = "actor:factory.follower"
CUT_4 = "Cut the Road Behind You (4 CP)"
CUT_FREE = "Cut the Road Behind You (No Road Behind Me, free)"


def _sp_bundle(actor_id, *talents, cl=10, dc=16):
    sheet = _sheet("TAL_SPACE_FOLD_STEP", cl=cl, dc=dc)
    sheet["spheres_and_talents"]["learned_talent_record_ids"] = list(talents)
    return compile_character(sheet, actor_id=actor_id)


def _sp_scene(*, cl=10, dc=16, no_road=True):
    """Two Space cultivators on opposing sides: the sealer (Fold Step, Cut the Road, No Road Behind Me) on (3,6) and a follower with Fold Step on
    (4,6).  The sealer's Cultivation Save DC is ``dc``: 1 lets any follower through, 50 stops every one."""
    from combat.gate4_engine import Gate4ControllerEngine
    from tests.test_auto_lane1 import ROOT

    talents = ["TAL_SPACE_FOLD_STEP", CUT, *(["TAL_SPACE_NO_ROAD_BEHIND_ME"] if no_road else [])]
    engine = Gate4ControllerEngine(
        ROOT, match_seed="SEAL", typed_bundles=(_sp_bundle(SEALER, *talents, cl=cl, dc=dc), _sp_bundle(FOLLOWER, "TAL_SPACE_FOLD_STEP")),
        roster_setup={"primary_actor_ids": [SEALER, FOLLOWER], "team_by_actor": {SEALER: "team:a", FOLLOWER: "team:b"},
                      "starting_positions": {SEALER: {"x": 3, "y": 6}, FOLLOWER: {"x": 4, "y": 6}}})
    _sp_turn(engine, SEALER)
    return engine


def _sp_turn(engine, actor_id):
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    engine.state.current_actor_id = actor_id
    engine._system_start_turn()
    actor = engine.state.actors[actor_id]
    actor.action_available, actor.bonus_action_available, actor.reaction_available = True, True, True
    return actor


def _sp_step(engine, actor_id, to):
    """A Fold Step to a square (the Bonus Action is handed back afterwards: Fold Step is one, and a second teleport by Action or Reaction leaves it)."""
    events = _pick(engine, f"Fold Step to {to[0]},{to[1]}", actor=actor_id)
    engine.state.actors[actor_id].bonus_action_available = True
    return events


def _sealed_scene(**kwargs):
    engine = _sp_scene(**kwargs)
    _sp_step(engine, SEALER, (3, 2))
    _pick(engine, CUT_4)
    return engine


def test_cut_the_road_is_a_button_that_needs_a_teleport_of_your_own_to_seal():
    engine = _sp_scene()
    names = {c.display_name for c in engine.legal_candidates()}
    assert "Cut the Road Behind You" not in names  # no GM-line stand-in: the compiled effect-less action is gone
    assert CUT_4 not in names and CUT_FREE not in names  # nothing to seal before a teleport
    me = engine.state.actors[SEALER]
    events = _sp_step(engine, SEALER, (3, 2))
    assert me.position == Position(x=3, y=2)
    assert _can(engine, CUT_4) and _can(engine, CUT_FREE)
    before = me.resources[QI]
    events = _pick(engine, CUT_4)
    assert me.resources[QI] == before - 4  # "Cost: 4 CP."
    zone = placed.of(engine, "seal", owner_id=SEALER)[0]
    assert (zone.center.x, zone.center.y) == (3, 6) and zone.duration_rounds == 1  # the trace's departure; "until the start of your next turn"
    data = placed.data(zone)
    assert data["from"] == [3, 6] and data["to"] == [3, 2] and data["dc"] == 16 and data["until"] == "start"
    assert "sealed road" in zone.trigger_profile["name"] and "16" in zone.trigger_profile["name"]
    assert any("seals the road" in line for line in _lines(events))
    _ready(engine)
    assert not _can(engine, CUT_4) and not _can(engine, CUT_FREE)  # one seal to a trace


def test_cut_the_road_needs_four_cp_and_the_sealers_own_turn():
    engine = _sp_scene(no_road=False)
    _sp_step(engine, SEALER, (3, 2))
    me = engine.state.actors[SEALER]
    me.resources[QI] = 3
    assert not _can(engine, CUT_4)
    me.resources[QI] = 4
    assert _can(engine, CUT_4) and not _can(engine, CUT_FREE)  # No Road Behind Me not learned: no free button
    _pick(engine, CUT_4)
    assert me.resources[QI] == 0
    low = _sp_scene(cl=9)
    _sp_step(low, SEALER, (3, 2))
    assert _can(low, CUT_4) and not _can(low, CUT_FREE)  # "Prerequisite: Space sphere, CL 10+."


def test_a_creature_that_follows_the_sealed_road_makes_a_cultivation_check_and_stays_put_on_a_failure():
    engine = _sealed_scene(dc=50)
    follower = _sp_turn(engine, FOLLOWER)
    events = _sp_step(engine, FOLLOWER, (4, 2))  # from beside the departure to beside the arrival: the same road
    assert follower.position == Position(x=4, y=6)  # the teleport failed
    checks = [e for e in events if e.event_type == "CHECK_ROLLED"]
    assert len(checks) == 1 and checks[0].payload["dc"] == 50 and checks[0].payload["success"] is False  # one check, though Fold Step has two rows
    numbers = seal._kit(engine, engine.state.actors[SEALER])["numbers"]
    roll = checks[0].payload["actor"]
    assert roll["modifier"] == int(numbers["pb"]) + int(numbers["key_mod"])  # d20 + Proficiency Bonus + key ability modifier
    assert not [e for e in events if e.event_type == "MOVEMENT_COMMITTED"]
    assert any("cannot follow" in line and "stays at (4, 6)" in line for line in _lines(events))


def test_a_creature_that_beats_the_seal_follows_and_other_teleports_are_not_held():
    engine = _sealed_scene(dc=1)
    follower = _sp_turn(engine, FOLLOWER)
    events = _sp_step(engine, FOLLOWER, (4, 2))
    assert follower.position == Position(x=4, y=2) and any("follows" in line for line in _lines(events))
    assert [e for e in events if e.event_type == "MOVEMENT_COMMITTED"]
    hard = _sealed_scene(dc=50)
    other = _sp_turn(hard, FOLLOWER)
    events = _sp_step(hard, FOLLOWER, (4, 9))  # not toward the arrival: not following
    assert other.position == Position(x=4, y=9) and not [e for e in events if e.event_type == "CHECK_ROLLED"]
    away = _sealed_scene(dc=50)
    away.state.actors[FOLLOWER].position = Position(x=12, y=12)
    _sp_turn(away, FOLLOWER)
    events = _sp_step(away, FOLLOWER, (12, 8))  # a teleport that begins far from the departure is another road
    assert not [e for e in events if e.event_type == "CHECK_ROLLED"]


def test_the_sealer_walks_its_own_road_and_a_walker_is_not_a_teleporter():
    engine = _sealed_scene(dc=50)
    me = engine.state.actors[SEALER]
    me.position = Position(x=3, y=6)
    _ready(engine)
    events = _sp_step(engine, SEALER, (3, 2))  # back the way it came
    assert me.position == Position(x=3, y=2) and not [e for e in events if e.event_type == "CHECK_ROLLED"]
    walker = _sp_turn(engine, FOLLOWER)
    _walk(engine, FOLLOWER, [(4, 5), (4, 4)])
    assert walker.position == Position(x=4, y=4)  # ordinary movement crosses the departure without a check


def test_the_seal_ends_at_the_start_of_the_sealers_next_turn_and_at_cl_20_at_the_end_of_it():
    engine = _sealed_scene()
    engine.state.round_number += 1
    zones.on_turn_start(engine, engine.state.actors[SEALER])
    assert not placed.of(engine, "seal")
    _sp_turn(engine, FOLLOWER)
    events = _sp_step(engine, FOLLOWER, (4, 2))
    assert not [e for e in events if e.event_type == "CHECK_ROLLED"]  # the road is open again
    long = _sealed_scene(dc=50, cl=20)
    zone = placed.of(long, "seal")[0]
    assert placed.data(zone)["until"] == "end" and zone.duration_rounds is None
    long.state.round_number += 1
    zones.on_turn_start(long, long.state.actors[SEALER])
    assert placed.of(long, "seal")  # "At CL 20, the seal lasts until the end of your next turn."
    _turn(long, SEALER, "TURN_ENDED")
    assert not placed.of(long, "seal")


def test_no_road_behind_me_makes_one_cut_free_each_long_rest():
    engine = _sp_scene()
    me = engine.state.actors[SEALER]
    _sp_step(engine, SEALER, (3, 2))
    before = me.resources[QI]
    events = _pick(engine, CUT_FREE)
    assert me.resources[QI] == before and placed.of(engine, "seal") and _held(me, seal.FREE_USED)  # "without spending CP"
    engine.state.round_number += 1
    zones.on_turn_start(engine, me)
    _sp_turn(engine, SEALER)
    _sp_step(engine, SEALER, (3, 6))
    assert not _can(engine, CUT_FREE) and _can(engine, CUT_4)  # "Once per long rest"


def test_the_seal_conditions_read_out_and_the_teleport_gate_hook_is_documented():
    assert condition_text.all_conditions()["seal_free_used"]["reading"]
    assert "teleport_gate" in ext.__doc__ and ext.has("teleport_gate")


# ---------------------------------------------------------------------------------------------- 7. Safe Return Mark (Space)

MARK_BTN = "Safe Return Mark (1 CP)"
BACK_STEP = "Fold Step to the Safe Return Mark (1 CP)"
BACK_SWAP = "Short Swap to the Safe Return Mark (1 CP)"


def _rm_scene(*extra, cl=10):
    """A Space cultivator with Fold Step, Safe Return Mark (and ``extra``) on (3,6), a foe-side Space creature on (4,6)."""
    from combat.gate4_engine import Gate4ControllerEngine
    from tests.test_auto_lane1 import ROOT

    talents = ["TAL_SPACE_FOLD_STEP", "tianxia.talent.space.safe_return_mark", *extra]
    engine = Gate4ControllerEngine(
        ROOT, match_seed="MARK", typed_bundles=(_sp_bundle(SEALER, *talents, cl=cl), _sp_bundle(FOLLOWER, "TAL_SPACE_FOLD_STEP")),
        roster_setup={"primary_actor_ids": [SEALER, FOLLOWER], "team_by_actor": {SEALER: "team:a", FOLLOWER: "team:b"},
                      "starting_positions": {SEALER: {"x": 3, "y": 6}, FOLLOWER: {"x": 4, "y": 6}}})
    _sp_turn(engine, SEALER)
    return engine


def _rm_marked(*extra, **kwargs):
    engine = _rm_scene(*extra, **kwargs)
    _pick(engine, MARK_BTN)
    engine.state.actors[SEALER].bonus_action_available = True
    return engine


def test_safe_return_mark_is_a_one_cp_bonus_action_button_that_marks_the_space_not_a_free_teleport():
    engine = _rm_scene()
    names = {c.display_name for c in engine.legal_candidates()}
    assert MARK_BTN in names and not any(n.startswith("Safe Return Mark at") for n in names)  # was a free 120-ft self-teleport for 1 CP
    assert BACK_STEP not in names  # nothing marked yet
    me = engine.state.actors[SEALER]
    before = me.resources[QI]
    events = _pick(engine, MARK_BTN)
    assert me.resources[QI] == before - 1 and not me.bonus_action_available  # "Cost: 1 CP.", "Action Type: Bonus Action"
    assert me.position == Position(x=3, y=6)  # marking does not move anyone
    zone = placed.of(engine, "return", owner_id=SEALER)[0]
    assert zone.center == Position(x=3, y=6) and zone.duration_rounds == 10  # "your current space", "Duration: 1 minute"
    assert any("marks (3, 6)" in line for line in _lines(events))


def test_a_new_mark_replaces_the_old_one_and_the_mark_lapses_after_a_minute():
    engine = _rm_marked()
    _sp_step(engine, SEALER, (3, 2))
    _pick(engine, MARK_BTN)
    marks = placed.of(engine, "return", owner_id=SEALER)
    assert len(marks) == 1 and marks[0].center == Position(x=3, y=2)  # default: one mark at a time
    engine.state.round_number += 10
    zones.on_turn_start(engine, engine.state.actors[SEALER])
    assert not placed.of(engine, "return")  # "Duration: 1 minute" = ten rounds


def test_fold_step_to_the_mark_teleports_the_marker_home_for_the_arts_price_and_uses_the_mark_up():
    engine = _rm_marked()
    me = engine.state.actors[SEALER]
    _sp_step(engine, SEALER, (3, 2))
    assert me.position == Position(x=3, y=2) and _can(engine, BACK_STEP)
    before = me.resources[QI]
    events = _pick(engine, BACK_STEP)
    assert me.position == Position(x=3, y=6) and me.resources[QI] == before - 1  # Fold Step's own price
    moved = [e for e in events if e.event_type == "MOVEMENT_COMMITTED"]
    assert moved and moved[0].payload.get("teleport") is True  # a teleport like any other
    assert not placed.of(engine, "return")  # "Once before the mark ends"
    assert any("returns to the mark" in line for line in _lines(events))
    _ready(engine)
    assert not _can(engine, BACK_STEP)


def test_the_return_jump_needs_distance_a_free_marked_space_the_cp_and_no_teleport_seal(monkeypatch):
    engine = _rm_marked()
    me = engine.state.actors[SEALER]
    assert not _can(engine, BACK_STEP)  # already on the mark
    _sp_step(engine, SEALER, (3, 2))
    monkeypatch.setattr(return_mark, "RANGE_FT", 10)
    assert not _can(engine, BACK_STEP)  # "if it is within 120 feet" (here shrunk to 10 ft; the test map is 100 ft wide)
    monkeypatch.undo()
    assert _can(engine, BACK_STEP)
    me.resources[QI] = 0
    assert not _can(engine, BACK_STEP)
    me.resources[QI] = 5
    engine.state.actors[FOLLOWER].position = Position(x=3, y=6)  # "unoccupied"
    assert not _can(engine, BACK_STEP)
    engine.state.actors[FOLLOWER].position = Position(x=4, y=6)
    assert _can(engine, BACK_STEP)
    engine._apply_condition(me, typed_executor.CONDITION_PREFIX + "cannot_teleport", "test:seal", FOLLOWER, expires_on="UNTIL_REMOVED")
    assert not _can(engine, BACK_STEP)  # a sealed creature cannot teleport by any Art


def test_a_creature_that_ends_a_move_on_the_marked_space_ends_the_mark():
    engine = _rm_marked()
    _sp_step(engine, SEALER, (3, 2))
    events = _walk(engine, FOLLOWER, [(3, 6)])  # the marked space is now occupied
    assert not placed.of(engine, "return")  # "If the marked space becomes occupied ... the mark ends"
    assert any("Safe Return Mark ends" in line for line in _lines(events))


def test_the_marker_may_stand_on_its_own_mark_and_walk_off_it():
    engine = _rm_marked()
    _walk(engine, SEALER, [(3, 5), (3, 6)])
    assert placed.of(engine, "return", owner_id=SEALER)
    other = _rm_marked()
    _walk(other, FOLLOWER, [(4, 5), (4, 4)])  # another creature passing by, not on it
    assert placed.of(other, "return", owner_id=SEALER)


def test_short_swap_to_the_mark_is_an_action_for_one_cp_and_needs_the_talent():
    engine = _rm_marked("tianxia.talent.space.short_swap")
    me = engine.state.actors[SEALER]
    _sp_step(engine, SEALER, (3, 2))
    assert _can(engine, BACK_SWAP)
    before = me.resources[QI]
    _pick(engine, BACK_SWAP)
    assert me.position == Position(x=3, y=6) and me.resources[QI] == before - 1 and not me.action_available
    assert not placed.of(engine, "return")
    plain = _rm_marked()
    _sp_step(plain, SEALER, (3, 2))
    assert not _can(plain, BACK_SWAP)  # Short Swap not learned


def test_a_sealed_road_holds_the_return_jump_like_any_other_teleport():
    engine = _rm_marked()
    sealer_turn = engine.state.actors[SEALER]
    _sp_step(engine, SEALER, (3, 2))
    # the foe's sealed road runs from where the marker now stands (3,2) to the marked space (3,6): a Cultivation Check against 50 to follow it
    foe = engine.state.actors[FOLLOWER]
    source = next(a.source_definition_id for a in engine.action_catalog.values() if a.owner_id == FOLLOWER)
    placed.place(engine, foe, source=source, tag="seal", cells=[(3, 2)], shape="sphere", size_ft=10, duration_rounds=1, name="a sealed road",
                 placed={"owner": FOLLOWER, "from": [3, 2], "to": [3, 6], "dc": 50, "until": "start", "sequence": 0}, numbers={})
    _sp_turn(engine, SEALER)
    events = _pick(engine, BACK_STEP)
    assert sealer_turn.position == Position(x=3, y=2)  # the Cultivation Check failed: stays put
    assert [e for e in events if e.event_type == "CHECK_ROLLED"]
    assert placed.of(engine, "return")  # the jump did not happen: the mark stands
