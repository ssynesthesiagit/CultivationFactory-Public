"""Rider lane 10 (owner 2026-09-29: "i want everything we can automated, keep going until its only the non-combat ones left"): the
printed lines of partly automated abilities that were only shown to the GM as riders. Each ability is compiled on a real character
and run through the engine; each behaviour test fails on the typing the authority carried before.

Overrides: authority/typed_mechanics/reviewed_final.d/riders_lane10.json (and the entries edited in place in the other
reviewed_final.d files); plug-ins: combat/ext/utilize_end.py and the lane-10 parts of combat/ext/needle.py.
"""

import json
from pathlib import Path

import pytest

from combat.gate2_runtime_models import ActionIntent
from tests import test_auto_lane4 as L4
from tests import test_needle as N

t = L4.t
ROOT = Path(__file__).resolve().parents[1]
AUTHORITY = ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json"


def _authority():
    return json.loads(AUTHORITY.read_text(encoding="utf-8"))["mechanics"]


def _as(engine, actor_id, name, target_id=None):
    """``actor_id`` takes its turn and uses the action named ``name`` (against ``target_id`` when given)."""
    L4._new_turn(engine, actor_id)
    actor = engine.state.actors[actor_id]
    actor.action_available, actor.bonus_action_available, actor.reaction_available = True, True, True
    found = [c for c in engine.legal_candidates() if c.display_name == name and c.actor_id == actor_id
             and (target_id is None or tuple(c.target_ids or ()) == (target_id,))]
    assert found, f"{name!r} is not legal for {actor_id}; legal: {sorted({c.display_name for c in engine.legal_candidates() if not c.display_name.startswith('Move')})}"
    candidate = found[0]
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"i-{name}-{engine.state.event_sequence}", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=actor_id,
                                       target_ids=candidate.target_ids, destination=candidate.destination))
    return engine.events[before:]


def _offered(engine, actor_id, name):
    L4._new_turn(engine, actor_id)
    engine.state.actors[actor_id].action_available = True
    return [tuple(c.target_ids or ()) for c in engine.legal_candidates() if c.display_name == name and c.actor_id == actor_id]


# ================================================================================================================ The Piercing Needle
NEEDLE_CLEARED = [
    "TAL_FENCING_ANKLE_STRIKE", "TAL_FENCING_COURT_OF_MEASURED_OPENINGS", "TAL_FENCING_EXPERT_FEINT", "TAL_FENCING_FATAL_OPENING",
    "TAL_FENCING_FEINT", "TAL_FENCING_FENCING_FOCUS", "TAL_FENCING_FOOTWORK", "TAL_FENCING_GREATER_FEINT", "TAL_FENCING_LUNGE",
    "TAL_FENCING_PARRY_AND_RIPOSTE", "TAL_FENCING_PARRY_ANYTHING", "TAL_FENCING_REPOSITIONING_STRIKE", "TAL_FENCING_RETURNING_POINT",
    "TAL_FENCING_THREE_STEP_FEINT", "TAL_FENCING_TO_THE_HILT", "TAL_FENCING_WIDE_OPEN",
]


def test_needle_lines_the_plugins_already_run_are_no_longer_gm_riders():
    """Feint, Footwork, Lunge, Court, the Exploits' costs and durations ...: the Needle plug-ins run these lines; the authority
    still listed them as GM riders (coverage CORE_WITH_RIDERS / RIDERS_ONLY)."""
    mechanics = _authority()
    assert {key: mechanics[key]["coverage"] for key in NEEDLE_CLEARED} == {key: "FULL" for key in NEEDLE_CLEARED}


def test_arm_strike_penalises_weapon_attacks_and_grapple_escapes_but_not_cultivation_attacks():
    """Arm Strike: "-2 to attack rolls made with a weapon, natural weapon, or object held ... by that limb; and Strength and Dexterity
    ability checks that rely primarily on that limb". The penalty landed on every typed attack (a Cultivation Attack too) and on no
    check."""
    from combat.ext import needle
    from combat.typed_executor import Context

    engine, me, foe = N._land_exploit("TAL_FENCING_ARM_STRIKE")
    assert N._bears(foe, "needle_arm_strike")
    catalog = engine.action_catalog

    def ctx_of(predicate):
        action = next(a for a in catalog.values() if a.owner_id == foe.entity_id and predicate(a))
        return Context(engine, foe, action, None, dict((action.parameters or {}).get("typed") or {}), [me], me)

    weapon = ctx_of(lambda a: ((a.parameters or {}).get("typed") or {}).get("weapon") is not None)
    escape = ctx_of(lambda a: any(e.get("type") == "escape_grapple" for e in ((a.parameters or {}).get("typed") or {}).get("effects") or []))
    technique = Context(engine, foe, weapon.action, None, {"effects": [{"type": "attack", "attack_kind": "cultivation_melee"}]}, [me], me)
    assert needle._attack_penalty(weapon, foe) == -2
    assert needle._attack_penalty(technique, foe) is None
    assert needle._check_penalty(escape, foe) == -2


def test_face_strike_blindness_ends_when_a_creature_within_reach_takes_the_utilize_action():
    """Face Strike: "The target or a creature within its reach may take the Utilize action to wipe away blood, dust, or another
    obstruction and end the effect early." There was no such action: the Blinded condition lasted its minute."""
    engine, me, foe = N._land_exploit("TAL_FENCING_FACE_STRIKE", foes=2)
    assert L4._has(foe, "blinded") and N._bears(foe, "needle_face_strike")
    name = "Wipe away the obstruction (Face Strike)"
    assert (N.FOE1,) in _offered(engine, N.FOE2, name)  # the foe's ally, 5 feet away
    assert not [ids for ids in _offered(engine, N.FENCER, name) if ids != (N.FOE1,)]
    _as(engine, N.FOE2, name, N.FOE1)
    assert not L4._has(foe, "blinded") and not N._bears(foe, "needle_face_strike")
    assert not engine.state.actors[N.FOE2].action_available  # it took the Action


def test_face_strike_utilize_leaves_other_blindness_alone():
    engine, me, foe = N._land_exploit("TAL_FENCING_FACE_STRIKE")
    engine._apply_condition(foe, "condition:typed.blinded", "test:darkness", N.FOE1, expires_on="UNTIL_REMOVED")
    _as(engine, N.FOE1, "Wipe away the obstruction (Face Strike)", N.FOE1)  # the target itself
    assert [c.source_definition_id for c in foe.conditions.values() if c.condition_id == "condition:typed.blinded"] == ["test:darkness"]


def test_bleed_air_choking_ends_on_a_medicine_check_by_a_creature_within_reach():
    """Bleed Air: "After choking begins, the effect ends if ... a creature within reach of the target takes the Utilize action and
    succeeds on a Wisdom (Medicine) check against your Cultivation Save DC." Nothing could end it but full Hit Points."""
    name = "Treat the choking (Bleed Air)"
    engine, me, foe = N._land_exploit("TAL_FENCING_BLEED_AIR", foes=2, prepare=lambda e: setattr(e.state.actors[N.FOE1], "current_hp",
                                                                                                    e.state.actors[N.FOE1].current_hp - 1))
    (found,) = N._bears(foe, "needle_bleed_air")
    assert found.data["dc"] >= 10
    assert _offered(engine, N.FOE2, name) == []  # before choking begins only full Hit Points ends it
    engine.state.round_number = int(found.data["begins_round"])
    L4._new_turn(engine, N.FOE1)
    assert "dies_round" in N._bears(foe, "needle_bleed_air")[0].data
    assert _offered(engine, N.FOE1, name) == []  # "a creature within reach of the target", not the target
    L4._script(engine, [1])
    _as(engine, N.FOE2, name, N.FOE1)
    assert N._bears(foe, "needle_bleed_air")  # a failed check
    L4._script(engine, [20])
    _as(engine, N.FOE2, name, N.FOE1)
    assert not N._bears(foe, "needle_bleed_air")


def test_parry_and_riposte_reduces_the_hit_by_the_parrying_weapons_own_damage_roll():
    """Parry and Riposte: "Roll the normal damage of that attack form (the weapon's dice, the ability modifier, a magic weapon's
    bonus) and reduce the triggering attack's damage by the amount rolled." The table rolled 1d8 + the key modifier whatever the
    weapon; a dagger is 1d4 + 3."""
    from tests.test_carry import KIT

    engine = L4._duel(["TAL_FENCING_PARRY_AND_RIPOSTE"], subject_sphere=N.NEEDLE, subject_kit={"starting_kit": KIT}, attacker_kit=t.AXE_KIT)
    subject = engine.state.actors[L4.SUBJ]
    subject.resources["resource:core.martial_focus"] = 1
    L4._script(engine, [15, 7, 6])  # the hit, the parry's die (a d4 reads 4, a d8 would read 7), the axe's d6
    events = L4._use(engine, "Fu (Short Axe) attack")
    assert L4._hp_lost(events) == (6 + 3) - (4 + 3)
    assert subject.resources["resource:core.martial_focus"] == 0


# ---------------------------------------------------------------------------------------------- Bind Weapon and its Guards
BOUND, BINDING, SEAL = "needle_bound", "needle_binding", "needle_meridian_seal"
DISARM = "Bi Shou (Dagger) attack: Disarm"


def _disarm(talents, *, save=1):
    """The fencer (dagger) tries a Disarm on FOE1 (a Brute with a dagger); the Disarm save's natural d20 is ``save``."""
    engine = N._team(list(talents), foes=1)
    N._pin(engine, ATTACK=15, SAVE=save)
    L4._use(engine, DISARM)
    return engine, engine.state.actors[N.FENCER], engine.state.actors[N.FOE1]


def _names_for(engine, actor_id):
    L4._new_turn(engine, actor_id)
    actor = engine.state.actors[actor_id]
    actor.action_available, actor.bonus_action_available = True, True
    return {c.display_name for c in engine.legal_candidates() if c.actor_id == actor_id}


def test_bind_weapon_binds_the_disarmed_weapon_instead_of_knocking_it_away():
    """Bind Weapon: "When you win a Disarm attempt, you may bind the target's object to your weapon instead of causing the target to
    drop it ... the target has the Grappled condition; the bound object cannot be used to make attacks; you cannot use the weapon
    maintaining the bind to make attacks". The modifier found no ability named Disarm, so the weapon always dropped."""
    engine, me, foe = _disarm(["TAL_FENCING_BIND_WEAPON"])
    assert L4._has(foe, "grappled") and N._bears(foe, BOUND) and N._bears(me, BINDING)
    assert not L4._has(foe, "disarmed")  # bound, not dropped
    assert "Bi Shou (Dagger) attack" not in _names_for(engine, N.FOE1)
    assert "Let go of the bound weapon" in _names_for(engine, N.FOE1)
    assert "Bi Shou (Dagger) attack" not in _names_for(engine, N.FENCER)


def test_the_bind_ends_with_its_grapple():
    engine, me, foe = _disarm(["TAL_FENCING_BIND_WEAPON"])
    L4._script(engine, [20])
    _as(engine, N.FOE1, "Escape grapple")
    assert not L4._has(foe, "grappled") and not N._bears(foe, BOUND) and not N._bears(me, BINDING)
    assert "Bi Shou (Dagger) attack" in _names_for(engine, N.FOE1)


def test_letting_go_of_the_bound_weapon_ends_the_bind_and_leaves_the_weapon():
    engine, me, foe = _disarm(["TAL_FENCING_BIND_WEAPON"])
    _as(engine, N.FOE1, "Let go of the bound weapon")
    assert not N._bears(foe, BOUND) and not L4._has(foe, "grappled") and not N._bears(me, BINDING)
    assert L4._has(foe, "disarmed")  # the weapon stays on the fencer's blade and falls at its feet


def test_meridian_sealing_bind_seals_a_creature_that_fails_to_escape():
    """Meridian-Sealing Bind: "When a creature fails to escape your Bind Weapon, choose one of the following effects until the bind
    ends: the creature cannot take Reactions ..." It never fired."""
    engine, me, foe = _disarm(["TAL_FENCING_BIND_WEAPON", "TAL_FENCING_MERIDIAN_SEALING_BIND"])
    L4._script(engine, [1])
    _as(engine, N.FOE1, "Escape grapple")
    assert L4._has(foe, "grappled") and [c.data["effect"] for c in N._bears(foe, SEAL)] == ["reactions"]
    assert L4._has(foe, "reaction_denied")
    L4._script(engine, [20])
    _as(engine, N.FOE1, "Escape grapple")
    assert not N._bears(foe, SEAL) and not L4._has(foe, "reaction_denied")


def test_meridian_sealing_bind_disadvantage_against_others_only():
    from combat.ext import needle_bind
    from combat.typed_executor import Context

    engine, me, foe = _disarm(["TAL_FENCING_BIND_WEAPON", "TAL_FENCING_MERIDIAN_SEALING_BIND"])
    N._answers(engine, {"meridian_seal": ("others",)})
    L4._script(engine, [1])
    _as(engine, N.FOE1, "Escape grapple")
    action = next(iter(engine.action_catalog.values()))
    ctx = Context(engine, foe, action, None, {}, [me], me)
    assert needle_bind.sealed_attacks(ctx, me) is None
    other = engine.state.actors[N.FENCER].model_copy(update={"entity_id": "actor:someone.else"})
    assert needle_bind.sealed_attacks(ctx, other) == "DISADVANTAGE"


def test_traitorous_blade_catches_the_disarmed_weapon():
    """Traitorous Blade: "When you win a Disarm attempt, you may immediately catch the disarmed object". The weapon always fell."""
    engine, me, foe = _disarm(["TAL_FENCING_TRAITOROUS_BLADE"])
    (disarmed,) = [c for c in foe.conditions.values() if c.condition_id == "condition:typed.disarmed"]
    assert disarmed.data.get("held_by") == N.FENCER and "dropped_at" not in disarmed.data


# ---------------------------------------------------------------------------------------------- Vacuum Cut, No Space, Vacuum Slice
def _vacuum(talents, positions):
    engine = N._team(["TAL_FENCING_VACUUM_CUT", *talents], foes=2, positions=positions)
    return engine, engine.state.actors[N.FENCER]


def _targets_of(engine, name):
    return [tuple(c.target_ids or ()) for c in engine.legal_candidates() if c.display_name == name and c.actor_id == N.FENCER]


def test_vacuum_cut_extends_one_melee_weapon_attack_to_thirty_feet_for_martial_focus():
    """Vacuum Cut: "you may expend Martial Focus to extend that attack's reach to 30 feet ... changes the reach of that single melee
    weapon attack". The typing added 30 feet only to Vacuum Slice; no weapon attack could reach."""
    engine, me = _vacuum([], {N.FOE1: (8, 6), N.FOE2: (4, 7)})  # 25 feet and adjacent
    name = "Bi Shou (Dagger) attack: Vacuum Cut"
    assert _targets_of(engine, name) == [(N.FOE1,)]  # not the adjacent one: its own reach does
    N._pin(engine, ATTACK=15)
    events = L4._use(engine, name)
    assert me.resources[N.FOCUS] == 0
    rolled = [e for e in events if e.event_type == "ATTACK_ROLLED"]
    assert len(rolled) == 1  # the later strikes of the Attack action keep the dagger's 5-foot reach
    assert _targets_of(engine, name) == []  # no Martial Focus left


def test_no_space_between_thought_and_steel_makes_the_reach_sixty_feet():
    positions = {N.FOE1: (14, 6), N.FOE2: (3, 14)}  # 55 and 40 feet
    engine, me = _vacuum([], positions)
    assert _targets_of(engine, "Bi Shou (Dagger) attack: Vacuum Cut") == []
    engine, me = _vacuum(["TAL_FENCING_NO_SPACE_BETWEEN_THOUGHT_AND_STEEL"], positions)
    assert sorted(_targets_of(engine, "Bi Shou (Dagger) attack: Vacuum Cut")) == [(N.FOE1,), (N.FOE2,)]


def test_vacuum_slice_is_deferred_until_normal_shared_roll_attack_defenses_exist():
    """The printed shared roll must respect attack modes/AC/reactions; a naked d20 is invalid automation."""
    engine, me = _vacuum(["TAL_FENCING_VACUUM_SLICE"], {N.FOE1: (5, 6), N.FOE2: (7, 6)})  # 10 and 20 feet, in a row
    for foe in (N.FOE1, N.FOE2):
        engine.state.actors[foe].armor_class = 5
    assert not [c for c in engine.legal_candidates() if "Vacuum Slice" in c.display_name]
    assert [c for c in engine.legal_candidates() if "Vacuum Cut" in c.display_name]
    row = _authority()["TAL_FENCING_VACUUM_SLICE"]
    # Not automated (no effects), and the row still names the one shared roll and
    # the three things a legal shared roll must respect. The removed "lock round 3"
    # note was implementation talk, not a rule, so the assertion moved onto the
    # rule itself and is now stricter than before.
    assert not row["effects"]
    assert any("one shared attack roll" in r and "attack modes" in r and "Armor Class" in r
               and "reaction choices" in r for r in row["riders"])


# ================================================================================================================ Force
import importlib.util  # noqa: E402

_SPEC = importlib.util.spec_from_file_location("review_sw_force", ROOT / "tests/test_review_sw-force.py")
SWF = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(SWF)
F = "TAL_FORCE_"
FOE = SWF.AN


def _anchor(e, me, at):
    me.action_available = True
    SWF.cast(e, "Set Anchor", at=at)


def _anchors(e, me):
    from combat.ext import force

    return [(force.anchor_cell(e, zone).x, force.anchor_cell(e, zone).y) for zone in force.external(e, me)]


def test_set_anchor_makes_pressure_anchors_up_to_the_proficiency_bonus_the_oldest_ending():
    """Set Anchor (a base ability the catalog never listed): "create one external Pressure Anchor ... you may maintain a number of
    external Pressure Anchors equal to your Proficiency Bonus; creating another ... ends one older anchor". There was no action."""
    _, e, me, foe = SWF.fight(F + "IMPACT")
    assert not [c for c in e.legal_candidates() if c.display_name == f"Set Anchor at {foe.position.x},{foe.position.y}"]  # unwilling
    cells = [(3, 7 + n) for n in range(me.proficiency_bonus + 1)]
    for cell in cells:
        _anchor(e, me, cell)
    assert _anchors(e, me) == cells[1:]


def test_impact_can_originate_from_a_pressure_anchor_and_pushes_away_from_it():
    """Impact: "Choose yourself or one Pressure Anchor you can perceive within 60 feet as the origin. Choose one visible creature ...
    within 30 feet of that origin ... push the target 5 feet directly away from the origin". It reached 30 feet from the user only."""
    _, e, me, foe = SWF.fight(F + "IMPACT")
    foe.position = foe.position.model_copy(update={"x": 13, "y": 6})  # 50 feet away
    assert not [c for c in e.legal_candidates() if c.display_name == "Impact"]
    _anchor(e, me, (9, 5))
    me.action_available = True
    SWF.cast(e, "Impact", target=FOE)
    assert foe.current_hp < 2000
    assert (foe.position.x, foe.position.y) == (14, 7)  # directly away from the anchor at 9,5, not from the user


def test_shockwave_can_be_centred_on_a_pressure_anchor():
    _, e, me, foe = SWF.fight(F + "SHOCKWAVE")
    foe.position = foe.position.model_copy(update={"x": 10, "y": 6})
    assert not [c for c in e.legal_candidates() if c.display_name == "Shockwave at 9,6"]
    _anchor(e, me, (9, 6))
    me.action_available = True
    SWF.cast(e, "Shockwave", at=(9, 6))
    assert SWF.rolls(e, "SAVE") and foe.current_hp < 2000


def test_counterpressure_answers_a_creature_beside_one_of_your_anchors():
    """Counterpressure: "You, a creature, or an object within 5 feet of yourself or one Pressure Anchor you can perceive within 60 feet
    takes damage". It answered only within 5 feet of the user."""
    from combat import typed_reactions as tr

    _, e, me, foe = SWF.fight(F + "COUNTERPRESSURE")
    friend = SWF.ally(e, me)
    friend.position = friend.position.model_copy(update={"x": 3, "y": 11})  # 25 feet away
    _anchor(e, me, (3, 11))  # on the ally
    e._typed_pending_damage_type = "SLASHING"
    left = tr.on_damage(e, friend, 50, 0, source_actor_id=FOE)
    assert left < 50 and not me.reaction_available


def test_force_limit_stops_impact_pushing_a_creature_too_large_for_your_level():
    """Force Limit: "your Force talents can meaningfully move ... creatures up to ... CL 1-4 Large". A Huge creature was pushed."""
    _, e, me, foe = SWF.fight(F + "IMPACT", cl=1)
    e.actor_footprints[FOE] = e._footprint(foe).model_copy(update={"width_cells": 3, "height_cells": 3})
    before = (foe.position.x, foe.position.y)
    SWF.cast(e, "Impact", target=FOE)
    assert foe.current_hp < 2000 and (foe.position.x, foe.position.y) == before


def test_immovable_anchor_gives_advantage_against_being_knocked_prone():
    from combat import typed_executor as te

    _, e, me, foe = SWF.fight(F + "IMMOVABLE_ANCHOR")
    action = next(iter(e.action_catalog.values()))
    ctx = te.Context(e, foe, action, None, {"numbers": {"pb": 4, "save_dc": 10}}, [me], me, {})
    te.block_save(ctx, {"type": "save", "ability": "str", "on_fail": [{"type": "condition", "condition": "prone", "applies_to": "target"}]})
    (rolled,) = [r for r in e.rolls if r.reason.startswith("SAVE")][-1:]
    assert rolled.mode == "ADVANTAGE"


def test_clinging_anchor_puts_an_anchor_on_the_struck_creature():
    """Clinging Anchor: "When Impact hits a creature ... place one external Pressure Anchor on that creature. ... Failed Save: The anchor
    remains for the duration." It only rolled a save."""
    _, e, me, foe = SWF.fight(F + "IMPACT", extras=(F + "CLINGING_ANCHOR",))
    SWF.cast(e, "Impact", contains="Clinging", target=FOE)
    assert _anchors(e, me) == [(foe.position.x, foe.position.y)]
    assert SWF.has(foe, "force_clinging_anchor") and me.concentration is not None


def test_kinetic_reservoir_stores_what_counterpressure_caught_and_impact_releases_it():
    from combat import typed_reactions as tr

    _, e, me, foe = SWF.fight(F + "COUNTERPRESSURE", extras=(F + "KINETIC_RESERVOIR",))
    e._typed_pending_damage_type = "SLASHING"
    left = tr.on_damage(e, me, 100, 0, source_actor_id=FOE)
    (stored,) = [c for c in me.conditions.values() if c.condition_id == "condition:typed.force_stored_pressure"]
    assert stored.data["amount"] == 100 - left
    me.action_available = True
    SWF.cast(e, "Impact", target=FOE)
    impact = sum(r.total for r in SWF.rolls(e, "DAMAGE"))
    assert foe.current_hp == 2000 - impact - (100 - left)
    assert not SWF.has(me, "force_stored_pressure")


def test_recoil_ward_pushes_the_creature_whose_damage_counterpressure_reduced():
    from combat import typed_reactions as tr

    _, e, me, foe = SWF.fight(F + "COUNTERPRESSURE", extras=(F + "RECOIL_WARD",))
    before, qi = foe.position.x, me.resources["resource:core.qi"]
    e._typed_pending_damage_type = "SLASHING"
    tr.on_damage(e, me, 100, 0, source_actor_id=FOE)
    assert foe.position.x == before + 1  # 5 feet directly away from the protected creature
    assert me.resources["resource:core.qi"] == qi - 2  # Counterpressure's 1 CP and Recoil Ward's 1


def test_force_mantle_adds_the_proficiency_bonus_to_one_force_damage_roll_a_turn():
    """Owner MOD1 (merge 5c892c64) adds Impact's key modifier; Mantle adds PB only once each turn."""
    _, e, me, foe = SWF.fight(F + "FORCE_MANTLE", extras=(F + "IMPACT",))
    impact = next(a for a in e.action_catalog.values()
                  if a.owner_id == me.entity_id and F + "IMPACT" in a.source_definition_id)
    key_mod = impact.parameters["typed"]["numbers"]["key_mod"]
    assert key_mod == 2  # The compiled fixture's Path key modifier, separate from PB=4.
    SWF.cast(e, "Force Mantle")
    me.action_available = True
    L4._script(e, [15])  # Keep the hit noncritical; test flat additions independently of critical dice.
    SWF.cast(e, "Impact", target=FOE)
    first = SWF.rolls(e, "DAMAGE")[-1]
    assert first.expression == f"4d8+{key_mod + me.proficiency_bonus}"
    assert foe.current_hp == 2000 - first.total
    assert me.turn_flags.get("force_mantle_bonus") is True
    me.action_available = True
    L4._script(e, [15])  # the second attack hits too
    SWF.cast(e, "Impact", target=FOE)
    first_two = SWF.rolls(e, "DAMAGE")
    assert len(first_two) == 2 and first_two[-1].expression == f"4d8+{key_mod}"
    assert foe.current_hp == 2000 - sum(r.total for r in first_two)
    L4._new_turn(e, me.entity_id)
    assert not me.turn_flags.get("force_mantle_bonus")
    L4._script(e, [15])
    SWF.cast(e, "Impact", target=FOE)
    all_damage = SWF.rolls(e, "DAMAGE")
    assert len(all_damage) == 3 and all_damage[-1].expression == f"4d8+{key_mod + me.proficiency_bonus}"
    assert foe.current_hp == 2000 - sum(r.total for r in all_damage)


def test_world_bracing_incarnation_makes_impact_six_d10_and_pushes_ten_feet_farther():
    _, e, me, foe = SWF.fight(F + "WORLD_BRACING_INCARNATION", extras=(F + "IMPACT",))
    SWF.cast(e, "World-Bracing Incarnation")
    me.action_available = True
    x = foe.position.x
    SWF.cast(e, "Impact", target=FOE)
    assert SWF.rolls(e, "DAMAGE")[-1].expression.startswith("6d10")
    assert foe.position.x == x + 3  # 5 feet and 10 more


def test_court_of_the_answering_world_failed_save_takes_one_chosen_consequence():
    """Court of the Answering World: "Failed Save: Choose one: push it 10 feet ...; knock it Prone; reduce its Speed to 0 ...; deal 2d8".
    All four landed on every failure."""
    _, e, me, foe = SWF.fight(F + "COURT_OF_THE_ANSWERING_WORLD", dc=50)
    SWF.cast(e, "Court of the Answering World")
    where = (foe.position.x, foe.position.y)
    e.end_turn()
    assert SWF.has(foe, "prone") and foe.current_hp == 2000 and (foe.position.x, foe.position.y) == where


def test_hammerfall_adds_the_proficiency_bonus_when_the_push_hits_a_wall():
    _, e, me, foe = SWF.fight(F + "IMPACT", extras=(F + "HAMMERFALL",))
    e.grid.blocked.add((5, 6))
    e._wall_base = None
    SWF.cast(e, "Impact", contains="Hammerfall", target=FOE)
    rolled = sum(r.total for r in SWF.rolls(e, "DAMAGE"))
    assert foe.current_hp == 2000 - rolled - me.proficiency_bonus


def test_compression_field_knocks_prone_a_creature_already_slowed_by_it():
    from combat import typed_executor as te

    _, e, me, foe = SWF.fight(F + "COMPRESSION_FIELD", dc=50)
    SWF.cast(e, "Compression Field")
    action = next(a for a in e.action_catalog.values() if a.owner_id == me.entity_id and a.display_name == "Compression Field")
    ctx = te.Context(e, me, action, None, {"numbers": {"pb": 4, "save_dc": 50}}, [foe], foe, {})
    te.run_effects(ctx, [{"type": "force_compression_prone"}])
    assert not SWF.has(foe, "prone")  # not slowed by it yet
    e._add_modifier(foe, action.source_definition_id, "speed_ft", "ADD", -10, "SELF", expires_on="UNTIL_REMOVED")
    te.run_effects(ctx, [{"type": "force_compression_prone"}])
    assert SWF.has(foe, "prone")


FORCE_CLEARED = [F + key for key in ("ANCHORED_PASSAGE", "CASCADING_COLLISION", "CLINGING_ANCHOR", "COMPRESSION_FIELD", "COUNTERPRESSURE",
                                     "CUSHION_THE_BLOW", "FORCE_MANTLE", "HAMMERFALL", "IMMOVABLE_ANCHOR", "INVISIBLE_MOUNTAIN", "KINETIC_RESERVOIR",
                                     "PRESSURE_PIN", "RECOIL_WARD", "REFUSE_THE_MOVEMENT")]


def test_force_lines_now_run_by_the_table_are_no_longer_gm_riders():
    mechanics = _authority()
    assert {key: mechanics[key]["coverage"] for key in FORCE_CLEARED} == {key: "FULL" for key in FORCE_CLEARED}


# ================================================================================================================ Shadow
S = "TAL_SHADOW_"
SH = "tianxia.talent.shadow."
SHADOW = "tianxia.sphere.shadow"


def _shadow(key, extras=(), dc=50, cl=20):
    return SWF.fight(key, cl=cl, dc=dc, extras=tuple(extras))


def _shadow_anchors(e, me):
    from combat.ext import shadow

    return [(shadow._cell_of(e, zone).x, shadow._cell_of(e, zone).y) for zone in shadow.external(e, me)]


def test_second_silhouette_makes_a_shadow_anchor_on_a_square():
    """Second Silhouette, Space or Object: "Create one Shadow Anchor. The anchor lasts for 1 hour." It was not automated."""
    _, e, me, foe = _shadow(S + "SHADOW_STEP")
    SWF.cast(e, "Second Silhouette: Shadow Anchor", at=(6, 6))
    assert _shadow_anchors(e, me) == [(6, 6)]


def test_long_road_between_lanterns_carries_you_and_an_ally_from_one_anchor_to_another():
    """Long Road Between Lanterns: "Teleport from one of your Shadow Anchors into another ... bring willing creatures ... within 5 feet of
    the starting anchor ... arrive within 5 feet of the destination anchor." It had no effects."""
    _, e, me, foe = _shadow(S + "SHADOW_STEP", extras=(S + "LONG_ROAD_BETWEEN_LANTERNS",))
    friend = SWF.ally(e, me)  # at 3,7
    SWF.cast(e, "Second Silhouette: Shadow Anchor", at=(2, 6))  # beside you, and within 5 feet of the ally at 3,7
    me.action_available = True
    SWF.cast(e, "Second Silhouette: Shadow Anchor", at=(12, 10))
    me.action_available = True
    SWF.cast(e, "Long Road Between Lanterns", at=(12, 11))
    assert (me.position.x, me.position.y) == (12, 11)
    assert e.grid.distance_ft(friend.position, me.position) <= 10 and abs(friend.position.x - 12) <= 1 and abs(friend.position.y - 10) <= 1


def test_court_of_the_second_silhouette_failed_save_takes_one_chosen_consequence():
    """Court of the Second Silhouette: "When an enemy starts its turn inside the Domain ... Failed Save: Choose one". The typing made each
    choice its own cast that saved at once; the domain's start-of-turn save never happened."""
    _, e, me, foe = _shadow(S + "COURT_OF_THE_SECOND_SILHOUETTE")
    SWF.cast(e, "Court of the Second Silhouette")
    assert not SWF.rolls(e, "SAVE")
    e.end_turn()
    assert SWF.rolls(e, "SAVE") and SWF.has(foe, "reaction_denied") and foe.current_hp == 2000


def test_court_of_the_second_silhouette_gives_allies_inside_plus_one_ac():
    from combat.ext import shadow

    _, e, me, foe = _shadow(S + "COURT_OF_THE_SECOND_SILHOUETTE")
    assert shadow.court_ac(e, me) is None
    SWF.cast(e, "Court of the Second Silhouette")
    assert shadow.court_ac(e, me) == 1 and shadow.court_ac(e, foe) is None


def test_seize_the_second_body_drags_the_creature_after_its_shadow():
    _, e, me, foe = _shadow(S + "SEIZE_THE_SECOND_BODY")
    foe.position = foe.position.model_copy(update={"x": 9, "y": 6})
    L4._script(e, [15])
    SWF.cast(e, "Second Silhouette: Unwilling Creature", target=FOE)
    me.action_available = True  # The printed control action requires our actual mark.
    SWF.cast(e, "Seize the Second Body: Move Shadow and Body", target=FOE)
    assert e.grid.distance_ft(foe.position, me.position) < 30  # moved toward the user, up to 20 feet


def test_seize_the_second_body_can_reduce_speed_to_zero():
    _, e, me, foe = _shadow(S + "SEIZE_THE_SECOND_BODY")
    L4._script(e, [15])
    SWF.cast(e, "Second Silhouette: Unwilling Creature", target=FOE)
    me.action_available = True
    SWF.cast(e, "Seize the Second Body: Reduce Speed to 0", target=FOE)
    assert e._effective_speed(foe) == 0


def test_sever_the_second_silhouette_stops_the_target_and_leaves_its_shadow_as_an_anchor():
    _, e, me, foe = _shadow(S + "SEVER_THE_SECOND_SILHOUETTE")
    L4._script(e, [15])
    SWF.cast(e, "Second Silhouette: Unwilling Creature", target=FOE)
    me.action_available = True
    SWF.cast(e, "Sever the Second Silhouette", target=FOE)
    assert e._effective_speed(foe) == 0 and SWF.has(foe, "reaction_denied")
    assert _shadow_anchors(e, me) == [(foe.position.x, foe.position.y)]


def test_shadow_lurk_is_a_summoned_scout_whose_destruction_stuns_its_source():
    """Shadow Lurk: "Detach the target's Cast Shadow as a loyal scout ... AC 10 + your Proficiency Bonus, HP equal to your CL ... If the lurk
    is reduced to 0 HP ... the target becomes Stunned until the end of its next turn." It was a 300-foot zone around the user."""
    _, e, me, foe = _shadow(SH + "shadow_lurk")
    SWF.cast(e, "Shadow Lurk")
    lurk = next(a for a in e.state.actors.values() if (getattr(a, "summon", None) or {}).get("group") == "shadow_lurk")
    assert lurk.active and lurk.armor_class == 10 + me.proficiency_bonus and lurk.maximum_hp == 20
    e._commit_damage(lurk, lurk.current_hp, "SLASHING", "test", FOE, None, reaction_depth=0)
    assert SWF.has(me, "stunned")


def _slip_duel(talents, ally=False):
    engine = L4._duel(list(talents), subject_sphere=SHADOW, attacker_kit=t.AXE_KIT)
    subject = engine.state.actors[L4.SUBJ]
    return engine, subject


def test_shadowless_reversal_slips_out_of_a_hit_and_leaves_a_snaring_silhouette():
    """Shadowless Reversal: "Leave a false silhouette behind and use Shadow Step immediately. If you move outside the attack's reach ... the
    attack misses." Its typing had the attacker make the silhouette's save."""
    engine, subject = _slip_duel([S + "SHADOWLESS_REVERSAL"])
    pool = "resource:core.stamina"
    qi = subject.resources[pool]
    L4._script(engine, [15, 6])
    events = L4._use(engine, "Fu (Short Axe) attack")
    assert L4._hp_lost(events) == 0 and engine.grid.distance_ft(subject.position, engine.state.actors[L4.ME].position) > 5
    assert not subject.reaction_available and subject.resources[pool] == qi - 5
    from combat.ext import placed

    assert placed.of(engine, "shadow_silhouette")


def test_shadow_exchange_teleports_the_struck_creature_out_of_reach():
    engine, subject = _slip_duel([S + "SHADOW_EXCHANGE"])
    pool = "resource:core.stamina"
    qi = subject.resources[pool]
    L4._script(engine, [15, 6])
    events = L4._use(engine, "Fu (Short Axe) attack")
    assert L4._hp_lost(events) == 0 and engine.grid.distance_ft(subject.position, engine.state.actors[L4.ME].position) > 5
    assert subject.resources[pool] == qi - 4


def test_two_shadows_crossing_brings_an_adjacent_ally_along():
    _, e, me, foe = _shadow(S + "SHADOW_STEP", extras=(S + "TWO_SHADOWS_CROSSING",))
    friend = SWF.ally(e, me)
    cands = [c for c in e.legal_candidates() if c.display_name.startswith("Shadow Step + Two Shadows Crossing to 6,")]
    assert cands
    SWF.cast(e, "Shadow Step + Two Shadows Crossing", at=(cands[0].destination.x, cands[0].destination.y))
    assert e.grid.distance_ft(friend.position, me.position) <= 5 and (friend.position.x, friend.position.y) != (3, 7)


def test_long_shadow_steps_your_full_speed():
    _, e, me, foe = _shadow(S + "SHADOW_STEP", extras=(SH + "long_shadow",))
    far = [c for c in e.legal_candidates() if c.display_name.startswith("Shadow Step + Long Shadow to ")
           and e.grid.distance_ft(c.destination, me.position) > e._effective_speed(me) // 2]
    assert far


def test_shadow_sovereign_steps_sixty_feet_once_a_turn_without_cp_and_marks_with_a_missed_fang():
    _, e, me, foe = _shadow(S + "SHADOW_SOVEREIGN_INCARNATION", extras=(S + "SHADOW_STEP", SH + "shadow_fang"))
    SWF.cast(e, "Shadow-Sovereign Incarnation")
    me.bonus_action_available = True
    qi = me.resources["resource:core.qi"]
    SWF.cast(e, "Shadow Step (Shadow-Sovereign, 60 feet)", at=(13, 6))
    assert (me.position.x, me.position.y) == (13, 6) and me.resources["resource:core.qi"] == qi
    me.action_available = True
    foe.armor_class = 99
    L4._script(e, [2])
    SWF.cast(e, "Shadow Fang", target=FOE)
    from combat.typed_executor import bears_mark

    assert bears_mark(foe, me.entity_id, "Shadow Mark")


def test_ambush_from_below_deals_its_printed_dice_only():
    auth = _authority()["TAL_SHADOW_AMBUSH_FROM_BELOW"]
    damage = auth["effects"][0]["on_fail"][0]
    assert "formula" not in damage and damage["dice_by_cl"][0] == [5, 10, 3, 8]


def test_a_shadow_mark_lasts_until_the_start_of_your_next_turn_unless_a_talent_says_otherwise():
    _, e, me, foe = _shadow(SH + "shadow_fang")
    L4._script(e, [15])
    SWF.cast(e, "Shadow Fang", target=FOE)
    (mark,) = [c for c in foe.conditions.values() if "shadow_mark" in c.condition_id]
    assert mark.expires_on == "START_OF_MARKER_NEXT_TURN"


def test_grasping_silhouette_restrains_a_creature_marked_through_second_silhouette():
    _, e, me, foe = _shadow(S + "SECOND_SILHOUETTE", extras=(SH + "grasping_silhouette",))
    L4._script(e, [15])
    SWF.cast(e, "Second Silhouette: Unwilling Creature + Grasping Silhouette", target=FOE)
    assert SWF.has(foe, "restrained")


def test_lingering_trace_keeps_the_mark_for_the_fight():
    _, e, me, foe = _shadow(S + "SECOND_SILHOUETTE", extras=(SH + "lingering_trace",))
    L4._script(e, [15])
    SWF.cast(e, "Second Silhouette: Unwilling Creature + Lingering Trace", target=FOE)
    (mark,) = [c for c in foe.conditions.values() if "shadow_mark" in c.condition_id]
    from combat.typed_executor import clock_expiry
    assert mark.expires_on == clock_expiry(e, "hours", 8) and mark.data.get("lingering")


def test_silhouette_veil_gives_the_first_opportunity_attack_each_round_disadvantage():
    from combat.ext import shadow
    from combat.typed_executor import Context

    _, e, me, foe = _shadow(SH + "silhouette_veil")
    SWF.cast(e, "Silhouette Veil")
    action = next(iter(e.action_catalog.values()))
    ctx = Context(e, foe, action, None, {"opportunity_of": "x"}, [me], me)
    assert shadow.veil_first_opportunity(ctx, me) == "DISADVANTAGE"
    assert shadow.veil_first_opportunity(ctx, me) is None


def test_world_of_living_shadows_strips_enemies_invisible_and_steadies_allies():
    from combat.ext import shadow

    _, e, me, foe = _shadow(S + "WORLD_OF_LIVING_SHADOWS")
    SWF.cast(e, "World of Living Shadows", at=(4, 6))
    assert shadow.world_ac(e, me) == 1
    e._apply_condition(foe, "condition:typed.invisible", "test", FOE, expires_on="UNTIL_REMOVED")
    assert shadow.world_invisible(e, me, foe)
    assert shadow.world_perception(e, foe, me) == "DISADVANTAGE"


def test_shadow_ward_reduces_by_its_printed_dice():
    auth = _authority()["tianxia.talent.shadow.shadow_ward"]
    assert auth["effects"][0]["dice_by_cl"] == [[1, 10, 1, 8], [11, 16, 2, 8], [17, 20, 3, 8]]


# ================================================================================================================ Destruction
DZ = "tianxia.talent.destruction."
BLAST = "TAL_DESTRUCTION_DESTRUCTIVE_BLAST"


def _ruin(*talents, dc=50, cl=20):
    return SWF.fight(BLAST, cl=cl, dc=dc, extras=tuple(DZ + t for t in talents))


def _pick(e, me, name):
    me.action_available = me.bonus_action_available = True
    SWF.cast(e, name)
    me.action_available = me.bonus_action_available = True


def _blast(e, me, name="Destructive Blast", **kw):
    me.action_available = me.bonus_action_available = True
    L4._script(e, [15])
    SWF.cast(e, name, **kw)


def _dmg(e):
    return [ev.payload for ev in e.events if ev.event_type == "DAMAGE_COMMITTED"]


def test_withering_break_is_a_blast_type_that_stops_healing():
    """Withering Break: "Destruction Die: d6, Damage Type: Necrotic. A creature damaged by Withering Break cannot regain Hit Points until the
    start of your next turn." The Blast Type list left it out: there was no way to choose it."""
    _, e, me, foe = _ruin("withering_break")
    _pick(e, me, "Blast Type: Withering Break")
    _blast(e, me, target=FOE)
    assert _dmg(e)[-1]["damage_type"] == "NECROTIC"
    assert [m for m in foe.modifiers.values() if "heal" in m.target_field] or [c for c in foe.conditions.values() if "heal" in c.condition_id]


def test_ashen_denial_strips_temporary_hp_before_withering_break_lands():
    _, e, me, foe = _ruin("withering_break", "ashen_denial")
    foe.temporary_hp = 10
    _pick(e, me, "Blast Type: Withering Break")
    _blast(e, me, target=FOE)
    assert foe.temporary_hp == 0 and _dmg(e)[-1].get("temporary_hp_absorbed", 0) == 0 and SWF.has(foe, "no_temp_hp")


def test_unmaking_pressure_suppresses_a_temporary_ac_bonus_until_your_next_turn():
    _, e, me, foe = _ruin("unmaking_pressure")
    e._add_modifier(foe, "test:shield", "armor_class", "ADD", 2, "ALL_ATTACKS", expires_on="UNTIL_REMOVED_LATER")
    _pick(e, me, "Blast Type: Unmaking Pressure")
    _blast(e, me, target=FOE)
    assert not [m for m in foe.modifiers.values() if m.source_definition_id == "test:shield"]
    from combat.ext import destruction_blast

    destruction_blast.restore_suppressed(e, me)
    assert [m for m in foe.modifiers.values() if m.source_definition_id == "test:shield" and m.value == 2]


def test_staggering_break_gives_disadvantage_on_the_next_concentration_save():
    _, e, me, foe = _ruin("staggering_break")
    _pick(e, me, "Blast Type: Staggering Break")
    _blast(e, me, target=FOE)
    rules = [c.data.get("rule") for c in foe.conditions.values() if c.condition_id == "condition:typed.concentration_mode"]
    assert rules == [{"concentration_mode": "DISADVANTAGE", "next": True}]


def test_break_the_guard_can_deny_half_cover():
    _, e, me, foe = _ruin("fracturing_break", "break_the_guard")
    _pick(e, me, "Blast Type: Fracturing Break")
    _pick(e, me, "Break the Guard: Ignore Half Cover")
    _blast(e, me, target=FOE)
    assert any(c.condition_id == "condition:an_eui.break_guard.no_half_cover" for c in foe.conditions.values())


def test_field_of_falling_forms_denies_half_cover_to_a_creature_blasted_inside_it():
    _, e, me, foe = _ruin("destructive_domain_field_of_falling_forms")
    _pick(e, me, "Destructive Domain: Field of Falling Forms")
    _blast(e, me, target=FOE)
    assert any(c.condition_id == "condition:an_eui.break_guard.no_half_cover" for c in foe.conditions.values())


def test_court_of_the_last_impact_knocks_prone_the_first_creature_failing_a_blast_save_each_round():
    _, e, me, foe = _ruin("destructive_domain_court_of_the_last_impact", "calamity_form")
    _pick(e, me, "Destructive Domain: Court of the Last Impact")
    me.action_available = True
    SWF.cast(e, "Calamity Form: Sphere", at=(foe.position.x, foe.position.y))
    assert SWF.has(foe, "prone")


def test_scouring_break_litters_a_blast_area_with_splinters():
    from combat.ext import placed

    _, e, me, foe = _ruin("scouring_break", "calamity_form")
    _pick(e, me, "Blast Type: Scouring Break")
    SWF.cast(e, "Calamity Form: Sphere", at=(foe.position.x, foe.position.y))
    (zone,) = placed.of(e, "scouring_splinters")
    assert zone.trigger_profile["difficult"] == "all"


def test_deepen_the_calamity_pays_one_cp_for_a_die_per_two_levels():
    """Deepen the Calamity (a core ability the catalog never listed): "Cost: 1 CP ... 1 Destruction Die + 1 additional Destruction Die per 2
    Cultivation Levels" -- 11 dice at CL 20."""
    _, e, me, foe = _ruin()
    qi = me.resources["resource:core.qi"]
    _pick(e, me, "Deepen the Calamity: on")
    _blast(e, me, target=FOE)
    assert SWF.rolls(e, "DAMAGE")[-1].expression.startswith("11d8") and me.resources["resource:core.qi"] == qi - 1


def test_catastrophe_engine_and_heaven_cracking_release_ride_deepen_the_calamity():
    _, e, me, foe = _ruin("calamity_form", "catastrophe_engine", "heaven_cracking_release")
    qi = me.resources["resource:core.qi"]
    _pick(e, me, "Deepen the Calamity: on")
    _pick(e, me, "Heaven-Cracking Release: next Deepened blast")
    SWF.cast(e, "Calamity Form: Cone (1 CP)", at=(foe.position.x, foe.position.y))
    assert me.resources["resource:core.qi"] == qi - 1 - 1 + 1 - 2  # the cone, Deepen, Catastrophe Engine's refund, Heaven-Cracking
    assert SWF.has(foe, "reaction_denied") and [m for m in foe.modifiers.values() if m.target_field == "speed_halved"]


def test_ruin_that_remembers_leaves_a_trace_the_next_blast_consumes_for_two_dice():
    from combat.typed_executor import bears_mark

    _, e, me, foe = _ruin("ruin_that_remembers")
    _blast(e, me, target=FOE)
    assert bears_mark(foe, me.entity_id, "Ruin Trace")
    _blast(e, me, target=FOE)
    assert not bears_mark(foe, me.entity_id, "Ruin Trace") and [r for r in e.rolls if r.reason.endswith(":ruin_trace")]


def test_calamity_chain_reaction_bursts_into_a_creature_near_one_it_dropped():
    _, e, me, foe = _ruin("calamity_chain_reaction")
    other = foe.model_copy(deep=True)
    other.entity_id, other.position = "review:foe2", foe.position.model_copy(update={"y": foe.position.y + 1})
    e.state.actors[other.entity_id] = other
    foe.current_hp = 1
    _blast(e, me, target=FOE)
    assert not foe.active and other.current_hp < 2000


def test_calamity_sovereign_takes_one_cp_off_an_augment_once_a_turn():
    _, e, me, foe = _ruin("calamity_sovereign_incarnation", "calamity_form")
    _pick(e, me, "Calamity-Sovereign Incarnation")
    qi = me.resources["resource:core.qi"]
    SWF.cast(e, "Calamity Form: Cone (1 CP)", at=(foe.position.x, foe.position.y))
    assert me.resources["resource:core.qi"] == qi


# ================================================================================================================ Monkey Style
MS = "TAL_MONKEY_STYLE_"
MONKEY = "tianxia.sphere.monkey_style"
_SPEC_M = importlib.util.spec_from_file_location("review_sw_monkey", ROOT / "tests/test_review_sw-monkey_style.py")
SWM = importlib.util.module_from_spec(_SPEC_M)
_SPEC_M.loader.exec_module(SWM)


def _monkey(*talents, dc=50, cl=20, weapon="gun"):
    """A Monkey Style fighter with both hands available to its selected weapon."""
    bundle, engine, actor, foe = SWM.fight(MS + "CAPERING_FOOTWORK", cl=cl, dc=dc,
                                         extras=tuple(MS + t for t in talents))
    # The fixture carries a sword, staff and bow. Use real equipment actions
    # to ready only the weapon delivering the technique this test exercises.
    from tests.test_typed_executor import _intent
    from combat.ext.hand_occupancy import weapon_grips
    target = next(action.source_definition_id for action in engine.action_catalog.values()
                  if action.owner_id == actor.entity_id and action.source_definition_id.endswith(".weapon." + weapon))
    def equip(identity, held):
        source = next(action.source_definition_id for action in engine.action_catalog.values()
                      if (action.parameters.get("equipment_grip") or {}).get("held") == held
                      and action.parameters["equipment_grip"]["weapon"] == identity)
        selected = next(candidate for candidate in engine.legal_candidates()
                        if candidate.actor_id == actor.entity_id and candidate.source_definition_id == source)
        engine.execute_intent(_intent(selected))
    for spare in weapon_grips(engine, actor):
        if spare != target:
            equip(spare, 0)
    if target not in weapon_grips(engine, actor):
        equip(target, 1)
    return bundle, engine, actor, foe


def _links(actor):
    return [c for c in actor.conditions.values() if c.condition_id == "condition:typed.monkey_link"]


def _give_link(e, me):
    from combat.ext import monkey

    monkey.create(e, me, "test", "test", counted=False)


def test_capering_footwork_makes_a_link_after_moving_and_a_staff_hit_spends_it_on_tap():
    """The Monkey Chain: "create one Monkey Link per turn when you ... move at least 10 feet before making an attack" and "when you hit with a
    Monkey Style attack ... spend your Monkey Link on ... TAP: Deal extra Bludgeoning damage equal to your Proficiency Bonus". There were no
    links: Capering Footwork gained and spent a point at once."""
    _, e, me, foe = _monkey()
    SWM.cast(e, "Capering Footwork")
    me.position = me.position.model_copy(update={"x": 1})
    e._append_event("MOVEMENT_COMMITTED", "test", actor_id=me.entity_id, payload={"cost_ft": 10, "destination": {"x": 3, "y": 6}})
    me.position = me.position.model_copy(update={"x": 3})
    L4._script(e, [15])
    SWM.cast(e, "Gun (Staff) attack", target=FOE)
    taps = [p for p in _dmg(e) if p.get("damage_type") == "BLUDGEONING"]
    assert not _links(me) and me.turn_flags.get("monkey_links_spent") == 1
    assert any(ev.event_type == "PASSIVE_TRIGGERED" and "creates a Monkey Link" in str((ev.payload or {}).get("log")) for ev in e.events)
    assert len(taps) >= 2  # the staff's own hit and the Tap Finish


def _dex_saves(e):
    return [ev for ev in e.events if ev.event_type == "SAVE_ROLLED" and "DEX" in str((ev.payload or {}).get("reason") or (ev.payload or {}).get("ability") or ev.payload)]


def test_laughing_trip_spends_a_link_to_trip():
    """Laughing Trip: "Hit: Deal normal damage. If you have a Monkey Link, you may spend it to force the target to make a Dexterity saving throw."
    The save came on every hit, link or not. (A staff's own Topple mastery may still knock it Prone: that is a Constitution save.)"""
    _, e, me, foe = _monkey("LAUGHING_TRIP")
    L4._script(e, [15])
    SWM.cast(e, "Laughing Trip", target=FOE)
    assert not _dex_saves(e)  # no link: the trip is only a hit
    me.action_available = True
    _give_link(e, me)
    L4._script(e, [15])
    SWM.cast(e, "Laughing Trip", target=FOE)
    assert _dex_saves(e) and not _links(me)


def test_vaulting_strike_needs_ten_feet_of_movement_first():
    _, e, me, foe = _monkey("VAULTING_STRIKE", weapon="jian")
    assert not [c for c in e.legal_candidates() if c.display_name == "Vaulting Strike"]
    e._append_event("MOVEMENT_COMMITTED", "test", actor_id=me.entity_id, payload={"cost_ft": 10})
    assert [c for c in e.legal_candidates() if c.display_name == "Vaulting Strike"]


def test_stone_skipping_strike_ricochets_with_a_link():
    _, e, me, foe = _monkey("STONE_SKIPPING_STRIKE", weapon="gong_jian")
    other = foe.model_copy(deep=True)
    other.entity_id, other.position = "review:foe2", foe.position.model_copy(update={"y": foe.position.y + 1})
    e.state.actors[other.entity_id] = other
    _give_link(e, me)
    L4._script(e, [15, 3, 3, 3, 3, 3, 15])
    SWM.cast(e, "Stone-Skipping", target=FOE)
    assert other.current_hp < 2000 and not _links(me)


def test_mischievous_feint_baits_a_link_bound_to_its_target():
    _, e, me, foe = _monkey("MISCHIEVOUS_FEINT")
    SWM.cast(e, "Capering Footwork")  # Mischievous Feint rides every Capering Footwork (it costs nothing)
    (link,) = _links(me)
    assert link.data.get("only_target") == FOE


def _monkey_duel(*talents):
    engine = L4._duel([MS + t for t in talents], subject_sphere=MONKEY, attacker_kit=t.AXE_KIT)
    return engine, engine.state.actors[L4.SUBJ]


def test_drunken_monkey_stance_steps_away_from_a_melee_miss_and_makes_a_link():
    engine, monkey_fighter = _monkey_duel("DRUNKEN_MONKEY_STANCE")
    L4._new_turn(engine, L4.SUBJ)
    monkey_fighter.bonus_action_available = True
    from tests.test_riders_lane10 import _as

    _as(engine, L4.SUBJ, "Drunken Monkey Stance")
    start = monkey_fighter.position
    engine.state.actors[L4.ME].position = engine.state.actors[L4.ME].position  # the Brute stands beside it
    L4._new_turn(engine, L4.ME)
    L4._script(engine, [1])
    L4._use(engine, "Fu (Short Axe) attack")
    assert _links(monkey_fighter) and monkey_fighter.position != start


def test_court_of_the_laughing_sage_holds_two_links_and_tests_the_first_attack():
    from combat.ext import monkey

    engine, monkey_fighter = _monkey_duel("COURT_OF_THE_LAUGHING_SAGE")
    from tests.test_riders_lane10 import _as

    _as(engine, L4.SUBJ, "Court of the Laughing Sage")
    assert monkey.hold_cap(engine, monkey_fighter) == 2
    L4._new_turn(engine, L4.ME)
    L4._script(engine, [1, 15])  # the Wisdom save's 1 comes before the attack's d20
    events = L4._use(engine, "Fu (Short Axe) attack")
    assert [p for p in L4._saves(events)] and any(e.event_type == "ATTACK_ROLLED" and (e.payload or {}).get("mode") == "DISADVANTAGE" for e in events)


def test_great_sage_laughs_at_heaven_once():
    from combat import typed_executor as te

    _, e, me, foe = _monkey("GREAT_SAGE_EQUAL_TO_HEAVEN")
    SWM.cast(e, "Great Sage")
    action = next(iter(e.action_catalog.values()))
    ctx = te.Context(e, foe, action, None, {"numbers": {"pb": 4, "save_dc": 99}}, [me], me, {})
    te.block_save(ctx, {"type": "save", "ability": "con", "on_fail": [{"type": "condition", "condition": "poisoned", "applies_to": "target"}]})
    assert not SWM.has(me, "poisoned") and SWM.has(me, "monkey_laughed")
    te.block_save(ctx, {"type": "save", "ability": "con", "on_fail": [{"type": "condition", "condition": "poisoned", "applies_to": "target"}]})
    assert SWM.has(me, "poisoned")  # once per transformation


def test_thousand_monkey_uprising_tests_an_attacking_enemy_and_covers_allies():
    from combat.ext import monkey

    engine, monkey_fighter = _monkey_duel("THOUSAND_MONKEY_UPRISING")
    from tests.test_riders_lane10 import _as

    _as(engine, L4.SUBJ, "Thousand-Monkey Uprising")
    brute = engine.state.actors[L4.ME]
    friend = monkey_fighter.model_copy(deep=True)
    friend.entity_id = "review:monkey_ally"
    friend.position = friend.position.model_copy(update={"y": friend.position.y + 2})
    engine.state.actors[friend.entity_id] = friend
    assert monkey.uprising_cover(engine, brute, friend) == 2
    L4._new_turn(engine, L4.ME)
    L4._script(engine, [1, 15])  # the Wisdom save fails
    L4._use(engine, "Fu (Short Axe) attack")
    assert L4._has(brute, "prone")


def test_staff_of_the_laughing_sage_offers_its_staff_finishes():
    from combat.ext import monkey

    _, e, me, foe = _monkey("STAFF_OF_THE_LAUGHING_SAGE")
    from combat import typed_executor as te

    action = next(a for a in e.action_catalog.values() if a.owner_id == me.entity_id and a.display_name == "Gun (Staff) attack")
    ctx = te.Context(e, me, action, None, dict(action.parameters["typed"]), [foe], foe, {})
    assert "sweeping_tail" in monkey._finish_options(ctx, foe)


def test_heaven_uprooting_staff_spends_a_link_for_a_wider_strike():
    _, e, me, foe = _monkey("HEAVEN_UPROOTING_STAFF")
    assert not [c for c in e.legal_candidates() if "Monkey Link: 40 feet" in c.display_name]
    _give_link(e, me)
    assert [c for c in e.legal_candidates() if "Monkey Link: 40 feet" in c.display_name]


def test_snatch_and_scatter_can_make_a_link():
    auth = _authority()["TAL_MONKEY_STYLE_SNATCH_AND_SCATTER"]
    assert "Create a Monkey Link" in [o["label"] for o in auth["options"]]
    disarm = next(o for o in auth["options"] if o["label"] == "Disarm Attacker")
    assert disarm["effects"][0]["on_fail"][0]["condition"] == "disarmed"


def test_mirror_monkey_afterimages_draw_attacks_away():
    """Mirror-Monkey Technique: "When you are targeted by an attack, roll 1d6. 1-2: The attack targets an afterimage ... An afterimage disappears
    when it is targeted." It had no effects at all."""
    engine, monkey_fighter = _monkey_duel("MIRROR_MONKEY_TECHNIQUE")
    from tests.test_riders_lane10 import _as

    _as(engine, L4.SUBJ, "Mirror-Monkey Technique")
    (mirror,) = [c for c in monkey_fighter.conditions.values() if c.condition_id == "condition:typed.monkey_mirror"]
    assert mirror.data["images"] == 2
    L4._new_turn(engine, L4.ME)
    L4._script(engine, [1, 15, 6])  # the d6 picks an afterimage; the attack would have hit
    events = L4._use(engine, "Fu (Short Axe) attack")
    assert L4._hp_lost(events) == 0
    (mirror,) = [c for c in monkey_fighter.conditions.values() if c.condition_id == "condition:typed.monkey_mirror"]
    assert mirror.data["images"] == 1


# ================================================================================================================ Disease
DS = "tianxia.talent.disease."
SOW = "DISEASE_BASE_SOW_THE_FEVER_SEED"


def _plague(*talents, dc=50, cl=20):
    return SWF.fight(SOW, cl=cl, dc=dc, extras=tuple(DS + t for t in talents))


def test_contagion_tokens_stack_and_a_spent_one_leaves_the_rest():
    """"A creature bearing at least two of your Contagion Tokens": tokens were a single mark, so two never stacked."""
    from combat.ext import disease

    _, e, me, foe = _plague()
    L4._script(e, [15])
    SWF.cast(e, "Sow the Fever Seed", target=FOE)
    disease.add_tokens(e, me, foe, 1, "test")
    assert disease.tokens(e, me, foe) == 2
    disease.spend_token(e, me, foe, "test")
    assert disease.tokens(e, me, foe) == 1


def test_quarantine_veil_outbreak_mode_sickens_an_enemy_starting_its_turn_inside():
    """Raise the Quarantine Veil, Outbreak Mode: "When an enemy enters the area ... or starts its turn there, it must make a Constitution saving
    throw. Failed Save: 1d6 ... and becomes Sickened". The veil was an empty zone with both modes as GM text."""
    _, e, me, foe = _plague()
    SWF.cast(e, "Raise the Quarantine Veil: Outbreak Mode", at=(foe.position.x, foe.position.y))
    e.end_turn()
    assert foe.current_hp < 2000 and SWF.has(foe, "sickened")


def test_quarantine_veil_containment_gives_allies_advantage_against_disease():
    from combat import typed_executor as te

    _, e, me, foe = _plague()
    SWF.cast(e, "Raise the Quarantine Veil: Containment Mode", at=(me.position.x, me.position.y))
    action = next(a for a in e.action_catalog.values() if a.owner_id == me.entity_id and "Sow the Fever Seed" == a.display_name)
    ctx = te.Context(e, foe, action, None, {"numbers": {"pb": 4, "save_dc": 10}}, [me], me, {})
    te.block_save(ctx, {"type": "save", "ability": "con", "on_fail": [{"type": "condition", "condition": "sickened", "applies_to": "target"}]})
    assert [r for r in e.rolls if r.reason.startswith("SAVE")][-1].mode == "ADVANTAGE"


def test_epidemic_surge_spends_a_token_from_each_bearer():
    from combat.ext import disease

    _, e, me, foe = _plague("epidemic_surge")
    other = foe.model_copy(deep=True)
    other.entity_id, other.position = "review:foe2", foe.position.model_copy(update={"y": foe.position.y + 2})
    e.state.actors[other.entity_id] = other
    disease.add_tokens(e, me, foe, 2, "test")
    disease.add_tokens(e, me, other, 1, "test")
    SWF.cast(e, "Epidemic Surge", target=FOE)
    assert disease.tokens(e, me, foe) == 1 and disease.tokens(e, me, other) == 0
    assert foe.current_hp < 2000 and other.current_hp < 2000


def test_plague_eruption_spends_a_token_for_extra_damage_on_a_failed_save():
    from combat.ext import disease

    _, e, me, foe = _plague("plague_eruption")
    disease.add_tokens(e, me, foe, 1, "test")
    SWF.cast(e, "Plague Eruption", at=(foe.position.x, foe.position.y))
    e.end_turn()
    assert disease.tokens(e, me, foe) == 0 and [r for r in e.rolls if r.reason.endswith(":token")]


def test_infection_of_the_cultivation_breath_answers_a_token_bearer_spending_cp():
    from combat.ext import disease

    engine = L4._duel([DS + "infection_of_the_cultivation_breath"], subject_sphere="tianxia.sphere.disease")
    carrier, brute = engine.state.actors[L4.SUBJ], engine.state.actors[L4.ME]
    disease.add_tokens(engine, carrier, brute, 2, "test")
    pool = next(p for p in ("resource:core.stamina", "resource:core.qi") if p in brute.resources)
    engine._spend_resource(brute, pool, 1, "test:technique")
    assert disease.tokens(engine, carrier, brute) == 1 and not carrier.reaction_available
    assert L4._has(brute, "no_cp_regain")


def test_spreading_infection_passes_a_token_to_a_creature_beside_the_bearer():
    from combat.ext import disease

    _, e, me, foe = _plague("spreading_infection")
    other = foe.model_copy(deep=True)
    other.entity_id, other.position = "review:foe2", foe.position.model_copy(update={"y": foe.position.y + 1})
    e.state.actors[other.entity_id] = other
    disease.add_tokens(e, me, foe, 1, "test")
    disease.disease_turn_start(e, foe)
    assert disease.tokens(e, me, other) == 1 and not me.reaction_available


def test_plague_sovereign_sow_deals_six_d10_and_its_presence_tests_a_nearby_enemy():
    _, e, me, foe = _plague("plague_sovereign_incarnation")
    SWF.cast(e, "Plague-Sovereign Incarnation")
    me.action_available = True
    L4._script(e, [15])
    SWF.cast(e, "Sow the Fever Seed", target=FOE)
    assert SWF.rolls(e, "DAMAGE")[-1].expression.startswith("6d10")
    from combat.ext import disease

    before = foe.current_hp
    disease.disease_turn_start(e, foe)
    assert foe.current_hp < before  # the default choice: 4d8


def test_plague_bearing_body_infects_its_grappler_and_steadies_its_disease_saves():
    from combat.ext import disease

    _, e, me, foe = _plague("plague_bearing_body")
    SWF.cast(e, "Plague-Bearing Body")
    e._apply_condition(me, "condition:typed.grappled", "test", FOE, expires_on="UNTIL_REMOVED")
    disease.disease_turn_start(e, foe)
    assert disease.tokens(e, me, foe) == 1


def test_purging_breath_removes_a_contagion_token():
    from combat.ext import disease

    _, e, me, foe = _plague("purging_breath")
    friend = SWF.ally(e, me)
    disease.add_tokens(e, me, friend, 2, "test")
    SWF.cast(e, "Purging Breath: Remove Contagion Token", target=friend.entity_id)
    assert disease.tokens(e, me, friend) == 1  # one of two stacked tokens goes; the other stays


def test_thousand_symptom_plague_puts_two_symptoms_on_a_failed_save():
    from combat import typed_executor as te

    _, e, me, foe = _plague("thousand_symptom_plague")
    SWF.cast(e, "Thousand-Symptom Plague", at=(foe.position.x, foe.position.y))
    rules = te.condition_rules(foe)
    assert any(r.get("no_reactions") for r in rules) and any(r.get("attacks_have") == "DISADVANTAGE" for r in rules)


def test_weakening_sickness_puts_its_chosen_symptom_on_a_failed_save():
    from combat import typed_executor as te

    _, e, me, foe = _plague("weakening_sickness")
    SWF.cast(e, "Weakening Sickness", target=FOE)
    assert any(r.get("no_reactions") for r in te.condition_rules(foe))


def test_coughing_breath_success_only_presses_the_next_concentration_save():
    auth = _authority()["tianxia.talent.disease.coughing_breath"]
    save = auth["modifier"]["effects"][0]
    assert [r["type"] for r in save["on_fail"]] == ["reaction_denied", "disadvantage"]
    assert "next concentration" in save["on_success"][0]["on"]


def test_living_plague_is_a_summon_whose_strike_leaves_a_token():
    from combat.ext import disease

    _, e, me, foe = _plague("living_plague")
    SWF.cast(e, "Living Plague")
    plague = next(a for a in e.state.actors.values() if (getattr(a, "summon", None) or {}).get("group") == "living_plague")
    assert plague.active and plague.armor_class == 13 + me.proficiency_bonus and plague.maximum_hp == 100
    e._append_event("DAMAGE_COMMITTED", "test", actor_id=plague.entity_id, target_ids=(FOE,), payload={"hp_damage": 5})
    assert disease.tokens(e, me, foe) == 1


# ================================================================================================================ Poison
PZ = "tianxia.talent.poison."
DELIVER = "POISON_BASE_DELIVER_THE_DOSE"


def _venom(*talents, dc=50, cl=20):
    return SWF.fight(DELIVER, cl=cl, dc=dc, extras=tuple(PZ + t for t in talents))


def test_ingrain_the_toxin_needs_and_spends_two_dose_marks():
    """Ingrain the Toxin: "Target: One creature with at least 2 Dose Marks from you ... You spend 2 Dose Marks". Marks did not stack, so the
    table could neither count two nor spend two."""
    from combat.ext import stacking_marks

    _, e, me, foe = _venom()
    stacking_marks.add(e, me, foe, "Dose Mark", 1, "test")
    assert not [c for c in e.legal_candidates() if c.display_name == "Ingrain the Toxin: Heavy Pulse"]
    stacking_marks.add(e, me, foe, "Dose Mark", 2, "test")
    SWF.cast(e, "Ingrain the Toxin: Heavy Pulse", target=FOE)
    assert stacking_marks.count(e, me, foe, "Dose Mark") == 1
    assert SWF.has(foe, "no_dash")  # "cannot benefit from the Dash action on its next turn"


def test_deepen_the_burden_turns_two_dose_marks_into_toxin_burden():
    from combat.ext import stacking_marks

    _, e, me, foe = _venom("deepen_the_burden")
    stacking_marks.add(e, me, foe, "Dose Mark", 3, "test")
    SWF.cast(e, "Deepen the Burden", target=FOE)
    assert stacking_marks.count(e, me, foe, "Dose Mark") == 1 and stacking_marks.count(e, me, foe, "Toxin Burden") == 1


def test_venom_sovereign_deliver_the_dose_is_six_d10_and_ignores_poison_resistance():
    """Venom-Sovereign Incarnation: "Deliver the Dose deals 6d10 ...; your Poison talents ignore ordinary Resistance to Poison and Acid damage."
    The resistance line was a GM rider (and the 6d10 a deferred row)."""
    engine = L4._duel([], attacker_sphere="tianxia.sphere.poison", attacker_talents=[DELIVER, PZ + "venom_sovereign_incarnation"])
    me, foe = engine.state.actors[L4.ME], engine.state.actors[L4.SUBJ]
    L4._use(engine, "Venom-Sovereign Incarnation")
    for kind in ("POISON", "ACID"):
        engine._add_modifier(foe, "test:resist", "damage_resistance", "ADD", kind, "SELF", expires_on="UNTIL_REMOVED")
    before = foe.current_hp
    L4._script(engine, [15])
    events = L4._use(engine, "Deliver the Dose")
    roll = [r for r in engine.rolls if r.reason.startswith("DAMAGE:")][-1]
    assert roll.expression.startswith("6d10") and before - foe.current_hp == min(before, roll.total)


def test_virulent_presence_tests_an_enemy_starting_its_turn_near_the_sovereign():
    from combat.ext import poison

    _, e, me, foe = _venom("venom_sovereign_incarnation", "virulent_presence")
    SWF.cast(e, "Venom-Sovereign Incarnation")
    poison.virulent_presence(e, foe)
    assert foe.current_hp < 2000


# ================================================================================================================ Radiance
RD = "tianxia.talent.radiance."
RSTRIKE = "RADIANCE_BASE_STRIKE"
RADIANCE_CLEARED = ["RADIANCE_TAL_JUDGMENT_RAY", RD + "mirror_of_clean_dawn", RD + "radiant_aegis_of_the_heart", RD + "solar_flare"]


AN, ME = FOE, SWF.ME


def _dawn(*talents, dc=50, cl=20, base=RSTRIKE):
    return SWF.fight(base, cl=cl, dc=dc, extras=tuple(t if t.isupper() else RD + t for t in talents))


def _cond(actor, suffix):
    return [c for c in actor.conditions.values() if c.condition_id.endswith(suffix)]


def _give(engine, actor, name, data=None, source="test"):
    engine._apply_condition(actor, f"condition:typed.{name}", source, AN, expires_on="UNTIL_REMOVED", data=data or {})


def _second_foe(engine, foe, x=5, y=6):
    other = foe.model_copy(deep=True)
    other.entity_id, other.position = "review:foe2", foe.position.model_copy(update={"x": x, "y": y})
    engine.state.actors[other.entity_id] = other
    return other


def _marked(engine, owner, creature):
    from combat.typed_executor import mark_condition_id

    return any(c.condition_id == mark_condition_id("Dawnmark", owner.entity_id) for c in creature.conditions.values())


def test_radiance_lines_the_table_already_runs_are_no_longer_gm_riders():
    """Judgment Ray's cover (a saving throw takes no cover bonus here; the area stops at walls), Mirror of Clean Dawn, Radiant Aegis's one-at-a-time
    (it is Concentration), Solar Flare's damage (its modifier)."""
    mechanics = _authority()
    assert {key: mechanics[key]["coverage"] for key in RADIANCE_CLEARED} == {key: "FULL" for key in RADIANCE_CLEARED}


def test_blinding_flash_offers_both_printed_areas_and_solar_flare_still_burns():
    """Blinding Flash: "Area: 15-foot cone or 10-foot-radius Emanation" (only the cone was typed); "Blinded until the end of your next turn"."""
    _, e, me, foe = _dawn("RADIANCE_TAL_BLINDING_FLASH", "solar_flare")
    names = {c.display_name for c in e.legal_candidates()}
    assert {"Blinding Flash: 15-Foot Cone", "Blinding Flash: 10-Foot Emanation"} <= {n.split(" + ")[0] for n in names}
    SWF.cast(e, "Blinding Flash: 10-Foot Emanation", contains="Solar Flare")
    (blind,) = _cond(foe, ".blinded")
    assert blind.expires_on == f"END_OF_SOURCE_TURN_AT:{me.turns_started + 1}"  # the end of the user's next turn
    assert foe.current_hp < 2000  # Solar Flare's damage rides the flash


def test_dawn_cleansing_wave_and_gentle_dawn_let_allies_repeat_their_saves():
    """Gentle Dawn: "the target may immediately repeat a saving throw against Charmed or Frightened" (it was Advantage and Temporary HP at once)."""
    _, e, me, foe = _dawn("gentle_dawn")
    friend = SWF.ally(e, me)
    friend.position = friend.position.model_copy(update={"x": 3, "y": 7})
    e._apply_condition(friend, "condition:typed.frightened", "test", AN, expires_on="UNTIL_REMOVED",
                       data={"origin_save": {"ability": "WIS", "dc": 1}})
    L4._script(e, [15])
    SWF.cast(e, "Gentle Dawn: Repeat Save vs Charm or Fear", target=friend.entity_id)
    assert not _cond(friend, ".frightened")
    assert not [c for c in e.legal_candidates() if c.display_name == "Gentle Dawn"]  # one choice, not all four at once


def test_gentle_dawn_temporary_hp_once_per_creature_and_fear_suppressed_until_your_next_turn():
    from combat.ext import radiance

    _, e, me, foe = _dawn("gentle_dawn")
    friend = SWF.ally(e, me)
    friend.position = friend.position.model_copy(update={"x": 3, "y": 7})
    SWF.cast(e, "Gentle Dawn: Temporary HP", target=friend.entity_id)
    assert friend.temporary_hp > 0
    me.action_available = True
    assert not [c for c in e.legal_candidates() if c.display_name == "Gentle Dawn: Temporary HP" and friend.entity_id in c.target_ids]
    e._apply_condition(friend, "condition:typed.frightened", "test", AN, expires_on="UNTIL_REMOVED")
    SWF.cast(e, "Gentle Dawn: Suppress Fear", target=friend.entity_id)
    assert not _cond(friend, ".frightened")
    radiance.restore_suppressed(e, me)
    assert _cond(friend, ".frightened")


def test_court_of_unshadowed_dawn_judges_a_hostile_starting_its_turn_inside():
    """Court: "when a hostile creature starts its turn inside, it makes a Constitution or Wisdom saving throw ... Failed Save: Choose one ..."
    and "ordinary Invisible provides no benefit" to enemies inside -- both were GM lines."""
    from combat import senses, zones
    from combat.ext import menus

    _, e, me, foe = _dawn("court_of_unshadowed_dawn", cl=20)
    menus.pick(e, me, "court_unshadowed_dawn_save", "Wisdom", "test")
    SWF.cast(e, "Court of Unshadowed Dawn")
    saves_before = len([r for r in e.rolls if "SAVE" in r.reason])
    zones.on_turn_start(e, foe)
    assert [r for r in e.rolls if "SAVE" in r.reason][saves_before:]
    assert _cond(foe, ".blinded")  # the standing pick (Blinded) on a failed save
    _give(e, foe, "invisible")
    masked = senses.masked_conditions(e, me, foe)
    assert {c.instance_id for c in _cond(foe, ".invisible")} <= masked.get(foe.entity_id, set())


def test_court_rewards_an_ally_resisting_fear_and_clears_light_blindness():
    from combat.ext import radiance
    from types import SimpleNamespace

    _, e, me, foe = _dawn("court_of_unshadowed_dawn", "RADIANCE_TAL_BLINDING_FLASH", cl=20)
    SWF.cast(e, "Court of Unshadowed Dawn")
    friend = SWF.ally(e, me)
    friend.temporary_hp = 0
    radiance.radiance_saves(SimpleNamespace(engine=e, actor=foe), friend, "WIS", {"frightened"}, False)
    assert friend.temporary_hp == me.proficiency_bonus
    radiance.radiance_saves(SimpleNamespace(engine=e, actor=foe), friend, "WIS", {"frightened"}, False)  # once per round
    assert friend.temporary_hp == me.proficiency_bonus
    flash = next(a for a in e.action_catalog if "BLINDING_FLASH" in a)
    e._apply_condition(friend, "condition:typed.blinded", flash, AN, expires_on="UNTIL_REMOVED")
    radiance.court_clears_sight(e, friend)
    assert not _cond(friend, ".blinded")


def test_crown_of_the_unblinking_sun_spreads_a_dawnmark_to_a_second_enemy():
    _, e, me, foe = _dawn("crown_of_the_unblinking_sun", cl=20)
    other = _second_foe(e, foe)
    SWF.cast(e, "Crown of the Unblinking Sun")
    me.action_available = True
    L4._script(e, [15])
    SWF.cast(e, "Radiance Strike", target=AN)
    assert _marked(e, me, foe) and _marked(e, me, other)


def test_dawn_ward_adds_proficiency_against_necrotic_damage_only():
    """Dawn Ward: "If the triggering damage is Necrotic, Radiant ... add your Proficiency Bonus to the reduction" (a GM line)."""
    from combat import typed_reactions as tr

    _, e, me, foe = _dawn("dawn_ward")
    rows = [r for kind in ("damaged", "ally_damaged") for r in tr._ordered_generic_rows(e, me.entity_id, kind) if "dawn_ward" in str(r.get("feature_id"))]
    assert rows
    L4._script(e, [4, 4, 4])
    e._typed_pending_damage_type = "FIRE"
    fire, _ = tr._generic_damage_reduction(e, me, rows[0], 100)
    e._typed_pending_damage_type = "NECROTIC"
    L4._script(e, [4, 4, 4])
    necrotic, _ = tr._generic_damage_reduction(e, me, rows[0], 100)
    assert fire - necrotic == me.proficiency_bonus


def test_expose_false_form_strips_invisibility_while_the_dawnmark_lasts():
    from combat import senses

    _, e, me, foe = _dawn("expose_false_form")
    _give(e, foe, "invisible")
    before = me.resources["resource:core.qi"]
    L4._script(e, [15])
    SWF.cast(e, "Radiance Strike", target=AN)
    assert _marked(e, me, foe) and me.resources["resource:core.qi"] == before - 1
    assert {c.instance_id for c in _cond(foe, ".invisible")} <= senses.masked_conditions(e, me, foe).get(foe.entity_id, set())


def test_halo_marks_a_nearby_enemy_when_its_bearer_resists_fear_and_only_one_halo_holds():
    from combat.ext import radiance
    from types import SimpleNamespace

    _, e, me, foe = _dawn("halo_of_the_merciful_sovereign", cl=20)
    friend = SWF.ally(e, me)
    friend.position = friend.position.model_copy(update={"x": 4, "y": 7})
    SWF.cast(e, "Halo of the Merciful Sovereign", target=friend.entity_id)
    assert [m for m in friend.modifiers.values() if radiance.HALO in m.source_definition_id]
    radiance.radiance_saves(SimpleNamespace(engine=e, actor=foe), friend, "WIS", {"frightened"}, False)
    assert _marked(e, me, foe)
    me.bonus_action_available = True
    SWF.cast(e, "Halo of the Merciful Sovereign", target=ME)
    assert not [m for m in friend.modifiers.values() if radiance.HALO in m.source_definition_id]


def test_mirror_of_clean_dawn_marks_the_creature_whose_effect_was_resisted():
    from combat.ext import radiance
    from types import SimpleNamespace

    _, e, me, foe = _dawn("mirror_of_clean_dawn")
    friend = SWF.ally(e, me)
    e._append_event("REACTION_RESOLVED", f"reaction:typed.{radiance.MIRROR}", actor_id=ME, target_ids=(friend.entity_id,),
                    payload={"checkpoint": "D20_PENDING", "roll": "save"})
    radiance.radiance_saves(SimpleNamespace(engine=e, actor=foe), friend, "WIS", {"charmed"}, False)
    assert _marked(e, me, foe)


def test_heavenly_radiance_strike_aura_and_dawn_wave():
    """Heavenly Radiance compiled with no effects at all: no resistances, no 8d10 Radiance Strike, no Solar Aura, no Dawn Wave."""
    from combat.ext import radiance

    _, e, me, foe = _dawn("heavenly_radiance", "solar_radiance_form", cl=20)
    assert not [c for c in e.legal_candidates() if "Dawn Wave" in c.display_name]
    SWF.cast(e, "Heavenly Radiance")
    assert any(m.value == "RADIANT" and m.target_field == "damage_immunity" for m in me.modifiers.values())
    me.action_available = True
    offered = {c.display_name.split(" at ")[0] for c in e.legal_candidates()}
    assert {"Radiance Strike: Dawn Wave (120-foot beam)", "Radiance Strike: Dawn Wave (60-foot line)", "Radiance Strike: Dawn Wave (30-foot cone)"} <= offered
    L4._script(e, [15])
    SWF.cast(e, "Radiance Strike", target=AN)
    assert any(r.expression.startswith("8d10") for r in e.rolls if r.reason.startswith("DAMAGE"))
    hp = foe.current_hp
    radiance.solar_aura(e, foe)
    assert foe.current_hp < hp


def test_heaven_opening_judgment_ignores_radiant_resistance():
    from combat.ext import radiance

    assert radiance.judgment_pierces(None, "RADIANT", {"source": "RADIANCE_TAL_HEAVEN_OPENING_JUDGMENT"}, ME) is True
    assert radiance.judgment_pierces(None, "RADIANT", {"source": "RADIANCE_TAL_JUDGMENT_RAY"}, ME) is None


def test_sun_white_judgment_spear_ignores_cover_for_its_attack_only():
    """"The attack ignores Half Cover, Three-Quarters Cover, ordinary Darkness, ordinary visual concealment": a GM line before."""
    from combat.ext import radiance

    _, e, me, foe = _dawn("RADIANCE_TAL_SUN_WHITE_JUDGMENT_SPEAR", cl=20)
    L4._script(e, [15])
    SWF.cast(e, "Sun-White Judgment Spear", target=AN)
    applied = [ev for ev in e.events if ev.event_type == "CONDITION_APPLIED" and (ev.payload or {}).get("condition_id") == radiance.NO_HALF_COVER]
    rolled = [ev for ev in e.events if ev.event_type == "ATTACK_ROLLED"]
    assert applied and rolled and applied[0].sequence < rolled[-1].sequence
    assert not [c for c in foe.conditions.values() if c.condition_id in (radiance.NO_HALF_COVER, radiance.PIERCING)]


def test_revealing_light_and_world_lift_darkness_and_invisibility():
    from types import SimpleNamespace
    from combat import senses
    from combat.ext import radiance

    _, e, me, foe = _dawn("revealing_light")
    SWF.cast(e, "Revealing Light")
    _give(e, foe, "invisible")
    assert {c.instance_id for c in _cond(foe, ".invisible")} <= senses.masked_conditions(e, me, foe).get(foe.entity_id, set())
    dark = SimpleNamespace(affected_cells=[foe.position], trigger_profile={"visual": {"darkness": True}},
                           radius_cells=0, center=foe.position, active=True, owner_id=AN)
    assert radiance.dawnlight(e, dark, me, foe) is True


def test_solar_radiance_form_and_searing_halo_reach_radiance_strike():
    """Solar Radiance Form: "Radiance Strike deals +1d8 Radiant damage ... once per turn when Radiance Strike hits a creature, it makes a
    Constitution saving throw. Failed Save: Blinded ..."; Searing Halo: "once per turn when Radiance Strike hits, deal +1d8 Radiant damage".
    Neither reached the Strike (the compiler merges no modifier of an Action or Bonus Action talent)."""
    _, e, me, foe = _dawn("solar_radiance_form", "searing_halo", cl=20)
    SWF.cast(e, "Solar Radiance Form")
    SWF.ally(e, me)
    me.bonus_action_available = True
    e.state.actors[me.entity_id].concentration = None
    SWF.cast(e, "Searing Halo")
    me.action_available = True
    L4._script(e, [15])
    before = len([r for r in e.rolls if r.reason.startswith("DAMAGE")])
    SWF.cast(e, "Radiance Strike", target=AN)
    assert len([r for r in e.rolls if r.reason.startswith("DAMAGE")]) - before >= 2  # the Strike and at least one +1d8
    assert _cond(foe, ".blinded") and not _cond(foe, ".reaction_denied")


def test_first_dawn_ends_invisibility_as_a_picked_consequence():
    from combat.ext import menus

    _, e, me, foe = _dawn("first_dawn_before_falsehood", "heavenly_radiance", "solar_radiance_form", cl=20)
    menus.pick(e, me, "first_dawn", "End one ordinary invisibility, disguise, or illusion covering it", "test")
    _give(e, foe, "invisible")
    SWF.cast(e, "First Dawn Before Falsehood")
    assert not _cond(foe, ".invisible")


def test_purifying_radiance_removes_one_disease(monkeypatch):
    from combat.ext import radiance

    _, e, me, foe = _dawn("purifying_radiance", cl=10)
    friend = SWF.ally(e, me)
    friend.position = friend.position.model_copy(update={"x": 3, "y": 7})
    _give(e, friend, "sickened", source="action:typed.test.DISEASE_BASE_SOW_THE_FEVER_SEED")
    monkeypatch.setattr(radiance, "_source_sphere", lambda engine, source: "tianxia.sphere.disease" if "DISEASE" in str(source) else "")
    SWF.cast(e, "Purifying Radiance: Remove Disease", target=friend.entity_id)
    assert not _cond(friend, ".sickened")


# ================================================================================================================ Music
MU = "tianxia.talent.music."
KEEP = "MUSIC_BASE_KEEP_THE_MEASURE"
MUSIC_CLEARED = ["MUSIC_BASE_RESONANT_NOTE", MU + "dissonant_note", MU + "captivating_melody", MU + "concerto_of_broken_breath", MU + "lullaby_of_settled_breath",
                 MU + "rhythmic_guard", MU + "shattering_chorus", MU + "war_song", MU + "march_of_the_immortal_host", MU + "rallying_song"]


def _song(*talents, dc=50, cl=20):
    return SWF.fight(KEEP, cl=cl, dc=dc, extras=tuple(t if t.isupper() else MU + t for t in talents))


def _friend(e, me, x=3, y=7):
    friend = SWF.ally(e, me)
    friend.position = friend.position.model_copy(update={"x": x, "y": y})
    return friend


def _measure(actor):
    return [c for c in actor.conditions.values() if c.condition_id == "condition:typed.music_measure"]


def test_music_lines_the_table_already_runs_are_no_longer_gm_riders():
    mechanics = _authority()
    assert {key: mechanics[key]["coverage"] for key in MUSIC_CLEARED} == {key: "FULL" for key in MUSIC_CLEARED}


def test_keep_the_measure_lasts_and_ends_when_incapacitated():
    """Keep the Measure compiled with no effects at all: nothing knew whether a performance was going."""
    _, e, me, foe = _song()
    SWF.cast(e, "Keep the Measure")
    assert _measure(me)
    e._apply_condition(me, "condition:typed.stunned", "test", AN, expires_on="UNTIL_REMOVED")
    assert not _measure(me)


def test_opening_phrase_needs_the_measure_once_a_round_and_adds_pb_to_a_fear_save():
    from types import SimpleNamespace
    from combat.ext import music

    _, e, me, foe = _song()
    friend = _friend(e, me)
    assert not [c for c in e.legal_candidates() if c.display_name.startswith("Opening Phrase")]
    SWF.cast(e, "Keep the Measure")
    me.bonus_action_available = True
    SWF.cast(e, "Opening Phrase: Save vs Charmed/Frightened", target=friend.entity_id)
    bonus = music.music_save_bonus(SimpleNamespace(engine=e), friend, "WIS", {"frightened"})
    assert bonus == {"bonus": me.proficiency_bonus, "modes": []}
    me.bonus_action_available = True
    assert not [c for c in e.legal_candidates() if c.display_name.startswith("Opening Phrase") and friend.entity_id in c.target_ids]


def test_rhythmic_guard_answers_only_while_keeping_the_measure():
    from combat.ext import music

    _, e, me, foe = _song("rhythmic_guard")
    row = {"feature_id": music.GUARD}
    assert music.guard_needs_the_measure(e, me, row) is False
    SWF.cast(e, "Keep the Measure")
    assert music.guard_needs_the_measure(e, me, row) is None


def test_battle_cadence_is_entered_with_the_measure_and_adds_pb_to_a_weapon_hit():
    """Battle Cadence (the bodyb variant of Keep the Measure): "your Speed increases by 5 feet; once per turn when you hit with an approved
    weapon ... add your Proficiency Bonus to one damage roll" -- and the Measure it enters is now a real performance."""
    _, e, me, foe = _song("battle_cadence")
    before = e._effective_speed(me)
    SWF.cast(e, "Keep the Measure", contains="Battle Cadence")
    assert _measure(me) and e._effective_speed(me) == before + 5
    me.action_available = True
    L4._script(e, [15])
    start = len(e.events)
    SWF.cast(e, "Jian (Straight Sword) attack", target=AN)
    hits = [ev for ev in e.events[start:] if ev.event_type == "DAMAGE_COMMITTED" and AN in ev.target_ids]
    assert len(hits) >= 2


def test_concerto_speed_zero_stops_the_creature():
    _, e, me, foe = _song("concerto_of_broken_breath")
    SWF.cast(e, "Concerto of Broken Breath: Speed 0")
    assert e._effective_speed(foe) == 0


def test_court_of_resonant_measure_is_an_aura_with_a_dissonant_start_of_turn_save():
    from combat import zones
    from combat.ext import music

    _, e, me, foe = _song("court_of_resonant_measure")
    ac, speed = e._ac_modifier(me) if hasattr(e, "_ac_modifier") else 0, e._effective_speed(me)
    SWF.cast(e, "Court of Resonant Measure: Harmonious Court")
    assert e._effective_speed(me) == speed + 10 and music.music_ac(e, me) == 1
    _, e, me, foe = _song("court_of_resonant_measure")
    SWF.cast(e, "Court of Resonant Measure: Dissonant Court")
    saves = len([r for r in e.rolls if "SAVE" in r.reason])
    zones.on_turn_start(e, foe)
    assert len([r for r in e.rolls if "SAVE" in r.reason]) > saves
    assert music.dissonance_spares_friends(e, me) and not music.dissonance_spares_friends(e, foe)


def test_harmonizing_breath_gives_twice_pb_temporary_hp_only_when_nothing_ends():
    _, e, me, foe = _song("harmonizing_breath")
    friend = _friend(e, me)
    e._apply_condition(friend, "condition:typed.frightened", "test", AN, expires_on="UNTIL_REMOVED")
    assert not [c for c in e.legal_candidates() if c.display_name == "Harmonizing Breath: Temporary HP" and friend.entity_id in c.target_ids]
    e._remove_condition(friend, "condition:typed.frightened", "test")
    friend.temporary_hp = 0
    SWF.cast(e, "Harmonizing Breath: Temporary HP", target=friend.entity_id)
    assert friend.temporary_hp == 2 * me.proficiency_bonus


def test_healing_hymn_heals_the_most_hurt_ally_at_the_end_of_the_turn_once():
    from combat.ext import music

    _, e, me, foe = _song("healing_hymn")
    friend = _friend(e, me)
    friend.current_hp = 100
    SWF.cast(e, "Healing Hymn")
    music.songs_heal(e, me)
    assert friend.current_hp > 100
    healed = friend.current_hp
    friend.current_hp = 100
    music.songs_heal(e, me)
    assert friend.current_hp == 100 and healed > 100


def test_march_of_the_immortal_host_marks_the_host_and_steps_after_a_weapon_hit():
    _, e, me, foe = _song("battle_cadence", "march_of_the_immortal_host")
    friend = _friend(e, me)
    SWF.cast(e, "March of the Immortal Host")
    assert SWF.has(me, "music_march") and SWF.has(friend, "music_march")
    assert e._effective_speed(friend) >= friend.speed_ft + 10
    me.action_available = True
    L4._script(e, [15])
    start = len(e.events)
    SWF.cast(e, "Jian (Straight Sword) attack", target=AN)
    assert [ev for ev in e.events[start:] if ev.event_type == "MOVEMENT_COMMITTED" and ev.actor_id == me.entity_id]


def test_shared_measure_lets_another_affected_creature_step_when_one_hits():
    _, e, me, foe = _song("shared_measure")
    friend = _friend(e, me)
    SWF.cast(e, "Shared Measure")
    assert SWF.has(friend, "music_shared_measure")
    me.action_available = True
    L4._script(e, [15])
    start = friend.position
    SWF.cast(e, "Jian (Straight Sword) attack", target=AN)
    assert friend.position != start  # printed movement happens at the trigger, on the other actor's turn
    assert not any(c.condition_id == "condition:typed.banner_step" for c in friend.conditions.values())


def test_soul_stirring_refrain_sorrow_halves_speed_and_calm_ends_fear():
    _, e, me, foe = _song("soul_stirring_refrain")
    speed = e._effective_speed(foe)
    SWF.cast(e, "Soul-Stirring Refrain: Sorrow", target=AN)
    assert e._effective_speed(foe) == speed - speed // 2
    friend = _friend(e, me)
    e._apply_condition(friend, "condition:typed.frightened", "test", AN, expires_on="UNTIL_REMOVED")
    me.action_available = True
    e.state.actors[ME].concentration = None
    SWF.cast(e, "Soul-Stirring Refrain: Calm", target=friend.entity_id)
    assert not [c for c in friend.conditions.values() if c.condition_id.endswith(".frightened")]


def test_symphony_takes_two_movements_from_a_menu():
    """Symphony of Heaven and Earth: "Choose two movements" was six fixed pairs, with Ruin's start-of-turn save and Courage's immunity GM lines."""
    from combat import zones
    from combat.ext import menus
    from combat.typed_executor import condition_immune

    _, e, me, foe = _song("symphony_of_heaven_and_earth")
    friend = _friend(e, me)
    menus.pick(e, me, "music_symphony", "Movement of Courage", "test")
    SWF.cast(e, "Symphony of Heaven and Earth")
    zones.sync_inside(e) if hasattr(zones, "sync_inside") else None
    assert condition_immune(e, friend, "frightened")
    hp = foe.current_hp
    zones.on_turn_start(e, foe)
    assert foe.current_hp < hp  # the default second movement, Ruin (the last picked replaced War)


def test_war_song_holds_one_singer_at_a_time():
    _, e, me, foe = _song("war_song")
    friend = _friend(e, me)
    e._apply_condition(friend, "condition:typed.music_war_song", "test", "someone-else", expires_on="UNTIL_REMOVED", data={"rule": {"music_speed": 10}})
    SWF.cast(e, "War Song")
    songs = [c for c in friend.conditions.values() if c.condition_id == "condition:typed.music_war_song"]
    assert len(songs) == 1 and songs[0].source_actor_id == ME


def test_weapon_hymn_adds_a_d6_once_per_turn():
    _, e, me, foe = _song("weapon_hymn")
    SWF.cast(e, "Weapon Hymn: Psychic", target=ME)
    me.action_available = True
    L4._script(e, [15])
    SWF.cast(e, "Jian (Straight Sword) attack", target=AN)
    assert any(r.expression.startswith("1d6") for r in e.rolls if r.reason.startswith("DAMAGE"))


def test_echo_performer_is_a_summoned_echo():
    _, e, me, foe = _song("echo_performer")
    SWF.cast(e, "Echo Performer")
    echoes = [a for a in e.state.actors.values() if (a.summon or {}).get("owner_id") == ME or "echo" in a.entity_id.lower()]
    assert echoes and echoes[0].armor_class == 14 and echoes[0].maximum_hp == 1


def test_shattering_chorus_reaches_fragile_objects():
    from types import SimpleNamespace
    from combat import object_rules

    assert object_rules.has_tag(SimpleNamespace(component={"material": "glass"}), "fragile")
    assert not object_rules.has_tag(SimpleNamespace(component={"material": "stone"}), "fragile")


def test_rallying_song_turns_a_narrowly_failed_fear_save_with_the_singers_pb():
    """Rallying Song: "Once per round, when one affected ally fails a saving throw against Charmed or Frightened, it may add your Proficiency
    Bonus to the result, potentially turning failure into success" -- a GM line."""
    from combat.typed_executor import Context, run_effects

    def frightening_save(with_song):
        _, e, me, foe = _song("rallying_song")
        friend = _friend(e, me)
        if with_song:
            SWF.cast(e, "Rallying Song")
        action = next(a for a in e.action_catalog.values() if a.owner_id == me.entity_id)
        natural = 15 - friend.saving_throws.get("WIS", 0) - 1  # one short of DC 15
        L4._script(e, [natural, natural])
        run_effects(Context(e, foe, action, None, {"numbers": {"save_dc": 15}, "effects": []}, [friend], friend, {}),
                    [{"type": "save", "ability": "wis", "on_fail": [{"type": "condition", "applies_to": "target", "condition": "frightened",
                                                                    "duration": "until_start_of_next_turn"}]}])
        return [c for c in friend.conditions.values() if c.condition_id.endswith(".frightened")]

    assert frightening_save(False) and not frightening_save(True)


def test_symphony_movement_of_mercy_heals_allies_inside_at_the_end_of_your_turn_once():
    from combat.ext import menus, music

    _, e, me, foe = _song("symphony_of_heaven_and_earth")
    friend = _friend(e, me)
    friend.current_hp = 100
    menus.pick(e, me, "music_symphony", "Movement of Mercy", "test")
    SWF.cast(e, "Symphony of Heaven and Earth")
    assert friend.current_hp == 100  # not on activation
    music.songs_heal(e, me)
    assert friend.current_hp > 100
    friend.current_hp = 100
    music.songs_heal(e, me)
    assert friend.current_hp == 100  # "only once during the Symphony"


def test_the_one_opening_beneath_heaven_moves_in_strikes_with_advantage_and_imposes_three_consequences():
    """The One Opening Beneath Heaven: "Move up to your Speed without provoking ... one melee attack ... with Advantage ... additional damage
    equal to twelve rolls of the attack's normal damage die ... Then choose three consequences" -- it compiled as a bare Cultivation Attack."""
    _, e, me, foe = SWF.fight("TAL_FENCING_THE_ONE_OPENING_BENEATH_HEAVEN")
    foe.position = foe.position.model_copy(update={"x": 8})
    name = "Jian (Straight Sword) attack: The One Opening Beneath Heaven"
    L4._script(e, [15, 15])
    SWF.cast(e, name, target=AN)
    assert e._distance_actor_to_actor(me, foe) <= 5  # moved in
    (rolled,) = [ev for ev in e.events if ev.event_type == "ATTACK_ROLLED"]
    assert rolled.payload["mode"] == "ADVANTAGE"
    assert any(r.expression.startswith("12d10") for r in e.rolls if r.reason.startswith("DAMAGE"))  # the jian's d10, twelve times
    # the default three consequences: no Reactions, Speed 0, Disadvantage on attack rolls
    assert any(c.condition_id.endswith("reaction_denied") for c in foe.conditions.values())
    assert e._effective_speed(foe) == 0
    assert any(m.target_field == "attack_mode" and m.value == "DISADVANTAGE" for m in foe.modifiers.values())
    me.action_available = True
    me.resources["resource:core.martial_focus"] = 1
    assert not [c for c in e.legal_candidates() if c.display_name.startswith(name)]  # once per fight


def test_force_wall_panels_resist_weapon_damage():
    """Force Wall: "Each panel has ... Resistances Bludgeoning, Piercing, Slashing" -- the panels took full weapon damage."""
    from combat import zones
    from combat.ext import docket_walls

    _, e, me, foe = SWF.fight("TAL_FORCE_FORCE_WALL")
    foe.position = foe.position.model_copy(update={"x": 9})
    SWF.cast(e, "Force Wall", at=(4, 6))
    zone = next(z for z in zones.typed_zones(e) if z.trigger_profile.get("wall"))
    row = docket_walls.stats(zone)
    assert row["resist"] == ["BLUDGEONING", "PIERCING", "SLASHING"]
    me.action_available = True
    L4._script(e, [19, 10])  # a hit against AC 15 + PB
    SWF.cast(e, "Attack a wall section", at=(4, 6))
    damage = [r for r in e.rolls if r.reason.startswith("DAMAGE") and ":wall:" in r.reason][-1]
    assert docket_walls.hit_points_left(zone, next(c for c in zone.affected_cells if (c.x, c.y) == (4, 6))) == row["hp"] - damage.total // 2


# -------------------------------------------------------------------------------- AUTO87 (2026-10-05): the printed Force reactions and the Court
def _caught(e, feature=F + "COUNTERPRESSURE"):
    """The damage Counterpressure caught on its last resolution, from the engine's own record."""
    return [int((event.payload or {}).get("reduction") or 0) for event in e.events
            if event.event_type == "REACTION_RESOLVED" and str(event.source_definition_id).startswith(feature)][-1]


def _cushion_roll(e):
    """What Cushion the Blow rolled, before the reduction path clamped it to the damage there was."""
    return [int(r.total) for r in e.rolls if r.reason.startswith(f"GENERIC_AMOUNT:{F}COUNTERPRESSURE")][-1]


def _force_bundle(key, cl=20, dc=50, extras=(), actor_id=None, plan=None):
    """One real compiled Force fighter: every base ability of the sphere, the named mechanic and any extra talents."""
    from combat.factory_compiler import compile_character
    from tests.test_auto_support import ME
    from tests.test_zones import SHEET

    sphere = SWF.AUTH[key]["sphere_id"]
    bases = [k for k, v in SWF.AUTH.items() if v.get("sphere_id") == sphere and v.get("kind") == "base_ability"]
    return compile_character({**SHEET,
        "equipment": [{"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.jian", "quantity": 1}]}}],
        "identity": {**SHEET["identity"], "cultivation_level": cl},
        "ability_scores_and_statistics": {**SHEET["ability_scores_and_statistics"], "technique_save_dc": dc,
            "technique_attack_bonus": 40, "primary_resource": {"name": "Qi", "maximum": 100}},
        "spheres_and_talents": {"sphere_record_ids": [sphere],
            "learned_talent_record_ids": list(dict.fromkeys([*bases, key, *extras]))}},
        actor_id=actor_id or ME, reaction_plan=plan)


def _engine_of(bundles, seed, starts, teams, current):
    from combat.gate4_engine import Gate4ControllerEngine

    engine = Gate4ControllerEngine(SWF.ROOT, match_seed=seed, typed_bundles=tuple(bundles),
                                   roster_setup={"primary_actor_ids": list(starts), "team_by_actor": teams,
                                                 "starting_positions": starts})
    engine.state.current_slot_index = engine.state.initiative_order.index(current)
    engine.state.current_actor_id = current
    engine._system_start_turn()
    for actor in engine.state.actors.values():
        if actor.entity_id in engine.typed_actor_ids:
            actor.maximum_hp = actor.current_hp = 2000
            actor.resources["resource:core.martial_focus"] = 1
    return engine


def _seeded(key, seed, cl=20, dc=50, extras=(), plan=None):
    """The same compiled fighter in a fight whose dice are drawn from ``seed``, so an exact amount is not one lucky roll."""
    from tests.test_auto_support import AN, ME

    bundle = _force_bundle(key, cl, dc, extras, ME, plan)
    engine = _engine_of([bundle], seed, {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}, {ME: "team:a", AN: "team:b"}, ME)
    foe = engine.state.actors[AN]
    foe.maximum_hp = foe.current_hp = 2000
    foe.armor_class = -50
    return engine, engine.state.actors[ME], foe


MATE = "actor:factory.rebounds-mate"


def _two_owners(key, seed, cl=20, dc=50, extras=()):
    """Two real Force fighters on one team, each with its own compiled rows, against one hostile creature."""
    from tests.test_auto_support import AN, ME

    bundles = [_force_bundle(key, cl, dc, extras, ME), _force_bundle(key, cl, dc, extras, MATE)]
    starts = {ME: {"x": 3, "y": 6}, MATE: {"x": 3, "y": 7}, AN: {"x": 4, "y": 6}}
    teams = {ME: "team:a", MATE: "team:a", AN: "team:b"}
    engine = _engine_of(bundles, seed, starts, teams, ME)
    engine.state.actors[AN].maximum_hp = engine.state.actors[AN].current_hp = 2000
    engine.state.actors[AN].armor_class = -50
    return engine, engine.state.actors[ME], engine.state.actors[MATE], engine.state.actors[AN]


def test_returning_impact_hits_the_source_for_what_counterpressure_caught():
    """Returning Impact: "Take Force damage equal to the damage Counterpressure reduced, to a maximum of 3 x CL, and push 10 feet
    directly away from the protected target". The GM line said the table only pushed."""
    from combat import typed_reactions as tr

    _, e, me, foe = SWF.fight(F + "COUNTERPRESSURE", extras=(F + "RETURNING_IMPACT",), cl=3)
    e._typed_pending_damage_type = "SLASHING"
    before = foe.current_hp
    tr.on_damage(e, me, 100, 0, source_actor_id=FOE)
    caught = _caught(e)
    assert caught > 0 and foe.current_hp == before - caught, "Force damage equal to the damage Counterpressure reduced"
    assert me.position.x == 3 and foe.position.x == me.position.x + 3  # pushed 10 feet directly away from the protected creature


@pytest.mark.parametrize("seed,pending", [("RI-A", 100), ("RI-B", 1), ("RI-C", 4), ("RI-D", 2), ("RI-E", 9)])
def test_returning_impact_returns_only_what_counterpressure_actually_kept_off(seed, pending):
    """The returned pressure is the damage the reduction really prevented, not the roll it rolled: a large Cushion the Blow
    against a 1-point hit prevented 1 point, and Returning Impact returns 1 ("Take Force damage equal to the damage
    Counterpressure reduced"), exactly as the engine's own reaction receipt records it."""
    from combat import typed_reactions as tr

    e, me, foe = _seeded(F + "COUNTERPRESSURE", seed, cl=5, extras=(F + "RETURNING_IMPACT",))
    e._typed_pending_damage_type = "SLASHING"
    before = foe.current_hp
    tr.on_damage(e, me, pending, 0, source_actor_id=FOE)
    caught = _caught(e)
    assert caught == min(_cushion_roll(e), pending), "the engine clamps a reduction at the damage the packet had"
    assert before - foe.current_hp == min(caught, 15), "equal to the damage reduced, to a maximum of 3 x CL"


def test_returning_impact_never_returns_more_than_three_times_the_cultivation_level():
    from combat import typed_reactions as tr

    _, e, me, foe = SWF.fight(F + "COUNTERPRESSURE", extras=(F + "RETURNING_IMPACT",), cl=1)
    e._typed_pending_damage_type = "SLASHING"
    before = foe.current_hp
    tr.on_damage(e, me, 100, 0, source_actor_id=FOE)
    assert 0 < before - foe.current_hp <= 3  # "to a maximum of 3 x CL"


def test_returning_impact_returns_exactly_three_times_the_cultivation_level_when_the_cap_bites():
    """The cap is the printed maximum, not a rough ceiling: when Counterpressure kept off more than 3 x CL, exactly 3 x CL comes
    back."""
    from combat import typed_reactions as tr

    seen = None
    for seed in ("CAP-A", "CAP-B", "CAP-C", "CAP-D", "CAP-E", "CAP-F"):
        e, me, foe = _seeded(F + "COUNTERPRESSURE", seed, cl=2, extras=(F + "RETURNING_IMPACT",))
        e._typed_pending_damage_type = "SLASHING"
        before = foe.current_hp
        tr.on_damage(e, me, 100, 0, source_actor_id=FOE)
        if _caught(e) > 6:
            seen = (before - foe.current_hp, _caught(e))
            break
    assert seen is not None, "no seed reduced more than 3 x CL, so the cap is untested here"
    assert seen[0] == 6


def test_returning_impact_does_not_double_count_a_successful_save():
    """Its own Strength save still answers it: "Successful Save: Take half damage and suffer no forced movement" -- the capped
    amount is divided once, on the saving branch, and the push does not happen."""
    from combat import typed_reactions as tr

    _, e, me, foe = SWF.fight(F + "COUNTERPRESSURE", extras=(F + "RETURNING_IMPACT",), cl=5, dc=1)
    e._typed_pending_damage_type = "SLASHING"
    before = foe.current_hp
    tr.on_damage(e, me, 100, 0, source_actor_id=FOE)
    assert (foe.position.x, foe.position.y) == (me.position.x + 1, me.position.y), "no push on a successful save"
    assert before - foe.current_hp == min(_caught(e), 15) // 2, "half of the capped amount, divided once"


def _counter_reactor(e):
    """The creature whose OWN compiled Counterpressure answered the most recent packet, from the engine's own record."""
    windows = [event for event in e.events if event.event_type == "REACTION_WINDOW_OPENED"
               and str(event.source_definition_id).split("#")[0] == F + "COUNTERPRESSURE"]
    return windows[-1].actor_id if windows else None


def _caught_by(e, actor_id):
    """The damage that one owner's own Counterpressure kept off, from that owner's own receipt (not from any other owner)."""
    return [int((event.payload or {}).get("reduction") or 0) for event in e.events
            if event.event_type == "REACTION_RESOLVED"
            and str(event.source_definition_id).split("#")[0] == F + "COUNTERPRESSURE"
            and event.actor_id == actor_id][-1]


def _next_round(e, *actors):
    """A round boundary, for the printed "once per round" limit the follow-up's GM grant counts in. The number is the engine's
    own counter, so this is the same state a real round change produces -- no test-only flag is invented."""
    e.state.round_number = int(e.state.round_number) + 1
    for actor in actors:
        actor.reaction_available = True


def test_returning_impact_reflects_a_protected_ally_back_for_what_counterpressure_caught():
    """Counterpressure's own printed trigger is "You, a creature, or an object within 5 feet of yourself or one Pressure Anchor
    ... takes damage", so its owner cushions an ally's blow as readily as its own. Returning Impact answers that same moment and
    returns "the damage Counterpressure reduced" -- so an ally's protection must reflect too, for exactly what that reaction
    caught. The amount cannot be read from the follow-up context: the follow-up is opened by a fresh context that never carries
    the reaction's protected creature (typed_reactions.py on_own_event -> _generic_context), so it has to come from the reaction
    window itself, which names the ally it shielded."""
    from combat import typed_reactions as tr

    e, me, foe = _seeded(F + "COUNTERPRESSURE", "RI-ALLY", cl=20, extras=(F + "RETURNING_IMPACT",))
    ally = SWF.ally(e, me)
    e._typed_pending_damage_type = "SLASHING"
    before = foe.current_hp
    tr.on_damage(e, ally, 100, 0, source_actor_id=FOE)  # the ALLY takes the blow; its owner cushions it
    caught = _caught_by(e, me.entity_id)
    assert _counter_reactor(e) == me.entity_id, "the owner's own compiled Counterpressure answered"
    assert caught > 0, "Counterpressure kept something off the ally's packet"
    assert before - foe.current_hp == min(caught, 60), \
        "an ally's protection reflects back too, for exactly the damage Counterpressure kept off it"


def test_returning_impact_uses_the_current_protection_not_an_earlier_self_protection():
    """The reaction window that is current is the one the engine opened for the blow in flight, never an older window from an
    earlier hit by the same attacker. Reading the older one paired its own larger pending damage with this hit's roll and
    returned several times the pressure this reaction actually caught."""
    from combat import typed_reactions as tr

    e, me, foe = _seeded(F + "COUNTERPRESSURE", "RI-STALE", cl=20, extras=(F + "RETURNING_IMPACT",))
    ally = SWF.ally(e, me)
    e._typed_pending_damage_type = "SLASHING"
    tr.on_damage(e, me, 100, 0, source_actor_id=FOE)  # an earlier blow the owner cushioned for itself
    stale = _caught_by(e, me.entity_id)
    _next_round(e, me)
    before = foe.current_hp
    tr.on_damage(e, ally, 2, 0, source_actor_id=FOE)  # a small blow against the ally this round
    caught = _caught_by(e, me.entity_id)
    assert caught == min(_cushion_roll(e), 2), "a 2-point packet cannot lose more than 2 points, whatever the roll said"
    assert before - foe.current_hp == caught, \
        f"the earlier self-protection window (pending 100) must not be paired with this hit's roll (stale caught {stale})"


def test_returning_impact_reflects_the_owner_whose_own_counterpressure_answered():
    """Two real Force fighters, each with its OWN compiled rows, on one team. The amount is scoped to the owner that actually
    answered this packet: the second fighter's own Cushion the Blow, from an earlier packet, is not this owner's pressure to
    return. Each owner's amount is read from that owner's own receipt, so a wrong owner's answer cannot pass."""
    from combat import typed_reactions as tr

    e, me, mate, foe = _two_owners(F + "COUNTERPRESSURE", "RI-TWO", cl=20, extras=(F + "RETURNING_IMPACT",))
    ally = SWF.ally(e, me)
    ally.position = ally.position.model_copy(update={"x": 2, "y": 6})  # a free cell, clear of both owners
    e._typed_pending_damage_type = "SLASHING"
    tr.on_damage(e, mate, 40, 0, source_actor_id=FOE)  # the second fighter cushions a blow of its own
    mate_caught = _caught_by(e, mate.entity_id)
    assert _counter_reactor(e) == mate.entity_id and mate_caught > 0
    _next_round(e, me, mate)
    before = foe.current_hp
    tr.on_damage(e, ally, 100, 0, source_actor_id=FOE)  # now an ally's blow, which one owner cushions
    reactor = _counter_reactor(e)
    caught = _caught_by(e, reactor)
    assert reactor in (me.entity_id, mate.entity_id), f"a real compiled owner answered, not a bystander ({reactor})"
    assert caught > 0
    assert before - foe.current_hp == min(caught, 60), "the reflecting amount is the answering owner's own caught pressure"
    assert min(caught, 60) != min(mate_caught, 60), \
        "the two owners' amounts differ, so the other owner's reduction is provably not reused"


def test_ten_thousand_rebounds_answers_each_foe_that_strikes_once():
    """Ten Thousand Rebounds: "the first time each hostile creature deals physical damage to you or an ally within 30 feet, it
    makes a Strength saving throw". The GM line ruled whether the Reaction could be taken at all."""
    from combat import typed_reactions as tr

    _, e, me, foe = SWF.fight(F + "COUNTERPRESSURE", extras=(F + "TEN_THOUSAND_REBOUNDS",))
    e._typed_pending_damage_type = "SLASHING"
    tr.on_damage(e, me, 100, 0, source_actor_id=FOE)
    assert SWF.has(me, "force_rebounds"), "activating Counterpressure arms it, spending its own 8 CP"
    before = foe.current_hp
    e._commit_damage(me, 20, "SLASHING", "system:test.attack", FOE, None, reaction_depth=0)
    assert foe.current_hp < before, "4d8 Force damage after the creature's Strength save"
    assert [r for r in e.rolls if r.reason.startswith(f"SAVE:{F}TEN_THOUSAND_REBOUNDS")], "the striking creature makes its own Strength saving throw"
    after = foe.current_hp
    e._commit_damage(me, 20, "SLASHING", "system:test.attack", FOE, None, reaction_depth=0)
    assert foe.current_hp == after, "a creature is affected only once during the duration"
    other = SWF.ally(e, me)
    other.entity_id, other.team_id = "review:foe-two", "team:b"
    e.state.actors["review:foe-two"] = e.state.actors.pop("review:ally")
    its_hp = other.current_hp
    e._commit_damage(me, 20, "SLASHING", "system:test.attack", other.entity_id, None, reaction_depth=0)
    assert other.current_hp < its_hp and foe.current_hp == after, \
        "the second hostile creature answers in its own right, by taking the blow's rebound itself"
    assert len([r for r in e.rolls if r.reason.startswith(f"SAVE:{F}TEN_THOUSAND_REBOUNDS")]) == 2


def test_ten_thousand_rebounds_answers_from_every_armed_owner_on_the_blow():
    """"each hostile creature ... deals physical damage to you or an ally": every armed owner the blow reaches answers for
    itself. One owner's answer is not the end of the fight's answer, and one owner's own retaliation is not a blow another owner
    answers."""
    from combat import typed_reactions as tr
    from combat.ext import force

    e, me, mate, foe = _two_owners(F + "COUNTERPRESSURE", "REBOUNDS-TWO-OWNERS", extras=(F + "TEN_THOUSAND_REBOUNDS",))
    e._typed_pending_damage_type = "SLASHING"
    tr.on_damage(e, me, 100, 0, source_actor_id=foe.entity_id)
    tr.on_damage(e, mate, 100, 0, source_actor_id=foe.entity_id)  # each owner arms on its own Counterpressure
    assert SWF.has(me, "force_rebounds") and SWF.has(mate, "force_rebounds"), "both owners are armed"
    before = foe.current_hp
    e._commit_damage(me, 20, "SLASHING", "system:test.attack", foe.entity_id, None, reaction_depth=0)
    saves = [r for r in e.rolls if r.reason.startswith(f"SAVE:{F}TEN_THOUSAND_REBOUNDS")]
    assert len(saves) == 2, f"both armed owners answered that blow, each with its own Strength save (saw {len(saves)})"
    assert foe.current_hp < before, "the striking creature took both rebounds"
    assert force._rebound_harmed(e, me, me, foe) is False and force._rebound_harmed(e, mate, me, foe) is False, \
        "and neither owner may answer that same creature again"


def test_ten_thousand_rebounds_answers_only_its_owner_own_compiled_response():
    """A malformed or legacy row is that owner's own gap, not the end of the table's answer: one owner with no readable
    response does not silence the other."""
    from combat import typed_reactions as tr
    from combat.ext import force

    e, me, mate, foe = _two_owners(F + "COUNTERPRESSURE", "REBOUNDS-LEGACY", extras=(F + "TEN_THOUSAND_REBOUNDS",))
    e._typed_pending_damage_type = "SLASHING"
    tr.on_damage(e, me, 100, 0, source_actor_id=foe.entity_id)
    tr.on_damage(e, mate, 100, 0, source_actor_id=foe.entity_id)
    rows = e.typed_reaction_rows[mate.entity_id]
    e.typed_reaction_rows[mate.entity_id] = [{**row, "effects": []} for row in rows]  # a saved fight whose row lost its response
    before = foe.current_hp
    e._commit_damage(me, 20, "SLASHING", "system:test.attack", foe.entity_id, None, reaction_depth=0)
    assert len([r for r in e.rolls if r.reason.startswith(f"SAVE:{F}TEN_THOUSAND_REBOUNDS")]) == 1, \
        "only the owner with a readable response answered"
    assert foe.current_hp < before, "that owner's answer still landed"


def test_ten_thousand_rebounds_leaves_poison_and_psychic_damage_to_the_gm_honestly():
    """The printed exclusions are two different things. Poison and Psychic damage are left out by the damage type the table can
    read, and the test drives a blow that is not physical. Ongoing damage is NOT separable from a fresh blow of the same type
    anywhere in the engine, so that exclusion stays the GM's call and says so in the rider rather than being claimed."""
    from combat import typed_reactions as tr
    from tests.h1_support import ROOT

    _, e, me, foe = SWF.fight(F + "COUNTERPRESSURE", extras=(F + "TEN_THOUSAND_REBOUNDS",))
    e._typed_pending_damage_type = "SLASHING"
    tr.on_damage(e, me, 100, 0, source_actor_id=FOE)
    after = foe.current_hp
    for kind in ("POISON", "PSYCHIC"):
        e._commit_damage(me, 20, kind, "system:test.attack", FOE, None, reaction_depth=0)
        assert foe.current_hp == after, f"{kind} is not a physical blow"
    import json
    row = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())["mechanics"][F + "TEN_THOUSAND_REBOUNDS"]
    assert any("Ongoing damage" in rider and "the GM decides by hand" in rider for rider in row["riders"]), \
        "the ongoing-damage exclusion is stated as the GM's manual call, not claimed as automated"
    assert row["coverage"] != "FULL", "a printed line the table does not run is not a FULL mechanic"


def test_ten_thousand_rebounds_ends_at_the_start_of_your_next_turn():
    """"Until the start of your next turn": the arming ends when its owner's next turn begins, through the expiry name the engine
    sweeps, not by luck."""
    from combat import typed_reactions as tr
    from combat.ext import force

    _, e, me, foe = SWF.fight(F + "COUNTERPRESSURE", extras=(F + "TEN_THOUSAND_REBOUNDS",))
    e._typed_pending_damage_type = "SLASHING"
    tr.on_damage(e, me, 100, 0, source_actor_id=FOE)
    held = force._armed(e, me)
    assert held is not None and held["spent"] == "", "armed, with nobody answered yet"
    before = foe.current_hp
    e._commit_damage(me, 20, "SLASHING", "system:test.attack", FOE, None, reaction_depth=0)
    assert foe.current_hp < before
    answered = foe.current_hp
    me.turns_started = int(me.turns_started) + 1
    e._system_start_turn()
    assert force._armed(e, me) is None, "it ended at the start of its owner's next turn"
    assert foe.current_hp == answered, "and no later blow rebounds"


def test_ten_thousand_rebounds_keeps_only_integers_and_strings_in_its_record():
    """The once-per-creature ledger is fight state, so it may hold nothing the table cannot store and replay."""
    from combat import typed_reactions as tr
    from combat.ext import force

    _, e, me, foe = SWF.fight(F + "COUNTERPRESSURE", extras=(F + "TEN_THOUSAND_REBOUNDS",))
    e._typed_pending_damage_type = "SLASHING"
    tr.on_damage(e, me, 100, 0, source_actor_id=FOE)
    e._commit_damage(me, 20, "SLASHING", "system:test.attack", FOE, None, reaction_depth=0)
    record = force._armed(e, me)
    assert record is not None and FOE in str(record["spent"]).split(), f"the answering creature is recorded (got {record})"
    assert all(type(value) in (int, str) for value in record.values()), "only integers and strings are stored"
    assert all(isinstance(condition.expires_on, str) for condition in me.conditions.values())


def test_ten_thousand_rebounds_is_asked_of_a_player_and_decides_for_itself_as_an_ai():
    """Checklist 9: the 8 CP arming is a player-owned decision, so an Ask me fighter played by a person is asked (Use or Pass) and
    nothing is spent without an answer; the same fighter under AI control answers for itself without a prompt."""
    from combat import typed_reactions as tr
    from combat.gate2_runtime_models import ReactionDecision

    from combat.gate2_runtime_models import ActionIntent

    def asked(selection, ai):
        """One blow answered on the owner's own turn, with the table asking the fighter's controller for every reaction it owns."""
        e, me, foe = _seeded(F + "COUNTERPRESSURE", "REBOUNDS-ASK", cl=15, extras=(F + "TEN_THOUSAND_REBOUNDS",),
                             plan={"ask": True})
        prompts = []

        def provider(request):
            asked = request["reaction_source_id"]
            prompts.append(asked)
            answer = selection if "TEN_THOUSAND_REBOUNDS" in asked else "USE"  # the arming rides an answered Counterpressure
            return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                    reaction_source_id=asked, selection=answer), None

        e.set_reaction_provider(provider)
        e.typed_ask_reactors = frozenset() if ai else frozenset({me.entity_id})
        e._active_intent = ActionIntent(intent_id="auto87f1", decision_id="d", candidate_id="c",
                                        state_version=e.state.state_version, actor_id=me.entity_id, target_ids=())
        qi = int(me.resources["resource:core.qi"])
        e._typed_pending_damage_type = "SLASHING"
        tr.on_damage(e, me, 100, 0, source_actor_id=FOE)
        return prompts, qi - int(me.resources["resource:core.qi"]), SWF.has(me, "force_rebounds")

    declined, spent, armed = asked("DECLINE", ai=False)
    assert f"reaction:typed.{F}TEN_THOUSAND_REBOUNDS" in declined, f"the player was asked about the arming (asked {declined})"
    assert f"reaction:typed.{F}COUNTERPRESSURE" in declined, "and about the Counterpressure it rides"
    assert spent == 1 and not armed, "a passed question spends none of its printed 8 CP and arms nothing"
    used, spent, armed = asked("USE", ai=False)
    assert f"reaction:typed.{F}TEN_THOUSAND_REBOUNDS" in used
    assert spent == 9 and armed, "the answered question spends the printed 8 CP and arms it"
    auto, spent, armed = asked("USE", ai=True)
    assert not auto and spent == 9 and armed, "an AI fighter answers for itself and is never asked"


def test_court_of_the_answering_world_cushions_an_allies_falling_damage():
    """Court of the Answering World: "Allies ... Reduce falling and collision damage by your Proficiency Bonus". The GM applied it."""
    from combat import falling

    _, e, me, foe = SWF.fight(F + "COURT_OF_THE_ANSWERING_WORLD")
    friend = SWF.ally(e, me)
    SWF.cast(e, "Court of the Answering World")
    me.position = friend.position  # the Domain is centred on its owner; the ally stands beside it
    e.__dict__["_fall_packet"] = falling.Fall(actor_id=friend.entity_id, distance_ft=60, cause="test")
    assert falling.remaining_packet(e, friend, 30, "BLUDGEONING", falling.SOURCE, None) == 30 - me.proficiency_bonus


def test_court_of_the_answering_world_takes_the_proficiency_bonus_off_a_hammerfall_collision():
    """"Reduce falling and collision damage by your Proficiency Bonus": the collision half is wired into Hammerfall's own slam
    (combat/ext/force.py impact_collisions -> court_collision_reduction), and the reduction is the Domain owner's Proficiency
    Bonus for an ally standing in the Domain. Today no blow can reach that code -- Impact's printed target is "one visible
    creature", a hostile one, and the Domain only cushions its own side -- so this pins both halves honestly instead of claiming a
    collision that cannot happen."""
    from combat.ext import force

    _, e, me, foe = SWF.fight(F + "IMPACT", extras=(F + "HAMMERFALL", F + "COURT_OF_THE_ANSWERING_WORLD"))
    ally = SWF.ally(e, me)
    SWF.cast(e, "Court of the Answering World")
    inside = force._court_zone(e, me).affected_cells[0]
    ally.position = ally.position.model_copy(update={"x": inside.x, "y": inside.y})
    assert force.court_collision_reduction(e, ally) == me.proficiency_bonus, "an ally in the Domain loses the Court's PB off a collision"
    foe.position = foe.position.model_copy(update={"x": inside.x, "y": inside.y + 1})
    assert force.court_collision_reduction(e, foe) == 0, "an enemy in the Domain is cushioned by nothing"
    me.action_available = True
    legal = [c for c in e.legal_candidates() if c.display_name.startswith("Impact")]
    assert all(ally.entity_id not in c.target_ids for c in legal), \
        "Impact's printed target is one hostile creature, so a Court ally cannot be the one slammed (inherited gap, see the report)"
    assert any(FOE in c.target_ids for c in legal), "the hostile one is"
    assert any("Hammerfall" in c.display_name for c in legal), "Hammerfall's own slam is compiled into the Impact options"


def test_impact_never_offers_a_target_with_total_cover_from_every_origin():
    """Impact: "Choose one visible creature or object within 30 feet of that origin. The target must not have Total Cover from the
    origin." The table measured cover from the user and offered the target anyway."""
    from combat import zones
    from combat.ext import force

    _, e, me, foe = SWF.fight(F + "IMPACT", extras=(F + "FORCE_WALL",))
    in_reach = [cell for cell in force.origins(e, me, 60) if e.grid.distance_ft(cell, foe.position) <= 30]
    assert force._always_total_cover(e, me, in_reach, foe) is False  # open ground: a legal target
    foe.position = foe.position.model_copy(update={"x": 9, "y": 6})
    me.action_available = True
    SWF.cast(e, "Force Wall", at=(4, 6))  # a solid wall between the two
    zones.sync_walls(e)
    assert force._always_total_cover(e, me, force.origins(e, me, 60), foe) is True
    assert not [c for c in e.legal_candidates() if c.display_name.startswith("Impact") and FOE in c.target_ids]


def test_impact_still_offers_a_target_behind_three_quarters_cover():
    """Three-quarters cover is the +5 bonus, not Total Cover: "The target must not have Total Cover from the origin" refuses a
    creature no origin can reach, and a creature behind three-quarters cover with an open ray from a legal origin is still a
    legal target."""
    from combat.effect_cover import query
    from combat.ext import force

    _, e, me, foe = SWF.fight(F + "IMPACT")
    foe.position = foe.position.model_copy(update={"x": 7, "y": 6})
    me.action_available = True
    assert [c for c in e.legal_candidates() if c.display_name.startswith("Impact") and FOE in c.target_ids]
    e.grid.cover.add((5, 6))  # the table's own three-quarters cover (combat/zones.py "cover": "three_quarters")
    e.__dict__["_cover_three_quarters"] = {(5, 6)}
    found = query(e, e._effect_cells(me), me.entity_id, foe, purpose="effect")
    assert found["bonus"] == 5 and found["blocked"] is False, \
        "three-quarters cover is +5 with an open ray, not Total Cover"
    assert force._always_total_cover(e, me, force._target_origins(e, me, F + "IMPACT", foe), foe) is False
    assert [c for c in e.legal_candidates() if c.display_name.startswith("Impact") and FOE in c.target_ids], \
        "the target behind three-quarters cover is still a legal Impact target"
    assert force._origin_choices(e, me, F + "IMPACT", foe), "and the origin menu still offers a usable origin"


def test_impact_asks_the_cover_question_only_of_origins_within_the_targets_thirty_feet():
    """"within 30 feet of that origin": the origins are filtered by the target's own range first, so one origin cannot satisfy
    the range while a different one supplies the sight line. The user is out of the target's 30 feet; the only origin that is
    inside them is walled off from it, so the printed Total Cover clause refuses the target."""
    from combat import zones
    from combat.ext import force

    _, e, me, foe = SWF.fight(F + "IMPACT", extras=(F + "FORCE_WALL",))
    me.position = me.position.model_copy(update={"x": 2, "y": 6})
    foe.position = foe.position.model_copy(update={"x": 10, "y": 6})
    _anchor(e, me, (6, 6))  # a second origin, 20 feet from the target and 20 feet from the user
    every = force.origins(e, me, 60)
    assert [e.grid.distance_ft(cell, foe.position) for cell in every] == [40, 20], "only the anchor is within the target's 30 feet"
    me.action_available = True
    assert [c for c in e.legal_candidates() if c.display_name.startswith("Impact") and FOE in c.target_ids], \
        "the anchor inside 30 feet keeps the target legal"
    SWF.cast(e, "Force Wall", at=(7, 6))  # a solid wall between that anchor and the target
    zones.sync_walls(e)
    usable = force._target_origins(e, me, F + "IMPACT", foe)
    assert [(cell.x, cell.y) for cell in usable] == [(6, 6)], "the cover question is asked of that origin alone"
    assert force._always_total_cover(e, me, usable, foe) is True
    assert force._origin_choices(e, me, F + "IMPACT", foe) == [], "so no origin is left to choose from"
    assert not [c for c in e.legal_candidates() if c.display_name.startswith("Impact") and FOE in c.target_ids]


def test_impact_origin_menu_never_offers_an_origin_the_target_cannot_be_seen_from():
    """Legacy origin queries still report a clear anchor ray; a new Impact action additionally
    requires the caster's actual sight. An anchor is an origin, not a second pair of eyes."""
    from combat import zones
    from combat.ext import force

    _, e, me, foe = SWF.fight(F + "IMPACT", extras=(F + "FORCE_WALL",))
    foe.position = foe.position.model_copy(update={"x": 9, "y": 6})
    _anchor(e, me, (7, 6))  # a second origin, beside the target
    me.action_available = True
    SWF.cast(e, "Force Wall", at=(4, 6))  # the user is walled off from the target; the anchor is not
    zones.sync_walls(e)
    cells = {(cell.x, cell.y): cell for cell in force.origins(e, me, 60)}
    assert sorted(cells) == [(3, 6), (7, 6)], "two origins exist"
    assert force._origin_reaches(e, me, cells[(3, 6)], foe) is False, "the user's own square is walled off from the target"
    assert force._origin_reaches(e, me, cells[(7, 6)], foe) is True
    assert force._always_total_cover(e, me, force._target_origins(e, me, F + "IMPACT", foe), foe) is False, \
        "one clear origin keeps the target legal"
    assert force._origin_choices(e, me, F + "IMPACT", foe) == [cells[(7, 6)]], "the legacy geometry query returns only the clear anchor"

    assert not [c for c in e.legal_candidates() if c.display_name.startswith("Impact") and FOE in c.target_ids], \
        "the caster cannot perceive either the anchor or target through the wall"


SENSE = "tianxia.talent.force.pressure_sense"


def _sensed(e):
    return [str((event.payload or {}).get("log") or "") for event in e.events
            if event.event_type == "PASSIVE_TRIGGERED" and "Pressure Sense" in str((event.payload or {}).get("log") or "")]


def test_pressure_sense_reports_a_creature_crossing_one_of_your_anchors():
    """Pressure Sense: "You know when one of your Pressure Anchors ... is crossed by a creature of Small size or larger". The whole
    talent was a GM line, and the second clause (an exact square) is the one the table must not give away."""
    from combat.ext import force

    _, e, me, foe = SWF.fight(F + "IMPACT", extras=(SENSE,))
    _anchor(e, me, (5, 6))  # one square beyond the foe, which stands next to the user
    assert not _sensed(e)
    me.action_available = True
    SWF.cast(e, "Impact", target=FOE)  # the push carries the foe across the anchor's square
    assert (foe.position.x, foe.position.y) == (5, 6)
    (line,) = _sensed(e)
    assert "5,6" not in line and FOE not in line, "it says an anchor answered, never which square or which creature"


def test_pressure_sense_reports_an_anchor_that_travels_with_its_creature_and_one_that_ends():
    from combat import typed_executor as te
    from combat.ext import force

    _, e, me, foe = SWF.fight(F + "IMPACT", extras=(SENSE,))
    ally = SWF.ally(e, me)
    ally.position = ally.position.model_copy(update={"x": 4, "y": 9})
    _anchor(e, me, (4, 9))
    zone = force.external(e, me)[0]
    assert zone.trigger_profile.get("anchor_id") == ally.entity_id
    action = next(row for row in e.action_catalog.values() if row.display_name == "Impact")
    te._push(te.Context(e, me, action, None, {"numbers": {"pb": 4, "save_dc": 50}}, [ally], ally, {}), ally, 5, pull=False)
    assert ally.position != ally.position.model_copy(update={"x": 4, "y": 9})
    assert any("moved with the creature" in line for line in _sensed(e))
    me.action_available = True
    SWF.cast(e, "Dismiss anchor")
    assert any("no longer there" in line for line in _sensed(e))
    assert force.external(e, me) == []


def test_pressure_sense_is_inert_for_a_character_who_does_not_own_it():
    _, e, me, foe = SWF.fight(F + "IMPACT")
    _anchor(e, me, (5, 6))
    me.action_available = True
    SWF.cast(e, "Impact", target=FOE)
    assert not _sensed(e)


# ------------------------------------------------------------------ AUTO87f1: the real table (commit + reload, and the player's own question)
def _two_blows(bundles):
    """Give each hostile fighter a second, free copy of its own Impact so one turn can land two physical blows, which is what
    "the first time each hostile creature deals physical damage" needs to be observed twice. The setup action's printed numbers
    are that fighter's own compiled Impact; only its economy is waived so the fixture can strike twice."""
    from combat.canonical import canonical_sha256
    from tests.r1i_service_support import FOE as ENEMY, SECOND

    for bundle in [b for b in bundles if b["actor_id"] in (ENEMY, SECOND)]:
        original = next(a for a in bundle["action_catalog"] if a["display_name"] == "Impact")
        extra = json.loads(json.dumps(original))
        extra["source_definition_id"] = f"test:auto87f1.second_blow:{bundle['actor_id']}"
        extra["display_name"] = "Second Impact"
        extra["economy"] = "NONE"
        bundle["action_catalog"].append(extra)
        bundle["actor_template"]["action_ids"].append(extra["source_definition_id"])
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)


def _rebounds_table(tmp_path):
    """A real table: the Force owner is played by hand with Ask me reactions, and two hostile Force fighters sit next to it, so
    two separate creatures can strike inside the one arming window."""
    from tests.r1i_service_support import FOE as ENEMY, OWNER, SECOND, candidate, fixture

    combat, table, mid, send, commit = fixture(tmp_path, [F + "COUNTERPRESSURE", F + "TEN_THOUSAND_REBOUNDS"],
                                               foe_talents=[F + "IMPACT"], foe_ac=0, seed="AUTO87F1-REBOUNDS",
                                               second_talents=[F + "IMPACT"], bundle_transform=_two_blows)
    return combat, table, mid, send, commit, ENEMY, SECOND, OWNER, candidate


def _blow(table, mid, send, commit, attacker, owner, candidate, label, pass_only=""):
    """Advance to ``attacker``'s turn and take one of its own Impact options against the owner, on a fighter played by hand
    while the owner is a MANUAL fighter whose reaction questions pause the table. Every question is answered Use, except a
    question naming ``pass_only``, which the player passes; the action is then committed."""
    while table.state(mid)["menu"]["actor_id"] != attacker:
        commit(table.state(mid)["menu"]["end_turn"])
    cid = candidate(table, mid, label, owner)
    answers, prompts = [], []
    for _ in range(12):
        result = send(cid, answers)
        if result["status"] == "COMMITTED":
            return prompts
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        prompts.append(prompt)
        asked = prompt["context"]["reaction_source_id"]
        answer = {**prompt["context"], "selection": "DECLINE" if pass_only and pass_only in asked else "USE"}
        if prompt.get("choice"):
            answer["option_ids"] = (prompt["choice"].get("preferred") or [prompt["choice"]["options"][0]["id"]])[:1]
        answers.append(answer)
    raise AssertionError("too many prompts")


def _armed_on(engine, owner):
    return next((c for c in engine.state.actors[owner].conditions.values()
                 if c.condition_id == "condition:typed.force_rebounds"), None)


def test_ten_thousand_rebounds_survives_a_table_commit_and_reload_and_still_answers_once(tmp_path):
    """A real table, a real commit, a real reload whose mechanical replay must pass: the arming, its printed text and its
    once-per-creature ledger are fight state, and the creature that already answered does not answer again after the reload."""
    from combat.ext import force
    from tests.test_r1i_round3 import reload

    combat, table, mid, send, commit, enemy, second, owner, candidate = _rebounds_table(tmp_path)
    prompts = _blow(table, mid, send, commit, enemy, owner, candidate, "Impact")
    assert [p for p in prompts if "TEN_THOUSAND_REBOUNDS" in p["context"]["reaction_source_id"]], \
        "the player was asked before Ten Thousand Rebounds spent its printed 8 CP"
    armed = _armed_on(combat._load_session(mid).engine, owner)
    assert armed is not None and enemy in str(armed.data["spent"]).split(), \
        "it armed on the real table and the blow that armed it was answered"
    saves = len([r for r in combat._load_session(mid).engine.rolls if r.reason.startswith(f"SAVE:{F}TEN_THOUSAND_REBOUNDS")])
    assert saves == 1, "that creature answered exactly once"

    engine = reload(tmp_path, mid)
    arming = _armed_on(engine, owner)
    assert arming is not None, "the arming is still there after a commit and a reload that replays mechanically"
    assert "until the start of your next turn" in str(arming.data.get("label")), "its printed duration travels with it"
    assert all(type(value) in (int, str) for value in arming.data.values()) and arming.expires_on, \
        "only integers and strings are stored, and the expiry travels with them"
    assert str(arming.data["spent"]) == str(armed.data["spent"]), "the once-per-creature ledger survives the reload"
    assert force._rebound_harmed(engine, engine.state.actors[owner], engine.state.actors[owner],
                                 engine.state.actors[enemy]) is False, \
        "so the creature that already answered is not live again"
    assert force._rebound_harmed(engine, engine.state.actors[owner], engine.state.actors[owner],
                                 engine.state.actors[second]) is True, \
        "while a creature that has not answered still is"

    _blow(table, mid, send, commit, second, owner, candidate, "Impact")
    after = reload(tmp_path, mid)
    assert len([r for r in after.rolls if r.reason.startswith(f"SAVE:{F}TEN_THOUSAND_REBOUNDS")]) == saves + 1, \
        "a second hostile creature answers in its own right, from the reloaded fight"
    _blow(table, mid, send, commit, second, owner, candidate, "Second Impact")
    last = reload(tmp_path, mid)
    assert len([r for r in last.rolls if r.reason.startswith(f"SAVE:{F}TEN_THOUSAND_REBOUNDS")]) == saves + 1, \
        "and neither of them answers a second blow during the duration"


def test_ten_thousand_rebounds_is_not_spent_when_the_player_passes(tmp_path):
    """Checklist 9 on the real table: a passed question costs nothing and arms nothing, and the Counterpressure it rode is
    untouched."""
    combat, table, mid, send, commit, enemy, second, owner, candidate = _rebounds_table(tmp_path)
    prompts = _blow(table, mid, send, commit, enemy, owner, candidate, "Impact", pass_only="TEN_THOUSAND_REBOUNDS")
    engine = combat._load_session(mid).engine
    assert any(p["context"]["reaction_source_id"] == f"reaction:typed.{F}TEN_THOUSAND_REBOUNDS" for p in prompts)
    assert _armed_on(engine, owner) is None, "a passed question arms nothing"
    assert any(e.event_type == "REACTION_RESOLVED" and str(e.source_definition_id).startswith(F + "COUNTERPRESSURE")
               for e in engine.events), "Counterpressure itself still answered"
