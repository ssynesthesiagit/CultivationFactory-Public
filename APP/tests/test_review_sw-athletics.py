"""Sphere typing review, sweep batch sw-athletics (athletics, axes, barrage): every corrected typing is compiled and run
through the engine, and each test fails on the typing the authority carried before the review.

Overrides live in authority/typed_mechanics/reviewed_final.d/review_sw-athletics.json (plus two in-place edits to
martial.json / bodyb.json); combat/factory_compiler.py gained _weapon_dice (weapon damage dice for Barrage) and
_target_mark (target.requires_mark).  Saves are forced with the sheet's technique DC (50: the foe fails, -40: the foe
succeeds) and attacks always hit (foe AC -50), so the assertions read the branch the printed text names.
"""

import json
import re
from functools import lru_cache
from pathlib import Path

import pytest

import combat.factory_compiler as factory_compiler
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate4_engine import Gate4ControllerEngine
from combat.typed_executor import bears_mark, mark_condition_id

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.sweep"
FOE = "actor:factory.foe"
ATHLETICS, AXES, BARRAGE = "tianxia.sphere.athletics", "tianxia.sphere.axes", "tianxia.sphere.barrage"
AXE_KIT = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.fu", "name": "Fu (Short Axe)", "quantity": 1}]}}
BOW_KIT = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.gong_jian", "name": "Gong Jian", "quantity": 1},
                                      {"item_id": "tianxia.mortal.weapon.fei_biao", "name": "Fei Biao", "quantity": 1}]}}
FAIL, PASS = 50, -40  # technique save DC that makes the foe fail / succeed every save
HEWING = "TAL_AXES_HEWING_STRIKE"
STRIKE = "Fu (Short Axe) attack: Hewing Strike: "


# ------------------------------------------------------------------------------------------------------- harness


@lru_cache(maxsize=4)
def _load_mechanics(path):
    return json.loads(Path(path).read_bytes())["mechanics"]


def _mechanics():
    return _load_mechanics(str(factory_compiler.TYPED_AUTHORITY))  # read at call time: the module attribute may be swapped


def _sheet(sphere, talents, kit, *, cl=10, dc=16):
    bases = [key for key, mech in _mechanics().items() if mech.get("sphere_id") == sphere and mech.get("kind") == "base_ability"]
    return {
        "identity": {"proficiency_bonus": 4, "cultivation_level": cl, "path": "Body Refining", "key_ability": "STR"},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "score": 16, "modifier": 3} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
            "primary_resource": {"name": "Stamina", "maximum": 60}, "armor_class": {"base_value": 14}, "hit_points": {"maximum": 80},
            "speed": {"walking_ft": 30}, "technique_save_dc": dc, "technique_attack_bonus": 8,
        },
        "path_and_subpath": {"path_record_ids": ["tianxia.path.body_refining"]},
        "equipment": [kit],
        "spheres_and_talents": {"sphere_record_ids": [sphere] if sphere else [], "learned_talent_record_ids": list(talents),
                                "automatic_sphere_component_record_ids": bases if sphere else []},
    }


def _bundle(sphere, talents, kit, *, cl=10, dc=16, actor_id=ME):
    return compile_character(_sheet(sphere, talents, kit, cl=cl, dc=dc), actor_id=actor_id)


def _rows(bundle):
    return {row["display_name"]: row for row in bundle["action_catalog"]}


def _costs(bundle, name):
    return [list(cost) for cost in _rows(bundle)[name]["costs"]]


def _engine(bundle, *, foe_at=(4, 6), foe_hp=None, sure_hit=True):
    engine = Gate4ControllerEngine(ROOT, match_seed="SWEEP", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": foe_at[0], "y": foe_at[1]}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    foe = engine.state.actors[AN]
    if sure_hit:
        foe.armor_class = -50
    if foe_hp:
        foe.maximum_hp = max(foe_hp, foe.maximum_hp)
        foe.current_hp = foe_hp
    _ready(engine)
    return engine


def _ready(engine):
    me = engine.state.actors[ME]
    engine.state.current_actor_id = ME
    me.action_available, me.bonus_action_available, me.reaction_available = True, True, True
    return me


def _legal(engine):
    return {c.display_name for c in engine.legal_candidates()}


def _use(engine, name, target=AN):
    # Reviewed hands change c18f4990: ready the requested weapon legally.
    from tests.equipment_readiness import ready_weapon
    base_name, separator, aim = name.rpartition(' at ')
    requested = base_name if separator else name
    ready_weapon(engine, requested, ME)
    matches = [c for c in engine.legal_candidates() if c.display_name == name
               or (c.display_name.partition(" — ")[0] == name
                   and c.display_name.partition(" — ")[2].startswith(("Hits allies too", "Allies you can choose")))]
    assert matches, f"{name!r} is not a legal action; legal: {sorted(_legal(engine))}"
    candidate = matches[0]
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"i-{name}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME,
                                       target_ids=candidate.target_ids or ((target,) if target else ()), destination=candidate.destination))
    return engine.events[before:]


def _bite(engine):
    """The foe already bears the caster's Bite."""
    engine._apply_condition(engine.state.actors[AN], mark_condition_id("Bite", ME), "test:bite", ME, expires_on="UNTIL_REMOVED")


def _cast(sphere, talents, name, kit, *, dc=16, cl=10, foe_at=(4, 6), foe_hp=None, marked=False, target=AN, bundle=None):
    engine = _engine(bundle or _bundle(sphere, talents, kit, cl=cl, dc=dc), foe_at=foe_at, foe_hp=foe_hp)
    if marked:
        _bite(engine)
    events = _use(engine, name, target)
    return engine, events


def _payloads(events, event_type):
    return [getattr(e, "payload", None) or {} for e in events if e.event_type == event_type]


def _foe(engine):
    return engine.state.actors[AN]


def _me(engine):
    return engine.state.actors[ME]


def _conditions(actor):
    return {c.condition_id.removeprefix("condition:") for c in actor.conditions.values()}


def _modifiers(actor):
    return [(m.target_field, m.value) for m in actor.modifiers.values()]


def _resource(actor, suffix):
    return next(value for key, value in actor.resources.items() if key.endswith(suffix))


def _damage_expressions(events):
    return [payload.get("expression") for payload in _payloads(events, "DAMAGE_ROLLED")]


def _axes_cast(talents, name, **kw):
    return _cast(AXES, [HEWING, *talents], name, AXE_KIT, **kw)


# ------------------------------------------------------------------------------------------------------ Athletics


def test_tumbling_recovery_is_a_reaction_to_being_attacked():
    """"Drop Prone at any time, including outside your turn ... When used to avoid an attack: impose Disadvantage on the attack
    roll": a Reaction to being targeted by an attack; it was a Bonus Action that dropped the holder Prone with nobody to impose
    Disadvantage on."""
    key = "TAL_ATHLETICS_TUMBLING_RECOVERY"
    me_bundle = _bundle(ATHLETICS, [key], AXE_KIT)
    assert not [n for n in _rows(me_bundle) if "Tumbling" in n]  # no Bonus Action row
    assert [r["name"] for r in me_bundle["typed_reactions"] if r.get("block") == "generic"] == ["Tumbling Recovery"]

    foe_bundle = compile_character(_sheet(None, [], AXE_KIT), actor_id=FOE)
    engine = Gate4ControllerEngine(ROOT, match_seed="TUMBLE", typed_bundles=(me_bundle, foe_bundle),
                                   roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(FOE)
    engine.state.current_actor_id = FOE
    engine._system_start_turn()
    me = engine.state.actors[ME]
    me.armor_class = -50
    attack = next(c for c in engine.legal_candidates()
                  if c.actor_id == FOE and ME in (c.target_ids or ()) and ".weapon." in c.source_definition_id
                  and (engine.action_catalog[c.source_definition_id].range_ft or 5) <= 5)
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id="foe-attack", decision_id=attack.decision_id, candidate_id=attack.candidate_id,
                                       state_version=attack.state_version, actor_id=FOE, target_ids=attack.target_ids))
    events = engine.events[before:]
    kinds = [e.event_type for e in events]
    assert "REACTION_RESOLVED" in kinds and kinds.index("REACTION_RESOLVED") < kinds.index("ATTACK_ROLLED")
    assert "typed.prone" in _conditions(me) and not me.reaction_available
    imposed = [p for p in _payloads(events, "MODIFIER_APPLIED") if p.get("target_field") == "attack_mode"]
    assert [p["value"] for p in imposed] == ["DISADVANTAGE"] and FOE in imposed[0]["modifier_id"]  # on the attacker
    assert any(p.get("reason") == "CONSUMED" for p in _payloads(events, "MODIFIER_REMOVED"))  # ... spent on that attack roll


def test_one_breath_ten_thousand_steps_grants_two_dashes():
    """"take Dash as part of this Bonus Action ... take Dash again without spending an Action": two Speed-worth movements."""
    key = "TAL_ATHLETICS_ONE_BREATH_TEN_THOUSAND_STEPS"
    engine = _engine(_bundle(ATHLETICS, [key], AXE_KIT))
    me = _me(engine)
    before = me.movement_remaining_ft
    speed = engine._effective_speed(me)
    events = _use(engine, "One Breath, Ten Thousand Steps")
    assert len(_payloads(events, "MOVEMENT_GRANTED")) == 2
    assert me.movement_remaining_ft == before + 2 * speed


def test_polearm_vaulter_expends_martial_focus():
    """"expend Martial Focus as a Bonus Action": it was a free Bonus Action.

    The button's label changed when the Athletics lane typed the printed height increase (it now says which jump
    height the purchase buys, "Polearm Vaulter: jump 5 feet higher"); the action id, the Bonus Action economy and
    the Martial Focus cost are unchanged, so this test still pins the same behaviour under the button a player
    now sees."""
    key = "TAL_ATHLETICS_POLEARM_VAULTER"
    from tests.test_auto_athletics import POLEARM_KIT
    bundle = _bundle(ATHLETICS, [key], POLEARM_KIT)
    assert _costs(bundle, "Polearm Vaulter: jump 5 feet higher") == [["resource:core.martial_focus", 1]]
    assert _rows(bundle)["Polearm Vaulter: jump 5 feet higher"]["economy"] == "BONUS_ACTION"
    engine = _engine(bundle)
    assert _resource(_me(engine), "core.martial_focus") == 1
    _use(engine, "Polearm Vaulter: jump 5 feet higher")
    assert _resource(_me(engine), "core.martial_focus") == 0
    _ready(engine)
    assert "Polearm Vaulter: jump 5 feet higher" not in _legal(engine)  # nothing left to expend


# --------------------------------------------------------------------------------------------------------- Axes


def test_dragon_felling_chop_reduces_speed_by_10_only_on_a_failed_save():
    """"Failed Save: Speed reduced by 10 feet ... Successful Save: reduced by 5 feet": the save had no branches."""
    name = STRIKE + "Drive + Dragon-Felling Chop"
    failed, _ = _axes_cast(["TAL_AXES_DRAGON_FELLING_CHOP"], name, dc=FAIL)
    saved, _ = _axes_cast(["TAL_AXES_DRAGON_FELLING_CHOP"], name, dc=PASS)
    assert failed._effective_speed(_foe(failed)) == 20
    assert saved._effective_speed(_foe(saved)) == 25


def test_hook_the_giants_knee_halves_one_movement_mode_on_a_failed_save():
    """"Failed Save: that movement mode is reduced by half ... Successful Save: reduced by 10 feet": it was Prone plus 10 feet."""
    name = STRIKE + "Drive + Hook the Giant's Knee"

    def hooked(dc, *, larger=True):
        # "When you hit a creature larger than you" (rider lane 3, 2026-09-29): the foe is made a Large creature (2 cells wide)
        engine = _engine(_bundle(AXES, [HEWING, "TAL_AXES_HOOK_THE_GIANT_S_KNEE"], AXE_KIT, dc=dc))
        if larger:
            engine.actor_footprints[AN] = engine._footprint(AN).model_copy(update={"width_cells": 2, "height_cells": 2, "occupied_relative_cells": (
                Position(x=0, y=0), Position(x=1, y=0), Position(x=0, y=1), Position(x=1, y=1))})
        _use(engine, name)
        return engine

    failed, saved = hooked(FAIL), hooked(PASS)
    assert failed._effective_speed(_foe(failed)) == 15 and "typed.prone" not in _conditions(_foe(failed))
    assert saved._effective_speed(_foe(saved)) == 20
    same_size = hooked(FAIL, larger=False)  # a creature no larger than you is not hooked
    assert same_size._effective_speed(_foe(same_size)) == 30


def test_low_chop_lengthens_only_hamper():
    """"when you choose Hamper, the Speed reduction becomes 10 feet instead of 5 feet": Hamper's 5 feet plus 5 more, no Prone,
    and nothing on the other options."""
    hamper, _ = _axes_cast(["TAL_AXES_LOW_CHOP"], STRIKE + "Hamper", dc=FAIL)
    assert hamper._effective_speed(_foe(hamper)) == 20 and "typed.prone" not in _conditions(_foe(hamper))
    drive, _ = _axes_cast(["TAL_AXES_LOW_CHOP"], STRIKE + "Drive", dc=FAIL)
    assert drive._effective_speed(_foe(drive)) == 30


def test_bearded_hook_method_is_not_a_modifier_on_every_hewing_strike():
    """It offered a "+ Bearded Hook Method" copy of every Hewing Strike option that pushed the target 5 feet (the text moves it
    to another space within reach) and gave it Disadvantage on opportunity attacks.  "When Hewing Strike hits and you choose
    Bite" (rider lane 3, 2026-09-29): the one copy is on the Bite option, and it repositions the target instead of pushing."""
    bundle = _bundle(AXES, [HEWING, "TAL_AXES_BEARDED_HOOK_METHOD"], AXE_KIT)
    assert STRIKE + "Bite" in _rows(bundle)
    # The legacy/AI variant remains, and player controls exist only on Bite.
    actions = bundle['action_catalog']
    assert [a['display_name'] for a in actions if 'Bearded Hook' in a['display_name']
            and not a['parameters'].get('setting_only')] == [STRIKE + 'Bite + Bearded Hook Method']
    controls = [a['parameters']['attack_modifier_setting'] for a in actions
                if a['parameters'].get('attack_modifier_setting')
                and a['parameters']['attack_modifier_setting']['modifier'] == 'TAL_AXES_BEARDED_HOOK_METHOD']
    bite = next(a['source_definition_id'] for a in actions if a['display_name'] == STRIKE + 'Bite')
    assert controls and {row['family'] for row in controls} == {bite}


def test_headsmans_mandate_costs_and_denies_recovery_on_a_failed_save():
    """"Cost: 3 CP, 3 Stamina, or expend Martial Focus and 2 CP/Stamina"; the Constitution-or-Wisdom save denies HP, Temporary
    HP and Invisibility on a Failed Save (HP alone on a Successful Save); it frightened every enemy within 30 feet."""
    key, name = "TAL_AXES_HEADSMAN_S_MANDATE", "Fu (Short Axe) attack: Headsman's Mandate"
    assert _costs(_bundle(AXES, [key], AXE_KIT), name) == [["resource:core.stamina", 3]]
    failed, _ = _cast(AXES, [key], name, AXE_KIT, dc=FAIL)
    assert {"typed.no_temp_hp", "typed.no_invisible"} <= _conditions(_foe(failed)) and "typed.frightened" not in _conditions(_foe(failed))
    assert ("healing_reduction", "none") in _modifiers(_foe(failed))
    assert _resource(_me(failed), "core.stamina") == 57
    saved, _ = _cast(AXES, [key], name, AXE_KIT, dc=PASS)
    assert ("healing_reduction", "none") in _modifiers(_foe(saved))
    assert not _conditions(_foe(saved))


def test_headsmans_red_line_imposes_disadvantage_only_on_a_successful_save():
    """"Successful Save: it has Disadvantage on the next attack roll it makes against that ally": a Failed Save cannot move
    closer instead; the save had no branches so the Disadvantage came either way."""
    name = STRIKE + "Drive + Headsman's Red Line"
    from tests import test_riders_lane3 as lane
    failed, ally = lane._with_ally(["TAL_AXES_HEADSMAN_S_RED_LINE"], dc=FAIL)
    saved, _ = lane._with_ally(["TAL_AXES_HEADSMAN_S_RED_LINE"], dc=PASS)
    _use(failed, name, target=lane.H.FOE)
    _use(saved, name, target=lane.H.FOE)
    failed_foe, saved_foe = (engine.state.actors[lane.H.FOE] for engine in (failed, saved))
    assert ("attack_mode", "DISADVANTAGE") not in _modifiers(failed_foe)
    # Printed "one ally of your choice" requires an actual ally; the caster
    # cannot substitute itself when none exists. Keep both save-branch checks.
    assert ("attack_mode_vs", f"DISADVANTAGE:{ally}") not in _modifiers(failed_foe)
    assert ("attack_mode_vs", f"DISADVANTAGE:{ally}") in _modifiers(saved_foe)
    assert ("attack_mode_vs", f"DISADVANTAGE:{ME}") not in _modifiers(saved_foe)


def test_sever_the_standard_costs_and_denies_reactions_only_on_a_failed_save():
    """"Cost: 2 CP, 2 Stamina, or expend Martial Focus and 1 CP/Stamina"; "Failed Save: Until the start of your next turn, it
    cannot ... activate command reactions"."""
    key = "TAL_AXES_SEVER_THE_STANDARD"
    assert _costs(_bundle(AXES, [key], AXE_KIT), "Sever the Standard") == [["resource:core.stamina", 2]]
    failed, _ = _cast(AXES, [key], "Sever the Standard", AXE_KIT, dc=FAIL)
    saved, _ = _cast(AXES, [key], "Sever the Standard", AXE_KIT, dc=PASS)
    assert "typed.reaction_denied" in _conditions(_foe(failed)) and _resource(_me(failed), "core.stamina") == 58
    assert "typed.reaction_denied" not in _conditions(_foe(saved))


def test_split_the_shield_wall_costs_two_stamina():
    """"Cost: 2 CP, 2 Stamina, or expend Martial Focus and 1 CP/Stamina" was free text (a free action)."""
    key = "TAL_AXES_SPLIT_THE_SHIELD_WALL"
    assert _costs(_bundle(AXES, [key], AXE_KIT), "Split the Shield Wall") == [["resource:core.stamina", 2]]
    engine, _ = _cast(AXES, [key], "Split the Shield Wall", AXE_KIT)
    assert _resource(_me(engine), "core.stamina") == 58


def test_moon_cleaver_return_marks_a_hit_target_with_bite():
    """"One hit target of your choice also gains Bite from you until the start of your next turn." """
    engine, _ = _cast(AXES, ["TAL_AXES_MOON_CLEAVER_RETURN"], "Moon-Cleaver Return", AXE_KIT)
    assert bears_mark(_foe(engine), ME, "Bite")


def test_rending_hew_scales_with_level_consumes_bite_and_needs_bite():
    """"2d6 + your Proficiency Bonus (3d6 at CL 11, 4d6 at CL 17)"; "you may consume the Bite"; Failed Save: the target
    cannot regain HP; it applies to a target already bearing your Bite."""
    name = STRIKE + "Drive + Rending Hew"
    talents = ["TAL_AXES_RENDING_HEW"]
    failed, events = _axes_cast(talents, name, dc=FAIL, cl=12, marked=True)
    assert "3d6+4" in _damage_expressions(events)
    assert not bears_mark(_foe(failed), ME, "Bite") and ("healing_reduction", "none") in _modifiers(_foe(failed))
    saved, _ = _axes_cast(talents, name, dc=PASS, cl=12, marked=True)
    assert not bears_mark(_foe(saved), ME, "Bite") and ("healing_reduction", "none") not in _modifiers(_foe(saved))
    _, events = _axes_cast(talents, name, dc=PASS, cl=10, marked=True)
    assert "2d6+4" in _damage_expressions(events)
    unmarked = _engine(_bundle(AXES, [HEWING, *talents], AXE_KIT))
    assert name not in _legal(unmarked)  # nothing to consume
    _bite(unmarked)
    assert name in _legal(unmarked)


def test_close_haft_strike_scales_and_needs_a_creature_with_bite():
    """"When a creature within your reach has Bite from you"; "At CL 5, the damage becomes 1d6. At CL 11, it becomes 1d8"."""
    name = "Close Haft Strike: Push (loses Bite)"
    talents = ["TAL_AXES_CLOSE_HAFT_STRIKE"]
    unmarked = _engine(_bundle(AXES, talents, AXE_KIT, cl=12))
    assert name not in _legal(unmarked)
    for cl, dice in ((3, "1d4+3"), (10, "1d6+3"), (12, "1d8+3")):
        _, events = _cast(AXES, talents, name, AXE_KIT, cl=cl, marked=True)
        assert dice in _damage_expressions(events), (cl, _damage_expressions(events))


def test_law_of_the_falling_tree_is_not_a_modifier_on_every_hewing_strike():
    """Its trigger (knock a creature Prone, reduce one to 0 HP, ...) acts on a *different* creature within 10 feet; it made every
    Hewing Strike option offer a "+ Law of the Falling Tree" copy that knocked the same target Prone."""
    bundle = _bundle(AXES, [HEWING, "TAL_AXES_LAW_OF_THE_FALLING_TREE"], AXE_KIT)
    assert STRIKE + "Bite" in _rows(bundle)
    assert not [n for n in _rows(bundle) if "Falling Tree" in n]


def test_work_axe_eye_adds_nothing_against_a_creature():
    """"+Proficiency Bonus when you deal damage to an unattended wooden object with an axe": it added PB to every attack."""
    engine, events = _axes_cast(["TAL_AXES_WORK_AXE_EYE"], STRIKE + "Drive")
    rolled = sum(p["total"] for p in _payloads(events, "DAMAGE_ROLLED"))
    assert 55 - _foe(engine).current_hp == rolled


def test_gate_splitting_blow_is_not_a_modifier_on_every_hewing_strike():
    """"+2d8 when you attack an unattended object, door, barricade ... or comparable structure" was +2d8 on every attack."""
    bundle = _bundle(AXES, [HEWING, "TAL_AXES_GATE_SPLITTING_BLOW"], AXE_KIT)
    assert STRIKE + "Bite" in _rows(bundle)
    # The only Gate-Splitting rows are the object attacks ("Attack an object + Gate-Splitting Blow (...)", combat/ext/objects.py);
    # none of the Hewing Strike options gets a "+ Gate-Splitting Blow" copy.
    assert not [n for n in _rows(bundle) if "Gate-Splitting" in n and not n.startswith("Attack an object")]
    engine, events = _axes_cast(["TAL_AXES_GATE_SPLITTING_BLOW"], STRIKE + "Drive")
    assert all(not expr.startswith("2d8") for expr in _damage_expressions(events))


def test_forest_of_falling_standards_denies_no_reactions_on_its_own():
    """Reactions are denied only on "Success by 5 or more against at least three objects"; the activation alone denied every
    target's Reactions."""
    engine, _ = _cast(AXES, ["TAL_AXES_FOREST_OF_FALLING_STANDARDS"], "Forest of Falling Standards", AXE_KIT)
    assert "typed.reaction_denied" not in _conditions(_foe(engine))


def test_lodged_axe_pull_pulls_a_far_target_that_bears_bite():
    """"Failed Save: If the target is no more than one size larger than you, pull it 10 feet toward you" -- it pushed 10 feet away
    from a target within 5 feet, whether or not the target bore Bite."""
    name, talents = "Lodged Axe Pull", ["TAL_AXES_LODGED_AXE_PULL"]
    failed, _ = _cast(AXES, talents, name, AXE_KIT, dc=FAIL, foe_at=(8, 6), marked=True)
    assert (_foe(failed).position.x, _foe(failed).position.y) == (6, 6)  # 8 -> 6: toward the caster at 3,6
    saved, _ = _cast(AXES, talents, name, AXE_KIT, dc=PASS, foe_at=(8, 6), marked=True)
    assert _foe(saved).position.x == 8
    unmarked = _engine(_bundle(AXES, talents, AXE_KIT, dc=FAIL), foe_at=(4, 6))
    assert name not in _legal(unmarked)


def test_root_hewing_passage_costs_two_stamina():
    """"spend 2 CP, 2 Stamina, or expend Martial Focus" was a free action."""
    key = "TAL_AXES_ROOT_HEWING_PASSAGE"
    bundle = _bundle(AXES, [key], AXE_KIT)
    assert _costs(bundle, "Root-Hewing Passage: Dense Roots") == [["resource:core.stamina", 2]]
    engine, _ = _cast(AXES, [key], "Root-Hewing Passage: Dense Roots", AXE_KIT, target=None)
    assert _resource(_me(engine), "core.stamina") == 58


# ------------------------------------------------------------------------------------------------------- Barrage


def _volley(key, name, *, dc=FAIL, target=None):
    # Damage tests must pay the printed whole-volley cost; keep the shared bow fixture unchanged.
    kit = {"starting_kit": {"items": [*BOW_KIT["starting_kit"]["items"],
                                   {"item_id": "tianxia.mortal.gear.arrows_20", "name": "Arrows (20)", "quantity": 2}]}}
    return _cast(BARRAGE, [key], name, kit, dc=dc, foe_hp=400, target=target)


def _dice(events, pattern):
    return [e for e in _damage_expressions(events) if re.fullmatch(pattern, e or "")]


def test_heaven_splitting_line_rolls_ten_weapon_dice_plus_twice_the_modifier():
    """"Take damage equal to ten weapon damage dice plus twice your ability modifier": the authority carried no dice."""
    engine, events = _volley("TAL_BARRAGE_HEAVEN_SPLITTING_LINE", "Heaven-Splitting Line at 10,6")
    assert _dice(events, r"10d\d+\+6")
    assert 400 - _foe(engine).current_hp >= 10 + 6


def test_hundred_arrow_passage_rolls_four_weapon_dice_plus_the_modifier():
    """"Take damage equal to four weapon damage dice plus your ability modifier"."""
    engine, events = _volley("TAL_BARRAGE_HUNDRED_ARROW_PASSAGE", "Hundred-Arrow Passage at 10,6")
    assert _dice(events, r"4d\d+\+3")
    assert 400 - _foe(engine).current_hp >= 4 + 3


def test_needle_rain_burst_is_a_two_dice_burst_at_the_weapons_range():
    """"Take damage equal to two weapon damage dice plus your ability modifier": a burst placed out to the weapon's range
    (it was a 5-foot row), with the weapon's dice."""
    engine, events = _volley("TAL_BARRAGE_NEEDLE_RAIN_BURST", "Needle-Rain Burst at 4,6")
    assert _dice(events, r"2d\d+\+3")
    assert 400 - _foe(engine).current_hp >= 2 + 3


def test_ten_thousand_projectile_rain_rolls_eight_dice_and_pins_only_on_a_failed_save():
    """"Take damage equal to eight weapon damage dice plus your ability modifier ... Failed Save: become Pinned until the start
    of your next turn" (Speed 0, no Reactions); the damage had no dice and half of it went through on a save."""
    name = "Ten-Thousand Projectile Rain at 4,6"
    key = "TAL_BARRAGE_TEN_THOUSAND_PROJECTILE_RAIN"
    failed, events = _volley(key, name, dc=FAIL)
    assert _dice(events, r"8d\d+\+3")
    assert failed._effective_speed(_foe(failed)) == 0 and "typed.reaction_denied" in _conditions(_foe(failed))
    saved, events = _volley(key, name, dc=PASS)
    assert _dice(events, r"8d\d+\+3")
    assert saved._effective_speed(_foe(saved)) == 30 and "typed.reaction_denied" not in _conditions(_foe(saved))
    assert 400 - _foe(saved).current_hp >= (8 + 3) // 2  # half of the least the dice can roll


def test_one_arrow_becomes_ten_thousand_rolls_twelve_dice_once_per_long_rest():
    """"12 weapon damage dice + twice your ability modifier", once per week (a fight has no reset)."""
    key, name = "tianxia.talent.barrage.one_arrow_becomes_ten_thousand", "One Arrow Becomes Ten Thousand"
    engine, events = _volley(key, name, target=AN)
    assert _dice(events, r"12d\d+\+6")
    assert 400 - _foe(engine).current_hp >= 12 + 6
    _ready(engine)
    _me(engine).resources[next(k for k in _me(engine).resources if k.endswith("core.martial_focus"))] = 1
    assert name not in _legal(engine)  # the use is spent, whatever Martial Focus is left


def test_court_of_falling_stars_gives_the_caster_nothing_at_once():
    """The ally Advantage is the *allies'*, on an attack against a creature hit twice, and Martial Focus returns only once at
    least two Barrage attacks hit; the caster was handed Advantage and the Martial Focus back on activation."""
    engine, _ = _volley("TAL_BARRAGE_COURT_OF_FALLING_STARS", "Court of Falling Stars")
    assert _resource(_me(engine), "core.martial_focus") == 0
    assert ("attack_mode", "ADVANTAGE") not in _modifiers(_me(engine))


@pytest.mark.parametrize("talent, label", [
    ("TAL_BARRAGE_MOBILE_BARRAGE", "Mobile Barrage"),   # 10 feet inside the turn's movement, not 10 more on every Barrage
])
def test_barrage_modifiers_are_not_offered_as_extra_attack_rows(talent, label):
    bundle = _bundle(BARRAGE, [talent], BOW_KIT)
    assert "Barrage: Gong Jian (Bow and Arrow)" in _rows(bundle)
    assert not [n for n in _rows(bundle) if label in n]


def test_cascading_barrage_is_not_legal_before_a_kill_or_critical_hit():
    # Task B gives Cascading Barrage a no-Action target choice after its trigger;
    # its compiled button exists but is hidden from the legal menu before then.
    bundle = _bundle(BARRAGE, ["TAL_BARRAGE_CASCADING_BARRAGE"], BOW_KIT)
    assert "Cascading Barrage: Gong Jian (Bow and Arrow)" in _rows(bundle)
    assert "Cascading Barrage: Gong Jian (Bow and Arrow)" not in _legal(_engine(bundle))


def test_blowback_barrage_does_not_push_on_the_first_hit():
    """"When the same creature is hit at least twice during one Barrage, it makes a Strength saving throw. Failed Save: push it
    5 feet": the modifier pushed the target on any single hit."""
    engine, _ = _cast(BARRAGE, ["TAL_BARRAGE_BLOWBACK_BARRAGE"], "Barrage: Gong Jian (Bow and Arrow)", BOW_KIT, dc=FAIL, foe_hp=400)
    assert (_foe(engine).position.x, _foe(engine).position.y) == (4, 6)


# ----------------------------------------------------------------------------------------------- the authority


def test_the_review_overrides_are_bound_to_the_current_text():
    """A rules-text edit un-binds an override (text_sha256): it would silently fall back to the parser's typing."""
    review = json.loads((ROOT / "authority/typed_mechanics/reviewed_final.d/review_sw-athletics.json").read_text(encoding="utf-8"))
    mechanics = _mechanics()
    # Three hit-count talents, three projectile talents and Polearm Vaulter now live in their dedicated overrides.
    assert len(review["mechanics"]) == 20
    for key in review["mechanics"]:
        assert mechanics[key]["typing_status"] == "reviewed_final", key
