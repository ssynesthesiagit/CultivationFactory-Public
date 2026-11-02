"""Shi Xunyun's automation pass (owner 2026-09-28, "automate every aspect before another playtest"):

  Pressure Points -- Precision Contact and Touch the Point were base sphere abilities never captured by the
  typed mechanics authority (see combat/ext/shi_pressure_points.py's docstring); this rebuilds the loop
  directly: a qualifying melee hit applies the picked Point talent and marks the target, and a later hit on
  an already-marked target closes the picked Seal talent instead.
  Karma Knot Root -- Generate Karmic Due (combat/ext/shi_karma.py) had no mechanism at all; Knot Judgment
  already worked once the Due exists to spend. Red Cord Guard's typing dropped the actual damage reduction
  (only the resource spend was typed); Flash Reveal's typing target was right but its effects were empty.

Built like tests/test_iron_fist.py and tests/test_reaction_effects.py (Gate4ControllerEngine fixture,
tests/test_zones.SHEET's abilities/statistics, direct typed_reactions.on_damage for a reaction check)."""

from pathlib import Path

import pytest

from combat import typed_executor, typed_reactions
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.shi"

PRESSURE_POINTS_TALENTS = [
    "PRESSURE_POINTS_BASE_PRESSURE_POINTS_TRAINING", "PRESSURE_POINTS_BASE_NUMBING_POINT", "PRESSURE_POINTS_BASE_READING_TOUCH",
    "tianxia.talent.pressure_points.grip_severing_point", "tianxia.talent.pressure_points.breath_seal",
]
FOUNDATION = {"foundation_id": "karma_knot_root_v0_2B", "stage": "Awakened",
              "resource": {"name": "Karmic Due", "resource_id": "foundation.resource.karma_knot_root_v0_2B", "maximum": 1, "current": 0}}
DAO = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.dao"}]}}


def _bundle(talents, *, sphere="tianxia.sphere.pressure_points", foundation=None, equipment=(DAO,)):
    sheet = {**SHEET, "equipment": list(equipment), "spheres_and_talents": {"sphere_record_ids": [sphere], "learned_talent_record_ids": talents}}
    if foundation:
        sheet = {**sheet, "foundation": foundation}
    return compile_character(sheet, actor_id=ME)


def _engine(bundle, foe_at=(4, 6)):
    engine = Gate4ControllerEngine(ROOT, match_seed="SHI", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": foe_at[0], "y": foe_at[1]}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine


def _hit_with(engine, name_prefix, *, attempts=10):
    """Attack with the named action until one lands (the dice decide, tests/test_iron_fist.py's pattern);
    returns True once it does."""
    me = engine.state.actors[ME]
    for attempt in range(attempts):
        strike = next((c for c in engine.legal_candidates() if c.display_name.startswith(name_prefix)), None)
        assert strike is not None, f"{name_prefix!r} should be a legal candidate"
        before = len([e for e in engine.events if e.event_type == "DAMAGE_COMMITTED"])
        engine.execute_intent(ActionIntent(intent_id=f"hit{attempt}", decision_id=strike.decision_id, candidate_id=strike.candidate_id,
                                           state_version=strike.state_version, actor_id=ME, target_ids=strike.target_ids))
        if len([e for e in engine.events if e.event_type == "DAMAGE_COMMITTED"]) > before:
            return True
        engine.state.current_actor_id = ME
        me.action_available = True
    return False


def _hit_with_dao(engine, *, attempts=10):
    return _hit_with(engine, "Dao ", attempts=attempts)


def test_touch_the_point_applies_a_point_then_closes_a_seal_on_a_later_hit():
    engine = _engine(_bundle(PRESSURE_POINTS_TALENTS))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    assert _hit_with_dao(engine)
    assert typed_executor.bears_mark(foe, ME, "Pressure Point")
    assert any(e.event_type == "GM_RIDER" and "Touch the Point: Apply a Point (Numbing Point (Numb Arm))" in str((e.payload or {}).get("rider"))
              for e in engine.events)
    # "Once per turn": a second hit the same turn does not touch the point again.
    riders_before = sum(1 for e in engine.events if e.event_type == "GM_RIDER" and "Touch the Point" in str((e.payload or {}).get("rider")))
    me.action_available = True
    if _hit_with_dao(engine):
        riders_after = sum(1 for e in engine.events if e.event_type == "GM_RIDER" and "Touch the Point" in str((e.payload or {}).get("rider")))
        assert riders_after == riders_before
    # A new turn, hitting an already-marked target: Close a Seal instead, and the mark comes off.
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    me.action_available = True
    assert _hit_with_dao(engine)
    assert not typed_executor.bears_mark(foe, ME, "Pressure Point")
    assert any(e.event_type == "GM_RIDER" and "Touch the Point: Close a Seal (Breath Seal)" in str((e.payload or {}).get("rider"))
              for e in engine.events)


def test_touch_the_point_toggles_change_the_picked_point_and_seal():
    bundle = _bundle(PRESSURE_POINTS_TALENTS)
    names = {row["display_name"] for row in bundle["action_catalog"]}
    assert "Touch the Point: Numbing Point (Numb Arm)" in names
    assert "Touch the Point: Grip-Severing Point" in names
    assert "Touch the Point: Breath Seal" in names
    engine = _engine(bundle)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    pick = next(c for c in engine.legal_candidates() if c.display_name == "Touch the Point: Grip-Severing Point")
    engine.execute_intent(ActionIntent(intent_id="pick", decision_id=pick.decision_id, candidate_id=pick.candidate_id,
                                       state_version=pick.state_version, actor_id=ME, target_ids=pick.target_ids))
    me.action_available = True
    assert _hit_with_dao(engine)
    assert any(e.event_type == "GM_RIDER" and "Touch the Point: Apply a Point (Grip-Severing Point)" in str((e.payload or {}).get("rider"))
              for e in engine.events)


def test_generate_karmic_due_gains_once_a_round_and_fades_after_your_next_turn():
    from combat import ext

    engine = _engine(_bundle(["foundation.karma_knot_root_v0_2B.karmic_root_reserve"], sphere="tianxia.sphere.pressure_points",
                             foundation=FOUNDATION))
    me = engine.state.actors[ME]
    resource = "resource:foundation.karmic_due"
    assert me.resources.get(resource, 0) == 0
    # The foe damaged Shi since the end of her last turn: Generate Karmic Due can now fire on her next hit.
    engine._commit_damage(me, 5, "SLASHING", "TEST:foe_hit", AN, None, reaction_depth=0)
    assert _hit_with_dao(engine)
    assert me.resources.get(resource, 0) == 1
    # "Once per round": a second hit the same round does not generate a second Due (the maximum is 1 anyway,
    # but the round cap is its own printed limit).
    me.action_available = True
    _hit_with_dao(engine)
    assert me.resources.get(resource, 0) == 1
    # "It fades at the end of your next turn": unspent, it is gone after two of Shi's own turn-ends pass.
    ext.run("turn_end", engine, me)
    assert me.resources.get(resource, 0) == 1
    ext.run("turn_end", engine, me)
    assert me.resources.get(resource, 0) == 0


def test_generate_karmic_due_feeds_knot_judgment_on_a_lightning_lash_hit():
    engine = _engine(_bundle(["foundation.karma_knot_root_v0_2B.karmic_root_reserve", "TAL_LIGHTNING_GATHER_CHARGE",
                             "TAL_LIGHTNING_LIGHTNING_LASH"], sphere="tianxia.sphere.lightning", foundation=FOUNDATION, equipment=()))
    me = engine.state.actors[ME]
    resource = "resource:foundation.karmic_due"
    engine._gain_resource(me, resource, 1, "TEST")
    assert _hit_with(engine, "Lightning Lash: Jolt")
    assert me.resources.get(resource, 0) == 0  # Knot Judgment (not optional) spent the pre-existing Due
    assert any(event.event_type == "RESOURCE_SPENT" and (event.payload or {}).get("resource_id") == resource for event in engine.events)
    damages = [(event.payload or {}).get("hp_damage") for event in engine.events if event.event_type == "DAMAGE_COMMITTED"]
    assert 4 in damages  # PB(4) added "after it resolves" (Knot Judgment's own follow-up damage event)


def test_red_cord_guard_reduces_damage_by_pb_plus_key_ability_modifier():
    engine = _engine(_bundle([], sphere="tianxia.sphere.pressure_points", foundation=FOUNDATION), foe_at=(4, 6))
    me = engine.state.actors[ME]
    engine._gain_resource(me, "resource:foundation.karmic_due", 1, "TEST")
    me.reaction_available = True
    reduced = typed_reactions.on_damage(engine, me, 20, 0, source_definition_id="action:test.attack", source_actor_id=AN)
    pb, key_mod = 4, 2  # tests/test_zones.SHEET: PB 4, every ability score 14 (+2)
    assert reduced == 20 - (pb + key_mod)
    assert me.resources.get("resource:foundation.karmic_due", 0) == 0
    resolved = [e for e in engine.events if e.source_definition_id == "foundation.karma_knot_root_v0_2B.red_cord_guard"
               and e.event_type == "REACTION_RESOLVED"]
    assert resolved


def test_flash_reveal_grants_advantage_against_the_target_on_lightning_lash_and_conductive_strike():
    bundle = _bundle(["TAL_LIGHTNING_LIGHTNING_LASH", "TAL_LIGHTNING_FLASH_REVEAL", "TAL_LIGHTNING_CONDUCTIVE_STRIKE"],
                     sphere="tianxia.sphere.lightning", equipment=())
    flash_reveal = next(row for row in bundle["modifiers"] if row["name"] == "Flash Reveal")
    assert flash_reveal["status"] == "applied"
    # Charge-worker 2026-09-28: Lightning Lash gained a fourth "Charge" option (its base rider previously
    # compiled to no option at all, dropping the mark it should place); Flash Reveal's own text ("When you
    # hit a creature with Lightning Lash or Conductive Strike...") is not limited to specific riders, so it
    # correctly rides that option too.
    assert set(flash_reveal["applied"]) == {"Lightning Lash: Charge", "Lightning Lash: Jolt", "Lightning Lash: Flash", "Lightning Lash: Arc"}
    action = next(row for row in bundle["action_catalog"] if row["display_name"] == "Lightning Lash: Flash")
    effects = action["parameters"]["typed"]["effects"][0]["on_hit"]
    assert any(effect.get("type") == "advantage" and effect.get("applies_to") == "attacker" for effect in effects)


def _second_hostile(engine, foe, *, dx=1, dy=0):
    """A second hostile creature dx/dy squares from the first one, for Nine-Needle Cascade's
    "one additional creature within 10 feet of the target"."""
    other = foe.model_copy(deep=True)
    other.entity_id = 'actor:shi.second'
    other.display_name = 'Second Hostile'
    other.position = foe.position.model_copy(update={'x': foe.position.x + dx, 'y': foe.position.y + dy})
    other.conditions = {}
    engine.state.actors[other.entity_id] = other
    return other


def _cascade_bundle(save_dc=50):
    """A high technique_save_dc so the second creature's printed "Failed Save" branch is the one that runs."""
    sheet = {**SHEET, "ability_scores_and_statistics": {**SHEET["ability_scores_and_statistics"],
                                                       "technique_save_dc": save_dc}}
    return compile_character({**sheet, "equipment": [DAO],
                              "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.pressure_points"],
                                                      "learned_talent_record_ids": [
                                                          "PRESSURE_POINTS_BASE_PRESSURE_POINTS_TRAINING",
                                                          "PRESSURE_POINTS_BASE_NUMBING_POINT",
                                                          "tianxia.talent.pressure_points.nine_needle_cascade"]}},
                              actor_id=ME)


def _pick_cascade(engine, me):
    """Nine-Needle Cascade is an owned Point, so the character picks it in Touch the Point's selector."""
    pick = next(c for c in engine.legal_candidates() if c.display_name == "Touch the Point: Nine-Needle Cascade")
    engine.execute_intent(ActionIntent(intent_id='choose', decision_id=pick.decision_id,
                                       candidate_id=pick.candidate_id, state_version=pick.state_version,
                                       actor_id=me.entity_id, target_ids=pick.target_ids))


@pytest.mark.parametrize('dx,dy,offered', [(1, 0, True), (6, 6, False)])
def test_nine_needle_cascade_offers_a_second_creature_only_within_ten_feet_of_the_first(dx, dy, offered):
    """Nine-Needle Cascade: "Choose one additional creature within 10 feet of the target ...
    Failed Save: Apply Numbing Point to the second creature."  Further away the printed clause offers no
    second creature, so it makes no save and is untouched."""
    engine = _engine(_cascade_bundle())
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    second = _second_hostile(engine, foe, dx=dx, dy=dy)
    _pick_cascade(engine, me)
    engine._typed_roll_outcome = {second.entity_id: "failure"}
    me.action_available = True
    assert _hit_with_dao(engine)
    assert typed_executor.bears_mark(second, ME, "Pressure Point") is offered
    assert any(m.target_field == "attack_mode" and m.value == "DISADVANTAGE"
               for m in second.modifiers.values()) is offered


@pytest.mark.parametrize('outcome,marked', [("failure", True), ("success", False)])
def test_nine_needle_cascade_resolves_the_second_creatures_own_save(outcome, marked):
    """The second creature saves for itself: failed -> Numbing Point, successful -> "No effect"."""
    engine = _engine(_cascade_bundle())
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    second = _second_hostile(engine, foe, dx=1, dy=0)
    _pick_cascade(engine, me)
    engine._typed_roll_outcome = {second.entity_id: outcome}
    me.action_available = True
    assert _hit_with_dao(engine)
    assert typed_executor.bears_mark(foe, ME, "Pressure Point")
    assert typed_executor.bears_mark(second, ME, "Pressure Point") is marked
    assert any(m.target_field == "attack_mode" and m.value == "DISADVANTAGE"
               for m in second.modifiers.values()) is marked
