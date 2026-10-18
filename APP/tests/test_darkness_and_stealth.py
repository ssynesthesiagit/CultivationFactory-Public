"""Shaping an area with its talents, what it does to those inside, round areas, and hiding (owner 2026-09-27: "numbing
darkness isnt showing up in actions, also pure darkness and pitch black should be usable together with any of the
darknesses like numbing or hungry. also i dont see a way to do a stealth check"; "all the aoes are square and im pretty
sure a number of them are radious not square"). combat/factory_compiler.py _zone_shapes, combat/zones.py _shaped and
sync_inside, combat/stealth.py, combat/typed_executor.py in_area."""

import json
import zipfile
from pathlib import Path

from combat import stealth, zones
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate4_context import build_decision_context
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.nightshade"
QI = "resource:core.qi"


def _sheet() -> dict:
    return {**SHEET, "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.dark"], "learned_talent_record_ids": [
        "DARK_BASE_DARKNESS", "TAL_DARK_NUMBING_DARKNESS", "TAL_DARK_PURE_DARKNESS", "TAL_DARK_PITCH_BLACK", "TAL_DARK_HUNGRY_DARKNESS"]}}


def _fight(me_at=(3, 6), foe_at=(10, 6)) -> Gate4ControllerEngine:
    engine = Gate4ControllerEngine(ROOT, match_seed="DARK", typed_bundles=(compile_character(_sheet(), actor_id=ME),),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": me_at[0], "y": me_at[1]}, AN: {"x": foe_at[0], "y": foe_at[1]}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine


def _do(engine, name, at=None):
    candidate = next(c for c in engine.legal_candidates() if c.display_name.split(" at ")[0] == name
                     and (at is None or (c.destination is not None and (c.destination.x, c.destination.y) == at)))
    engine.execute_intent(ActionIntent(intent_id=name, decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids,
                                       destination=candidate.destination))


def _names(engine) -> set[str]:
    return {c.display_name.split(" at ")[0] for c in engine.legal_candidates()}


def test_each_darkness_talent_and_pitch_black_pairs_are_one_free_choice_not_dozens_of_abilities():
    bundle = compile_character(_sheet(), actor_id=ME)
    names = {row["display_name"] for row in bundle["action_catalog"]}
    assert {"Shape Darkness: Numbing Darkness", "Shape Darkness: Pure Darkness", "Shape Darkness: Hungry Darkness",
            "Shape Darkness: Pure Darkness + Numbing Darkness", "Shape Darkness: Pure Darkness + Hungry Darkness",
            "Shape Darkness: plain Darkness"} <= names
    assert not any(name.startswith("Darkness + Numbing") or name.startswith("Darkness + Hungry") for name in names)
    pair = next(row for row in bundle["action_catalog"] if row["display_name"] == "Shape Darkness: Pure Darkness + Numbing Darkness")
    assert pair["parameters"]["shape_costs"] == {QI: 1}  # Pitch Black's 1 CP
    darkness = next(row for row in bundle["action_catalog"] if row["display_name"] == "Darkness")
    assert darkness["parameters"]["typed"]["zone_spec"]["default_shape"] == ["TAL_DARK_HUNGRY_DARKNESS"]


def test_pure_and_numbing_darkness_together_weigh_on_those_inside_until_they_leave():
    engine = _fight()
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    _do(engine, "Shape Darkness: Pure Darkness + Numbing Darkness")
    qi = me.resources[QI]
    _do(engine, "Darkness", at=(10, 6))
    assert me.resources[QI] == qi - 1
    [zone] = zones.typed_zones(engine)
    assert zone.trigger_profile["talents"] == ["Pure Darkness", "Numbing Darkness"]
    effects = [c for c in foe.conditions.values() if c.condition_id == zones.ZONE_EFFECT]
    assert {c.data["name"] for c in effects} == {"Pure Darkness", "Numbing Darkness"} and zones.muffled(engine, foe)
    assert engine._roll_save(foe, "DEX", 10, "test").mode == "DISADVANTAGE"
    assert engine._roll_save(foe, "WIS", 10, "test").mode == "NORMAL"
    start, foe.position = foe.position, Position(x=18, y=6)  # out of the 15-foot radius
    zones.on_moved(engine, foe, start, foe.position)
    assert not [c for c in foe.conditions.values() if c.condition_id == zones.ZONE_EFFECT]
    assert engine._roll_save(foe, "DEX", 10, "test").mode == "NORMAL"


def test_the_effect_ends_with_the_concentration_that_holds_the_darkness():
    engine = _fight()
    _do(engine, "Shape Darkness: Numbing Darkness")
    _do(engine, "Darkness", at=(10, 6))
    foe = engine.state.actors[AN]
    assert any(c.condition_id == zones.ZONE_EFFECT for c in foe.conditions.values())
    engine._end_concentration(engine.state.actors[ME], "TEST")
    assert not zones.typed_zones(engine) and not any(c.condition_id == zones.ZONE_EFFECT for c in foe.conditions.values())


def test_a_sphere_is_round():
    engine = _fight()
    _do(engine, "Shape Darkness: plain Darkness")
    _do(engine, "Darkness", at=(12, 7))
    [zone] = zones.typed_zones(engine)
    cells = {(cell.x, cell.y) for cell in zone.affected_cells}
    assert {(15, 7), (12, 10), (14, 9), (13, 9)} <= cells  # 15 ft out along a side, 10 ft on a diagonal
    assert (15, 10) not in cells and (15, 8) not in cells  # the square's corners are outside the circle
    assert len(cells) == 29


def test_hide_only_out_of_sight_and_it_ends_with_an_attack_or_a_search():
    engine = _fight()
    assert "Hide" not in _names(engine)  # in plain view of the foe
    _do(engine, "Shape Darkness: plain Darkness")
    _do(engine, "Darkness", at=(3, 6))  # on itself: magical darkness hides it
    engine._system_start_turn()
    assert "Hide" in _names(engine)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    _do(engine, "Hide")
    iid = stealth.hidden(me)
    if iid is None:  # the check failed on this seed: hide again next turn until it lands
        for _ in range(6):
            engine._system_start_turn()
            _do(engine, "Hide")
            if stealth.hidden(me):
                break
    iid = stealth.hidden(me)
    assert iid is not None and me.conditions[iid].data["stealth_total"] >= stealth.HIDE_DC
    assert "Hide" not in _names(engine)
    assert stealth.search(engine, foe, 40, "test") == [ME]  # a +40 Perception finds it, even with Disadvantage
    assert stealth.hidden(me) is None


def test_stepping_into_plain_view_ends_hiding():
    engine = _fight()
    me = engine.state.actors[ME]
    engine._apply_condition(me, stealth.HIDDEN, "test", ME, expires_on="UNTIL_REMOVED", data={"stealth_total": 20})
    zones.on_moved(engine, me, me.position, me.position)
    assert stealth.hidden(me) is None  # nothing hides it from the foe


def test_the_built_in_ai_is_not_offered_hiding_or_shaping_but_a_player_is():
    from combat.gate4_policy import PolicyLibrary

    engine = _fight()
    _do(engine, "Shape Darkness: plain Darkness")
    _do(engine, "Darkness", at=(3, 6))
    engine._system_start_turn()
    policy, _ = PolicyLibrary(ROOT).for_actor(ME)
    names = lambda context: {row.display_name.split(" at ")[0] for row in context.legal_candidates}  # noqa: E731
    ai = build_decision_context(engine, policy, for_ai=True)
    player = build_decision_context(engine, policy, include_item_actions=True)
    assert "Hide" in names(player) and "Shape Darkness: Numbing Darkness" in names(player)
    assert not {"Hide", "Search"} & names(ai) and not any(name.startswith("Shape ") for name in names(ai))


def test_hide_in_darkness_hides_in_your_own_darkness_and_moving_inside_it_keeps_you_hidden():
    sheet = _sheet()
    sheet["spheres_and_talents"]["learned_talent_record_ids"].append("TAL_DARK_HIDE_IN_DARKNESS")
    bundle = compile_character(sheet, actor_id=ME)
    hide = next(row for row in bundle["action_catalog"] if row["display_name"] == "Hide")
    assert hide["parameters"]["hide_inside"] == "Darkness"
    engine = _fight()
    me = engine.state.actors[ME]
    _do(engine, "Shape Darkness: plain Darkness")
    _do(engine, "Darkness", at=(3, 6))
    assert stealth.can_hide(engine, me, "Darkness") and stealth.in_own_area(engine, me, "Darkness")
    engine._apply_condition(me, stealth.HIDDEN, "test", ME, expires_on="UNTIL_REMOVED", data={"stealth_total": 20, "inside": "Darkness"})
    start, me.position = me.position, Position(x=4, y=6)
    zones.on_moved(engine, me, start, me.position)
    assert stealth.hidden(me) is not None


def _augmented_fight():
    from combat.gate4_engine import Gate4ControllerEngine as Engine

    sheet = _sheet()
    sheet["spheres_and_talents"]["learned_talent_record_ids"] += ["TAL_DARK_GREATER_DARKNESS", "TAL_DARK_PERSISTENT_DARKNESS"]
    engine = Engine(ROOT, match_seed="AUG", typed_bundles=(compile_character(sheet, actor_id=ME),),
                    roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                  "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 10, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine


def test_any_number_of_augments_on_one_use_each_paid_and_only_the_chosen_combination_is_offered():
    engine = _augmented_fight()
    me = engine.state.actors[ME]
    # Not chosen yet: the ability and each single augment, as before.
    assert {"Darkness", "Darkness + Greater Darkness", "Darkness + Persistent Darkness"} <= _names(engine)
    assert "Darkness + Greater Darkness + Persistent Darkness" not in _names(engine)
    _do(engine, "Augment Darkness: Greater Darkness")
    _do(engine, "Augment Darkness: Persistent Darkness")
    names = _names(engine)
    assert "Darkness + Greater Darkness + Persistent Darkness" in names
    assert not {"Darkness", "Darkness + Greater Darkness", "Darkness + Persistent Darkness"} & names
    _do(engine, "Shape Darkness: plain Darkness")
    qi = me.resources[QI]
    _do(engine, "Darkness + Greater Darkness + Persistent Darkness", at=(10, 6))
    assert me.resources[QI] == qi - 3  # 1 + 2 CP
    [zone] = zones.typed_zones(engine)
    assert zone.radius_cells == 6 and not zone.concentration_link and me.concentration is None  # 30 ft; no Concentration
    _do(engine, "Augment Darkness: no augments (clears all of them)")
    engine._system_start_turn()  # its Action was spent on the Darkness
    assert "Darkness" in _names(engine) and "Darkness + Greater Darkness" not in _names(engine)


def test_clearsight_keeps_its_own_darkness_talents_off_the_caster_but_not_off_a_foe():
    from combat.gate4_engine import Gate4ControllerEngine as Engine

    sheet = _sheet()
    sheet["spheres_and_talents"]["learned_talent_record_ids"] += ["TAL_DARK_CLEARSIGHT"]
    bundle = compile_character(sheet, actor_id=ME)
    assert bundle["clearsight"] == ["Darkness"]
    engine = Engine(ROOT, match_seed="CLEAR", typed_bundles=(bundle,),
                    roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                  "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 5, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    _do(engine, "Shape Darkness: Pure Darkness + Numbing Darkness")
    _do(engine, "Darkness", at=(4, 6))  # both of them inside
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    assert not any(c.condition_id == zones.ZONE_EFFECT for c in me.conditions.values())
    assert {c.data["name"] for c in foe.conditions.values() if c.condition_id == zones.ZONE_EFFECT} == {"Pure Darkness", "Numbing Darkness"}


# --------------------------------------------------------------------------- Clearsight at the table (owner playtest round 24)
DARKNESS_KIT = ["DARK_BASE_DARKNESS", "TAL_DARK_PURE_DARKNESS", "TAL_DARK_HUNGRY_DARKNESS", "TAL_DARK_PITCH_BLACK",
                "TAL_DARK_GREATER_DARKNESS", "TAL_DARK_PERSISTENT_DARKNESS"]
MELD_SOURCE = "TAL_DARK_MELD"  # the source a table-granted Meld is filed under (its Concentration is held on the same one)


def _install(root, project, sheet):
    """The portable character sheet a factory match is built from."""
    folder = root / "portable_characters" / project
    folder.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(folder / "current.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet))


def _darkness_at_the_table(tmp_path, *, clearsight, running_meld, meld_concentration=False):
    """A real table fight: Tabik Damu's Darkness shaped as Pure Darkness + Hungry Darkness and cast over himself.
    ``clearsight`` compiles the character with the talent; leaving it out reproduces a fight made before the talent
    was recorded, the state the owner's fight was in (his Clearsight manual was handed over at the table). A stale
    bundle compiles no Meld action at all, so the Meld is granted the way a table manual is: through the same effect
    the Meld action runs. ``meld_concentration`` makes it the Concentration Meld (also held, combat/concentration.py)
    rather than the Persistent one (2 CP, no Concentration)."""
    from combat.ext import docket_senses
    from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX

    actor, foe = FACTORY_ACTOR_PREFIX + "tabik", FACTORY_ACTOR_PREFIX + "foe"
    learned = DARKNESS_KIT + (["TAL_DARK_CLEARSIGHT"] if clearsight else [])
    sheet = {**SHEET, "identity": {**SHEET["identity"], "name": "Tabik Damu"},
             "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.dark"], "learned_talent_record_ids": learned}}
    _install(tmp_path, "tabik", sheet)
    _install(tmp_path, "foe", SHEET)
    combat = CombatService(ROOT, tmp_path)
    mid = combat.create_factory_match(project_ids=["tabik"], opponent_actor_ids=[foe], match_seed="MMX84")["match_id"]
    session = combat._load_session(mid)  # the live table session; a commit must go through it, not a throwaway engine
    engine = session.engine
    if running_meld:  # the Meld the table is running (pre-fight pick, in-fight cast or a table manual)
        docket_senses.meld_set(type("Grant", (), {"engine": engine, "actor": engine.state.actors[actor],
                                                  "source": MELD_SOURCE})(),
                               {"talent": "TAL_DARK_CLEARSIGHT", "name": "Clearsight", "concentration": meld_concentration})
        if meld_concentration:  # a Concentration Meld is held as well as stored
            engine._start_concentration(engine.state.actors[actor], MELD_SOURCE)
    engine.state.current_slot_index = engine.state.initiative_order.index(actor)
    engine.state.current_actor_id = actor
    engine._system_start_turn()
    engine.state.actors[actor].position = Position(x=3, y=6)  # keep the two creatures in distinct legal cells
    engine.state.actors[foe].position = Position(x=4, y=5)  # the opponent stands in the area he is about to make

    def cast(name, at=None):
        candidate = next(c for c in engine.legal_candidates() if c.display_name.split(" at ")[0] == name
                         and (at is None or (c.destination is not None and (c.destination.x, c.destination.y) == at)))
        engine.execute_intent(ActionIntent(intent_id=name, decision_id=candidate.decision_id,
                                           candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                           actor_id=actor, target_ids=candidate.target_ids,
                                           destination=candidate.destination))

    cast("Augment Darkness: Greater Darkness")
    cast("Augment Darkness: Persistent Darkness")
    cast("Shape Darkness: Pure Darkness + Hungry Darkness")
    cast("Darkness + Greater Darkness + Persistent Darkness", at=(4, 6))  # he is inside his own Darkness
    # The live session holds the area; storage sees it after the table commit below.
    return combat, mid, actor, foe, engine, session


def _inside_readings(engine, actor_id):
    return sorted(str(c.data.get("reading") or c.data.get("name")) for c in engine.state.actors[actor_id].conditions.values()
                  if c.condition_id == zones.ZONE_EFFECT)


def _darkness_zone(engine):
    """The Darkness he made, not the battlefield terrain the table also carries."""
    return next(zone for zone in zones.typed_zones(engine) if zone.source_definition_id != "system:battlefield.terrain")


def test_clearsight_leaves_the_caster_untouched_even_in_a_fight_compiled_before_the_talent(tmp_path):
    """Owner playtest round 24: "Tabik Damu is inside Pure Darkness: Wisdom (Perception) checks relying on hearing
    have Disadvantage" while Meld: Clearsight was active. The immunity used to be decided by a display-name list
    compiled into the fight's bundle, so a fight made before the talent was recorded silently lost it while the
    table still showed the Meld as running."""
    from combat.gate5_service import CombatService

    combat, mid, actor, foe, engine, session = _darkness_at_the_table(tmp_path, clearsight=False, running_meld=True)
    assert _inside_readings(engine, actor) == []  # his own Darkness talents do not touch him
    assert [row for row in _inside_readings(engine, foe) if "hearing" in row] == [
        "Wisdom (Perception) checks relying on hearing have Disadvantage."]  # the foe still gets it

    session.mechanical.explicit_snapshot()  # a normal table commit
    fresh = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert _darkness_zone(fresh).active  # the fight that comes back still has the area, so the empty rows mean something
    assert _inside_readings(fresh, actor) == []
    assert [row for row in _inside_readings(fresh, foe) if "hearing" in row] == [
        "Wisdom (Perception) checks relying on hearing have Disadvantage."]


def test_clearsight_also_spares_the_caster_the_hungry_darkness_saving_throw_damage(tmp_path):
    """Hungry Darkness reaches a creature through the area's start-of-turn trigger, not the inside rows, and the
    caster must be spared that too (a fight compiled with the talent, the ordinary case)."""
    combat, mid, actor, _foe, engine, _session = _darkness_at_the_table(tmp_path, clearsight=True, running_meld=True)
    hp = engine.state.actors[actor].current_hp
    engine._system_start_turn()  # he starts a turn inside his own Pure Darkness
    assert engine.state.actors[actor].current_hp == hp  # "Take Necrotic damage equal to your Cultivation Level"
    assert _inside_readings(engine, actor) == []


def test_without_clearsight_the_caster_still_takes_its_own_darkness_talents(tmp_path):
    """The negative control: immunity belongs to Clearsight, not to making a Darkness."""
    combat, mid, actor, _foe, engine, _session = _darkness_at_the_table(tmp_path, clearsight=False, running_meld=False)
    assert [row for row in _inside_readings(engine, actor) if "hearing" in row] == [
        "Wisdom (Perception) checks relying on hearing have Disadvantage."]


def test_a_stale_bundle_loses_clearsight_when_its_concentration_meld_ends(tmp_path):
    """MMX84 review, P1: a Meld is stored until it is removed, so a fight compiled before the character learned
    Clearsight found the immunity on a stored row and kept it after the Meld's Concentration ended -- dropped, or
    broken by damage. The immunity has to follow the Meld that is actually running, and the fight has to agree after
    a table commit and reload, not only in the session that decided it."""
    from combat.gate5_service import CombatService

    combat, mid, actor, foe, engine, session = _darkness_at_the_table(tmp_path, clearsight=False, running_meld=True, meld_concentration=True)
    me = engine.state.actors[actor]
    assert me.concentration is not None and me.concentration.source_definition_id == MELD_SOURCE
    assert _inside_readings(engine, actor) == []  # while he holds the Meld's Concentration his own Darkness leaves him be
    assert [row for row in _inside_readings(engine, foe) if "hearing" in row] == [
        "Wisdom (Perception) checks relying on hearing have Disadvantage."]

    engine._end_concentration(me, "TEST")  # he drops the Meld; the stored row is still on him
    zones.sync_inside(engine, _darkness_zone(engine).source_definition_id)
    assert me.concentration is None
    assert [row for row in _inside_readings(engine, actor) if "hearing" in row] == [
        "Wisdom (Perception) checks relying on hearing have Disadvantage."]  # now it reaches him

    session.mechanical.explicit_snapshot()  # a normal table commit
    fresh = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert _darkness_zone(fresh).active  # the area is retained, so the rows below are about the live fight
    assert [row for row in _inside_readings(fresh, actor) if "hearing" in row] == [
        "Wisdom (Perception) checks relying on hearing have Disadvantage."]  # the reloaded fight agrees
    zones.sync_inside(fresh, _darkness_zone(fresh).source_definition_id)  # ... and so does the retained area
    assert [row for row in _inside_readings(fresh, actor) if "hearing" in row] == [
        "Wisdom (Perception) checks relying on hearing have Disadvantage."]


def test_a_persistent_meld_keeps_clearsight_through_the_end_of_a_concentration(tmp_path):
    """The positive control for the one above: a Persistent Meld is not a Concentration Meld ("2 CP, no
    Concentration"), so a Concentration ending must not take its immunity with it. Without this the fix could pass by
    refusing every stale-bundle immunity."""
    from combat.gate5_service import CombatService

    combat, mid, actor, _foe, engine, session = _darkness_at_the_table(tmp_path, clearsight=False, running_meld=True, meld_concentration=False)
    me = engine.state.actors[actor]
    engine._start_concentration(me, "test:an.unrelated.technique")  # something else he is concentrating on
    engine._end_concentration(me, "TEST")
    zones.sync_inside(engine, _darkness_zone(engine).source_definition_id)
    assert _inside_readings(engine, actor) == []  # the stored Meld is still running, so it still protects him
    session.mechanical.explicit_snapshot()
    fresh = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert _darkness_zone(fresh).active
    assert _inside_readings(fresh, actor) == []  # and the reloaded fight agrees
