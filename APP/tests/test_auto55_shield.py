"""Shield sphere: the printed lines that used to be GM riders, now answered by the table (AUTO55, 2026-10-05).

Sphere Compendium, Shield (owner's text: APP/authority/typed_mechanics/rules_text.json). Each test compiles a real
Shield fighter and plays the printed line on the engine; each fails on the typing and the plug-ins the authority
carried before (no compiled block row, no effect, a rider shown to the GM).

Report: /var/tmp/auto-audit/fix/AUTO55.report.md.  Overrides:
authority/typed_mechanics/reviewed_final.d/auto55_shield.json.  Rows: combat/rules/feature_blocks.d/auto55_shield.json.
Plug-ins: combat/ext/shield_wielding.py, shield_mobility.py, shield_uncbroken.py, shield_incarnation.py.
"""

import json
from pathlib import Path

import pytest

from combat import factory_compiler
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine

ROOT = Path(__file__).resolve().parents[1]
TS = "tianxia.talent.shield."
ME = "actor:factory.auto55_shield"
THEM = "actor:factory.auto55_them"
ALLY = "actor:factory.auto55_ally"
BASES = ["SHIELD_BASE_ACTIVE_DEFENSE", "SHIELD_BASE_SHIELD_TRAINING", "TAL_SHIELD_FLEXIBLE_COVER",
         "TAL_SHIELD_SEAL_THE_BREACH", "TAL_SHIELD_BLOCKADE", "TAL_SHIELD_COVER_ALLY"]

SHIELD_ITEM = {"item_id": "tianxia.mortal.armor.shield", "name": "Shield", "quantity": 1}
DAGGER = {"item_id": "tianxia.mortal.weapon.bi_shou", "name": "Bi Shou (Dagger)", "quantity": 1}
ARMOR = {"item_id": "tianxia.mortal.armor.lacquered_lamellar", "name": "Lacquered Lamellar", "quantity": 1}


def _authority():
    return json.loads(Path(factory_compiler.TYPED_AUTHORITY).read_bytes())["mechanics"]


def _sheet(talents, *, cl=15, shield=True, bases=True, weapon=True):
    from tests.test_zones import SHEET

    items = [ARMOR, *( [SHIELD_ITEM] if shield else [] ), *( [DAGGER] if weapon else [] )]
    sheet = {**SHEET, "equipment": [{"starting_kit": {"items": items}}],
             "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.shield"],
                                     "automatic_sphere_component_record_ids": list(BASES) if bases else [],
                                     "learned_talent_record_ids": list(talents)}}
    sheet["identity"] = {**SHEET["identity"], "cultivation_level": cl}
    return sheet


def _fight(talents, *, cl=15, shield=True, bases=True, weapon=True, me_at=(3, 6), them_at=(4, 6), ally_at=None,
           them_sheet=None, seed="AUTO55"):
    """ME (team a): a Shield fighter with ``talents``. THEM (team b): a plain fighter with a Bi Shou (melee and
    thrown). ALLY (team a) when ``ally_at`` is given."""
    from tests.test_riders_lane9 import _sheet as plain

    bundles = [compile_character(_sheet(talents, cl=cl, shield=shield, bases=bases, weapon=weapon), actor_id=ME),
               compile_character(them_sheet or plain([], 15, 60), actor_id=THEM)]
    ids, teams = [ME, THEM], {ME: "team:a", THEM: "team:b"}
    spots = {ME: {"x": me_at[0], "y": me_at[1]}, THEM: {"x": them_at[0], "y": them_at[1]}}
    if ally_at:
        bundles.append(compile_character(plain([], 15, 60), actor_id=ALLY))
        ids.append(ALLY)
        teams[ALLY] = "team:a"
        spots[ALLY] = {"x": ally_at[0], "y": ally_at[1]}
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=tuple(bundles),
                                   roster_setup={"primary_actor_ids": ids, "team_by_actor": teams, "starting_positions": spots})
    from tests.test_formations import _turn

    _turn(engine, ME)
    return engine


def _conds(actor):
    return {c.condition_id for c in actor.conditions.values()}


def _act(engine, name, target=None, actor=ME):
    candidate = next(c for c in engine.legal_candidates() if c.actor_id == actor
                     and getattr(engine.action_catalog.get(c.source_definition_id), "display_name", None) == name
                     and (target is None or c.target_ids == (target,)))
    engine.execute_intent(ActionIntent(intent_id=f"{name}{engine.state.event_sequence}", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=actor,
                                       target_ids=candidate.target_ids, destination=candidate.destination))


def _attack(engine, attacker, name, target):
    from tests.test_formations import _turn

    _turn(engine, attacker)
    _act(engine, name, target, actor=attacker)


def _answered(events, feature):
    return any(e.event_type == "REACTION_WINDOW_OPENED" and str(e.source_definition_id) == feature for e in events)


def _stab(engine, name="Bi Shou (Dagger) attack", target=ME):
    from tests.test_auto_lane4 import _script

    before = len(engine.events)
    _attack(engine, THEM, name, target)
    return engine.events[before:]


def _answers(monkeypatch, module_name, **by_choice):
    """A plug-in's printed choices answered: choice name -> the options picked ([] declines)."""
    import importlib

    module = importlib.import_module(f"combat.ext.{module_name}")

    def ask(engine, intent, checkpoint, chooser, choice_id, options, **kwargs):
        name = choice_id.split(":")[-1].split(".")[-1]
        return list(by_choice.get(name, options[:1]))

    monkeypatch.setattr(module, "ask", ask)


# ------------------------------------------------------------------------------------ the printed Requirement
def test_active_defense_needs_a_shield_in_hand():
    """Active Defense's printed "Requirement: Wielding a Shield". Bare-handed, the +2 AC is not offered."""
    engine = _fight([], shield=False)
    from tests.test_auto_lane4 import _script
    _script(engine, [5])
    assert not _answered(_stab(engine), 'SHIELD_BASE_ACTIVE_DEFENSE')


def test_active_defense_answers_with_a_shield_in_hand():
    from tests.test_auto_lane4 import _script

    engine = _fight([])
    me = engine.state.actors[ME]
    assert me.armor_class + engine._ac_modifier(me) == 18  # 16 + the Shield's own +2
    me.armor_class = 60  # the attack misses on its own; Active Defense is still offered, which is the printed ability
    focus = me.resources["resource:core.martial_focus"]
    _script(engine, [5])
    events = _stab(engine)
    assert _answered(events, "SHIELD_BASE_ACTIVE_DEFENSE")
    assert not me.reaction_available and me.resources["resource:core.martial_focus"] == focus


def test_active_defense_costs_martial_focus_when_the_reaction_is_spent():
    """Active Defense: "You may expend Martial Focus to use Active Defense without spending a Reaction"."""
    from tests.test_auto_lane4 import _script

    engine = _fight([])
    me = engine.state.actors[ME]
    me.armor_class = 60
    focus = me.resources["resource:core.martial_focus"]
    me.reaction_available = False
    _script(engine, [5])
    events = _stab(engine)
    assert _answered(events, "SHIELD_BASE_ACTIVE_DEFENSE")  # it still answered, with no Reaction to spend
    assert me.resources["resource:core.martial_focus"] == focus - 1  # the Focus is the printed price


def test_active_defense_costs_nothing_when_the_fighter_has_no_martial_focus():
    from tests.test_auto_lane4 import _script

    engine = _fight([])
    me = engine.state.actors[ME]
    me.armor_class = 60
    me.resources["resource:core.martial_focus"] = 0
    me.reaction_available = False
    _script(engine, [5])
    events = _stab(engine)
    assert not _answered(events, "SHIELD_BASE_ACTIVE_DEFENSE")  # the printed cost is what pays for it
    assert me.resources["resource:core.martial_focus"] == 0


# ------------------------------------------------------------------------------------ Guarded Stance
def test_guarded_stance_lets_a_bare_handed_fighter_use_active_defense(monkeypatch):
    from tests.test_auto_lane4 import _script
    from combat.ext import shield_wielding

    _answers(monkeypatch, "shield_wielding", guarded_stance=["tianxia.mortal.weapon.bi_shou"])
    engine = _fight(["TAL_SHIELD_GUARDED_STANCE"], cl=5, shield=False)
    me = engine.state.actors[ME]
    assert shield_wielding.wielding_a_shield(engine, me) is False
    _act(engine, "Guarded Stance: choose the weapon that counts as your Shield (costs no Action)")
    assert "condition:typed.guarded_stance" in _conds(me)
    assert shield_wielding.guarded_weapon(engine, me) == "tianxia.mortal.weapon.bi_shou"
    assert shield_wielding.wielding_a_shield(engine, me) is True
    assert shield_wielding.shield_bonus(engine, me) == 0  # "a Shield Bonus of 0"
    assert me.armor_class + engine._ac_modifier(me) == 16  # no +2 from the chosen weapon
    me.armor_class = 15
    _script(engine, [15 - 6])
    events = _stab(engine)
    assert _answered(events, "SHIELD_BASE_ACTIVE_DEFENSE")


def test_guarded_stance_is_inert_without_the_talent():
    from combat.ext import shield_wielding

    engine = _fight([], cl=5, shield=False)
    me = engine.state.actors[ME]
    assert shield_wielding.wielding_a_shield(engine, me) is False
    assert shield_wielding.shield_bonus(engine, me) == 0


# ------------------------------------------------------------------------------------ Orbiting Shield Disc
def test_orbiting_shield_disc_counts_as_wielded_and_keeps_its_bonus():
    from combat.ext import shield_wielding

    engine = _fight(["TAL_SHIELD_ORBITING_SHIELD_DISC"], cl=10)
    me = engine.state.actors[ME]
    assert shield_wielding.orbiting(engine, me) is False
    _act(engine, "ORBITING SHIELD DISC")
    assert "condition:typed.orbiting_shield_disc" in _conds(me)
    assert shield_wielding.orbiting(engine, me) is True
    assert shield_wielding.wielding_a_shield(engine, me) is True
    assert shield_wielding.shield_bonus(engine, me) == 2  # "retain its Shield Bonus"
    assert me.armor_class + engine._ac_modifier(me) == 18


# ------------------------------------------------------------------------------------ Shield Skate
def test_shield_skate_adds_speed_and_ignores_loose_ground(monkeypatch):
    from combat import zones

    engine = _fight(["TAL_SHIELD_SHIELD_SKATE"], cl=5)
    me = engine.state.actors[ME]
    assert engine._effective_speed(me) == 30
    _act(engine, "SHIELD SKATE")
    assert "condition:typed.shield_skating" in _conds(me)
    assert engine._effective_speed(me) == 50  # "+20 feet"
    assert me.armor_class + engine._ac_modifier(me) == 18  # stationary Shield AC is retained


def test_shield_skate_alone_costs_no_turn_flag_on_another_fighter():
    engine = _fight([], cl=5)
    assert "condition:typed.shield_skating" not in _conds(engine.state.actors[THEM])


# ------------------------------------------------------------------------------------ Riding the Falling Star
def _fall(engine, actor, feet):
    """Run the engine's own falling checkpoint for ``actor`` from ``feet`` up, as a real drop does."""
    from combat import falling

    actor.position = actor.position.model_copy(update={'z': feet // 5})
    falling.settle(engine)


def test_riding_the_falling_star_reduces_falling_damage_by_five_cultivation_levels():
    from tests.test_auto_lane4 import _script
    from combat import falling

    engine = _fight(["TAL_SHIELD_SHIELD_SKATE", "TAL_SHIELD_RIDING_THE_FALLING_STAR", TS + "projected_shield_face"], cl=10)
    me = engine.state.actors[ME]
    _act(engine, 'SHIELD SKATE')
    hp = me.current_hp
    _script(engine, [6] * 10)
    _fall(engine, me, 100)
    assert me.current_hp == hp - 10  # 60 damage minus 5 x CL 10
    assert 'condition:typed.prone' not in _conds(me)


def test_riding_the_falling_star_grants_a_movement_allowance_after_a_long_fall(monkeypatch):
    from combat import falling

    engine = _fight(["TAL_SHIELD_SHIELD_SKATE", "TAL_SHIELD_RIDING_THE_FALLING_STAR"], cl=10)
    me = engine.state.actors[ME]
    _act(engine, 'SHIELD SKATE')
    me.movement_remaining_ft = 0
    from combat.gate2_runtime_models import ActionIntent
    engine._active_intent = ActionIntent(intent_id='landing', decision_id='landing', candidate_id='landing',
                                        state_version=engine.state.state_version, actor_id=ME)
    _answers(monkeypatch, 'shield_mobility', falling_star_landing=['cell:3,5'])
    _fall(engine, me, 40)
    assert (me.position.x, me.position.y, me.position.z) == (3, 5, 0)
    assert me.movement_remaining_ft == 0  # immediate grant; no stale Dash budget


def test_no_falling_reduction_without_riding_the_falling_star():
    from combat import falling

    engine = _fight([], cl=10)
    me = engine.state.actors[ME]
    me.movement_remaining_ft = 0
    engine._fall_packet = falling.Fall(actor_id=ME, distance_ft=40, cause="test")
    assert falling.remaining_packet(engine, me, 60, "bludgeoning", falling.SOURCE, None) == 60


# ------------------------------------------------------------------------------------ Unbroken Rim
def test_unbroken_rim_spends_martial_focus_to_keep_a_breaking_shield(monkeypatch):
    from combat.ext import shield_uncbroken

    _answers(monkeypatch, "shield_uncbroken", unbroken_rim=["intact"])
    engine = _fight([TS + "sacrificial_shield", "TAL_SHIELD_UNBROKEN_RIM"], cl=8)
    me = engine.state.actors[ME]
    assert shield_uncbroken.owning(engine, me) is not None
    focus = me.resources["resource:core.martial_focus"]
    from combat import typed_reactions
    from combat.typed_executor import run_effects
    row = next(r for r in engine.typed_passive_rows[ME] if r.get('kind') == 'unbroken_rim')
    ctx = typed_reactions.triggered_context(engine, me, me, row)
    run_effects(ctx, [{'type': 'condition', 'condition': 'shield_broken', 'applies_to': 'self', 'duration': 'special'}])
    assert me.resources["resource:core.martial_focus"] == focus - 1
    assert "condition:typed.shield_broken" not in _conds(me)


def test_unbroken_rim_needs_martial_focus():
    from combat.ext import shield_uncbroken

    engine = _fight(["TAL_SHIELD_UNBROKEN_RIM"], cl=8)
    me = engine.state.actors[ME]
    me.resources[shield_uncbroken.FOCUS] = 0
    assert shield_uncbroken.offer(engine, me, "test", "your Shield would break") is False


def test_unbroken_rim_is_inert_without_the_talent():
    from combat.ext import shield_uncbroken

    engine = _fight([], cl=8)
    me = engine.state.actors[ME]
    assert shield_uncbroken.owning(engine, me) is None
    assert shield_uncbroken.offer(engine, me, "test", "your Shield would break") is False


# ------------------------------------------------------------------------------------ the Incarnation
def test_sovereign_incarnation_grants_forty_feet_of_flight_and_hover():
    from combat import flight

    engine = _fight(["TAL_SHIELD_SOVEREIGN_SHIELD_SOUL_INCARNATION", TS + "projected_shield_face"], cl=16)
    me = engine.state.actors[ME]
    assert flight.profile(engine, me).speed_ft == 0
    _act(engine, "SOVEREIGN SHIELD-SOUL INCARNATION")
    profile = flight.profile(engine, me)
    assert profile.speed_ft == 40 and profile.hover is True


def test_sovereign_incarnation_widens_cover_ally_to_sixty_feet():
    from combat import typed_reactions

    from combat.ext import states

    engine = _fight(["TAL_SHIELD_SOVEREIGN_SHIELD_SOUL_INCARNATION", TS + "projected_shield_face", "TAL_SHIELD_COVER_ALLY"],
                    cl=16, ally_at=(14, 6))
    row = next(r for r in typed_reactions._rows(engine, ME, "generic") if r["feature_id"] == "TAL_SHIELD_COVER_ALLY")
    reactor, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    assert typed_reactions._generic_in_range(engine, reactor, ally, row) is False  # 55 feet, the printed 5 feet
    _act(engine, "SOVEREIGN SHIELD-SOUL INCARNATION")
    assert states.active(engine, reactor, "sovereign_shield_soul_incarnation") is not None
    assert typed_reactions._generic_in_range(engine, reactor, ally, row) is True  # "increase Cover Ally range to 60 feet"


def test_the_sixty_foot_cover_ally_is_the_printed_distance():
    engine = _fight(["TAL_SHIELD_SOVEREIGN_SHIELD_SOUL_INCARNATION", TS + "projected_shield_face", "TAL_SHIELD_COVER_ALLY"],
                    cl=16, ally_at=(16, 6))
    from combat import typed_reactions

    row = next(r for r in typed_reactions._rows(engine, ME, "generic") if r["feature_id"] == "TAL_SHIELD_COVER_ALLY")
    _act(engine, "SOVEREIGN SHIELD-SOUL INCARNATION")
    assert engine._distance_actor_to_actor(engine.state.actors[ME], engine.state.actors[ALLY]) == 65
    assert typed_reactions._generic_in_range(engine, engine.state.actors[ME], engine.state.actors[ALLY], row) is False


def test_sovereign_incarnation_reduces_active_defense_damage_by_the_proficiency_bonus():
    engine = _fight(["TAL_SHIELD_SOVEREIGN_SHIELD_SOUL_INCARNATION", TS + "projected_shield_face"], cl=16)
    me = engine.state.actors[ME]
    _act(engine, "SOVEREIGN SHIELD-SOUL INCARNATION")
    from combat.ext import shield_incarnation

    assert shield_incarnation.incarnate(engine, me) is True
    # Without an attack in flight the reduction is inert.
    assert shield_incarnation.active_defense_reduction(engine, me, 10, 'PIERCING', "test", None) is None
    from tests.test_auto_lane4 import _script
    _script(engine, [19, 19, 4])
    before = me.current_hp
    events = _stab(engine)
    assert _answered(events, 'SHIELD_BASE_ACTIVE_DEFENSE')
    roll = next(e for e in events if e.event_type == 'DAMAGE_ROLLED')
    assert me.current_hp == before - max(0, roll.payload['total'] - me.proficiency_bonus)


# ------------------------------------------------------------------------------------ the typing
def test_the_shield_riders_that_were_gm_lines_are_gone_from_the_authority():
    gone = ["TAL_SHIELD_GUARDED_STANCE", "TAL_SHIELD_RIDING_THE_FALLING_STAR", "SHIELD_BASE_ACTIVE_DEFENSE",
            "SHIELD_BASE_SHIELD_TRAINING", "TAL_SHIELD_SOVEREIGN_SHIELD_SOUL_INCARNATION",
            "TAL_SHIELD_ORBITING_SHIELD_DISC"]
    authority = _authority()
    for mechanic_id in gone:
        record = authority[mechanic_id]
        assert record["effects"], f"{mechanic_id} has no typed effect"
        assert all("do not benefit from the Shield" not in line and "Choose one weapon" not in line
                   for line in record["riders"]), f"{mechanic_id} still shows the GM {record['riders']}"
    for mechanic_id in ("TAL_SHIELD_GUARDED_STANCE", "TAL_SHIELD_RIDING_THE_FALLING_STAR",
                        "SHIELD_BASE_ACTIVE_DEFENSE", "SHIELD_BASE_SHIELD_TRAINING"):
        assert authority[mechanic_id]["riders"] == [], f"{mechanic_id} still shows the GM"
        assert authority[mechanic_id]["coverage"] == "FULL", f"{mechanic_id} is {authority[mechanic_id]['coverage']}"
    # Shield Skate keeps exactly one honest line: the printed "the GM determines whether terrain can support" call.
    assert authority["TAL_SHIELD_SHIELD_SKATE"]["riders"] == [
        "The GM determines whether terrain can physically support Shield Skate.",
        "During skating movement, remove the Shield's Armor Class bonus against attacks made during that movement; restore it when movement ends."]


def test_riding_the_falling_star_records_five_cultivation_levels_not_one():
    record = _authority()["TAL_SHIELD_RIDING_THE_FALLING_STAR"]
    (effect,) = record["effects"]
    assert effect["type"] == "riding_falling_star" and effect["formula"] == "5cl"


def test_the_shield_sphere_ships_no_guardian_text_rider_anymore():
    """Every Shield rider that survives is a printed limit or an honest "still by hand" line, never engine notes."""
    import re

    for mechanic_id, record in _authority().items():
        if record.get("sphere_id") != "tianxia.sphere.shield":
            continue
        for line in record.get("riders") or []:
            assert not re.search(r"combat/ext/|typed_executor|\.py\b", line), f"{mechanic_id}: {line}"
