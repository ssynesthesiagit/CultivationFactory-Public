"""Rider lane C11 (owner 2026-09-30: "i want everything we can automated, keep going until its only the non-combat ones left"):
the printed lines of partly automated Sphere talents that were only shown to the GM as riders (Magma, Metal, Qiweaving, Smoke,
Sniper, Sound, Source, Space, Spear, Thread, Warleader, Water, Wax, Yang). Every automated line is compiled on a real character
and run through the engine. C11_OLD=1 swaps in the base typing (a9d0770f): the typing tests then fail, and the plug-in tests
fail on the base code (their modules do not exist there).

Overrides: authority/typed_mechanics/reviewed_final.d/riders_c11.json (and entries edited in place in the other reviewed files);
feature blocks combat/rules/feature_blocks.d/riders_c11.json; plug-ins named per section below.
"""

from __future__ import annotations

import copy
import importlib
from contextlib import contextmanager
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import combat.factory_compiler as compiler
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent

sys.path.insert(0, str(Path(__file__).resolve().parent))
t = importlib.import_module("test_review_sw-athletics")

ROOT = Path(__file__).resolve().parents[1]
ME, AN = t.ME, t.AN
BASE = "a9d0770f"


@pytest.fixture(autouse=True, scope="session")
def base_typing(tmp_path_factory):
    if os.environ.get("C11_OLD"):
        path = tmp_path_factory.mktemp("authority") / "base.json"
        path.write_bytes(subprocess.check_output(["git", "show", f"{BASE}:APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json"], cwd=ROOT))
        compiler.TYPED_AUTHORITY = path


def _authority():
    return json.loads(Path(compiler.TYPED_AUTHORITY).read_text(encoding="utf-8"))["mechanics"]


# ------------------------------------------------------------------------------------------------------------ harness
def _sheet(spheres, talents, items=(), cl=12, dc=16):
    spheres = [spheres] if isinstance(spheres, str) else list(spheres)
    sheet = t._sheet(spheres[0], list(talents), {"starting_kit": {"items": list(items)}} if items else {}, cl=cl, dc=dc)
    mechanics = t._mechanics()
    for sphere in spheres[1:]:
        sheet["spheres_and_talents"]["sphere_record_ids"].append(sphere)
        sheet["spheres_and_talents"]["automatic_sphere_component_record_ids"] += [
            key for key, row in mechanics.items() if row.get("sphere_id") == sphere and row.get("kind") == "base_ability"]
    return sheet


def _bundle(spheres, talents, items=(), cl=12, dc=16):
    return compile_character(_sheet(spheres, talents, items, cl, dc), actor_id=ME)


def _fight(spheres, talents, items=(), cl=12, dc=16, foe_hp=400, sure_hit=True, foe_at=(4, 6)):
    engine = t._engine(_bundle(spheres, talents, items, cl, dc), foe_hp=foe_hp, sure_hit=sure_hit, foe_at=foe_at)
    return engine, engine.state.actors[ME], engine.state.actors[AN]


def _duel(my_bundle, foe_bundle, foe_at=(4, 6), foe_hp=400):
    """Me against a compiled Factory foe (its typed defenses run: typed_reactions.defend)."""
    from combat.gate4_engine import Gate4ControllerEngine

    engine = Gate4ControllerEngine(ROOT, match_seed="C11-DUEL", typed_bundles=(my_bundle, foe_bundle),
                                   roster_setup={"primary_actor_ids": [ME, t.FOE], "team_by_actor": {ME: "team:a", t.FOE: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, t.FOE: {"x": foe_at[0], "y": foe_at[1]}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    foe = engine.state.actors[t.FOE]
    foe.armor_class = -50
    foe.maximum_hp = foe.current_hp = foe_hp
    t._ready(engine)
    return engine, engine.state.actors[ME], foe


def _names(engine):
    t._ready(engine)
    return {c.display_name for c in engine.legal_candidates() if c.actor_id == ME}


def _use(engine, name, target=AN, contains=False):
    t._ready(engine)
    found = [c for c in engine.legal_candidates() if (name in c.display_name if contains else c.display_name == name) and c.actor_id == ME
             and (target is None or not c.target_ids or target in c.target_ids)]
    assert found, f"{name!r} is not legal; legal: {sorted(n for n in _names(engine) if not n.startswith('Move'))}"
    candidate = found[0]
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"i-{name}-{engine.state.event_sequence}", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=ME,
                                       target_ids=candidate.target_ids, destination=candidate.destination, option_ids=candidate.option_ids))
    return engine.events[before:]


def _events(events, kind):
    return [e for e in events if e.event_type == kind]


# ================================================================================================================ Qiweaving
QI, FIRE, ICE = "tianxia.sphere.qiweaving", "tianxia.sphere.fire", "tianxia.sphere.ice"
DISTANT, RETUNE = "TAL_QIWEAVING_DISTANT_MODULATION", "TAL_QIWEAVING_RETUNE_CURRENT"
STABLE, CIRCUIT = "TAL_QIWEAVING_STABLE_MODULATION", "TAL_QIWEAVING_STABILIZING_CIRCUIT"


def test_qiweaving_rider_lines_the_table_now_runs_are_gone():
    mechanics = _authority()
    for key in (DISTANT, RETUNE, CIRCUIT):
        assert mechanics[key]["riders"] == [], key
        assert mechanics[key]["coverage"] == "FULL", key


def test_distant_modulation_reaches_any_sphere_technique_with_a_range_and_never_a_self_one():
    """"When you activate a sphere technique with a range of at least 10 feet, increase its range by 30 feet. At CL 11, ... 60 feet";
    "cannot make a touch-range technique ranged". A Modulation alters a technique of any sphere you know (Apply Modulation)."""
    bundle = _bundle([QI, FIRE], [DISTANT, "TAL_QIWEAVING_COURT_OF_TEN_THOUSAND_CURRENTS"], cl=12)
    rows = {row["display_name"]: row for row in bundle["action_catalog"]}
    distant = {name: row for name, row in rows.items() if name.endswith("+ Distant Modulation")}
    fire = [name for name in distant if name.startswith("Ignite")]
    assert fire, sorted(distant)
    assert all(rows[name]["range_ft"] == rows[name.removesuffix(" + Distant Modulation")]["range_ft"] + 60 for name in fire)
    assert "Court of Ten Thousand Currents + Distant Modulation" not in distant  # a self technique
    assert "Minor Qi Arts + Distant Modulation" not in distant  # no range at all


def test_retune_current_changes_the_damage_to_a_type_another_known_sphere_deals():
    """"choose one damage type from that list that another sphere you know could plausibly produce. Change one damage roll of the
    technique to the chosen damage type": a Fire technique of a Qiweaver who also knows Ice may deal Cold; against a creature that
    resists Fire the table picks Cold (the owner's damage-type choice rule)."""
    engine, me, foe = _fight([QI, FIRE, ICE], [RETUNE], cl=12)
    engine._add_modifier(foe, "test:fire_resistance", "damage_resistance", "ADD", "FIRE", "self", expires_on="UNTIL_REMOVED")
    retune = sorted(n for n in _names(engine) if n.endswith("+ Retune Current"))
    assert retune and all(n.startswith(("Ignite", "Conflagration")) for n in retune), retune
    name = next(n for n in retune if n.startswith("Ignite"))
    events = _use(engine, name)
    kinds = {e.payload.get("damage_type") for e in _events(events, "DAMAGE_COMMITTED") if AN in (e.target_ids or ())}
    assert kinds == {"COLD"}, [e.payload for e in _events(events, "DAMAGE_COMMITTED")]


def test_retune_current_needs_another_sphere_that_justifies_a_type():
    """"Retune Current cannot create a damage type that none of your known spheres can justify": Qiweaving and Fire only."""
    engine, _me, _foe = _fight([QI, FIRE], [RETUNE], cl=12)
    assert not [n for n in _names(engine) if n.endswith("+ Retune Current")]
    # and never on a technique that deals none of the listed types (Qi Bond deals no damage)
    engine, _me, _foe = _fight([QI, FIRE, ICE], [RETUNE], cl=12)
    assert "Qi Bond + Retune Current" not in _names(engine)


def _stable_fight():
    engine, me, foe = _fight([QI], [STABLE, CIRCUIT], cl=12)
    _use(engine, "Qi Bond + Stable Modulation")
    assert me.concentration is not None and me.concentration.source_definition_id.endswith(
        next(a for a in engine.action_catalog.values() if a.display_name == "Qi Bond + Stable Modulation").source_definition_id.rsplit(".", 1)[-1])
    return engine, me


def _circuit(me):
    return [c for c in me.conditions.values() if c.condition_id == "condition:typed.stabilizing_circuit"]


def test_stabilizing_circuit_adds_pb_to_the_first_concentration_save_for_that_technique():
    """"When you apply Stable Modulation, you may also add your Proficiency Bonus to the first Concentration saving throw made for
    that technique before the start of your next turn." """
    engine, me = _stable_fight()
    assert len(_circuit(me)) == 1
    before = len(engine.events)
    engine._concentration_check(me, 10)
    bonus = [e for e in engine.events[before:] if e.event_type == "D20_REWRITTEN" and e.source_definition_id == CIRCUIT]
    assert [e.payload["bonus"] for e in bonus] == [4]
    assert _circuit(me) == []  # the first save uses it up
    before = len(engine.events)
    if me.concentration is not None:
        engine._concentration_check(me, 10)
    assert not [e for e in engine.events[before:] if e.event_type == "D20_REWRITTEN" and e.source_definition_id == CIRCUIT]


def test_stabilizing_circuit_is_inert_without_the_talent():
    engine, me, _foe = _fight([QI], [STABLE], cl=12)
    _use(engine, "Qi Bond + Stable Modulation")
    assert _circuit(me) == []


def test_stabilizing_circuit_survives_a_table_commit_and_reload(tmp_path):
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="C11-CIRCUIT", typed_bundles=(_bundle([QI], [STABLE, CIRCUIT]),),
                                       roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                     "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 5, "y": 6}}})

    def commit(candidate):
        session.mechanical.execute_intent(ActionIntent(
            intent_id=f"c11-{candidate.state_version}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
            state_version=candidate.state_version, actor_id=candidate.actor_id, target_ids=candidate.target_ids,
            destination=candidate.destination))

    while session.engine.state.current_actor_id != ME:
        commit(next(c for c in session.engine.legal_candidates() if c.display_name == "End turn"))
    commit(next(c for c in session.engine.legal_candidates() if c.display_name == "Qi Bond + Stable Modulation"))
    reloaded = persistence.load_match(session.match_id)
    assert reloaded.verify()["status"] == "PASS"
    me = reloaded.engine.state.actors[ME]
    assert len(_circuit(me)) == 1 and (_circuit(me)[0].data or {}).get("bonus") == 4


# ================================================================================================================ Smoke
SMOKE = "tianxia.sphere.smoke"
DOMAIN = "TAL_SMOKE_SMOKE_DOMAIN_COURT_OF_HIDDEN_WITNESSES"


def test_dense_smoke_is_what_the_tables_dense_areas_already_are():
    """Dense Smoke: "Dense smoke is Heavily Obscured for creatures that rely on sight ... does not automatically deafen creatures,
    poison creatures, block Tremorsense, or prevent creatures from making attacks into or out of it." The table's Dense area (Smoke
    Domain: "The area is Dense Smoke") is a heavily obscured zone: sight cannot see a creature inside it, Blindsight can, and it
    adds no condition. The lines are no longer GM riders."""
    from combat import stealth

    assert _authority()["SMOKE_BASE_DENSE_SMOKE"]["riders"] == []
    engine, me, foe = _fight([SMOKE], [DOMAIN], cl=20, foe_at=(12, 6))
    rows = {a.display_name: a for a in engine.action_catalog.values() if a.owner_id == ME}
    assert rows["Smoke Domain: Court of Hidden Witnesses"].parameters["typed"]["zone_spec"]["obscured"] == "heavy"
    _use(engine, "Smoke Domain: Court of Hidden Witnesses", target=None, contains=True)
    zone = next(z for z in engine.state.zones.values() if DOMAIN in z.source_definition_id)
    inside = zone.affected_cells[len(zone.affected_cells) // 2]
    foe.position = inside.model_copy()
    watcher = me.model_copy(deep=True)
    watcher.entity_id, watcher.team_id = "c11:watcher", foe.team_id + ":other"
    watcher.position = watcher.position.model_copy(update={"x": inside.x - 6 if inside.x > 6 else inside.x + 6, "y": inside.y})
    engine.state.actors[watcher.entity_id] = watcher
    assert not stealth.sees(engine, watcher, foe)
    assert not [c for c in foe.conditions.values() if c.condition_id.endswith((".deafened", ".poisoned"))]


# ================================================================================================================ Sniper
SNIPER = "tianxia.sphere.sniper"
BOUNCING, PHASIC = "TAL_SNIPER_BOUNCING_SHOT", "TAL_SNIPER_PHASIC_SHOT"
WRONG_DOOR, RICOCHET = "TAL_SNIPER_THROUGH_THE_WRONG_DOOR", "TAL_SNIPER_WORLD_NEEDLE_RICOCHET"
BOW = {"item_id": "tianxia.mortal.weapon.gong_jian", "name": "Gong Jian", "quantity": 1}
SNIPE = "Snipe Shot: Gong Jian (Bow and Arrow)"
PLAIN = "Gong Jian (Bow and Arrow) attack"  # "a Snipe Shot with none is the plain attack" (combat/ext/docket_maneuvers.py)


def _sniper(talents, cl=17, foe_at=(9, 6)):
    engine, me, foe = _fight([SNIPER], talents, items=[BOW], cl=cl, foe_at=foe_at)
    me.resources["resource:core.martial_focus"] = 1
    return engine, me, foe


@contextmanager
def _map_cover(engine, cell):
    """A square of the map's own Half Cover (combat/zones.sync_walls rebuilds the grid's cover from the map base each time)."""
    from combat import zones

    zones.sync_walls(engine)
    base = engine._wall_base
    engine._wall_base = (base[0], base[1], frozenset({*base[2], cell}), base[3])
    zones.sync_walls(engine)
    try:
        yield
    finally:
        engine._wall_base = base
        zones.sync_walls(engine)


def _attack_modifier(events):
    rolls = [e for e in events if e.event_type == "ATTACK_ROLLED"]
    assert rolls, [e.event_type for e in events]
    return int(rolls[0].payload["modifier"]), int(rolls[0].payload.get("cover_bonus") or 0)


def _shot_modifier(talents, name, cover):
    engine, me, _foe = _sniper(talents)
    if not cover:
        events = _use(engine, name)
    else:
        # Cover on both the direct ray and the final leg of the native bounce.
        with _map_cover(engine, (6, 6)), _map_cover(engine, (9, 3)):
            events = _use(engine, name)
        if 'Bouncing Shot' in name:
            geometry = next(e.payload['shot_geometry'] for e in events if e.payload.get('shot_geometry'))
            assert geometry['cover_before'] == 2
            assert geometry['cover_after'] == 0
    return _attack_modifier(events), [e.payload.get("log") for e in events if e.event_type == "PASSIVE_TRIGGERED"]


def test_sniper_rider_lines_the_table_now_runs_are_gone():
    mechanics = _authority()
    # Wall-route cover is native, but approved openings/exact-location and all
    # unseen-mode sources are not; the chapter cannot honestly be FULL yet.
    assert mechanics[WRONG_DOOR]["riders"] and mechanics[WRONG_DOOR]["coverage"] == "CORE_WITH_RIDERS"
    assert not [r for r in mechanics[RICOCHET]["riders"] if "Three-Quarters" in r]
    assert mechanics[BOUNCING]["modifier"]["cost"] == [[{"resource": "martial_focus", "amount": 1}]]


def test_through_the_wrong_door_bounced_shot_ignores_half_cover():
    """Native routed cover replaces the older attack-bonus compensation once."""
    bounce = f"{SNIPE} + Bouncing Shot"
    (plain, plain_cover), _ = _shot_modifier([BOUNCING, WRONG_DOOR], PLAIN, cover=True)
    (bounced, cover), logs = _shot_modifier([BOUNCING, WRONG_DOOR], bounce, cover=True)
    assert plain_cover == 2 and cover == 0
    assert bounced == plain  # reduced defense, without a second attack bonus
    assert any("Bouncing Shot bends" in (log or "") for log in logs), logs
    (clear, _no_cover), _ = _shot_modifier([BOUNCING, WRONG_DOOR], bounce, cover=False)
    assert clear == plain  # nothing to ignore


def test_bouncing_shot_native_route_is_offered_and_costs_martial_focus():
    engine, me, _foe = _sniper([BOUNCING])
    assert f"{SNIPE} + Bouncing Shot" in _names(engine)
    events = _use(engine, f"{SNIPE} + Bouncing Shot")
    assert me.resources["resource:core.martial_focus"] == 0
    assert any(e.payload.get('shot_geometry', {}).get('route') for e in events)
    engine, me, _foe = _sniper([BOUNCING, RICOCHET])
    assert f"{SNIPE} + Bouncing Shot" in _names(engine)
    _use(engine, f"{SNIPE} + Bouncing Shot")
    assert me.resources["resource:core.martial_focus"] == 0


def test_phasic_shot_ignores_cover():
    """Phasic Shot: "For this attack, you ignore cover" (Half Cover: the +2 no longer counts)."""
    engine, me, foe = _sniper([PHASIC], cl=17)
    with _map_cover(engine, (6, 6)):
        (plain, cover), = [_attack_modifier(_use(engine, PLAIN))]
        me.resources["resource:core.martial_focus"] = 1
        (phasic, _), = [_attack_modifier(_use(engine, f"{SNIPE} + Phasic Shot"))]
    assert cover == 2 and phasic == plain + 2


def test_through_the_wrong_door_drops_the_unseen_disadvantage_but_not_against_a_hidden_foe(monkeypatch):
    """"If you expend Martial Focus, you may also ignore the Disadvantage from attacking a target you cannot see, provided you know
    its exact location" (Bouncing Shot has already expended it). A Hidden foe's location is not known."""
    from combat import stealth, zones

    monkeypatch.setattr(zones, "attack_modes", lambda *_: ('DISADVANTAGE',))  # a heavy cloud hides the foe from the shooter
    engine, me, foe = _sniper([BOUNCING, WRONG_DOOR])
    events = _use(engine, f"{SNIPE} + Bouncing Shot")
    roll = next(e for e in events if e.event_type == "ATTACK_ROLLED")
    assert roll.payload["mode"] == "NORMAL", roll.payload
    assert any("not seeing it gives no Disadvantage" in (e.payload.get("log") or "") for e in events if e.event_type == "PASSIVE_TRIGGERED")
    engine, me, foe = _sniper([BOUNCING, WRONG_DOOR])
    engine._apply_condition(foe, stealth.HIDDEN, "test:hide", foe.entity_id, expires_on="UNTIL_REMOVED", data={"dc": 5})
    t._ready(engine)
    found = [c for c in engine.legal_candidates() if c.display_name == f"{SNIPE} + Bouncing Shot"]
    if found:  # a Hidden foe can still be targeted by guess here: no Through the Wrong Door help
        events = _use(engine, f"{SNIPE} + Bouncing Shot")
        assert not any("not seeing it gives no Disadvantage" in (e.payload.get("log") or "") for e in events if e.event_type == "PASSIVE_TRIGGERED")


# ================================================================================================================ Sound
SOUND = "tianxia.sphere.sound"
HARMONIC, STONE_BELL, SHATTER = "TAL_SOUND_HARMONIC_WEAKNESS", "TAL_SOUND_STONE_BELL_PROPAGATION", "TAL_SOUND_RESONANT_SHATTER"
DOOR = "object:map.1"


def _door_fight(talents):
    from tests import test_sysv2_objects as O

    bundle = O.build(SOUND, [SHATTER, *talents])
    engine = O.fight(bundle, objects=[{"id": 1, "kind": "door", "x": 6, "y": 6, "hp": 999}], foe=(11, 6))
    return O, engine


def _marked(engine):
    return (engine.state.objects[DOOR].component or {}).get("harmonic_weakness")


def test_harmonic_weakness_marks_a_struck_object_and_the_next_hit_adds_the_sound_die():
    """"When you damage an object ... with Sound damage, mark it with Harmonic Weakness until the start of your next turn. The next
    time it takes damage before the mark ends, add one Sound Die to that damage" (CL 10, Foundation: 1d8)."""
    O, engine = _door_fight([HARMONIC])
    O.use(engine, "Resonant Shatter (at an object)", at=(6, 6))
    assert _marked(engine) == {"owner": O.ME, "count": 1, "sides": 8}
    rolls_before = len(engine.rolls)
    events = O.use(engine, "Resonant Shatter (at an object)", at=(6, 6))
    extra = [roll for roll in engine.rolls[rolls_before:] if roll.reason == "HARMONIC_WEAKNESS"]
    assert len(extra) == 1 and 1 <= extra[0].total <= 8
    assert O.lost(engine, DOOR, events) == O.damage_dice(engine, rolls_before) + extra[0].total
    assert any("Harmonic Weakness" in (e.payload.get("log") or "") for e in events if e.event_type == "PASSIVE_TRIGGERED")
    assert _marked(engine)  # this Sound hit rang it again (one mark, not two)


def test_harmonic_weakness_ends_at_the_owners_next_turn_and_is_inert_without_the_talent():
    O, engine = _door_fight([HARMONIC])
    O.use(engine, "Resonant Shatter (at an object)", at=(6, 6))
    assert _marked(engine)
    engine._system_start_turn()  # the owner's next turn starts
    assert not _marked(engine)
    O, engine = _door_fight([])
    O.use(engine, "Resonant Shatter (at an object)", at=(6, 6))
    assert not _marked(engine)


def test_harmonic_weakness_mark_survives_a_table_commit_and_reload(tmp_path):
    from combat.gate4_persistence import Gate4Persistence
    from combat.tabletop import normalize_map, to_battlefield
    from tests import test_sysv2_objects as O

    document = normalize_map({"display_name": "Yard", "width_squares": 20, "height_squares": 14,
                              "objects": [{"id": 1, "kind": "door", "x": 6, "y": 6, "hp": 999}],
                              "starts": {"team1": [[3, 6]], "team2": [[11, 6]]}})
    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="C11-HARMONIC", typed_bundles=(O.build(SOUND, [SHATTER, HARMONIC]),),
                                       battlefield=to_battlefield(document),
                                       roster_setup={"primary_actor_ids": [O.ME, AN], "team_by_actor": {O.ME: "team:a", AN: "team:b"},
                                                     "starting_positions": {O.ME: {"x": 3, "y": 6}, AN: {"x": 11, "y": 6}}})

    def commit(candidate):
        session.mechanical.execute_intent(ActionIntent(
            intent_id=f"c11-{candidate.state_version}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
            state_version=candidate.state_version, actor_id=candidate.actor_id, target_ids=candidate.target_ids,
            destination=candidate.destination))

    while session.engine.state.current_actor_id != O.ME:
        commit(next(c for c in session.engine.legal_candidates() if c.display_name == "End turn"))
    commit(next(c for c in session.engine.legal_candidates() if c.display_name.startswith("Resonant Shatter (at an object)")
                and c.destination and (c.destination.x, c.destination.y) == (6, 6)))
    reloaded = persistence.load_match(session.match_id)
    assert reloaded.verify()["status"] == "PASS"
    assert (reloaded.engine.state.objects[DOOR].component or {}).get("harmonic_weakness", {}).get("sides") == 8


def test_stone_bell_propagation_reaches_30_feet_farther_with_sound_talents():
    """"When using a Sound talent against a target touching the same continuous surface ... floor ... as you, increase the range by
    30 feet": already typed (its modifier's add_range_ft); the table has no flight, so every creature stands on the one floor.
    "This does not allow damage to ignore Total Cover" is no longer a GM line (nothing at the table does)."""
    assert _authority()[STONE_BELL]["riders"] == [
        "When Resonant Shatter affects a structure, choose one connected point within 30 feet. Harmless sound, a warning bell, or your "
        "Carry Voice message may emerge from that point."]
    plain = {row["display_name"]: row for row in _bundle([SOUND], [SHATTER], cl=10)["action_catalog"]}
    bell = {row["display_name"]: row for row in _bundle([SOUND], [SHATTER, "TAL_SOUND_TREMOR_LISTENING", STONE_BELL], cl=10)["action_catalog"]}
    assert bell["Resonant Shatter"]["range_ft"] == plain["Resonant Shatter"]["range_ft"] + 30


# ================================================================================================================ Space
SPACE = "tianxia.sphere.space"
FOLDED = "tianxia.talent.space.folded_reach"
DAO = {"item_id": "tianxia.mortal.weapon.dao", "name": "Dao", "quantity": 1}
DAO_ATTACK = "Dao (Saber / Broadsword) attack"


def test_folded_reach_typing():
    mechanic = _authority()[FOLDED]
    assert [row["type"] for row in mechanic["effects"]] == ["folded_reach"]
    assert len(mechanic["riders"]) == 1 and "own square" in mechanic["riders"][0]


def test_folded_reach_lets_the_next_melee_attack_reach_a_foe_15_feet_farther():
    """"Your next melee weapon attack ... made before the end of your turn may originate from a point you can see within 10 feet of
    you. At CL 10, this distance becomes 15 feet ... The attack still uses its normal range from the folded point." """
    engine, me, foe = _fight([SPACE], [FOLDED], items=[DAO], cl=10, foe_at=(7, 6))  # 20 feet away: Dao reach 5 + 15
    assert DAO_ATTACK not in _names(engine) and f"{DAO_ATTACK} (Folded Reach)" not in _names(engine)
    _use(engine, "Folded Reach", target=None)
    assert f"{DAO_ATTACK} (Folded Reach)" in _names(engine)
    events = _use(engine, f"{DAO_ATTACK} (Folded Reach)")
    assert _events(events, "ATTACK_ROLLED") and foe.current_hp < foe.maximum_hp
    assert f"{DAO_ATTACK} (Folded Reach)" not in _names(engine)  # the fold is spent


def test_folded_reach_twin_is_only_for_foes_beyond_normal_reach_and_inert_without_the_talent():
    engine, me, foe = _fight([SPACE], [FOLDED], items=[DAO], cl=10, foe_at=(4, 6))
    _use(engine, "Folded Reach", target=None)
    assert f"{DAO_ATTACK} (Folded Reach)" not in _names(engine)  # the foe is in ordinary reach
    engine, me, foe = _fight([SPACE], [], items=[DAO], cl=10, foe_at=(7, 6))
    assert not [a for a in engine.action_catalog.values() if a.display_name.endswith("(Folded Reach)")]


def test_folded_reach_survives_a_table_commit_and_reload(tmp_path):
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="C11-FOLD", typed_bundles=(_bundle([SPACE], [FOLDED], items=[DAO], cl=10),),
                                       roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                     "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 7, "y": 6}}})

    def commit(candidate):
        session.mechanical.execute_intent(ActionIntent(
            intent_id=f"c11-{candidate.state_version}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
            state_version=candidate.state_version, actor_id=candidate.actor_id, target_ids=candidate.target_ids,
            destination=candidate.destination))

    while session.engine.state.current_actor_id != ME:
        commit(next(c for c in session.engine.legal_candidates() if c.display_name == "End turn"))
    commit(next(c for c in session.engine.legal_candidates() if c.display_name == "Folded Reach"))
    reloaded = persistence.load_match(session.match_id)
    assert reloaded.verify()["status"] == "PASS"
    assert any(c.display_name == f"{DAO_ATTACK} (Folded Reach)" for c in reloaded.engine.legal_candidates())


# ================================================================================================================ Spear
SPEAR = "tianxia.sphere.spear"
FPP = "TAL_SPEAR_FORMATION_PIERCING_POINT"
QIANG = {"item_id": "tianxia.mortal.weapon.qiang", "name": "Qiang", "quantity": 1}


def _shielded(engine, foe, value=2):
    """An AC bonus the foe's own side put on it (an ordinary ongoing defensive effect)."""
    current = engine.state.current_actor_id
    engine.state.current_actor_id = foe.entity_id
    engine._add_modifier(foe, "test:ward", "armor_class", "ADD", value, "self", expires_on="UNTIL_REMOVED")
    engine.state.current_actor_id = current
    return next(key for key, m in foe.modifiers.items() if m.source_definition_id == "test:ward")


def test_formation_piercing_point_typing():
    mechanic = _authority()[FPP]
    assert [option["label"] for option in mechanic["options"]] == ["Spear Line", "Spear Light", "Object"]
    assert mechanic["cost"] == [[{"resource": "cp", "amount": 6, "amount_formula": None}]]
    rows = {row["display_name"]: row for row in _bundle([SPEAR], [FPP], items=[QIANG], cl=12)["action_catalog"]}
    assert rows["Formation-Piercing Point: Spear Light"]["range_ft"] == 90 and rows["Formation-Piercing Point: Object"]["range_ft"] == 90


def test_formation_piercing_point_hits_for_4d8_more_and_suppresses_a_defense_until_your_next_turn():
    """"Make one approved Spear weapon attack ... Hit: Deal normal attack damage plus: 4d8 Piercing or Force damage The target makes a
    Constitution saving throw. Failed Save: Suppress one ordinary ongoing defensive effect affecting it until the start of your next
    turn." """
    engine, me, foe = _fight([SPEAR], [FPP], items=[QIANG], cl=12, dc=50)
    ward = _shielded(engine, foe)
    rolls_before = len(engine.rolls)
    events = _use(engine, "Formation-Piercing Point: Spear Line")
    damage = [r for r in engine.rolls[rolls_before:] if str(r.reason).startswith("DAMAGE")]
    assert any(len(r.dice) == 4 and r.expression.startswith("4d8") for r in damage), [r.expression for r in damage]
    assert foe.modifiers[ward].target_field == "suppressed:armor_class"
    assert any("until the start of" in (e.payload.get("log") or "") for e in events if e.event_type == "PASSIVE_TRIGGERED")
    from combat.ext import end_effect
    end_effect.suppressed_effects_return(engine, me)  # the end of this turn: still suppressed (until the START of the next)
    assert foe.modifiers[ward].target_field == "suppressed:armor_class"
    me.turns_started += 1
    end_effect.suppressed_effects_return_at_start(engine, me)
    assert foe.modifiers[ward].target_field == "armor_class"


def test_formation_piercing_point_reaches_90_feet_through_spear_light_and_pierces_an_object():
    """"Range: Spear Line or 90 feet through Spear Light"; "Object or Barrier Deal: 6d8 Piercing or Force damage This damage ignores
    ordinary hardness" (Damage Threshold)."""
    engine, me, foe = _fight([SPEAR], [FPP], items=[QIANG], cl=12, dc=50, foe_at=(15, 6))  # 60 feet
    assert "Formation-Piercing Point: Spear Line" not in _names(engine)
    events = _use(engine, "Formation-Piercing Point: Spear Light")
    assert _events(events, "ATTACK_ROLLED") and foe.current_hp < foe.maximum_hp
    from tests import test_sysv2_objects as O

    bundle = compile_character(_sheet([SPEAR], [FPP], items=[QIANG], cl=12), actor_id=O.ME)
    engine = O.fight(bundle, objects=[{"id": 1, "kind": "door", "x": 8, "y": 6, "hp": 999, "threshold": 60}], foe=(14, 3))
    rolls_before = len(engine.rolls)
    events = O.use(engine, "Formation-Piercing Point: Object", "object:map.1")
    rolled = O.damage_dice(engine, rolls_before)
    assert 6 <= rolled <= 48 and O.lost(engine, "object:map.1", events) == rolled  # a threshold of 60 does not stop it


def _foe_sheet():
    sheet = _sheet(["tianxia.sphere.force"], ["TAL_FORCE_FORCE_MANTLE"], cl=12)
    return compile_character(sheet, actor_id=t.FOE)


def test_formation_piercing_point_suppression_survives_a_table_commit_and_reload(tmp_path):
    """The foe's own Force Mantle (+2 AC) is suppressed by a committed Formation-Piercing Point and stays suppressed, with its
    "until the start of your next turn" clock, after the fight is saved and loaded."""
    from combat.ext import end_effect
    from combat.gate4_persistence import Gate4Persistence

    mine = _sheet([SPEAR], [FPP], items=[QIANG], cl=12, dc=50)
    mine["ability_scores_and_statistics"]["technique_attack_bonus"] = 60
    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="C11-FPP", typed_bundles=(compile_character(mine, actor_id=ME), _foe_sheet()),
                                       roster_setup={"primary_actor_ids": [ME, t.FOE], "team_by_actor": {ME: "team:a", t.FOE: "team:b"},
                                                     "starting_positions": {ME: {"x": 3, "y": 6}, t.FOE: {"x": 4, "y": 6}}})

    def commit(name):
        candidate = next(c for c in session.engine.legal_candidates() if c.display_name == name)
        session.mechanical.execute_intent(ActionIntent(
            intent_id=f"c11-{candidate.state_version}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
            state_version=candidate.state_version, actor_id=candidate.actor_id, target_ids=candidate.target_ids,
            destination=candidate.destination))

    for _ in range(4):
        if session.engine.state.current_actor_id == t.FOE and not any(
                m.target_field == "armor_class" for m in session.engine.state.actors[t.FOE].modifiers.values()):
            commit("Force Mantle")
        if session.engine.state.current_actor_id == ME and any(
                m.target_field == "armor_class" for m in session.engine.state.actors[t.FOE].modifiers.values()):
            break
        commit("End turn")
    commit("Formation-Piercing Point: Spear Line")
    foe = session.engine.state.actors[t.FOE]
    assert any(m.target_field == "suppressed:armor_class" for m in foe.modifiers.values())
    reloaded = persistence.load_match(session.match_id)
    assert reloaded.verify()["status"] == "PASS"
    foe = reloaded.engine.state.actors[t.FOE]
    assert any(m.target_field == "suppressed:armor_class" for m in foe.modifiers.values())
    rows = foe.turn_flags.get(end_effect.SUPPRESSED_FLAG) or []
    assert rows and rows[0].get("boundary", rows[0].get("at")) == "start" and rows[0]["by"] == ME


PINNED = "TAL_SPEAR_THE_POINT_THAT_PINNED_HEAVEN_TO_EARTH"


def _conditions_of(actor):
    return {c.condition_id.removeprefix("condition:typed.") for c in actor.conditions.values()}


def test_the_point_that_pinned_heaven_to_earth_hits_with_advantage_for_16d10_and_three_picks_on_a_failed_save():
    """"Make one approved Spear weapon attack ... with: - Advantage ... ordinary Resistance to Piercing and Force ignored. Hit: Deal:
    16d10 Piercing or Force damage The target makes a Constitution saving throw. Failed Save: Choose three: - become Stunned ...;
    - Speed becomes 0 ...; - cannot take Reactions ... until the end of your next turn" (the default three)."""
    engine, me, foe = _duel(_bundle([SPEAR], [PINNED], items=[QIANG], cl=20, dc=50), _foe_sheet())  # a Factory foe: typed defenses
    for kind in ("PIERCING", "FORCE"):
        engine._add_modifier(foe, "test:resist", "damage_resistance", "ADD", kind, "self", expires_on="UNTIL_REMOVED")
    rolls_before = len(engine.rolls)
    events = _use(engine, "The Point That Pinned Heaven to Earth: Spear Line", target=t.FOE)
    roll = next(e for e in events if e.event_type == "ATTACK_ROLLED")
    assert roll.payload["mode"] == "ADVANTAGE"
    big = next(r for r in engine.rolls[rolls_before:] if str(r.reason).startswith("DAMAGE") and r.expression in ("16d10+0", "32d10+0"))
    packet = next(e.payload for e in events if e.event_type == "DAMAGE_COMMITTED" and t.FOE in (e.target_ids or ()))
    assert packet["rolled_or_pending_damage"] == big.total and packet["reduced_to"] > big.total // 2 + 1  # Resistance ignored: not halved
    assert {"stunned", "held_fast", "reaction_denied"} <= _conditions_of(foe)
    t._ready(engine)
    assert "Choose The Point That Pinned Heaven to Earth: Stunned" in _names(engine)  # the picks are the player's to change
    assert "The Point That Pinned Heaven to Earth: Spear Light" not in _names(engine)  # the one use is spent


def test_the_point_that_pinned_heaven_to_earth_successful_save_gets_one_pick():
    engine, me, foe = _fight([SPEAR], [PINNED], items=[QIANG], cl=20, dc=-40)
    _use(engine, "The Point That Pinned Heaven to Earth: Spear Line")
    got = _conditions_of(foe) & {"stunned", "held_fast", "reaction_denied"}
    assert got == {"stunned"}, _conditions_of(foe)


# ================================================================================================================ Thread
THREAD = "tianxia.sphere.thread"
SCRIPTURE, HUNDRED = "tianxia.talent.thread.qi_thread_scripture", "tianxia.talent.thread.hundred_line_weaving"
PULL = "Draw the Line: Pull"
SNARE = "Draw the Line: Snare"  # moves nobody, so the foe stays beyond the mundane 20 feet


def _thread_fight(talents, foe_at=(8, 6)):  # 25 feet: beyond mundane thread (20), inside Qi Thread (30)
    engine, me, foe = _fight([THREAD], talents, cl=12, foe_at=foe_at)
    return engine, me, foe


def _lines_on(actor):
    from combat.typed_executor import mark_condition_id

    return [c for c in actor.conditions.values() if c.condition_id == mark_condition_id("Thread Line", ME)]


def test_thread_rider_lines_the_table_now_runs_are_gone():
    mechanics = _authority()
    assert mechanics["THREAD_BASE_SPOOL_AND_STRAND"]["riders"] == []
    assert [r[:10] for r in mechanics[SCRIPTURE]["riders"]] == ["Martial Us"]
    assert len(mechanics[HUNDRED]["riders"]) == 1 and "object" in mechanics[HUNDRED]["riders"][0]


def test_qi_thread_reaches_30_feet_for_1_cp():
    """Spool and Strand: "If you spend 1 CP, you can create Qi Thread"; Draw the Line: "Range: Mundane 20 feet, Qi Thread 30 feet"."""
    engine, me, foe = _thread_fight([])
    assert SNARE not in _names(engine)
    before = me.resources["resource:core.stamina"]
    _use(engine, f"{SNARE} (Qi Thread)")
    assert me.resources["resource:core.stamina"] == before - 1 and _lines_on(foe)
    t._ready(engine)
    assert f"{SNARE} (Qi Thread)" in _names(engine)  # without the Scripture every Qi Thread line pays again
    engine, me, foe = _thread_fight([], foe_at=(5, 6))
    assert f"{SNARE} (Qi Thread)" not in _names(engine)  # within 20 feet the mundane line does


def test_qi_thread_scripture_pays_once_for_the_fight():
    """"When you spend 1 CP to create Qi Thread, it lasts for 10 minutes ... While active, your Thread Lines may be Qi Threads by default
    instead of requiring separate CP for each line." """
    engine, me, foe = _thread_fight([SCRIPTURE])
    before = me.resources["resource:core.stamina"]
    _use(engine, f"{SNARE} (Qi Thread)")
    assert me.resources["resource:core.stamina"] == before - 1
    assert any(c.condition_id == "condition:typed.qi_thread" for c in me.conditions.values())
    t._ready(engine)
    free = [c for c in engine.legal_candidates() if c.display_name == f"{SNARE} (Qi Thread)" and c.actor_id == ME]
    assert len(free) == 1 and not engine.action_catalog[free[0].source_definition_id].costs
    _use(engine, f"{SNARE} (Qi Thread)")
    assert me.resources["resource:core.stamina"] == before - 1


def test_thread_line_limit_grows_with_the_scripture_and_hundred_line_weaving():
    from combat.typed_executor import Context, mark_capacity

    for talents, cap in (([], 4), ([SCRIPTURE], 5), ([HUNDRED], 6), ([SCRIPTURE, HUNDRED], 7)):
        engine, me, foe = _thread_fight(talents)
        action = next(a for a in engine.action_catalog.values() if a.display_name == PULL)
        ctx = Context(engine, me, action, None, action.parameters["typed"], [foe], foe)
        assert mark_capacity(ctx, "Thread Line") == cap, talents


def test_hundred_line_weaving_draws_two_lines_for_one_more_cp():
    """"When you use Draw the Line, you may spend 1 additional CP to target one additional creature ... Make a separate Thread Attack
    for each target." """
    engine, me, foe = _thread_fight([HUNDRED], foe_at=(5, 6))
    other = foe.model_copy(deep=True)
    other.entity_id, other.display_name = "c11:second", "Second Foe"
    other.position = other.position.model_copy(update={"y": 8})
    engine.state.actors[other.entity_id] = other
    engine.actor_footprints[other.entity_id] = engine.actor_footprints[AN]
    before = me.resources["resource:core.stamina"]
    events = _use(engine, f"{PULL} (two targets)")
    assert len(_events(events, "ATTACK_ROLLED")) == 2
    assert _lines_on(foe) and _lines_on(other) and me.resources["resource:core.stamina"] == before - 1


def test_tension_mastery_keeps_an_ending_line_a_turn_longer():
    """"Once per round when a Thread Line you maintain would end at the end of your turn, you may maintain it until the end of your
    next turn without spending an action." """
    from combat.ext import thread_weaving

    engine, me, foe = _thread_fight([HUNDRED], foe_at=(5, 6))
    _use(engine, PULL)
    (line,) = _lines_on(foe)
    placed = line.data["marker_turn"]
    me.turns_started += 1  # the next turn: this line ends at its end
    thread_weaving.tension_mastery(engine, me)
    (line,) = _lines_on(foe)
    assert line.data["marker_turn"] == placed + 1
    engine, me, foe = _thread_fight([SCRIPTURE], foe_at=(5, 6))  # without Hundred-Line Weaving
    _use(engine, PULL)
    me.turns_started += 1
    thread_weaving.tension_mastery(engine, me)
    assert _lines_on(foe)[0].data["marker_turn"] == placed


def test_tension_mastery_and_qi_thread_survive_a_table_commit_and_reload(tmp_path):
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="C11-THREAD", typed_bundles=(_bundle([THREAD], [SCRIPTURE, HUNDRED], cl=12),),
                                       roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                     "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 8, "y": 6}}})

    def commit(name):
        candidate = next(c for c in session.engine.legal_candidates() if c.display_name == name)
        session.mechanical.execute_intent(ActionIntent(
            intent_id=f"c11-{candidate.state_version}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
            state_version=candidate.state_version, actor_id=candidate.actor_id, target_ids=candidate.target_ids,
            destination=candidate.destination))

    while session.engine.state.current_actor_id != ME:
        commit("End turn")
    commit(f"{SNARE} (Qi Thread)")  # 25 feet: pays 1 CP and starts the Scripture's Qi Thread
    placed = _lines_on(session.engine.state.actors[AN])[0].data["marker_turn"]
    commit("End turn")
    while session.engine.state.current_actor_id != ME:
        commit("End turn")
    lines = _lines_on(session.engine.state.actors[AN])
    assert lines and lines[0].data["marker_turn"] == placed + 1  # Tension Mastery kept it (the table's automatic answer)
    reloaded = persistence.load_match(session.match_id)
    assert reloaded.verify()["status"] == "PASS"
    me, foe = reloaded.engine.state.actors[ME], reloaded.engine.state.actors[AN]
    assert _lines_on(foe)[0].data["marker_turn"] == placed + 1
    assert any(c.condition_id == "condition:typed.qi_thread" for c in me.conditions.values())


LOOM = "tianxia.talent.thread.loom_of_the_narrow_gate"


def test_loom_of_the_narrow_gate_is_difficult_for_hostiles_and_counts_as_two_lines():
    """"Range: 90 feet. Area: Up to six connected 5-foot squares, arranged as lines ... Duration: 1 minute. Cost: 4 CP. Hostile creatures
    treat the affected squares as Difficult Terrain. Persistent Lines: The loom counts as two active Thread Lines for your limit." """
    from combat import zones
    from combat.typed_executor import Context, mark_capacity

    assert len(_authority()[LOOM]["riders"]) == 2  # arcs; the Reaction Thread Attack (no movement-in-area trigger)
    engine, me, foe = _thread_fight([LOOM], foe_at=(12, 6))
    before = me.resources["resource:core.stamina"]
    t._ready(engine)
    candidate = next(c for c in engine.legal_candidates() if c.display_name.startswith("Loom of the Narrow Gate") and c.destination
                     and (c.destination.x, c.destination.y) == (8, 6))
    engine.execute_intent(ActionIntent(intent_id="c11-loom", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids,
                                       destination=candidate.destination))
    assert me.resources["resource:core.stamina"] == before - 4
    zone = next(z for z in engine.state.zones.values() if LOOM in z.source_definition_id)
    cells = {(c.x, c.y) for c in zone.affected_cells}
    assert len(cells) == 6
    assert cells <= zones.difficult_cells(engine, foe) and not cells & zones.difficult_cells(engine, me)
    action = next(a for a in engine.action_catalog.values() if a.display_name == "Draw the Line: Snare")
    assert mark_capacity(Context(engine, me, action, None, action.parameters["typed"], [foe], foe), "Thread Line") == 4 - 2


# ================================================================================================================ Warleader
WARLEADER = "tianxia.sphere.warleader"
HERDSMAN, FOCUSING = "tianxia.talent.warleader.deadly_herdsman", "tianxia.talent.warleader.focusing_tactics"
ALLY1, ALLY2 = "actor:factory.ally1", "actor:factory.ally2"


def _squad(leader_talents, *, foe_at=(6, 6), ally1_at=(5, 6), ally2_at=(7, 6)):
    """A Warleader (me) and two Dao-armed allies against the stock foe; the allies stand beside the foe."""
    from combat.gate4_engine import Gate4ControllerEngine

    leader = _bundle([WARLEADER], leader_talents, items=[DAO], cl=12)
    allies = [compile_character(_sheet([SPACE], [], items=[DAO], cl=12), actor_id=who) for who in (ALLY1, ALLY2)]
    engine = Gate4ControllerEngine(ROOT, match_seed="C11-SQUAD", typed_bundles=(leader, *allies),
                                   roster_setup={"primary_actor_ids": [ME, ALLY1, ALLY2, AN],
                                                 "team_by_actor": {ME: "team:a", ALLY1: "team:a", ALLY2: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, ALLY1: {"x": ally1_at[0], "y": ally1_at[1]},
                                                                        ALLY2: {"x": ally2_at[0], "y": ally2_at[1]}, AN: {"x": foe_at[0], "y": foe_at[1]}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    foe = engine.state.actors[AN]
    foe.armor_class = -50
    foe.maximum_hp = foe.current_hp = 400
    return engine


def _act(engine, who, name, target=None):
    actor = engine.state.actors[who]
    engine.state.current_actor_id = who
    actor.action_available = actor.bonus_action_available = actor.reaction_available = True
    found = [c for c in engine.legal_candidates() if c.actor_id == who and c.display_name == name
             and (target is None or target in (c.target_ids or ()))]
    assert found, (who, name, sorted({c.display_name for c in engine.legal_candidates() if c.actor_id == who and not c.display_name.startswith("Move")}))
    candidate = found[0]
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"i-{who}-{engine.state.event_sequence}", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=who,
                                       target_ids=candidate.target_ids, destination=candidate.destination))
    return engine.events[before:]


def test_deadly_herdsman_is_a_standard_now():
    mechanic = _authority()[HERDSMAN]
    assert mechanic["activation"]["economy"] == "bonus_action" and mechanic["riders"] == []
    assert [(row["type"], row["standard"]) for row in mechanic["effects"]] == [("warleader_standard", "deadly_herdsman")]


def test_deadly_herdsman_shoves_after_a_hit_and_opens_an_opportunity_attack():
    """"once per turn when a Commanded ally damages a hostile creature with an attack, the ally may Shove the target as a Bonus Action.
    If the forced movement moves the target out of another Commanded ally's reach, that other ally may make one Opportunity Attack." """
    engine = _squad([HERDSMAN])
    _act(engine, ME, "Deadly Herdsman")
    foe = engine.state.actors[AN]
    foe.saving_throws = {**foe.saving_throws, "STR": -50, "DEX": -50}  # the shove lands
    # ally 1 (west of the foe) hits it and shoves it east, out of the reach of ally 2 (north-west of the foe)
    engine.state.actors[ALLY2].position = engine.state.actors[ALLY2].position.model_copy(update={"x": 5, "y": 5})
    start = foe.position
    events = _act(engine, ALLY1, DAO_ATTACK, target=AN)
    assert foe.position != start and not engine.state.actors[ALLY1].bonus_action_available
    assert any("Deadly Herdsman" in (e.payload.get("log") or "") for e in events if e.event_type == "PASSIVE_TRIGGERED")
    oa = [e for e in events if e.event_type == "ATTACK_ROLLED" and e.actor_id == ALLY2]
    assert oa and not engine.state.actors[ALLY2].reaction_available
    ally1 = engine.state.actors[ALLY1]
    ally1.position = foe.position.model_copy(update={"x": foe.position.x - 1})  # step up beside it again, same turn
    engine.state.current_actor_id = ALLY1
    ally1.action_available = True
    candidate = next(c for c in engine.legal_candidates() if c.actor_id == ALLY1 and c.display_name == DAO_ATTACK)
    before = foe.position
    ally1.bonus_action_available = True
    engine.execute_intent(ActionIntent(intent_id="c11-herd-2", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ALLY1, target_ids=candidate.target_ids))
    assert foe.position == before and ally1.bonus_action_available  # once per turn: no second shove


def test_deadly_herdsman_is_inert_under_another_standard():
    engine = _squad([HERDSMAN])
    _act(engine, ME, "Set the Standard")  # Press the Opening
    foe = engine.state.actors[AN]
    foe.saving_throws = {**foe.saving_throws, "STR": -50, "DEX": -50}
    start = foe.position
    _act(engine, ALLY1, DAO_ATTACK, target=AN)
    assert foe.position == start and engine.state.actors[ALLY1].bonus_action_available


def test_focusing_tactics_lets_a_commanded_ally_restore_the_leaders_martial_focus_once():
    """"A Commanded ally affected by your active Standard ... may use its Action to restore your Martial Focus if absent. A creature can
    restore your Martial Focus with this talent once per short rest." """
    restore = "Restore Martial Focus (Focusing Tactics)"
    engine = _squad([FOCUSING])
    me = engine.state.actors[ME]
    _act(engine, ME, "Set the Standard")
    me.resources["resource:core.martial_focus"] = 0
    _act(engine, ALLY1, restore)
    assert me.resources["resource:core.martial_focus"] == 1
    me.resources["resource:core.martial_focus"] = 0
    engine.state.current_actor_id = ALLY1
    assert restore not in {c.display_name for c in engine.legal_candidates() if c.actor_id == ALLY1}  # once
    engine.state.current_actor_id = ALLY2
    assert restore in {c.display_name for c in engine.legal_candidates() if c.actor_id == ALLY2}  # another creature may
    engine = _squad([])  # a leader without the talent
    _act(engine, ME, "Set the Standard")
    engine.state.actors[ME].resources["resource:core.martial_focus"] = 0
    engine.state.current_actor_id = ALLY1
    assert restore not in {c.display_name for c in engine.legal_candidates() if c.actor_id == ALLY1}


# ================================================================================================================ Water
WATER, MIST_VEIL = "tianxia.sphere.water", "TAL_WATER_MIST_VEIL"
DENSE = "Shape Current: Mist Basin + Mist Veil: Heavily Obscured"


def _mist(engine, name, at=(8, 6)):
    t._ready(engine)
    candidate = next(c for c in engine.legal_candidates() if c.actor_id == ME and c.display_name.startswith(name) and c.destination
                     and (c.destination.x, c.destination.y) == at)
    engine.execute_intent(ActionIntent(intent_id=f"c11-mist-{engine.state.event_sequence}", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=ME,
                                       target_ids=candidate.target_ids, destination=candidate.destination))
    return max((z for z in engine.state.zones.values() if z.owner_id == ME and z.active), key=lambda z: z.zone_id)


def test_mist_veil_dense_mist_is_heavy_until_your_next_turn_then_light():
    """"By spending 1 additional CP when you create it, you may make the area Heavily Obscured until the start of your next turn; after
    that, it becomes Lightly Obscured for the remaining duration." """
    from combat.ext import water_mist

    assert _authority()[MIST_VEIL]["riders"] == []
    engine, me, foe = _fight([WATER], [MIST_VEIL], cl=12, foe_at=(14, 6))
    before = me.resources["resource:core.stamina"]
    zone = _mist(engine, DENSE)
    assert me.resources["resource:core.stamina"] == before - 2  # Mist Basin 1 + 1 more
    assert zone.trigger_profile["obscured"] == "heavy"
    water_mist.thin_out(engine, me)  # the same turn: still heavy
    assert zone.trigger_profile["obscured"] == "heavy"
    me.turns_started += 1
    water_mist.thin_out(engine, me)
    assert zone.trigger_profile["obscured"] == "light" and "dense_until_turn" not in zone.trigger_profile
    engine, me, foe = _fight([WATER], [MIST_VEIL], cl=12, foe_at=(14, 6))
    zone = _mist(engine, "Shape Current: Mist Basin + Mist Veil: Lightly Obscured")
    assert zone.trigger_profile["obscured"] == "light"


def test_mist_veil_dense_mist_survives_a_table_commit_and_reload(tmp_path):
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="C11-MIST", typed_bundles=(_bundle([WATER], [MIST_VEIL], cl=12),),
                                       roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                     "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 14, "y": 6}}})

    def commit(name, at=None):
        candidate = next(c for c in session.engine.legal_candidates() if c.display_name.startswith(name)
                         and (at is None or (c.destination and (c.destination.x, c.destination.y) == at)))
        session.mechanical.execute_intent(ActionIntent(
            intent_id=f"c11-{candidate.state_version}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
            state_version=candidate.state_version, actor_id=candidate.actor_id, target_ids=candidate.target_ids,
            destination=candidate.destination))

    while session.engine.state.current_actor_id != ME:
        commit("End turn")
    commit(DENSE, at=(8, 6))
    reloaded = persistence.load_match(session.match_id)
    assert reloaded.verify()["status"] == "PASS"
    zone = next(z for z in reloaded.engine.state.zones.values() if z.owner_id == ME)
    assert zone.trigger_profile["obscured"] == "heavy" and zone.trigger_profile["dense_until_turn"] >= 1


# ================================================================================================================ Wax
WAX = "tianxia.sphere.wax"
MOLD, RAMPART, CANDLE = "TAL_WAX_MOLD_WAX", "TAL_WAX_WAX_RAMPART", "TAL_WAX_FUNERAL_CANDLE_SHELTER"
HALF_RAMPART = "Mold Wax: Set Shape + Wax Rampart: Half Cover"


def test_wax_rampart_raises_a_set_wax_wall_that_gives_cover():
    """"creatures behind it may use it as half cover"; "At CL 5, a rampart can instead provide three-quarters cover ... each 5-foot
    section used this way counts as two sections of your Set Shape"; Set Wax sections: AC 12 + PB, 5 + 2 x CL (+ CL) hit points."""
    from combat.ext import docket_walls

    assert _authority()[RAMPART]["riders"] == []
    engine, me, foe = _fight([WAX], [MOLD, RAMPART], cl=12, foe_at=(12, 6))
    t._ready(engine)
    candidate = next(c for c in engine.legal_candidates() if c.actor_id == ME and c.display_name.startswith(HALF_RAMPART) and c.destination
                     and (c.destination.x, c.destination.y) == (8, 6))
    engine.execute_intent(ActionIntent(intent_id="c11-rampart", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids,
                                       destination=candidate.destination))
    wall = next(z for z in engine.state.zones.values() if z.owner_id == ME and (z.trigger_profile.get("wall") or {}).get("cover"))
    assert len(wall.affected_cells) == 6  # CL 10+: six cubes
    assert (8, 6) in {(c.x, c.y) for c in wall.affected_cells}
    assert engine._cover_bonus_actor_to_actor(me, foe) == 2
    stats = docket_walls.stats(wall)
    assert stats["ac"] == 12 + 4 and stats["hp"] == 5 + 3 * 12 and "FIRE" in stats["vulnerable"]
    assert any(n.startswith("Mold Wax: Set Shape + Wax Rampart: Three-Quarters Cover") for n in _names(engine))
    engine, me, foe = _fight([WAX], [MOLD, RAMPART], cl=4, foe_at=(12, 6))
    assert any(n.startswith(HALF_RAMPART) for n in _names(engine))
    assert not [n for n in _names(engine) if "Three-Quarters" in n]  # "At CL 5"


def _candle_squad(talents, monkeypatch):
    from combat.ext import life_state
    from combat.gate4_engine import Gate4ControllerEngine

    monkeypatch.setattr(life_state, "DEATH_SAVES_FOR_ALL", True)
    mine = _bundle([WAX], talents, cl=15)
    ally = compile_character(_sheet([SPACE], [], items=[DAO], cl=12), actor_id=ALLY1)
    engine = Gate4ControllerEngine(ROOT, match_seed="C11-CANDLE", typed_bundles=(mine, ally),
                                   roster_setup={"primary_actor_ids": [ME, ALLY1, AN], "team_by_actor": {ME: "team:a", ALLY1: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, ALLY1: {"x": 5, "y": 6}, AN: {"x": 12, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    friend = engine.state.actors[ALLY1]
    friend.current_hp, friend.maximum_hp = 10, 10
    return engine, engine.state.actors[ME], friend


def test_funeral_candle_shelter_keeps_a_creature_dying_from_damage_at_zero_and_stable(monkeypatch):
    """"If the creature would die from damage, it instead falls to 0 hit points and becomes stable ... A creature can benefit from Funeral
    Candle Shelter only once per long rest." """
    engine, me, friend = _candle_squad([CANDLE], monkeypatch)
    pool = next(p for p in ("resource:core.stamina", "resource:core.qi") if p in me.resources)
    before = me.resources[pool]
    engine._commit_damage(friend, 25, "SLASHING", "test:blow", AN, None, reaction_depth=0)  # 10 to 0, 15 over: massive damage
    assert friend.active and friend.life_state == "STABLE" and friend.current_hp == 0
    assert me.resources[pool] == before - 5 and not me.reaction_available
    me.reaction_available = True
    engine._commit_damage(friend, 25, "SLASHING", "test:blow", AN, None, reaction_depth=0)
    assert not friend.active  # once per long rest: the second death is not sheltered


def test_funeral_candle_shelter_is_inert_without_the_talent(monkeypatch):
    engine, me, friend = _candle_squad([], monkeypatch)
    engine._commit_damage(friend, 25, "SLASHING", "test:blow", AN, None, reaction_depth=0)
    assert not friend.active


def test_wax_rampart_survives_a_table_commit_and_reload(tmp_path):
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="C11-RAMPART", typed_bundles=(_bundle([WAX], [MOLD, RAMPART], cl=12),),
                                       roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                     "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 12, "y": 6}}})

    def commit(name, at=None):
        candidate = next(c for c in session.engine.legal_candidates() if c.display_name.startswith(name)
                         and (at is None or (c.destination and (c.destination.x, c.destination.y) == at)))
        session.mechanical.execute_intent(ActionIntent(
            intent_id=f"c11-{candidate.state_version}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
            state_version=candidate.state_version, actor_id=candidate.actor_id, target_ids=candidate.target_ids,
            destination=candidate.destination))

    while session.engine.state.current_actor_id != ME:
        commit("End turn")
    commit(HALF_RAMPART, at=(8, 6))
    reloaded = persistence.load_match(session.match_id)
    assert reloaded.verify()["status"] == "PASS"
    me, foe = reloaded.engine.state.actors[ME], reloaded.engine.state.actors[AN]
    assert reloaded.engine._cover_bonus_actor_to_actor(me, foe) == 2


# ================================================================================================================ Yang
YANG = "tianxia.sphere.yang"
RESOLVE = "TAL_YANG_KINDLED_RESPONSES#complete_resolve"


def test_yang_rule_lines_the_table_already_runs_are_no_longer_gm_riders():
    """Mark Limit ("a number of Rising Marks equal to your Proficiency Bonus", "only one Rising Mark from you at a time", "lasts until the
    end of your next turn"), Spending a Rising Mark ("Once per round ... without using an Action") and Yang Saves run already."""
    mechanics = _authority()
    for key in ("TAL_YANG_MARK_LIMIT", "TAL_YANG_SPENDING_A_RISING_MARK", "TAL_YANG_YANG_SAVES", RESOLVE):
        assert mechanics[key]["riders"] == [] and mechanics[key]["coverage"] == "FULL", key
    assert "120 feet" not in " ".join(mechanics["TAL_YANG_OVERKINDLED_RESPONSES#overcommit_step"]["riders"])
    assert "60 feet" not in " ".join(mechanics["TAL_YANG_OVERKINDLED_RESPONSES#overexpose"]["riders"])
    from combat.typed_executor import Context, block_mark, mark_capacity, mark_condition_id

    engine, me, foe = _fight([YANG], [RESOLVE, "TAL_YANG_APPLYING_A_RISING_MARK#kindle_the_rising"], cl=12)
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.parameters.get("typed"))
    ctx = Context(engine, me, action, None, action.parameters["typed"], [foe], foe)
    assert mark_capacity(ctx, "Kindled Mark") == 4
    block_mark(ctx, {"type": "mark", "mark": "Kindled Mark", "applies_to": "target", "duration": {"kind": "until_end_of_your_next_turn"}})
    block_mark(ctx, {"type": "mark", "mark": "Overkindled Mark", "applies_to": "target", "duration": {"kind": "until_end_of_your_next_turn"}})
    rising = [c for c in foe.conditions.values() if c.condition_id in (mark_condition_id("Kindled Mark", ME), mark_condition_id("Overkindled Mark", ME))]
    assert len(rising) == 1 and rising[0].expires_on == "END_OF_MARKER_NEXT_TURN"


def test_complete_resolve_answers_a_save_against_any_speed_reaction_or_action_taking_condition():
    """"a saving throw against an effect that would reduce its Speed, prevent it from taking Reactions, ... or suppress its ability to
    act": Speed 0 (held fast), petrified, no Reactions (flustered) are recognised too."""
    from combat import typed_reactions
    from combat.typed_executor import mark_condition_id

    engine, me, foe = _fight([YANG], [RESOLVE], cl=12)
    row = next(r for r in engine.typed_reaction_rows[ME] if r["feature_id"] == RESOLVE)
    assert {"held_fast", "petrified", "flustered", "grappled"} <= set(row["conditions"])
    engine._apply_condition(me, mark_condition_id("Kindled Mark", ME), "test:kindle", ME, expires_on="UNTIL_REMOVED")
    shaped = typed_reactions.on_d20_pending(engine, me, "save", ability="STR", conditions={"held_fast"})
    assert shaped["bonus"] >= 1


# ------------------------------------------------------------------------------------------------ Qiweaving: Rapid Unweave
RAPID = "Unweave Pattern (Rapid Unweave)"


def _mantled_foe(engine, foe):
    """The foe's own Force Mantle (+2 AC, 3 CP: Pattern Rank 3)."""
    mantle = next(a for a in engine.action_catalog.values() if a.owner_id == foe.entity_id and a.display_name == "Force Mantle")
    current = engine.state.current_actor_id
    engine.state.current_actor_id = foe.entity_id
    engine._add_modifier(foe, mantle.source_definition_id, "armor_class", "ADD", 2, "self", expires_on="UNTIL_REMOVED")
    engine.state.current_actor_id = current
    return next(key for key, m in foe.modifiers.items() if m.source_definition_id == mantle.source_definition_id)


def test_rapid_unweave_ends_an_active_qi_pattern_and_certain_unweave_raises_the_threshold():
    """"Rapid Unweave - 1 CP: Reduce the Action Type to Action." "If the pattern's Pattern Rank is equal to or lower than half your
    Proficiency Bonus ... it ends automatically." "Certain Unweave - 1 CP: The automatic-ending threshold becomes your Proficiency
    Bonus." Pattern Rank: "CP spent to activate or maintain it" (Force Mantle, 3 CP: rank 3; PB 4)."""
    from combat.ext import qiweaving_unweave

    engine, me, foe = _duel(_bundle([QI], [], cl=12), _foe_sheet())
    assert RAPID not in _names(engine)  # nothing to unweave on it
    mantle = _mantled_foe(engine, foe)
    assert qiweaving_unweave.pattern_rank(engine, foe.modifiers[mantle]) == 3
    before = me.resources["resource:core.stamina"]
    events = _use(engine, RAPID, target=t.FOE)
    assert mantle not in foe.modifiers  # Certain Unweave (the table's default when it turns a check into an automatic ending)
    assert me.resources["resource:core.stamina"] == before - 2
    assert not _events(events, "CHECK_ROLLED")
    assert any("unweaves" in (e.payload.get("log") or "") for e in events if e.event_type == "PASSIVE_TRIGGERED")


def test_rapid_unweave_rolls_the_qiweaving_check_against_10_plus_rank_without_the_augment():
    engine, me, foe = _duel(_bundle([QI], [], cl=12), _foe_sheet())
    mantle = _mantled_foe(engine, foe)
    me.resources["resource:core.stamina"] = 1  # only the Action's own CP: no augment can be paid
    events = _use(engine, RAPID, target=t.FOE)
    (check,) = _events(events, "CHECK_ROLLED")
    assert check.payload["dc"] == 13 and check.payload["skill"] == "Qiweaving Check"
    assert (mantle not in foe.modifiers) == check.payload["success"]
