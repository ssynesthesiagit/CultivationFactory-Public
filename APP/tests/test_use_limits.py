"""Printed use limits in a fight (owner ruling 2026-09-29: "Once per fight yes and the once per week can be once per day
instead. So once per fight unless a saved state is brought to the fight with it being exhausted which will only apply in
roleplaying").  combat/factory_compiler.py ``_fight_limited`` / ``_uses_of``: a scene, combat, day, week or rest limit -- as
the parser's key, a reviewed override's key, or the printed "text:..." -- gives the ability (an action, a reaction row, a
free trigger, an Immortal Art, a modifier's variant) a one-use counter that starts full and that the use spends.  Every
fight starts fresh; nothing carries an exhausted use into a fight (see the compiler note on ``_use_counter``)."""

import json

import pytest

from combat import typed_reactions
from combat.factory_compiler import _fight_limited, compile_character
from combat.gate2_runtime_content import AN
from tests.test_auto_bodya import BODY_REFINING_SHEET, ME as BODY_ME, _engine as _body_engine, _use
from tests.test_auto_docket import ME, QI, _do, _fight, _my_turn, _names, _sheet
from tests.test_immortal_arts import AUTHORITY, IRON_VOICE, IRON_VOICE_ART, QI_ARMOR, QI_ARMOR_ART, SHEET as ART_SHEET
from tests.test_zones import SHEET

FIRST_SPARK = "tianxia.talent.fire.first_spark_that_burned_the_sky"  # "once per week", 15 Qi, an action
SEALING_EDICT = "tianxia.subpath.qi.cultivator_of_seals.feature.heaven_sealing_edict"  # "once per scene", 8 Qi, an action
ASHEN_REBIRTH = "tianxia.subpath.qi.cinder_heart_cultivator.feature.ashen_rebirth"  # "once per scene", 5 Qi, a reaction
BLOOD_PUMP = "tianxia.path.body_refining.feature.blood_pump"  # "once per scene", a free (no-action) trigger
SOUL_SEVERANCE = "tianxia.subpath.body.kukishin.feature.soul_severance"  # "once per scene", a Stun on an unarmed hit (asked)
GOLDEN_AURA = "tianxia.subpath.body.goruden.feature.golden_aura"  # "once per scene", a bonus action
IMMORTAL_GOLD = "tianxia.subpath.body.goruden.feature.immortal_gold"  # "once per scene", starts Golden Aura free
STAMINA = "resource:core.stamina"

# What the printed limits look like in the authority (the counts are from Tianxia_Typed_Mechanics_Authority_R1.json).
ONCE_PER_FIGHT = [
    "once_per_long_rest", "once_per_short_rest", "once_per_day",  # the keys the parser keeps
    "once_per_scene",  # a reviewed override's key (3)
    "text:once per scene",  # 119
    "text:once per week", "text:once per week.",  # 46
    "text:once per week choose one creature, unattended object, temporary barrier, or ordinary ongoing supernatural effect.",
    "text:perfected only; once per combat or major scene; requires 1 empty bowl mark and 2 cp.",
    "text:requires legal last cinder guard on self; once per combat/major scene.",
    "text:once per target per scene", "text:once per creature per scene",  # no per-target counter: once per fight
]
LEFT_TO_THE_GM = [
    None, "", "none", "once_per_turn", "once_per_round",  # not a fight limit (turn/round ones have their own gates)
    "text:once per realm", "text:once per realm per creature", "text:once per cultivation session",
    "text:once per month or once per major story arc, as determined by the gm",
    "text:once per campaign arc, or once ever unless the gm permits the demon's return",
    "text:once per item per scene",  # a limit on each item, not on the ability
    "text:requires selecting safe beast digestion as a refined expression; once per major processing scene unless the gm sets stricter limits.",
    "text:once per spend. requires 1 moon-sea radiance. cannot spend on the same event that generated it.",
    "text:once per triggering hit; requires 1 golden sea pulse from a prior event; no same-event spending.",
    "text:a creature cannot benefit from Blood Mending again until it completes a short rest (per target, not per use)",
    "text:passive rider; no resource, action, or extra reaction.",
]


def _use_counters(template: dict) -> list[dict]:
    return [row for row in template["resources"] if row["resource_id"].startswith("resource:uses.")]


@pytest.mark.parametrize("limit", ONCE_PER_FIGHT)
def test_a_scene_week_day_or_rest_limit_is_once_per_fight(limit):
    assert _fight_limited({"use_limit": limit}) is True


@pytest.mark.parametrize("limit", LEFT_TO_THE_GM)
def test_longer_and_other_limits_stay_with_the_gm(limit):
    assert _fight_limited({"use_limit": limit}) is False


@pytest.mark.parametrize("sheet, name, cost", [
    pytest.param(_sheet([FIRST_SPARK], spheres=["tianxia.sphere.fire"]), "First Spark That Burned the Sky", 15, id="once-per-week-talent"),
    pytest.param({**SHEET, "path_and_subpath": {"path_feature_record_ids": [SEALING_EDICT]}}, "Heaven-Sealing Edict", 8, id="once-per-scene-feature"),
])
def test_a_once_per_week_or_scene_action_is_used_once_per_fight(sheet, name, cost):
    action = next(row for row in compile_character(sheet, actor_id=ME)["action_catalog"] if row["display_name"] == name)
    [counter] = _use_counters(compile_character(sheet, actor_id=ME)["actor_template"])
    assert (counter["initial"], counter["maximum"]) == (1, 1)  # every fight starts with the use unspent
    assert [list(part) for part in action["costs"]] == [[QI, cost], [counter["resource_id"], 1]]
    engine = _fight(sheet, foe_at=(5, 6))
    me = engine.state.actors[ME]
    assert name in _names(engine) and me.resources[counter["resource_id"]] == 1
    _do(engine, name)
    assert me.resources[counter["resource_id"]] == 0 and me.resources[QI] == 30 - cost
    _my_turn(engine)  # the Qi left still pays for a second use (8 or 15 of the 22 or 15 it has); the printed limit is what stops it
    assert me.resources[QI] >= cost and name not in _names(engine)


def test_a_once_per_scene_reaction_answers_once_per_fight():
    sheet = {**SHEET, "path_and_subpath": {"path_feature_record_ids": [ASHEN_REBIRTH]}}
    bundle = compile_character(sheet, actor_id=ME)
    row = next(row for row in bundle["typed_reactions"] if row["feature_id"] == ASHEN_REBIRTH)
    [counter] = _use_counters(bundle["actor_template"])
    assert (counter["initial"], counter["maximum"]) == (1, 1)
    assert row["costs"] == [{"resource_id": QI, "amount": 5}, {"resource_id": counter["resource_id"], "amount": 1}]
    engine = _fight(sheet)
    me = engine.state.actors[ME]

    def lethal_hit() -> None:  # the checkpoint a hit that would drop the character to 0 passes (tests/test_auto_bodya.py's own convention)
        me.current_hp, me.reaction_available = 20, True
        pending = typed_reactions.on_damage(engine, me, 999, 0, source_actor_id=AN)
        engine._commit_damage(me, pending, "FORCE", "reaction:test.lethal_hit", AN, None, reaction_depth=0)

    def answers() -> list:
        return [event for event in engine.events if event.event_type == "REACTION_RESOLVED" and event.source_definition_id == ASHEN_REBIRTH]

    lethal_hit()
    assert len(answers()) == 1 and me.resources[QI] == 25 and me.resources[counter["resource_id"]] == 0
    lethal_hit()  # 25 Qi and a Reaction, but the one use is spent
    assert len(answers()) == 1 and me.resources[QI] == 25 and me.current_hp == 0


def test_a_free_once_per_scene_trigger_is_once_per_fight_too():
    sheet = {**BODY_REFINING_SHEET, "path_and_subpath": {"path_feature_record_ids": ["tianxia.path.body_refining.feature.iron_fist", BLOOD_PUMP]}}
    engine = _body_engine(compile_character(sheet, actor_id=BODY_ME))
    me = engine.state.actors[BODY_ME]
    for held_at_one_hp in (True, False):  # Blood Pump holds the first lethal hit at 1 HP; the Stamina is topped up for the second
        me.resources[STAMINA], me.current_hp = 10, 20
        pending = typed_reactions.on_damage(engine, me, 999, 0, source_actor_id=AN)
        engine._commit_damage(me, pending, "FORCE", "reaction:test.lethal_hit", AN, None, reaction_depth=0)
        assert (me.current_hp == 1) is held_at_one_hp


def test_a_once_per_scene_on_hit_feature_is_an_asked_choice_not_a_stun_on_every_hit():
    """Soul Severance's Stun was once merged into every Iron Fist hit, then made an "Iron Fist attack + Soul Severance" variant.
    Rider lane C7 (Kukishin) made it what the printed text says: after an unarmed strike hits, the player is asked whether to pay
    5 Stamina for it, once per scene (once a fight at the table). No variant, and the plain attack itself never stuns; the table
    behaviour (asked, Stunned until the end of your next turn, not again that fight) is
    tests/test_riders_c7.py::test_soul_severance_stuns_until_the_end_of_your_next_turn_once_a_fight."""
    sheet = {**BODY_REFINING_SHEET, "path_and_subpath": {"path_feature_record_ids": ["tianxia.path.body_refining.feature.iron_fist", SOUL_SEVERANCE]}}
    bundle = compile_character(sheet, actor_id=BODY_ME)
    names = [row["display_name"] for row in bundle["action_catalog"]]
    assert "Iron Fist attack" in names and not any("Soul Severance" in name for name in names)
    plain = next(row for row in bundle["action_catalog"] if row["display_name"] == "Iron Fist attack")
    assert "stunned" not in json.dumps(plain["parameters"]["typed"]["effects"])
    from combat.factory_compiler import TYPED_AUTHORITY

    [row] = json.loads(TYPED_AUTHORITY.read_text(encoding="utf-8"))["mechanics"][SOUL_SEVERANCE]["effects"]
    assert (row["type"], row["kind"], row["limit"], row["costs"]) == ("path_passive", "paid_hit", "fight", [[STAMINA, 5]])


def test_immortal_gold_spends_its_own_use_and_starts_golden_aura_without_expending_golden_auras():
    """Printed: "Activate Golden Aura without paying its cost or expending its use." (Immortal Gold, Goruden). Both once-per-scene
    features keep their own use counter; Immortal Gold's statue spends only its own, and a second lethal hit that fight is not held."""
    from tests.test_riders_c7 import ME as C7_ME, _typed_foe, answers, bundle as c7_bundle, fight, hostile_packet, turn

    compiled = c7_bundle([IMMORTAL_GOLD, GOLDEN_AURA])
    counters = {row["resource_id"]: row for row in _use_counters(compiled["actor_template"])}
    gold = next(key for key in counters if key.endswith(IMMORTAL_GOLD))
    aura = next(key for key in counters if key.endswith(GOLDEN_AURA))
    assert all((row["initial"], row["maximum"]) == (1, 1) for row in counters.values()) and len(counters) == 2
    engine = fight(compiled, foe=_typed_foe())
    me = engine.state.actors[C7_ME]
    answers(engine)
    hostile_packet(engine, C7_ME, 500, "FIRE")
    assert me.current_hp == 1 and (me.resources[gold], me.resources[aura]) == (0, 1)
    turn(engine, C7_ME)  # the statue ends: 5 x PB Hit Points and Golden Aura, free
    assert any(z.source_definition_id.endswith(GOLDEN_AURA) and z.active for z in engine.state.zones.values())
    assert me.resources[aura] == 1 and me.resources[STAMINA] == 60 - 6
    hostile_packet(engine, C7_ME, 500, "FIRE")
    assert me.current_hp == 0  # once per scene


def test_an_immortal_art_carries_its_source_talents_limit():
    limited = {"mechanics": {**AUTHORITY["mechanics"],
                             IRON_VOICE["mechanic_id"]: {**IRON_VOICE, "use_limit": "text:once per week"},
                             QI_ARMOR["mechanic_id"]: {**QI_ARMOR, "use_limit": "text:once per scene"}}}
    bundle = compile_character({**ART_SHEET, "immortal_arts": [IRON_VOICE_ART, QI_ARMOR_ART]}, actor_id="actor:test.limited_arts",
                               typed_authority=limited)
    counters = {row["resource_id"]: row for row in _use_counters(bundle["actor_template"])}
    action = next(row for row in bundle["action_catalog"] if "Iron Voice" in row["display_name"])
    assert list(action["costs"]) == [[STAMINA, 4], [f"resource:uses.{action['source_definition_id']}", 1]]
    reaction = next(row for row in bundle["typed_reactions"] if "Qi Armor" in row["name"])
    assert [cost["amount"] for cost in reaction["costs"]] == [5, 1] and reaction["costs"][1]["resource_id"] in counters
    assert set(counters) == {f"resource:uses.{action['source_definition_id']}", reaction["costs"][1]["resource_id"]}
    assert all((row["initial"], row["maximum"]) == (1, 1) for row in counters.values())
    unlimited = compile_character({**ART_SHEET, "immortal_arts": [IRON_VOICE_ART]}, actor_id="actor:test.unlimited_art", typed_authority=AUTHORITY)
    assert not _use_counters(unlimited["actor_template"])  # no printed limit, no counter
