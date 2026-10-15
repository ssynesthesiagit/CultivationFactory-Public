"""Forged Techniques and treasure weapon enchantments (forged-worker 2026-09-29, wave 4: "make sure all the talents
and class abilities and foundations and methods and everything is applied" -- the two per-character systems every
Quick Build character carries).

Exhaustion (combat/ext/forged_exhaustion.py): before this, a Forged Technique's Exhausting Drawback ("gives 1 level
of Exhaustion after the technique resolves", PHB ch. 18) was a GM-only line and the table had no Exhaustion at all
(combat/rules/typed_conditions.json's Choke Hold note said so explicitly). The Sphere Compendium's own "Use the 2024
meanings of ... Exhaustion ... unless this sphere explicitly replaces or expands a rule" (repeated on dozens of
spheres) is Tianxia's printed rule: -1 to every d20 Test per level, -5 ft Speed per level, dead at 6.

Forged Counters (combat/forged.py as_reaction): ~12 of the 13 live Counter Forged Techniques were silently skipped
(the "reaction" gate wrongly required the PRIMARY talent's own economy to already be "reaction", when a Counter's
whole point is to turn any known ability into one).

Treasure enchantments (combat/factory_compiler.py _enchantment_on_hit): Moonless-Yin's no-healing rider, Frost-
Meridian's Speed rider, and Dream-Piercing's condition-gated bonus damage were GM-only lines on every hit; several
non-hit enchantments (Balanced-Grip and similar) were dropped with no GM line at all."""

from pathlib import Path

from combat import forged
from combat.ext import forged_exhaustion
from combat.factory_compiler import _enchantment_on_hit, compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.forged"


def _engine():
    bundle = compile_character({**SHEET, "equipment": [], "spheres_and_talents": {"sphere_record_ids": [], "learned_talent_record_ids": []}},
                               actor_id=ME)
    engine = Gate4ControllerEngine(ROOT, match_seed="FORGED", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine


# ------------------------------------------------------------------ Exhaustion


def test_exhaustion_levels_reduce_speed_and_reach_six_kills():
    engine = _engine()
    me = engine.state.actors[ME]
    base_speed = engine._effective_speed(me)
    forged_exhaustion.add(engine, me, 1, "test:exhaustion")
    assert forged_exhaustion.level(me) == 1
    assert engine._effective_speed(me) == base_speed - 5
    forged_exhaustion.add(engine, me, 2, "test:exhaustion")  # 3 total
    assert forged_exhaustion.level(me) == 3
    assert engine._effective_speed(me) == base_speed - 15
    assert me.active
    forged_exhaustion.add(engine, me, 3, "test:exhaustion")  # 6 total: dead
    assert forged_exhaustion.level(me) == 6
    assert not me.active


def test_exhaustion_never_exceeds_six_or_goes_negative():
    engine = _engine()
    me = engine.state.actors[ME]
    forged_exhaustion.add(engine, me, 9, "test:exhaustion")
    assert forged_exhaustion.level(me) == 6
    assert not me.active


def test_exhaustion_penalizes_attacks_saves_and_checks_via_the_ext_hooks():
    from combat import ext

    engine = _engine()
    me = engine.state.actors[ME]
    assert ext.run("attack_bonus", None, me) == []  # no Exhaustion yet: no penalty offered
    forged_exhaustion.add(engine, me, 2, "test:exhaustion")  # 2024: a d20 Test is reduced by 2 x the level
    assert ext.run("attack_bonus", None, me) == [-4]
    assert ext.run("check_bonus", None, me) == [-4]
    assert ext.run("save", None, me, "CON", set()) == [{"bonus": -4}]


# ------------------------------------------------------------------ combat/forged.py mechanism


_FAKE_PRIMARY_DAMAGE = {
    "mechanic_id": "talent:fake.primary_damage", "name": "Fake Strike", "sphere_id": "tianxia.sphere.fake",
    "activation": {"economy": "action", "trigger": None},
    "effects": [{"type": "attack", "attack_kind": "weapon", "on_hit": [{"type": "damage", "weapon_damage": True}]}],
    "duration": {"kind": "instant"}, "range": {"kind": "feet", "feet": 5},
}


def test_exhausting_drawback_adds_a_real_exhaustion_effect_not_only_a_rider():
    technique = {"technique_id": "forged:test.exhausting", "name": "Test Exhausting Strike",
                "primary_sphere_effect": {"talent_id": "talent:fake.primary_damage"},
                "base_form": {"form_id": "strike"}, "drawbacks": [{"drawback_id": "exhausting", "display_name": "Exhausting"}],
                "augments": [], "cp_cost": {"final": 1}, "action_type": "action"}
    mechanic = forged.mechanic_for(technique, {"talent:fake.primary_damage": _FAKE_PRIMARY_DAMAGE})
    assert mechanic is not None
    kinds = [effect.get("type") for effect in mechanic["effects"]]
    assert "exhaustion" in kinds, "the Exhausting Drawback must add a real effect, not just a rider"
    assert not any("Exhausting" in str(r) for r in mechanic["riders"]), "Exhausting must not also duplicate as a GM rider"


_FAKE_PRIMARY_PASSIVE_TRIGGER = {
    "mechanic_id": "talent:fake.passive_trigger", "name": "Fake Passive", "sphere_id": "tianxia.sphere.fake",
    # Break Defenses' own shape (Brute sphere): a passive with a printed trigger sentence, not a Reaction.
    "activation": {"economy": "passive", "trigger": "Whenever you successfully shove a creature"},
    "effects": [{"type": "condition", "condition": "prone", "applies_to": "target"}],
    "duration": {"kind": "instant"}, "range": {"kind": "feet", "feet": 5},
}


def test_a_counter_borrows_a_passive_primarys_own_printed_trigger():
    """The bug this closes: as_reaction used to require the PRIMARY's own economy to already be "reaction", so a
    Counter built around a passive talent's own trigger sentence (Gu's Brute-Gravity Counter/Berserker-Sand Counter)
    was always skipped, whatever its printed trigger said."""
    technique = {"technique_id": "forged:test.counter", "name": "Test Counter", "trigger": None,
                "primary_sphere_effect": {"talent_id": "talent:fake.passive_trigger"},
                "base_form": {"form_id": "counter"}, "drawbacks": [], "augments": [], "cp_cost": {"final": 3}, "action_type": "reaction"}
    mechanics = {"talent:fake.passive_trigger": _FAKE_PRIMARY_PASSIVE_TRIGGER}
    mechanic = forged.mechanic_for(technique, mechanics)
    assert mechanic is not None
    reaction = forged.as_reaction(technique, mechanic, mechanics)
    assert reaction is not None, "a Counter must borrow its primary's own printed trigger even when the primary is not itself a Reaction"
    assert reaction["activation"]["trigger"] == "Whenever you successfully shove a creature"
    assert reaction["activation"]["economy"] == "reaction"


def test_a_counter_with_no_known_trigger_anywhere_stays_unbuilt():
    technique = {"technique_id": "forged:test.counter_blind", "name": "Test Blind Counter", "trigger": None,
                "primary_sphere_effect": {"talent_id": "talent:fake.primary_damage"},
                "base_form": {"form_id": "counter"}, "drawbacks": [], "augments": [], "cp_cost": {"final": 3}, "action_type": "reaction"}
    mechanics = {"talent:fake.primary_damage": _FAKE_PRIMARY_DAMAGE}  # no trigger anywhere on this primary
    mechanic = forged.mechanic_for(technique, mechanics)
    assert forged.as_reaction(technique, mechanic, mechanics) is None


# ------------------------------------------------------------------ treasure weapon enchantments


def test_moonless_yin_becomes_real_damage_plus_a_no_healing_effect():
    effects = _enchantment_on_hit([{"name": "Moonless-Yin Inscription",
                                    "text": "Whenever you hit with the weapon, the target takes an additional 1d6 cold "
                                            "damage and cannot regain Hit Points until the start of your next turn."}])
    kinds = [e["type"] for e in effects]
    assert kinds == ["damage", "healing_reduction"]
    assert effects[0]["damage_types"] == ["cold"]


def test_frost_meridian_becomes_damage_plus_a_speed_penalty_with_a_stacking_cap_rider():
    effects = _enchantment_on_hit([{"name": "Frost-Meridian Inscription",
                                    "text": "Whenever you hit a creature with the weapon, it takes an additional 1d4 cold "
                                            "damage, and its Speed is reduced by 5 feet until the start of your next turn. "
                                            "Speed reductions from this enchantment stack to a maximum reduction of 15 feet."}])
    kinds = [e["type"] for e in effects]
    assert kinds == ["damage", "speed", "rider"]
    assert effects[1]["flat"] == -5 and effects[1]["expires_on"] == "START_OF_SOURCE_NEXT_TURN"
    assert "stack" in effects[2]["evidence"].lower()


def test_flame_vein_is_always_lit_with_no_toggle_rider_spam():
    effects = _enchantment_on_hit([{"name": "Flame-Vein Inscription",
                                    "text": "Whenever you hit with the weapon, the target takes an additional 1d4 fire "
                                            "damage. You can ignite or extinguish the weapon’s flame as a Bonus "
                                            "Action. While extinguished, this additional damage does not apply."}])
    assert [e["type"] for e in effects] == ["damage"]
    assert effects[0]["damage_types"] == ["fire"]


def test_dream_piercing_is_condition_gated_damage_with_the_unchecked_clause_kept_as_a_rider():
    effects = _enchantment_on_hit([{"name": "Dream-Piercing Inscription",
                                    "text": "Whenever the weapon hits a creature that is Charmed, Frightened, "
                                            "Unconscious, or affected by a Dreams Sphere effect, it takes an additional "
                                            "1d6 psychic damage."}])
    kinds = [e["type"] for e in effects]
    assert kinds == ["conditional_damage", "rider"]
    assert set(effects[0]["when_target_condition"]) == {"charmed", "frightened", "unconscious"}
    assert "dreams sphere" in effects[1]["evidence"].lower()


def test_a_non_hit_enchantment_is_no_longer_silently_dropped():
    """Balanced-Grip's printed text never says "hit"; before this fix it produced no effect and no GM line at all."""
    effects = _enchantment_on_hit([{"name": "Balanced-Grip Inscription",
                                    "text": "While you are conscious and wielding the weapon, it cannot be disarmed "
                                            "from you unless you choose to release it."}])
    assert len(effects) == 1 and effects[0]["type"] == "rider" and "Balanced-Grip" in effects[0]["evidence"]


def test_conditional_damage_only_lands_when_the_target_bears_the_condition():
    sheet = {**SHEET, "spheres_and_talents": {"sphere_record_ids": [], "learned_talent_record_ids": []},
            "equipment": [{"starting_kit": {"items": [], "resolved_treasure_weapon": {
                "chassis": {"item_id": "test.dreamblade", "name": "Dreamblade", "damage": "1d8 Slashing", "properties": ""},
                "refinement_bonus": 0,
                "enchantments": [{"name": "Dream-Piercing Inscription",
                                  "text": "Whenever the weapon hits a creature that is Charmed, Frightened, "
                                          "Unconscious, or affected by a Dreams Sphere effect, it takes an additional "
                                          "1d6 psychic damage."}]}}}]}
    bundle = compile_character(sheet, actor_id=ME)
    weapon_row = next(row for row in bundle["action_catalog"] if row["display_name"] == "Dreamblade attack")
    on_hit = weapon_row["parameters"]["typed"]["effects"][0]["on_hit"]
    assert any(effect.get("type") == "conditional_damage" for effect in on_hit)
