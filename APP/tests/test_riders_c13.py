"""Rider lane C13 (owner 2026-09-30: "i want everything we can automated, keep going until its only the non-combat ones left"):
the printed lines of Sphere base abilities and core features that were still only shown to the GM as riders. Every automated line
is compiled on a real character and run through the engine; C13_OLD=1 swaps in the base typing (a9d0770f): the typing tests then
fail, and the plug-in tests fail on the base code (their modules or effects do not exist there).

Overrides: authority/typed_mechanics/reviewed_final.d/riders_c13.json (and entries edited in place in the other reviewed files);
plug-ins named per section below.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import combat.factory_compiler as compiler
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent, Position, ReactionDecision
from combat.typed_executor import mark_condition_id

sys.path.insert(0, str(Path(__file__).resolve().parent))
t = importlib.import_module("test_review_sw-athletics")

ROOT = Path(__file__).resolve().parents[1]
ME, AN = t.ME, t.AN
BASE = "a9d0770f"


@pytest.fixture(autouse=True, scope="session")
def base_typing(tmp_path_factory):
    if os.environ.get("C13_OLD"):
        path = tmp_path_factory.mktemp("authority") / "base.json"
        path.write_bytes(subprocess.check_output(["git", "show", f"{BASE}:APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json"], cwd=ROOT))
        compiler.TYPED_AUTHORITY = path


def _authority():
    return json.loads(Path(compiler.TYPED_AUTHORITY).read_text(encoding="utf-8"))["mechanics"]


# ------------------------------------------------------------------------------------------------------------ harness
def _sheet(spheres, talents=(), items=(), cl=10, dc=16):
    spheres = [spheres] if isinstance(spheres, str) else list(spheres)
    sheet = t._sheet(spheres[0], list(talents), {"starting_kit": {"items": list(items)}} if items else {}, cl=cl, dc=dc)
    mechanics = t._mechanics()
    for sphere in spheres[1:]:
        sheet["spheres_and_talents"]["sphere_record_ids"].append(sphere)
        sheet["spheres_and_talents"]["automatic_sphere_component_record_ids"] += [
            key for key, row in mechanics.items() if row.get("sphere_id") == sphere and row.get("kind") == "base_ability"]
    return sheet


def _bundle(spheres, talents=(), items=(), cl=10, dc=16, features=()):
    sheet = _sheet(spheres, talents, items, cl, dc)
    if features:
        sheet["path_and_subpath"]["path_feature_record_ids"] = list(features)
    return compile_character(sheet, actor_id=ME)


def _fight(spheres, talents=(), items=(), cl=10, dc=16, foe_hp=400, sure_hit=True, foe_at=(4, 6), features=()):
    engine = t._engine(_bundle(spheres, talents, items, cl, dc, features), foe_hp=foe_hp, sure_hit=sure_hit, foe_at=foe_at)
    return engine, engine.state.actors[ME], engine.state.actors[AN]


def _names(engine):
    t._ready(engine)
    return {c.display_name for c in engine.legal_candidates() if c.actor_id == ME}


def _use(engine, name, target=AN, destination=None, contains=False):
    t._ready(engine)
    found = [c for c in engine.legal_candidates() if (name in c.display_name if contains else c.display_name.split(" at ")[0] == name)
             and c.actor_id == ME and (target is None or not c.target_ids or target in c.target_ids)
             and (destination is None or (c.destination is not None and (c.destination.x, c.destination.y) == destination))]
    assert found, f"{name!r} is not legal; legal: {sorted(n for n in _names(engine) if not n.startswith('Move'))}"
    candidate = found[0]
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"i-{name}-{engine.state.event_sequence}", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=ME,
                                       target_ids=candidate.target_ids, destination=candidate.destination, option_ids=candidate.option_ids))
    return engine.events[before:]


def _events(events, kind):
    return [e for e in events if e.event_type == kind]


def _answers(engine, picks):
    """Immediate engine choice provider: ``picks`` maps a choice id's last part to a function of the offered option ids returning the
    ones picked (None declines). Unlisted choices take the first option. Returns the requests seen."""
    requests = []

    def provider(request):
        if not str(request["reaction_source_id"]).startswith("choice:needle."):
            return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                    reaction_source_id=request["reaction_source_id"], selection="DECLINE", option_ids=()), None
        requests.append(request)
        options = list(request["legal_option_ids"])
        pick = picks.get(str(request["reaction_source_id"]).split(".")[-1])
        chosen = pick(options) if pick else options[:1]
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"], reaction_source_id=request["reaction_source_id"],
                                selection="DECLINE" if chosen is None else "USE", option_ids=tuple(chosen or ())), None

    engine.set_reaction_provider(provider)
    return requests


def _end_turn(engine):
    """End the current creature's turn; returns whose turn it is now."""
    c = next(c for c in engine.legal_candidates() if c.display_name == "End turn")
    engine.execute_intent(ActionIntent(intent_id=f"end-{engine.state.event_sequence}", decision_id=c.decision_id, candidate_id=c.candidate_id,
                                       state_version=c.state_version, actor_id=c.actor_id, target_ids=c.target_ids))
    return engine.state.current_actor_id


def _persisted(tmp_path, bundle, seed, *, foe_at=(4, 6)):
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed=seed, typed_bundles=(bundle,),
                                       roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                     "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": foe_at[0], "y": foe_at[1]}}})
    while session.engine.state.current_actor_id != ME:
        c = next(c for c in session.engine.legal_candidates() if c.display_name == "End turn")
        session.submit_intent(ActionIntent(intent_id=f"end-{c.state_version}", decision_id=c.decision_id, candidate_id=c.candidate_id,
                                           state_version=c.state_version, actor_id=c.actor_id, target_ids=c.target_ids),
                              primary_decision_record=None, reaction_provider=None)
    return persistence, session


def _submit(session, name, target=AN):
    c = next(c for c in session.engine.legal_candidates() if c.display_name == name and c.actor_id == ME
             and (target is None or target in (c.target_ids or ())))
    session.submit_intent(ActionIntent(intent_id=f"i-{name}-{c.state_version}", decision_id=c.decision_id, candidate_id=c.candidate_id,
                                       state_version=c.state_version, actor_id=ME, target_ids=c.target_ids, destination=c.destination),
                          primary_decision_record=None, reaction_provider=session.engine._gate4_reaction_provider)


# ================================================================================================================ Alchemy
ALCHEMY = "tianxia.sphere.alchemy"


def test_field_formula_lines_the_table_already_runs_are_gone_and_its_three_formulae_are_offered():
    """"Choose one Field Formula you know and resolve its effect" (the three formulae every Alchemist knows are its options) and "It
    does not mean the cauldron itself attacks" (the formula is released by the user) were shown to the GM; the supplies requirement stays."""
    riders = _authority()["ALCHEMY_BASE_FIELD_FORMULA"]["riders"]
    assert len(riders) == 1
    assert "alchemist" in riders[0].lower() and "supplies" in riders[0].lower()
    assert "body as cauldron" in riders[0].lower()
    names = {row["display_name"] for row in _bundle(ALCHEMY)["action_catalog"]}
    assert {"Field Formula: Medicinal Smoke", "Field Formula: Numbing Smoke", "Field Formula: Corrosive Dregs"} <= names


# ================================================================================================================ Ash
ASH = "tianxia.sphere.ash"


def _remnants(engine):
    from combat.ext import placed

    return placed.of(engine, "ash_remnant")


def test_cinder_brand_applies_ashen_brand_and_a_branded_creature_cannot_gain_temporary_hp():
    """"Hit: Deal Fire, Necrotic, or Psychic damage and apply Ashen Brand"; "Ashen Brand lasts until the start of your next turn. A
    branded creature cannot gain Temporary HP." (Core Ash Rules)."""
    engine, me, foe = _fight(ASH)
    _use(engine, "Cinder Brand: Reduce Healing")
    brand = mark_condition_id("Ashen Brand", ME)
    assert any(c.condition_id == brand for c in foe.conditions.values())
    engine._grant_temp_hp(foe, 6, "test:temp", AN)
    assert foe.temporary_hp == 0
    assert _end_turn(engine) == AN and _end_turn(engine) == ME
    from combat import typed_executor

    typed_executor.expire_marks(engine)
    assert not any(c.condition_id == brand for c in foe.conditions.values())
    assert not any(c.condition_id == "condition:typed.no_temp_hp" for c in foe.conditions.values())  # it goes with the brand
    engine._grant_temp_hp(foe, 6, "test:temp", AN)
    assert foe.temporary_hp == 6


def test_a_branded_creature_cannot_hide_behind_obscurement_alone():
    """"While the visible cinder trail remains exposed, the creature cannot successfully take the Hide action solely by becoming Heavily
    Obscured or moving behind cover. Total Cover ... can still protect it.": a Dark cultivator in its own magical Darkness may Hide,
    but not while it bears an Ashen Brand and the foe still has a clear line to it."""
    engine, me, foe = _fight(["tianxia.sphere.dark", ASH], ["TAL_DARK_PURE_DARKNESS"], foe_at=(10, 6))
    _use(engine, "Shape Darkness: plain Darkness", target=None)
    _use(engine, "Darkness", target=None, destination=(3, 6))
    engine._system_start_turn()
    assert "Hide" in _names(engine)
    engine._apply_condition(me, mark_condition_id("Ashen Brand", AN), "test:brand", AN, expires_on="UNTIL_REMOVED")
    assert "Hide" not in _names(engine)


def test_cinder_brand_creates_a_remnant_of_ash_terrain_next_to_the_target_and_keeps_only_pb_of_them():
    """"create one Remnant in an unoccupied space adjacent to the target"; "a Remnant counts as Ash Terrain; a Remnant lasts for 1
    minute ...; you may maintain a number of Remnants equal to your Proficiency Bonus; when you exceed that limit, remove the oldest"."""
    engine, me, foe = _fight(ASH)
    seen = _answers(engine, {"ash_remnant": lambda options: [options[-1]]})
    _use(engine, "Cinder Brand: Create Remnant")
    (zone,) = _remnants(engine)
    assert seen and seen[0]["legal_option_ids"][-1] == f"cell:{zone.center.x},{zone.center.y}"  # the player's square
    assert engine.grid.distance_ft(zone.center, foe.position) == 5 and zone.center != me.position
    assert zone.trigger_profile["terrain"] == ["ash terrain"] and zone.trigger_profile["difficult"] == "hostile"
    assert zone.trigger_profile["obscured"] == "light" and zone.duration_rounds == 10
    assert zone.trigger_profile["move_through"]["ability"] == "CON"
    first = zone.zone_id
    for _ in range(4):  # PB 4 at CL 10
        _use(engine, "Cinder Brand: Create Remnant")
    assert len(_remnants(engine)) == 4 and first not in {z.zone_id for z in _remnants(engine)}


def test_cinder_brand_moves_a_remnant_within_30_feet_up_to_10_feet():
    engine, me, foe = _fight(ASH, foe_at=(8, 6))
    _use(engine, "Cinder Brand: Create Remnant")
    (zone,) = _remnants(engine)
    start = zone.center
    _answers(engine, {"ash_remnant_move": lambda options: [next(o for o in options if o.endswith("|north"))]})
    _use(engine, "Cinder Brand: Move Remnant")
    (moved,) = _remnants(engine)
    assert (moved.center.x, moved.center.y) == (start.x, start.y - 2)


def test_cinder_brand_suppresses_temporary_hp_until_the_start_of_your_next_turn():
    """"suppress one ordinary source of Temporary HP already affecting the target until the start of your next turn"."""
    engine, me, foe = _fight(ASH)
    engine._grant_temp_hp(foe, 40, "test:temp", AN)
    events = _use(engine, "Cinder Brand: Suppress Temporary HP")
    absorbed = sum(int(e.payload.get("temporary_hp_absorbed") or 0) for e in _events(events, "DAMAGE_COMMITTED"))
    assert 0 < absorbed < 40 and foe.temporary_hp == 0  # the hit's damage lands first, then what is left is suppressed
    assert _end_turn(engine) == AN
    assert foe.temporary_hp == 0
    assert _end_turn(engine) == ME
    assert foe.temporary_hp == 40 - absorbed  # back, though the brand still forbids new Temporary HP


def test_remnants_and_the_brands_temporary_hp_lock_survive_a_table_commit_and_reload(tmp_path):
    persistence, session = _persisted(tmp_path, _bundle(ASH), "C13-ASH")
    _submit(session, "Cinder Brand: Create Remnant")
    loaded = persistence.load_match(session.match_id).engine
    assert [(z.zone_id, z.center, z.duration_rounds) for z in _remnants(loaded)] == \
        [(z.zone_id, z.center, z.duration_rounds) for z in _remnants(session.engine)]
    (lock,) = [c for c in loaded.state.actors[AN].conditions.values() if c.condition_id == "condition:typed.no_temp_hp"]
    assert lock.data["ashen_brand"] in loaded.state.actors[AN].conditions


# ================================================================================================================ Beastmastery
def test_rider_package_lines_are_what_the_table_already_runs():
    """"Gain Skillful Riding" and Skillful Riding's no-damage-on-a-success / half-on-a-failure for the mount's Dexterity save are
    combat/ext/mounts.py (skillful_riding, the evasion hook; tests/test_mounts.py
    test_skillful_riding_a_passed_half_damage_save_takes_none_and_a_failed_one_half): no GM line is left."""
    entry = _authority()["BEASTMASTERY_BASE_RIDER_PACKAGE"]
    assert entry["riders"] == [] and entry["coverage"] == "FULL"
    from combat.ext import mounts

    assert callable(mounts.skillful_riding)


# ================================================================================================================ shared: persist augments
# combat/ext/persist_augment.py: "Augment - 2 CP: <it> persists for its remaining duration without Concentration. You may apply this
# augment after creating <it> on your turn without spending an Action." (Conflagration, Dreamscape, Qi Bond, Turbulent Field,
# Darkness / Persistent Darkness, Meld / Persistent Meld).
FIRE, DARK, DREAMS, QIW = "tianxia.sphere.fire", "tianxia.sphere.dark", "tianxia.sphere.dreams", "tianxia.sphere.qiweaving"
STAMINA = "resource:core.stamina"


def _keep(engine, word):
    names = [n for n in _names(engine) if "without Concentration" in n and word in n]
    assert len(names) == 1, sorted(n for n in _names(engine) if "Concentration" in n)
    return _use(engine, names[0], target=None)


def test_persist_augment_lines_are_gone():
    mechanics = _authority()
    for key in ("FIRE_BASE_CONFLAGRATION", "DREAMS_BASE_DREAMSCAPE", "TAL_QIWEAVING_QI_BOND", "TAL_DARK_PERSISTENT_DARKNESS",
                "TAL_DARK_PERSISTENT_MELD"):
        assert mechanics[key]["riders"] == [] and mechanics[key]["coverage"] == "FULL", key
    meld = mechanics["TAL_DARK_MELD"]
    assert meld["coverage"] == "CORE_WITH_RIDERS"
    assert meld["riders"] == ["The current Meld actions grant their known Meld to the caster. Granting a chosen Meld to another creature, including the unwilling Wisdom save, is not yet supported."]
    assert not any("Persistent" in line or "without Concentration" in line for line in meld["riders"])
    assert not any("Lingering Turbulence" in line for line in mechanics["TAL_QIWEAVING_TURBULENT_FIELD"]["riders"])


def test_lingering_conflagration_keeps_the_fire_terrain_for_its_minute_after_concentration_ends():
    """Also Conflagration's other rider lines are what the typing already runs: the Fire Terrain area, the successful save's half
    damage and Kindled, the CL damage table."""
    engine, me, foe = _fight(FIRE, foe_at=(8, 6))
    assert not [n for n in _names(engine) if "without Concentration" in n]  # nothing to keep yet
    events = _use(engine, "Conflagration", target=None, destination=(8, 6))
    zone = next(z for z in engine.state.zones.values() if z.active and z.source_definition_id.endswith("FIRE_BASE_CONFLAGRATION"))
    assert "fire terrain" in zone.trigger_profile["terrain"] and zone.concentration_link
    before = me.resources[STAMINA]
    _keep(engine, "Conflagration")
    assert me.resources[STAMINA] == before - 2 and me.concentration is None
    assert zone.active and not zone.concentration_link and zone.duration_rounds == 10
    assert not [n for n in _names(engine) if "without Concentration" in n]
    assert _end_turn(engine) == AN and _end_turn(engine) == ME
    assert zone.active  # it lasts for its own minute


def test_persistent_darkness_keeps_an_older_copy_held_beside_a_newer_technique():
    engine, me, foe = _fight([DARK, QIW], ["TAL_DARK_PURE_DARKNESS"], foe_at=(9, 6))
    from combat import concentration

    _use(engine, "Shape Darkness: plain Darkness", target=None)
    _use(engine, "Darkness", target=None, destination=(12, 10))
    _use(engine, "Turbulent Field", target=None)
    darkness = next(z for z in engine.state.zones.values() if z.active and z.trigger_profile.get("name") == "Darkness")
    assert [s.source_definition_id.rsplit(".", 1)[-1] for _i, s in concentration.held(me)] == ["DARK_BASE_DARKNESS"]
    _keep(engine, "Darkness")
    assert concentration.held(me) == [] and me.concentration.source_definition_id.endswith("TAL_QIWEAVING_TURBULENT_FIELD")
    assert darkness.active and not darkness.concentration_link
    field = next(z for z in engine.state.zones.values() if z.active and z.trigger_profile.get("name") == "Turbulent Field")
    _keep(engine, "Turbulent Field")  # Lingering Turbulence
    assert me.concentration is None and field.active and not field.concentration_link and field.trigger_profile["follows_owner"]


def test_persistent_qi_bond_mark_lasts_the_rest_of_its_minute():
    engine, me, foe = _fight(QIW, foe_at=(5, 6))
    _use(engine, "Qi Bond")
    bond = mark_condition_id("Qi Bond", ME)
    assert [c.expires_on for c in foe.conditions.values() if c.condition_id == bond] == ["CONCENTRATION_END"]
    _keep(engine, "Qi Bond")
    (row,) = [c for c in foe.conditions.values() if c.condition_id == bond]
    assert row.expires_on == f"START_OF_SLOT_AT:{engine.state.round_number + 10}:{engine.state.current_slot_index}"
    assert me.concentration is None


def test_persistent_meld_drops_the_melds_concentration():
    from combat import senses

    engine, me, foe = _fight(DARK, ["TAL_DARK_HIDE_IN_DARKNESS"], foe_at=(9, 6))
    _use(engine, "Meld: Hide in Darkness", target=None)
    (meld,) = [c for c in me.conditions.values() if c.condition_id == senses.MELD]
    assert meld.data["concentration"] is True and me.concentration is not None
    _keep(engine, "Meld")
    (meld,) = [c for c in me.conditions.values() if c.condition_id == senses.MELD]
    assert meld.data["concentration"] is False and me.concentration is None
    assert "TAL_DARK_HIDE_IN_DARKNESS" in senses.melds_of(engine, me)


def test_lingering_dreamscape_and_the_kept_area_survive_a_table_commit_and_reload(tmp_path):
    persistence, session = _persisted(tmp_path, _bundle(DREAMS), "C13-DREAMSCAPE")
    c = next(c for c in session.engine.legal_candidates() if c.display_name == "Dreamscape at 9,9")
    session.submit_intent(ActionIntent(intent_id="dream", decision_id=c.decision_id, candidate_id=c.candidate_id, state_version=c.state_version,
                                       actor_id=ME, destination=c.destination), primary_decision_record=None, reaction_provider=None)
    name = next(c.display_name for c in session.engine.legal_candidates() if "without Concentration" in c.display_name)
    _submit(session, name, target=None)
    zone = next(z for z in session.engine.state.zones.values() if z.active and z.trigger_profile.get("name") == "Dreamscape")
    loaded = persistence.load_match(session.match_id).engine
    kept = loaded.state.zones[zone.zone_id]
    assert kept.active and not kept.concentration_link and loaded.state.actors[ME].concentration is None


# ================================================================================================================ Fire
def test_ignite_overheat_rolls_one_more_die_for_1_cp_and_burns_its_user_for_pb():
    """"Overheat - Ignite / Augment - 1 CP: Roll one additional damage die for Ignite. After the attack resolves, take Fire damage
    equal to your Proficiency Bonus." (combat/ext/base_augments.py). Ignite's other rider lines (ranged Cultivation Attack, the CL
    damage table, the once-per-hit choice) were what the typing already runs."""
    entry = _authority()["FIRE_BASE_IGNITE"]
    assert entry["riders"] == [] and entry["coverage"] == "FULL"
    engine, me, foe = _fight(FIRE, foe_at=(8, 6), cl=10)
    plain = _use(engine, "Ignite: Push Target")
    assert [len(e.payload["dice"]) for e in _events(plain, "DAMAGE_ROLLED") if AN in e.target_ids] == [2]  # CL 10: 2d10
    hp, stamina = me.current_hp, me.resources[STAMINA]
    events = _use(engine, "Ignite: Push Target + Overheat (1 CP)")
    assert [len(e.payload["dice"]) for e in _events(events, "DAMAGE_ROLLED") if AN in e.target_ids] == [3]
    assert me.resources[STAMINA] == stamina - 1
    (burn,) = [e for e in _events(events, "DAMAGE_COMMITTED") if ME in e.target_ids]
    assert burn.payload["damage_type"] == "FIRE" and me.current_hp == hp - 4  # PB 4


# ================================================================================================================ Earth
def _move(engine, who, to):
    c = next(c for c in engine.legal_candidates() if c.actor_id == who and c.display_name == f"Move to {to[0]},{to[1]}")
    engine.execute_intent(ActionIntent(intent_id=f"mv-{who}-{engine.state.event_sequence}", decision_id=c.decision_id, candidate_id=c.candidate_id,
                                       state_version=c.state_version, actor_id=who, destination=c.destination))


@pytest.mark.parametrize("destination, expected_mark", [((9, 2), False), ((9, 10), True)])
def test_set_foundation_marks_a_hostile_creature_that_willingly_crosses_it_and_never_your_side(destination, expected_mark):
    """"When a creature you did not designate as safe willingly moves at least 10 feet across, out of, or through your Foundation Spaces
    during one turn, you may give that creature one Burden Mark." Was: every creature crossing it, allies and the maker included."""
    from tests import test_riders_lane9 as L9

    assert _authority()["EARTH_BASE_SET_FOUNDATION"]["riders"] == []
    # Isolate creation: native per-step marking would otherwise let the separate
    # Spending a Burden Mark response consume it later in this same movement.
    engine = L9._earth_fight([], them_at=(9, 6), ally_at=(9, 7), bases=("EARTH_BASE_SET_FOUNDATION",))
    c = next(c for c in engine.legal_candidates() if c.display_name == "Set Foundation" and L9.ALLY in (c.target_ids or ()))
    engine.execute_intent(ActionIntent(intent_id="found", decision_id=c.decision_id, candidate_id=c.candidate_id, state_version=c.state_version,
                                       actor_id=L9.ME, target_ids=c.target_ids))
    zone = next(z for z in engine.state.zones.values() if z.active and z.source_definition_id.endswith("EARTH_BASE_SET_FOUNDATION"))
    assert {(9, 6), (9, 7)} <= {(cell.x, cell.y) for cell in zone.affected_cells}  # around the ally, the foe inside too
    L9._turn(engine, L9.ALLY)
    _move(engine, L9.ALLY, (6, 10))  # 15 feet away, out of the Foundation
    assert not L9._burdened(engine, L9.ALLY)
    L9._turn(engine, L9.THEM)
    # Cross two actual Foundation steps before leaving. Going north from
    # (9, 6) immediately exits after only 5 feet, below the printed 10 feet.
    _move(engine, L9.THEM, destination)
    movement = next(e for e in reversed(engine.events) if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == L9.THEM)
    cells = {(cell.x, cell.y) for cell in zone.affected_cells}
    if expected_mark:
        assert all((cell["x"], cell["y"]) in cells for cell in movement.payload["path"][:3])
    else:
        assert (movement.payload["path"][1]["x"], movement.payload["path"][1]["y"]) not in cells
    assert L9._burdened(engine, L9.THEM) == expected_mark


def test_settle_the_impact_that_stops_a_push_lets_the_creature_step_5_feet():
    """"If this reduces the displacement to 0, the displaced creature or object may immediately move 5 feet without provoking
    Opportunity Attacks from the marked target." (CL 15: the push is 20 feet shorter)."""
    from combat import typed_reactions
    from tests import test_riders_lane9 as L9

    engine = L9._earth_fight([], ally_at=(3, 7))
    L9._burden(engine)
    ally = engine.state.actors[L9.ALLY]
    start = ally.position
    assert typed_reactions.on_forced_movement(engine, ally, engine.state.actors[L9.THEM], 20) == 0
    assert engine.grid.distance_ft(start, ally.position) == 5
    stepped = [e for e in engine.events if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == L9.ALLY]
    assert stepped and stepped[-1].payload["cost_ft"] == 0
    rider = _authority()["EARTH_BASE_SPENDING_A_BURDEN_MARK"]["riders"]
    assert len(rider) == 1 and "Settle" not in rider[0]


# ================================================================================================================ Disease
def test_quarantine_veil_spread_line_needs_no_gm():
    """"Disease effects created by you cannot spread from inside the veil to creatures outside the veil unless you allow it": on this
    table a Disease spreads between creatures only through Spreading Infection, which is the veil-maker's own Reaction -- choosing it is
    allowing it (combat/ext/disease.py _spreading asks the maker). Nothing else spreads, so no GM line is left."""
    assert _authority()["DISEASE_BASE_RAISE_THE_QUARANTINE_VEIL"]["riders"] == []
    import inspect

    from combat.ext import disease

    assert "pick(engine, owner" in inspect.getsource(disease._spreading)


# ================================================================================================================ Glass
def test_a_hostile_creature_crossing_your_shattered_glass_terrain_may_gain_a_faultline_mark():
    """Faultline Marks: "You may place a Faultline Mark when ... a creature willingly moves across Shattered Glass Terrain you created"
    (combat/ext/glass_refraction.py _shattered_mark). The rest of that rider line (attacks through a Glass Surface, touching one)
    stays the GM's."""
    from combat.ext import placed
    from tests import test_riders_lane9 as L9

    engine = L9._glass_fight([], them_at=(8, 6))
    me, them = engine.state.actors[L9.ME], engine.state.actors[L9.THEM]
    source = next(a for a, row in engine.action_catalog.items() if row.owner_id == L9.ME and "GLASS" in a)
    from combat.typed_executor import run_effects

    run_effects(placed.context(engine, me, source, {"pb": 5}, [them]),
                [{"type": "terrain_patch", "terrain": "shattered glass terrain", "center": {"x": 8, "y": 3}, "radius_ft": 10,
                  "duration": {"kind": "minutes", "amount": 1}}])
    assert not L9._faulted(engine)
    L9._turn(engine, L9.THEM)
    _move(engine, L9.THEM, (8, 3))  # into the broken glass
    assert L9._faulted(engine)
    rider = _authority()["GLASS_BASE_FAULTLINE_MARKS"]["riders"]
    assert len(rider) == 1 and "Shattered Glass" not in rider[0]


# ================================================================================================================ Music
def test_opening_phrase_adds_pb_to_the_next_concentration_save():
    """"the target adds your Proficiency Bonus to one Concentration saving throw before the start of your next turn": the engine's
    save_bonus seam now reaches the Concentration save (combat/ext/music.py), so the Advantage stand-in and its rider are gone."""
    assert _authority()["MUSIC_BASE_OPENING_PHRASE"]["riders"] == []
    engine, me, foe = _fight(["tianxia.sphere.music", DARK], ["TAL_DARK_PURE_DARKNESS"], foe_at=(9, 6))
    _use(engine, "Shape Darkness: plain Darkness", target=None)
    _use(engine, "Darkness", target=None, destination=(12, 10))
    _use(engine, "Keep the Measure", target=None)
    _use(engine, "Opening Phrase: Concentration Save", target=ME)
    assert not any(c.condition_id.endswith("advantage") for c in me.conditions.values())
    saves = []
    for _ in range(2):
        before = len(engine.events)
        engine._commit_damage(me, 2, "FIRE", "test:hit", AN, None, reaction_depth=0)
        saves += [e.payload for e in engine.events[before:] if e.event_type == "SAVE_ROLLED" and e.source_definition_id == "system:combat.concentration"]
        if me.concentration is None:
            break
    con = me.saving_throws.get("CON", 0)
    assert saves[0]["modifier"] == con + 4  # PB 4, once
    assert all(save["modifier"] == con for save in saves[1:])
    assert not any(c.condition_id == "condition:typed.music_opening_concentration" for c in me.conditions.values())


# ================================================================================================================ Metal
def test_weight_instead_of_sharpen_is_the_metal_expression_menu():
    """The expression menu is automated; ordinary weapons still need Metal Qi confirmed.

    The printed trigger requires a qualifying Metal Qi attack, so the menu alone
    does not establish that an ordinary weapon carries Metal Qi.
    """
    riders = _authority()["METAL_BASE_WEIGHT"]["riders"]
    assert len(riders) == 1
    assert "GM to confirm it carries Metal Qi" in riders[0]
    assert "not automatically checked" in riders[0]
    names = {row["display_name"] for row in _bundle("tianxia.sphere.metal")["action_catalog"]}
    assert {"Choose Metal expression: Sharpen", "Choose Metal expression: Weight: Push 5 feet",
            "Choose Metal expression: Weight: Pull 5 feet"} <= names


# ================================================================================================================ Poison
REALM_D8 = [[1, 4, 1, 8], [5, 9, 2, 8], [10, 14, 3, 8], [15, 20, 4, 8]]  # core rules 1.2: Foundation CL 5-9, Core Formation 10-14, Nascent Soul 15+


def test_deliver_the_dose_damage_follows_the_printed_realms():
    """"Mortal: 1d8 Foundation: 2d8 Core Formation: 3d8 Nascent Soul: 4d8" -- the Realms of the core rules (CL 5-9 / 10-14 / 15-19), not
    the 5 / 11 / 17 cantrip steps the typing carried: a CL 10 Poison cultivator is in Core Formation and rolls 3d8."""
    entry = _authority()["POISON_BASE_DELIVER_THE_DOSE"]
    assert entry["effects"][0]["on_hit"][0]["dice_by_cl"] == REALM_D8
    assert not any(line.startswith("####") for line in entry["riders"])
    engine, me, foe = _fight("tianxia.sphere.poison", cl=10)
    events = _use(engine, "Deliver the Dose")
    assert [len(e.payload["dice"]) for e in _events(events, "DAMAGE_ROLLED") if AN in e.target_ids][:1] == [3]


# ================================================================================================================ Protection
def test_armored_aegis_keeps_a_carried_shields_plus_2_on_top():
    """Armored Aegis: "The target's base AC becomes equal to your Cultivation Save DC" -- a base AC, so the bearer's shield still adds its
    +2 (the GM line said so; the table took the higher of the bearer's AC and the DC)."""
    from tests import test_riders_c4 as C4

    engine = C4.protect(dc=16)
    ally = engine.state.actors[C4.ALLY]
    engine.typed_passive_rows.setdefault(C4.ALLY, []).append({"feature_id": "shield_ac", "block": "shield_ac", "amount": 2})
    ally.armor_class = 12  # 10 + the shield's 2
    C4.use(engine, "Aegis: Armored Aegis", target=C4.ALLY)
    assert ally.armor_class + engine._ac_modifier(ally) == 18
    assert _authority()["PROTECTION_BASE_ARMORED_AEGIS"]["riders"] == []


def test_an_aegis_can_be_ended_by_its_creator_without_an_action():
    """"An Aegis may be ended early by its creator without spending an action.\""""
    from tests import test_riders_c4 as C4

    engine = C4.protect("shielded")
    me, ally = engine.state.actors[C4.ME], engine.state.actors[C4.ALLY]
    assert "End an Aegis you made" not in C4.legal(engine)
    C4.use(engine, "Aegis: Shielded (Persistent)", target=C4.ALLY)
    me.action_available = False
    assert C4.aegis_of(ally)
    C4.use(engine, "End an Aegis you made", target=C4.ALLY)
    assert not C4.aegis_of(ally) and me.bonus_action_available and not me.action_available
    assert _authority()["PROTECTION_BASE_AEGIS"]["riders"] == []


# ================================================================================================================ Smoke
SMOKE = "tianxia.sphere.smoke"


def test_smoke_veil_moves_10_feet_as_a_bonus_action():
    """"As a Bonus Action while the veil persists, move it up to 10 feet to a space within range." (combat/ext/smoke_riders.py)"""
    engine, me, foe = _fight(SMOKE, foe_at=(9, 6))
    assert "Smoke Veil: move it 10 feet" not in _names(engine)
    _use(engine, "Smoke Veil", target=None, destination=(6, 6))
    veil = next(z for z in engine.state.zones.values() if z.active and z.trigger_profile.get("name") == "Smoke Veil")
    t._ready(engine)
    aims = {(c.destination.x, c.destination.y) for c in engine.legal_candidates() if c.display_name.startswith("Smoke Veil: move it 10 feet")}
    assert (8, 6) in aims and (9, 6) not in aims and all(engine.grid.distance_ft(veil.center, Position(x=x, y=y)) <= 10 for x, y in aims)
    me.bonus_action_available = True
    _use(engine, "Smoke Veil: move it 10 feet", target=None, destination=(8, 6))
    assert (veil.center.x, veil.center.y) == (8, 6) and not me.bonus_action_available


def test_smoke_trace_limit_is_pb_and_every_marks_limit_counts():
    """Smoke Trace: "You can have a number of Smoke Traces active at one time equal to your Proficiency Bonus" (a mark_caps row). A Glass +
    Smoke character keeps both limits: typed_executor.mark_capacity read only the first mark_caps row before."""
    from combat.ext import placed
    from combat.typed_executor import mark_capacity

    engine, me, foe = _fight([SMOKE, "tianxia.sphere.glass"], cl=10)
    ctx = placed.context(engine, me, next(a for a, row in engine.action_catalog.items() if row.owner_id == ME), {})
    assert mark_capacity(ctx, "Smoke Trace") == 4 and mark_capacity(ctx, "Faultline Mark") == 4
    riders = _authority()["SMOKE_BASE_SMOKE_TRACE"]["riders"]
    assert not any(line.startswith(("You can have a number", "A Smoke Trace lasts")) for line in riders)


# ================================================================================================================ Source
SOURCE = "tianxia.sphere.source"


def test_source_pulse_realm_dice_and_rider_lines():
    """"The damage becomes 2d8 at Foundation Realm, 3d8 at Core Formation Realm, and 4d8 at Nascent Soul Realm" (it never scaled);
    its 0 cost, its own non-stacking Speed reduction and "does not damage the ground ..." were what the table already does."""
    entry = _authority()["SOURCE_BASE_SOURCE_PULSE"]
    assert entry["effects"][0]["on_hit"][0]["dice_by_cl"] == REALM_D8
    engine, me, foe = _fight(SOURCE, cl=10, foe_at=(8, 6))
    events = _use(engine, "Source Pulse")
    assert [len(e.payload["dice"]) for e in _events(events, "DAMAGE_ROLLED") if AN in e.target_ids] == [3]


def test_fetter_seal_slows_the_first_hostile_creature_on_it_and_ends():
    """Fetter Seal: "The first time a creature of your choice enters that section or starts its turn there before the seal ends, you may
    end the seal. If you do, that creature's Speed is reduced by 10 feet until the end of that turn." Before, Source Seal's options were
    aimed at you or an ally (a Fetter Seal slowed your own side)."""
    from tests import test_riders_lane9 as L9

    engine, me, foe = _fight(SOURCE, cl=10, foe_at=(8, 6))
    assert all(c.target_kind == "CELL" for c in [engine.action_catalog[a] for a in me.action_ids] if c.display_name == "Source Seal")
    _use(engine, "Source Seal", target=None, destination=(4, 6))
    (seal,) = [z for z in engine.state.zones.values() if z.active and z.trigger_profile.get("name") == "Source Seal"]
    speed = engine._effective_speed(foe)
    L9._turn(engine, AN)
    _move(engine, AN, (4, 6))
    assert not seal.active
    assert any(m.target_field == "speed_ft" and m.value == -10 and m.expires_on == "END_OF_CURRENT_TURN" for m in foe.modifiers.values())


def test_source_seals_are_limited_to_pb_with_oldest_as_the_ai_fallback():
    engine, me, foe = _fight(SOURCE, cl=10, foe_at=(9, 6))
    for cell in ((2, 5), (2, 6), (2, 7), (3, 5), (3, 7)):
        _use(engine, "Source Seal", target=None, destination=cell)
    seals = [z for z in engine.state.zones.values() if z.active and z.trigger_profile.get("name") == "Source Seal"]
    assert len(seals) == 4 and (2, 5) not in {(z.center.x, z.center.y) for z in seals}  # AI fallback, not a forced player choice


# ================================================================================================================ shared: Special Attacks
EXTRA = ["tianxia.path.body_refining.feature.extra_attack"]
AXE_ITEMS = t.AXE_KIT["starting_kit"]["items"]


def _rest(engine):
    return sorted(n for n in _names(engine) if n.endswith("(rest of the Attack action)"))


def test_a_special_attack_replaces_one_attack_and_the_rest_of_the_attack_action_follows():
    """Brute/Wrestling "Special Attacks": "When a talent says it is a Special Attack, replace one attack when you take the Attack action";
    Brutal Shove: "Replace one attack when you take the Attack action." (combat/ext/special_attacks.py). With Extra Attack (2 attacks at
    CL 10) a Brutal Shove leaves one more attack this turn; before, the shove spent the whole Action."""
    engine, me, foe = _fight("tianxia.sphere.brute", items=AXE_ITEMS, cl=10, features=EXTRA)
    assert _rest(engine) == []
    _use(engine, "Brutal Shove")
    rest = _rest(engine)
    assert rest and all(name.startswith("Fu (Short Axe)") for name in rest)
    events = _use(engine, rest[0])
    assert len(_events(events, "ATTACK_ROLLED")) == 1
    assert _rest(engine) == []  # that was the one attack left
    plain, _me, _foe = _fight("tianxia.sphere.brute", items=AXE_ITEMS, cl=10)
    _use(plain, "Brutal Shove")
    assert _rest(plain) == []  # no Extra Attack: nothing more
    mechanics = _authority()
    for key in ("BRUTE_BASE_SPECIAL_ATTACKS", "WRESTLING_BASE_SPECIAL_ATTACKS", "SPEAR_BASE_SPEAR_THRUST", "TAL_BERSERKER_BATTER"):
        assert mechanics[key]["riders"] == [] and mechanics[key]["coverage"] == "FULL", key
    # C16 retains these printed reminders in the player-facing row; the runtime checks above prove the replacement works.
    assert mechanics["BRUTE_BASE_BRUTAL_SHOVE"]["coverage"] == "CORE_WITH_RIDERS"
    assert "Replace one attack when you take the Attack action." in mechanics["BRUTE_BASE_BRUTAL_SHOVE"]["riders"]
    assert not any("GM" in line for line in mechanics["BRUTE_BASE_BRUTAL_SHOVE"]["riders"])


def test_batter_with_the_unarmed_strike_batters_until_the_end_of_your_next_turn_and_keeps_the_other_attacks():
    """Batter: "A Batter is a Special Attack ... On a hit that deals damage, the target becomes Battered until the end of your next turn."
    The unarmed Batter (combat/ext/gu_berserker.py) used the holder's next turn; it now runs the weapon Batters' own ``batter`` effect."""
    engine, me, foe = _fight("tianxia.sphere.berserker", items=AXE_ITEMS, cl=10, features=EXTRA)
    _use(engine, "Batter")
    (battered,) = [c for c in foe.conditions.values() if c.condition_id == "condition:typed.battered"]
    assert battered.expires_on == f"END_OF_SOURCE_TURN_AT:{me.turns_started + 1}"
    assert _rest(engine)


# ================================================================================================================ Space
def test_spatial_edge_damage_scales_by_its_printed_cl_table_and_fold_step_lines_already_run():
    """Spatial Edge: "CL 1-4: 1d8. CL 5-10: 2d8. CL 11-16: 3d8. CL 17-20: 4d8." (it stayed 1d8); range, cost and "does not move the target
    and does not bypass total cover" were the typing's own. Fold Step: no Opportunity Attacks (a teleport), every teleport block on the
    table stops it (typed_executor._teleport's teleport_gate), and 20 feet + Extended Fold's 15 never passes the 50-foot cap."""
    mechanics = _authority()
    assert mechanics["TAL_SPACE_FOLD_STEP"]["riders"] == []
    assert not any("GM" in line for line in mechanics["TAL_SPACE_SPATIAL_EDGE"]["riders"])
    engine, me, foe = _fight("tianxia.sphere.space", cl=11, foe_at=(9, 6))
    events = _use(engine, "Spatial Edge")
    assert [len(e.payload["dice"]) for e in _events(events, "DAMAGE_ROLLED") if AN in e.target_ids] == [3]


# ================================================================================================================ Void
def test_void_needle_cost_lock_keeps_the_targets_techniques_at_their_listed_cost():
    """Cost Lock: "the target cannot reduce technique costs below the listed cost until the start of your next turn" -- the engine's
    technique_cost_floor seam now prices every reduced cost (combat/ext/void_riders.py), so the GM line is gone."""
    QI = "resource:core.qi"
    engine, me, foe = _fight("tianxia.sphere.void", cl=10, foe_at=(8, 6))
    assert engine.effective_costs(foe, "test:technique", ((QI, 2),), reduced_costs=((QI, 1),)) == ((QI, 1),)
    _use(engine, "Void Needle: Cost Lock")
    assert engine.effective_costs(foe, "test:technique", ((QI, 2),), reduced_costs=((QI, 1),)) == ((QI, 2),)
    assert _end_turn(engine) == AN and _end_turn(engine) == ME
    assert engine.effective_costs(foe, "test:technique", ((QI, 2),), reduced_costs=((QI, 1),)) == ((QI, 1),)
    assert not any(line.startswith("Cost Lock") for line in _authority()["TAL_VOID_VOID_NEEDLE"]["riders"])


# ================================================================================================================ Chains
CHAINS = "tianxia.sphere.chains"


def test_set_the_tether_bound_slows_stops_dashing_and_holds_the_creature_within_30_feet():
    """Bound: "has its Speed reduced by 10 feet; cannot Dash; has Disadvantage on checks made to escape ...; cannot willingly increase the
    distance from the Tether beyond the Tether's maximum length" ("The Tether has a maximum length of 30 feet"). The condition had no
    rule at all: a Bound creature lost nothing (combat/ext/chains_core.py, typed_conditions "bound")."""
    from tests import test_riders_lane9 as L9

    engine, me, foe = _fight(CHAINS, cl=10, dc=50, foe_at=(6, 6))
    speed = engine._effective_speed(foe)
    _use(engine, "Set the Tether")
    assert any(c.condition_id == "condition:typed.bound" for c in foe.conditions.values())
    assert engine._effective_speed(foe) == speed - 10
    L9._turn(engine, AN)
    names = {c.display_name for c in engine.legal_candidates() if c.actor_id == AN}
    assert "Dash" not in names
    far = {c.destination.x for c in engine.legal_candidates() if c.actor_id == AN and c.display_name.startswith("Move to") and c.destination.y == 6}
    assert 9 in far and 10 not in far  # (9,6) is 30 feet from me at (3,6); (10,6) would be 35
    from combat.ext import chains_sphere

    assert chains_sphere.bound_escapes(engine, foe, list(foe.conditions.values())) == "DISADVANTAGE"
    assert not any(line.startswith(("Failed Save: The target becomes Bound", "The Tether has a maximum length"))
                   for line in _authority()["TAL_CHAINS_SET_TETHER_BASE"]["riders"])
    # Chain Gang Method's Bound chains the linked creatures to each other, not to you: it is slowed but not held near you.
    engine, me, foe = _fight(CHAINS, ["tianxia.talent.chains.chain_gang_method"], cl=10, dc=50, foe_at=(8, 6))
    _use(engine, "Chain Gang Method")
    assert any(c.condition_id == "condition:typed.bound" for c in foe.conditions.values())
    L9._turn(engine, AN)
    far = {c.destination.x for c in engine.legal_candidates() if c.actor_id == AN and c.display_name.startswith("Move to") and c.destination.y == 6}
    assert max(far) > 9  # past 30 feet from me at (3,6)


def test_anchor_the_link_reduces_a_push_on_an_ally_within_30_feet_by_10_or_20_feet():
    """"reduce forced movement by 10 feet ... At Core Formation Realm, reduce forced movement by 20 feet instead"; Range 30 feet. It used
    to default to Advantage on a save (no use against a push without one) and answer allies anywhere on the map."""
    from combat import typed_reactions
    from tests import test_riders_lane9 as L9

    for cl, cut in ((9, 10), (10, 20)):
        bundle = compile_character(_sheet(CHAINS, cl=cl), actor_id=L9.ME)
        rows = [r for r in bundle["typed_reactions"] if r["feature_id"] == "TAL_CHAINS_ANCHOR_LINK_BASE" and r["kind"] == "ally_forced_moved"]
        assert rows and rows[0]["range_ft"] == 30 and rows[0]["effects"][0]["type"] == "forced_movement"
    from combat.gate4_engine import Gate4ControllerEngine

    chains = compile_character(_sheet(CHAINS, cl=10), actor_id=L9.ME)
    plain = [compile_character(t._sheet(None, [], {}), actor_id=who) for who in (L9.ALLY, L9.THEM)]

    def fight(ally_at):
        engine = Gate4ControllerEngine(ROOT, match_seed="C13-ANCHOR", typed_bundles=(chains, *plain),
                                       roster_setup={"primary_actor_ids": [L9.ME, L9.ALLY, L9.THEM],
                                                     "team_by_actor": {L9.ME: "team:a", L9.ALLY: "team:a", L9.THEM: "team:b"},
                                                     "starting_positions": {L9.ME: {"x": 3, "y": 6}, L9.ALLY: {"x": ally_at[0], "y": ally_at[1]},
                                                                            L9.THEM: {"x": ally_at[0] + 1, "y": ally_at[1]}}})
        return engine, engine.state.actors[L9.ALLY], engine.state.actors[L9.THEM]

    engine, ally, them = fight((3, 8))
    assert typed_reactions.on_forced_movement(engine, ally, them, 25) == 5  # CL 10, Core Formation: 20 feet off
    engine, ally, them = fight((10, 8))  # 35 feet away: out of the reaction's range
    assert typed_reactions.on_forced_movement(engine, ally, them, 25) == 25


def test_chain_lash_follows_the_realms_and_can_attach_a_link():
    """"Mortal: 1d8 Foundation: 2d8 Core Formation: 3d8 Nascent Soul: 4d8" (core-rules Realms) and the fifth minor link effect,
    "attach a harmless visible Link to the target until the start of your next turn"."""
    engine, me, foe = _fight(CHAINS, cl=10, foe_at=(6, 6))
    events = _use(engine, "Chain Lash: Attach a Link")
    assert [len(e.payload["dice"]) for e in _events(events, "DAMAGE_ROLLED") if AN in e.target_ids] == [3]
    assert any(c.condition_id == mark_condition_id("Link", ME) for c in foe.conditions.values())


# ================================================================================================================ Axes
def test_turning_cast_lets_the_target_choose_the_push_or_the_slow():
    """Turning Cast: "it must choose either to be pushed 5 feet or to have its Speed reduced by 5 feet until the start of your next turn"
    (combat/ext/martial_axes.py; the target's controller is asked). It always pushed."""
    name = "Fu (Short Axe) thrown: Cast Axe: Turning Cast"
    for pick, moved, slowed in (("slow", False, True), ("push", True, False)):
        engine, me, foe = _fight("tianxia.sphere.axes", items=AXE_ITEMS, cl=10, foe_at=(6, 6))
        seen = _answers(engine, {"axes_turning_cast": lambda options, pick=pick: [pick]})
        start, speed = foe.position, engine._effective_speed(foe)
        _use(engine, name)
        assert seen and seen[0]["reactor_id"] == AN  # the target chooses
        assert (foe.position != start) is moved and (engine._effective_speed(foe) == speed - 5) is slowed
    assert not any(line.startswith("Turning Cast") for line in _authority()["TAL_AXES_CAST_AXE"]["riders"])


# ================================================================================================================ Daemonic Cultivation
DAEMONIC = "tianxia.sphere.daemonic_cultivation"
ESSENCE = "resource:named.devoured_essence"


def test_devour_essence_answers_a_demon_marked_creature_taking_damage_once_a_round_with_the_bonus_action_on_your_turn():
    """"Use Devour Essence when ... a creature bearing your demonic mark takes damage ... Gain 1 Devoured Essence. You can use Devour Essence
    once per round." (Bonus Action or Reaction). It only answered a creature dropping to 0 HP and always spent the Reaction."""
    engine, me, foe = _fight(DAEMONIC, items=AXE_ITEMS, cl=10, foe_hp=300)
    engine._apply_condition(foe, mark_condition_id("Demon Mark", ME), "test:mark", ME, expires_on="UNTIL_REMOVED")
    _use(engine, "Fu (Short Axe) attack")
    assert me.resources[ESSENCE] == 1 and not me.bonus_action_available and me.reaction_available
    me.bonus_action_available = True
    _use(engine, "Fu (Short Axe) attack")
    assert me.resources[ESSENCE] == 1  # once per round
    assert _end_turn(engine) == AN and _end_turn(engine) == ME
    me.reaction_available = True
    engine.state.current_actor_id = AN  # the next hit lands on another creature's turn: the Reaction pays
    engine._commit_damage(foe, 3, "SLASHING", "test:hit", ME, None, reaction_depth=0)
    assert me.resources[ESSENCE] == 2 and not me.reaction_available


def test_devour_essence_answers_a_hostile_creature_dropping_to_0_hp():
    engine, me, foe = _fight(DAEMONIC, items=AXE_ITEMS, cl=10, foe_hp=1)
    _use(engine, "Fu (Short Axe) attack")
    assert me.resources[ESSENCE] == 1
    entry = _authority()["TAL_DAEMONIC_CULTIVATION_DEVOUR_ESSENCE"]
    assert entry["effects"] == [] and all("not modeled" not in line for line in entry["riders"])
    assert not [r for r in _bundle(DAEMONIC)["typed_reactions"] if r["feature_id"] == "TAL_DAEMONIC_CULTIVATION_DEVOUR_ESSENCE"]


# ================================================================================================================ Drunken Style
DRUNKEN = "tianxia.sphere.drunken_style"


def _off_rhythm(creature):
    return any(c.condition_id == mark_condition_id("Off-Rhythm", ME) for c in creature.conditions.values())


def test_broken_rhythm_strike_is_a_weapon_strike_that_leaves_the_target_off_rhythm():
    """"Make an Unarmed Strike ..., an improvised melee weapon attack, or a melee weapon attack. Hit: The attack deals normal damage, and the
    target becomes Off-Rhythm from you until the start of your next turn." It was a damage-less attack and Off-Rhythm did not exist."""
    engine, me, foe = _fight(DRUNKEN, items=AXE_ITEMS, cl=10)
    assert "Broken-Rhythm Strike" not in _names(engine)
    events = _use(engine, "Broken-Rhythm Strike: Fu (Short Axe)")
    assert [e for e in _events(events, "DAMAGE_COMMITTED") if AN in e.target_ids] and _off_rhythm(foe)
    assert _authority()["TAL_DRUNKEN_STYLE_BROKEN_RHYTHM_STRIKE"]["riders"][0].startswith("An improvised melee weapon")


def test_a_narrow_miss_can_leave_a_false_opening_and_its_next_attack_turns_it_off_rhythm():
    """"Miss by 5 or Less: You may choose to create a False Opening for the target" -- "that creature has Advantage on the next attack roll it
    makes against you ... it becomes Off-Rhythm from you immediately after the attack resolves"."""
    from combat.ext import drunken_style
    from combat.typed_executor import run_effects
    from combat.ext import placed

    engine, me, foe = _fight(DRUNKEN, items=AXE_ITEMS, cl=10)
    run_effects(placed.context(engine, me, next(a for a in me.action_ids if a.endswith("broken_rhythm")), {}, [foe]),
                [{"type": "drunken_false_opening"}])
    assert drunken_style._opening(foe, me) is not None
    assert drunken_style.false_opening_advantage(engine, foe, me, None, {}) == {"mode": "ADVANTAGE"}
    from tests import test_riders_lane9 as L9

    L9._turn(engine, AN)
    me.armor_class = 5
    attack = next(c for c in engine.legal_candidates() if c.actor_id == AN and ME in (c.target_ids or ()) and c.display_name == "Paired Bi Shou Assault")
    engine.execute_intent(ActionIntent(intent_id="an-attack", decision_id=attack.decision_id, candidate_id=attack.candidate_id,
                                       state_version=attack.state_version, actor_id=AN, target_ids=attack.target_ids))
    assert drunken_style._opening(foe, me) is None and _off_rhythm(foe)


def test_reeling_step_tests_a_creature_and_frees_the_move_from_opportunity_attacks():
    """Reeling Step: the Wisdom save -- "Failed Save: Off-Rhythm from you"; "Successful Save: ... it cannot make Opportunity Attacks against
    you during the movement"; and "does not provoke Opportunity Attacks from one creature you can see"."""
    from combat.ext import drunken_style

    engine, me, foe = _fight(DRUNKEN, items=AXE_ITEMS, cl=10, dc=50)
    _use(engine, "Reeling Step", target=None)
    assert _off_rhythm(foe) and not getattr(engine, "_granted_movement_oa", None)
    engine, me, foe = _fight(DRUNKEN, items=AXE_ITEMS, cl=10, dc=-40)
    _use(engine, "Reeling Step", target=None)
    assert not _off_rhythm(foe) and not getattr(engine, "_granted_movement_oa", None)
    assert drunken_style.reeling_needs_speed(engine, me, None, engine.action_catalog[next(a for a in me.action_ids if "REELING" in a)]) is True


def test_swaying_guard_answers_an_attack_on_you_only_when_the_attacker_is_off_rhythm_or_you_moved():
    """Swaying Guard read the trigger as an attack on any ally and always imposed Disadvantage; now: "a creature ... makes an attack roll
    against you"; "If the attacker is Off-Rhythm from you, impose Disadvantage ... If you moved at least 5 feet since the end of your last
    turn, add your Proficiency Bonus to your AC against the triggering attack"."""
    from combat.ext import drunken_style

    bundle = _bundle(DRUNKEN, items=AXE_ITEMS, cl=10)
    (row,) = [r for r in bundle["typed_reactions"] if r["feature_id"] == "TAL_DRUNKEN_STYLE_SWAYING_GUARD"]
    assert row["kind"] == "attacked" and row["effects"][0]["type"] == "drunken_swaying_guard"
    engine, me, foe = _fight(DRUNKEN, items=AXE_ITEMS, cl=10)
    assert drunken_style.swaying_needs_a_way(engine, me, foe, row) is False
    _use(engine, "Broken-Rhythm Strike: Fu (Short Axe)")
    assert drunken_style.swaying_needs_a_way(engine, me, foe, row) is True


# ================================================================================================================ Gravity, Dual Wielding
def test_burden_ends_on_a_successful_repeat_save_at_the_end_of_the_creatures_turn():
    """Burden: "its Speed is reduced by 10 feet ... At the end of each of its turns, it repeats the save, ending the effect on itself on a
    success." The penalties held for the whole Concentration."""
    from tests.test_auto_lane4 import _script

    engine, me, foe = _fight("tianxia.sphere.gravity", cl=10, foe_at=(8, 6))
    speed = engine._effective_speed(foe)
    _script(engine, [1])
    _use(engine, "External Weight Shift: Unwilling: Burden")
    assert engine._effective_speed(foe) == speed - 10
    assert _end_turn(engine) == AN
    _script(engine, [20])
    assert _end_turn(engine) == ME
    assert engine._effective_speed(foe) == speed and not any(c.condition_id == "condition:typed.burdened" for c in foe.conditions.values())


def test_twin_weapon_training_lines_the_compiler_already_runs_are_gone():
    """Balanced Defense's +1 AC with a qualifying pair and no shield, unarmed/natural weapons not qualifying: factory_compiler's own
    armor_class; Dual Draw (drawing two weapons) stays blocked on held items."""
    riders = _authority()["TAL_DUAL_WIELDING_TWIN_WEAPON_TRAINING"]["riders"]
    assert len(riders) == 2 and riders[1].startswith("Dual Draw")


# ================================================================================================================ Lightning
LIGHTNING = "tianxia.sphere.lightning"


def test_gather_charge_targets_you_a_willing_creature_your_weapon_or_a_space_never_an_enemy():
    """Gather Charge: "Target: Yourself, ... one weapon you are holding, one willing creature you can see, ... or one unoccupied 5-foot space";
    it was compiled as an attack on an enemy."""
    engine, me, foe = _fight(LIGHTNING, items=AXE_ITEMS, cl=10, foe_at=(8, 6))
    gathered = [c for c in engine.legal_candidates() if c.display_name.startswith("Gather Charge")]
    assert gathered and not any(AN in (c.target_ids or ()) for c in gathered)
    assert {c.display_name.split(" at ")[0] for c in gathered} == {"Gather Charge: Charge Yourself", "Gather Charge: Charge a Willing Creature",
                                                                   "Gather Charge: Charge Your Weapon", "Gather Charge: Charge a 5-foot Space"}


def test_a_charged_weapons_next_hit_can_spend_the_charge_for_pb_lightning():
    engine, me, foe = _fight(LIGHTNING, items=AXE_ITEMS, cl=10)
    _use(engine, "Gather Charge: Charge Your Weapon", target=ME)
    assert any(c.condition_id == "condition:typed.charged_weapon" for c in me.conditions.values())
    events = _use(engine, "Fu (Short Axe) attack")
    lightning = [e for e in _events(events, "DAMAGE_COMMITTED") if AN in e.target_ids and e.payload.get("damage_type") == "LIGHTNING"]
    assert lightning and lightning[0].payload["rolled_or_pending_damage"] == 4  # PB 4
    assert not any(c.condition_id == "condition:typed.charged_weapon" for c in me.conditions.values())


def test_a_charged_space_discharges_into_the_first_creature_that_enters_it():
    from tests import test_riders_lane9 as L9

    engine, me, foe = _fight(LIGHTNING, cl=10, foe_at=(8, 6))
    _use(engine, "Gather Charge: Charge a 5-foot Space", target=None, destination=(6, 6))
    hp = foe.current_hp
    L9._turn(engine, AN)
    _move(engine, AN, (6, 6))
    assert foe.current_hp == hp - 4
    assert not [z for z in engine.state.zones.values() if z.active and "TAL_LIGHTNING_GATHER_CHARGE" in z.source_definition_id]
    rider = _authority()["TAL_LIGHTNING_GATHER_CHARGE"]["riders"]
    assert not any(line.startswith(("If you Charge a weapon", "If you Charge a 5-foot space")) for line in rider)


# ================================================================================================================ Magma
MAGMA = "tianxia.sphere.magma"


def _magma(engine, kind=None):
    from combat.ext import magma_crust

    return magma_crust.patches(engine, engine.state.actors[ME], kind)


def test_magma_glob_leaves_one_patch_next_to_the_target():
    """"create one 5-foot patch of Molten Terrain adjacent to the target until the start of your next turn" / "... Obsidian Terrain ... for 1
    minute": it used to be a five-square plus of both terrains on the target itself."""
    engine, me, foe = _fight(MAGMA, cl=10, foe_at=(8, 6))
    _use(engine, "Magma Glob: Molten Terrain Patch")
    (patch,) = _magma(engine, "molten")
    assert len(patch.affected_cells) == 1 and engine.grid.distance_ft(patch.center, foe.position) == 5
    assert patch.trigger_profile["terrain"] == ["molten terrain"] and patch.duration_rounds == 1
    # combat/rules/terrain.json: Molten Terrain's save is "against the creating ability's own
    # damage", so the patch carries the Glob's listed 2d10 + key (MMX87). What it must not carry is
    # another ability's rider: Eruption Strike has its own trigger, 2 CP and once-per-turn limit.
    on_fail = [row for trig in patch.trigger_profile["triggers"] for eff in trig.get("effects") or []
               for row in (eff.get("on_fail") or [])]
    assert [row for row in on_fail if row.get("dice_by_cl")], "the patch lost the Molten Terrain save damage"
    assert not [row for row in on_fail if row.get("source_modifier")], "the patch repeated a paid rider's damage"
    # Glob grants only one expression per turn; the next patch uses a new turn.
    _end_turn(engine)
    _end_turn(engine)
    _use(engine, "Magma Glob: Obsidian Terrain Patch")
    (obsidian,) = _magma(engine, "obsidian")
    assert obsidian.duration_rounds == 10 and obsidian.trigger_profile["difficult"] == "hostile"


def test_magma_glob_heat_pressure_is_one_effect_at_a_time():
    engine, me, foe = _fight(MAGMA, cl=10, foe_at=(8, 6))
    speed = engine._effective_speed(foe)
    _use(engine, "Magma Glob: Heat Pressure")
    assert engine._effective_speed(foe) == speed - 10  # the AI's pick: the Speed cut
    _answers(engine, {"magma_heat_pressure": lambda options: ["reactions"]})
    # Test the reusable pressure replacement directly: a second Glob expression
    # in this same turn is forbidden by the printed once-per-turn limit.
    from combat.ext.magma_crust import heat_pressure
    from combat.typed_executor import Context
    action = next(a for a in engine.action_catalog.values() if a.display_name == 'Magma Glob: Heat Pressure')
    intent = ActionIntent(intent_id='pressure-replacement', decision_id='test', candidate_id='test',
                          state_version=engine.state.state_version, actor_id=ME, target_ids=(foe.entity_id,))
    heat_pressure(Context(engine, me, action, intent, action.parameters['typed'], [foe], foe), {})
    assert engine._effective_speed(foe) == speed  # replaced, not stacked
    assert any(c.condition_id == "condition:typed.reaction_denied" for c in foe.conditions.values())


def test_a_magma_patch_and_heat_pressure_survive_a_table_commit_and_reload(tmp_path):
    # Both Globs hit and the target survives the owner's current damage scaling.
    persistence, session = _persisted(tmp_path, _bundle(MAGMA, cl=10), "C13-MAGMA-11", foe_at=(8, 6))
    _submit(session, "Magma Glob: Obsidian Terrain Patch")
    for _ in range(2):  # my turn ends, then the foe's
        c = next(c for c in session.engine.legal_candidates() if c.display_name == "End turn")
        session.submit_intent(ActionIntent(intent_id=f"end-{c.state_version}", decision_id=c.decision_id, candidate_id=c.candidate_id,
                                           state_version=c.state_version, actor_id=c.actor_id, target_ids=c.target_ids),
                              primary_decision_record=None, reaction_provider=None)
    assert session.engine.state.current_actor_id == ME
    _submit(session, "Magma Glob: Heat Pressure")
    loaded = persistence.load_match(session.match_id).engine
    assert [(z.zone_id, z.center, z.duration_rounds) for z in _magma(loaded, "obsidian")] == \
        [(z.zone_id, z.center, z.duration_rounds) for z in _magma(session.engine, "obsidian")] != []
    heat = lambda engine: sorted((c.instance_id, tuple(c.data.get("modifiers") or ())) for c in engine.state.actors[AN].conditions.values()  # noqa: E731
                                 if c.condition_id == "condition:typed.heat_pressure")
    assert heat(loaded) == heat(session.engine) and heat(loaded)


def test_shape_the_crust_cools_moves_and_cracks_your_patches():
    engine, me, foe = _fight(MAGMA, cl=10, foe_at=(8, 6))
    _use(engine, "Magma Glob: Molten Terrain Patch")
    (patch,) = _magma(engine, "molten")
    at = (patch.center.x, patch.center.y)
    aims = {(c.destination.x, c.destination.y) for c in engine.legal_candidates() if c.display_name.startswith("Shape the Crust: Cool")}
    assert aims == {at}
    _use(engine, "Shape the Crust: Cool Molten Patch", target=None, destination=at)
    assert not _magma(engine, "molten") and [(z.center.x, z.center.y) for z in _magma(engine, "obsidian")] == [at]
    me.bonus_action_available = True
    _use(engine, "Shape the Crust: Crack Obsidian Patch", target=None, destination=at)
    assert not _magma(engine)
    assert not _authority()["TAL_MAGMA_SHAPE_THE_CRUST"]["riders"][0].startswith("Choose one patch")


# ================================================================================================================ Yang
def test_complete_aim_adds_a_die_to_the_kindled_creatures_attack_roll_and_spends_the_mark():
    """Kindled Responses, Complete Aim: "Trigger: the marked subject makes an attack roll ... Add 1d4 to the attack roll. At CL 11, the die
    becomes 1d6." (a split ability beside Complete Force/Breath/Resolve). The parents' rider lines for the responses that already run
    are gone."""
    from combat.gate4_engine import Gate4ControllerEngine
    from tests import test_riders_lane9 as L9

    yang = compile_character(_sheet("tianxia.sphere.yang", cl=10), actor_id=L9.ME)
    ally = compile_character(t._sheet(None, [], t.AXE_KIT), actor_id=L9.ALLY)
    foe_bundle = compile_character(t._sheet(None, [], {}), actor_id=L9.THEM)
    engine = Gate4ControllerEngine(ROOT, match_seed="C13-AIM", typed_bundles=(yang, ally, foe_bundle),
                                   roster_setup={"primary_actor_ids": [L9.ME, L9.ALLY, L9.THEM],
                                                 "team_by_actor": {L9.ME: "team:a", L9.ALLY: "team:a", L9.THEM: "team:b"},
                                                 "starting_positions": {L9.ME: {"x": 3, "y": 6}, L9.ALLY: {"x": 4, "y": 7}, L9.THEM: {"x": 5, "y": 7}}})
    L9._turn(engine, L9.ME)
    kindle = next(c for c in engine.legal_candidates() if c.display_name == "Kindle the Rising" and L9.ALLY in (c.target_ids or ()))
    engine.execute_intent(ActionIntent(intent_id="kindle", decision_id=kindle.decision_id, candidate_id=kindle.candidate_id,
                                       state_version=kindle.state_version, actor_id=L9.ME, target_ids=kindle.target_ids))
    ally_actor = engine.state.actors[L9.ALLY]
    assert any(c.condition_id == mark_condition_id("Kindled Mark", L9.ME) for c in ally_actor.conditions.values())
    L9._turn(engine, L9.ALLY)
    swing = next(c for c in engine.legal_candidates() if c.actor_id == L9.ALLY and c.display_name == "Fu (Short Axe) attack")
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id="swing", decision_id=swing.decision_id, candidate_id=swing.candidate_id,
                                       state_version=swing.state_version, actor_id=L9.ALLY, target_ids=swing.target_ids))
    events = engine.events[before:]
    # AUTO136: Complete Aim moved from the split's generic reaction to the Yang plug-in, which records
    # the printed bonus die as CHECK_ROLLED. The rule asserted here is unchanged: a 1d4 (1d6 at CL 11)
    # is rolled for the marked creature's attack and its Kindled Mark is spent.
    resolved = [e for e in events if e.event_type == "CHECK_ROLLED" and e.source_definition_id.endswith("#complete_aim")]
    assert resolved and 1 <= resolved[0].payload["total"] <= 4
    assert not any(c.condition_id == mark_condition_id("Kindled Mark", L9.ME) for c in ally_actor.conditions.values())
    mechanics = _authority()
    assert mechanics["TAL_YANG_OVERKINDLED_RESPONSES"]["riders"] == [] and mechanics["TAL_YANG_APPLYING_A_RISING_MARK"]["riders"] == []
    assert [line.split(".")[0] for line in mechanics["TAL_YANG_KINDLED_RESPONSES"]["riders"]] == ["Complete Step", "Complete Revelation"]


# ================================================================================================================ Water
WATER = "tianxia.sphere.water"


def _current(engine):
    return next(z for z in engine.state.zones.values() if z.active and "WATER_BASE_SHAPE_CURRENT" in z.source_definition_id)


def test_shape_current_forms_each_make_their_own_kind_of_area():
    """Flowing Current: "Difficult Terrain for hostile creatures"; Mist Basin: "Lightly Obscured"; Cleansing and Pressure Basins: neither.
    Every form used to be both (the whole printed text was read for one area)."""
    seen = {}
    for form in ("Flowing Current", "Mist Basin", "Cleansing Basin", "Pressure Basin"):
        engine, me, foe = _fight(WATER, cl=10, foe_at=(9, 6))
        _use(engine, f"Shape Current: {form}", target=None, destination=(6, 6))
        zone = _current(engine)
        seen[form] = (zone.trigger_profile.get("obscured") or None, zone.trigger_profile.get("difficult") or None)
    assert seen == {"Flowing Current": (None, "hostile"), "Mist Basin": ("light", None), "Cleansing Basin": (None, None),
                    "Pressure Basin": (None, None)}


def test_pressure_basin_slows_the_first_hostile_creature_to_enter_and_cleansing_basin_puts_out_your_flames():
    from tests import test_riders_lane9 as L9

    engine, me, foe = _fight(WATER, cl=10, dc=50, foe_at=(9, 6))
    _use(engine, "Shape Current: Pressure Basin", target=None, destination=(6, 6))
    speed = engine._effective_speed(foe)
    L9._turn(engine, AN)
    _move(engine, AN, (6, 6))
    assert any(m.target_field == "speed_ft" and m.value == -10 for m in foe.modifiers.values())
    engine, me, foe = _fight(WATER, cl=10, foe_at=(9, 6))
    _use(engine, "Shape Current: Cleansing Basin", target=None, destination=(3, 6))
    engine._apply_condition(me, "condition:typed.burning", "test:fire", AN, expires_on="UNTIL_REMOVED")
    assert _end_turn(engine) == AN and _end_turn(engine) == ME  # it starts its turn in the Basin
    assert not any(c.condition_id == "condition:typed.burning" for c in me.conditions.values())


def test_a_named_save_modifier_rides_a_save_only_the_zone_triggers_make():
    """Crushing Current ("fails its saving throw against your Pressure Basin") rides the Basin's enter/start save; a broad
    modifier (any technique) never reaches into zone triggers, and an ability's own save still comes first."""
    added = [{"type": "rider_menu", "id": "drowning_pressure", "options": []}]
    save = {"type": "save", "ability": "str", "on_fail": [{"type": "speed", "flat": -10}]}
    zone = [{"type": "zone", "triggers": [{"on": ["enter", "start"], "who": "hostile", "effects": [save]}]}]
    named = compiler._attach(zone, added, "failed_save", zone_saves=True)
    assert [row["type"] for row in named[0]["triggers"][0]["effects"][0]["on_fail"]] == ["speed", "rider_menu"]
    assert compiler._attach(zone, added, "failed_save") == []  # broad: no save of its own to ride, as before
    assert compiler._attach(zone, added, "hit", zone_saves=True) == []
    own = {"type": "save", "ability": "con", "on_fail": []}
    both = compiler._attach([*zone, own], added, "failed_save", zone_saves=True)
    assert both[1]["on_fail"] == added and len(both[0]["triggers"][0]["effects"][0]["on_fail"]) == 1


def test_shape_current_moves_10_feet_as_a_bonus_action_and_water_lash_lines_already_run():
    engine, me, foe = _fight(WATER, cl=10, foe_at=(9, 6))
    _use(engine, "Shape Current: Mist Basin", target=None, destination=(6, 6))
    me.bonus_action_available = True
    _use(engine, "Shape Current: move it 10 feet", target=None, destination=(6, 8))
    assert (_current(engine).center.x, _current(engine).center.y) == (6, 8)
    assert not any("GM" in line for line in _authority()["WATER_BASE_WATER_LASH"]["riders"])
    assert "WATER_BASE_WATER_LASH" in __import__("combat.ext.special_attacks", fromlist=["x"]).special_ids()


# ============================================================================================================ Wrestling (wrestling_framework.py)
WRESTLING, FOE = "tianxia.sphere.wrestling", "actor:factory.c13_foe"
GRAPPLED, HOLD = "condition:typed.grappled", "condition:typed.wrestling_hold"


def _duel(talents, cl=10, dc=16):
    """ME (Wrestling) against a compiled Factory foe that can take the Escape grapple Action."""
    Gate4ControllerEngine = t.Gate4ControllerEngine
    foe = compile_character(_sheet("tianxia.sphere.athletics", (), (), cl, dc), actor_id=FOE)
    engine = Gate4ControllerEngine(ROOT, match_seed="C13W", typed_bundles=(_bundle(WRESTLING, talents, (), cl, dc), foe),
                                   roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    t._ready(engine)
    return engine, engine.state.actors[ME], engine.state.actors[FOE]


def _grab(engine, by, held, dc=14):
    # This helper represents the physical Unarmed Strike grip in the printed
    # Grappling Reminder, not a magical condition that happens to be Grappled.
    engine._apply_condition(held, GRAPPLED, "test:grapple", by.entity_id, expires_on="UNTIL_REMOVED",
                            data={"escape_dc": dc, "reach_ft": 5, "grapple_source": "physical"})


def _act_as(engine, actor_id, name, target=None):
    actor = engine.state.actors[actor_id]
    engine.state.current_actor_id = actor_id
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    actor.action_available = actor.bonus_action_available = actor.reaction_available = True
    found = [c for c in engine.legal_candidates() if c.actor_id == actor_id and c.display_name == name
             and (target is None or target in (c.target_ids or ()))]
    assert found, f"{name!r} not legal for {actor_id}: {sorted(c.display_name for c in engine.legal_candidates() if c.actor_id == actor_id)}"
    c = found[0]
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"i-{name}-{engine.state.event_sequence}", decision_id=c.decision_id, candidate_id=c.candidate_id,
                                       state_version=c.state_version, actor_id=actor_id, target_ids=c.target_ids, destination=c.destination))
    return engine.events[before:]


def _holds(creature):
    return [c for c in creature.conditions.values() if c.condition_id == HOLD]


def test_punish_the_escape_attempt_slams_a_creature_that_fails_to_escape_for_your_reaction():
    engine, me, foe = _duel(["TAL_WRESTLING_HAMMERLOCK"])
    asked = _answers(engine, {})
    _grab(engine, me, foe, dc=60)
    events = _act_as(engine, FOE, "Escape grapple")
    assert any(e.event_type == "CHECK_ROLLED" and e.payload.get("success") is False for e in events)
    assert [r for r in asked if r["reaction_source_id"].endswith("wrestling_punish")]
    assert not me.reaction_available and [h.data.get("hold") for h in _holds(foe)] == ["hammerlock"]
    # declined: nothing happens, the Reaction is kept
    engine, me, foe = _duel(["TAL_WRESTLING_HAMMERLOCK"])
    _answers(engine, {"wrestling_punish": lambda options: None})
    _grab(engine, me, foe, dc=60)
    _act_as(engine, FOE, "Escape grapple")
    assert not _holds(foe) and me.reaction_available


def test_a_slam_ends_when_the_grapple_ends():
    engine, me, foe = _duel(["TAL_WRESTLING_HAMMERLOCK"])
    _grab(engine, me, foe)
    _act_as(engine, ME, "Apply a Slam: Hammerlock", FOE)
    assert _holds(foe)
    _act_as(engine, ME, "Release grapple")
    assert not any(c.condition_id == GRAPPLED for c in foe.conditions.values()) and not _holds(foe)


def test_an_incapacitated_grappler_lets_go():
    engine, me, foe = _duel([])
    _grab(engine, me, foe)
    engine._apply_condition(me, "condition:typed.stunned", "test:stun", FOE, expires_on="UNTIL_REMOVED")
    assert not any(c.condition_id == GRAPPLED for c in foe.conditions.values())
    engine, me, foe = _duel([])  # an unrelated condition does not
    _grab(engine, me, foe)
    engine._apply_condition(me, "condition:typed.frightened", "test:fear", FOE, expires_on="UNTIL_REMOVED")
    assert any(c.condition_id == GRAPPLED for c in foe.conditions.values())


def test_wrestling_talents_use_the_wrestling_save_dc():
    bundle = _bundle(WRESTLING, ["TAL_WRESTLING_HEEL_TACTICS"], cl=10, dc=30)
    rows = {row["display_name"]: row for row in bundle["action_catalog"]}
    grapple = rows["Grapple"]["parameters"]["typed"]["numbers"]["save_dc"]
    assert grapple == 8 + 4 + 3
    assert rows["Apply a Slam: Heel Tactics"]["parameters"]["typed"]["numbers"]["save_dc"] == grapple
    assert _authority()["WRESTLING_BASE_GRAPPLING_REMINDER"]["effects"] == []


def test_lines_that_already_run_are_no_longer_shown_to_the_gm():
    """Riders whose lines the table already runs (or that state nothing) are gone; what remains is only what is still the GM's."""
    mech = _authority()
    assert mech["TAL_YIN_YIN_SAVES"]["riders"] == []  # "your Cultivation Save DC equals your Cultivation Save DC"
    assert mech["WARLEADER_BASE_COMMAND_RESPONSES"]["riders"] == []  # the three Responses run (combat/ext/warleader_commands.py)
    # AUTO16 (Sound): Dampen Sound's last line described what its typed rows already do (Disadvantage on a
    # hearing-based Perception from outside, Advantage moving quietly inside, Proficiency Bonus off its Thunder),
    # so it is FULL now and says nothing more to the GM. It still never Silences: that is in its own typed rows.
    assert mech["TAL_SOUND_DAMPEN_SOUND"]["riders"] == [] and mech["TAL_SOUND_DAMPEN_SOUND"]["coverage"] == "FULL"
    assert mech["TAL_DEATH_LESSER_CORPSE_SERVANT_STAT_BLOCK"]["riders"] == []
    assert len(mech["TAL_DEATH_ROUSE_LESSER_DEAD"]["riders"]) == 3 and not any("appear" in r.lower() for r in mech["TAL_DEATH_ROUSE_LESSER_DEAD"]["riders"])
    assert [r for r in mech["TAL_DARK_DARKVISION"]["riders"] if r.startswith("Augment")] == mech["TAL_DARK_DARKVISION"]["riders"]
    assert len(mech["TAL_DUAL_WIELDING_TWIN_WEAPON_TRAINING"]["riders"]) == 2
    # reviewer notes about typing fixed long ago, and Daemonic Augment's "once per turn, also on non-Daemonic talents" (its modifier's
    # scope any_sphere_technique and limit once_per_turn)
    assert mech["TAL_DEATH_WITHERING_HAND"]["riders"] == [] and mech["TAL_DAEMONIC_CULTIVATION_BASE_SPHERE_ABILITIES"]["riders"] == []
    assert not any(r.startswith("Was compiling") for r in mech["TAL_DAEMONIC_CULTIVATION_DEMON_SEED"]["riders"])
    augment = mech["TAL_DAEMONIC_CULTIVATION_DAEMONIC_AUGMENT"]
    # AUTO103: Daemonic Augment is typed, but matching each chosen benefit to the actual damage, movement,
    # difficult terrain or failed save -- and applying it to older native attacks -- is still the GM's, so
    # exactly one rider remains and the ability is CORE_WITH_RIDERS, not FULL (AUTO63's own reclassification).
    assert len(augment["riders"]) == 1 and "manual resolution" in augment["riders"][0] \
        and augment["modifier"]["scope"] == "any_sphere_technique" and augment["modifier"]["limit"] == "once_per_turn"


# ============================================================================================================ Imbuement: Set Mandate (persist_augment.py)
def test_set_mandate_keeps_a_place_mandate_without_concentration_and_it_still_counts_against_mandate_load():
    c5 = importlib.import_module("tests.test_riders_c5")
    L1, engine, me, ally, foe = c5._imbuer(["clarify_and_cloud", "quicken_and_slow"])
    c5._cast_as(L1, engine, "Place Mandate: Quicken", L1.ALLY)
    quick = lambda: [m for m in ally.modifiers.values() if m.source_definition_id.endswith("mandate.imbue.quicken")]  # noqa: E731
    assert quick() and all(m.expires_on == "CONCENTRATION_END" for m in quick())
    from combat.ext.rider_support import cp_pool

    pool = cp_pool(me)
    me.resources[pool] = 5
    c5._cast_as(L1, engine, "Set Mandate: keep Place Mandate without Concentration (2 CP)", None)
    assert me.resources[pool] == 3 and me.concentration is None
    assert quick() and all(m.expires_on not in ("CONCENTRATION_END", None) for m in quick())
    # "it still counts against Mandate Load": a second Mandate on a Load of 1 ends the set one, the oldest.
    c5._cast_as(L1, engine, "Place Mandate: Clarify", L1.ALLY)
    assert not quick() and not any(c.condition_id == "condition:typed.persisted_technique" for c in me.conditions.values())
    assert _authority()["IMBUEMENT_BASE_PLACE_MANDATE"]["riders"] == []


# ============================================================================================================ Illusion: Apply Glamer's augment (persist_augment.py)
def test_a_glamer_can_be_kept_without_concentration_and_still_ends_when_its_bearer_uses_a_technique():
    engine, me, foe = _fight("tianxia.sphere.illusion", ["TAL_ILLUSION_OBSCURING_GLAMER"], cl=10)
    _use(engine, "Obscuring Glamer: Blurred", target=ME)
    glamer = lambda: [m for m in me.modifiers.values() if "OBSCURING_GLAMER" in m.source_definition_id]  # noqa: E731
    assert glamer() and me.concentration is not None
    from combat.ext.rider_support import cp_pool

    me.resources[cp_pool(me)] = 5
    _use(engine, "Glamer Augment: keep your glamer without Concentration (2 CP)", target=None)
    assert me.concentration is None and glamer() and all(m.expires_on not in ("CONCENTRATION_END", None) for m in glamer())
    assert not any(r.startswith("Augment 2 CP") for r in _authority()["TAL_ILLUSION_APPLY_GLAMER"]["riders"])
    me.action_available = True
    _use(engine, "Minor Illusion", target=None, destination=(5, 5))
    assert not glamer()  # "The effect ends early if the target ... uses a sphere talent"
