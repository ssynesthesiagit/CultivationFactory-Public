"""Axes' Bite mark, Spear's weapon-delivery fix, and the Dual Wielding Paired-Strike hooks (worker martial,
2026-09-28, "automate every aspect before another playtest"). combat/ext/martial_axes.py,
combat/ext/martial_spear.py, combat/ext/martial_dual_wielding.py, authority/typed_mechanics/reviewed_final.d/
martial.json."""

from pathlib import Path

from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from combat.typed_executor import bears_mark, mark_condition_id

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.martial_test"
AXE_KIT = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.fu", "name": "Fu (Short Axe)", "quantity": 1}]}}
SPEAR_KIT = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.qiang", "name": "Qiang (Spear)", "quantity": 1}]}}
DAGGER_PAIR_KIT = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.bi_shou", "name": "Bi Shou (Dagger)", "quantity": 2}]}}

BASE_SHEET = {
    "identity": {"proficiency_bonus": 4, "cultivation_level": 10, "path": "Body Refining", "key_ability": "STR"},
    "ability_scores_and_statistics": {
        "abilities": [{"ability": a, "score": 16, "modifier": 3} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
        "primary_resource": {"name": "Stamina", "maximum": 30}, "armor_class": {"base_value": 14}, "hit_points": {"maximum": 60},
        "speed": {"walking_ft": 30}, "technique_save_dc": 16, "technique_attack_bonus": 8,
    },
}


def _bundle(sphere, talents, kit, extra_spheres=()):
    sheet = {**BASE_SHEET, "equipment": [kit],
             "spheres_and_talents": {"sphere_record_ids": [sphere, *extra_spheres], "learned_talent_record_ids": talents}}
    return compile_character(sheet, actor_id=ME)


def _engine(bundle, foe_at=(4, 6)):
    engine = Gate4ControllerEngine(ROOT, match_seed="MARTIAL", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": foe_at[0], "y": foe_at[1]}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine


def _use(engine, name, *, target=None):
    candidate = next(c for c in engine.legal_candidates() if c.display_name == name)
    engine.execute_intent(ActionIntent(intent_id=f"i{name}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME,
                                       target_ids=candidate.target_ids or ((target,) if target else ())))
    return candidate


def _ready(engine):
    me = engine.state.actors[ME]
    engine.state.current_actor_id = ME
    me.action_available, me.bonus_action_available = True, True


# ------------------------------------------------------------------------------------------------- Axes / Bite


BITE = "Fu (Short Axe) attack: Hewing Strike: Bite"
SPLIT_GUARD = "Fu (Short Axe) attack: Hewing Strike: Split Guard"
HAMPER = "Fu (Short Axe) attack: Hewing Strike: Hamper"


def test_hewing_strike_bite_option_marks_the_target():
    bundle = _bundle("tianxia.sphere.axes", ["TAL_AXES_HEWING_STRIKE"], AXE_KIT)
    names = {row["display_name"] for row in bundle["action_catalog"]}
    assert BITE in names and SPLIT_GUARD in names  # both missing options now present
    engine = _engine(bundle)
    foe = engine.state.actors[AN]
    for _attempt in range(10):
        _ready(engine)
        _use(engine, BITE)
        if bears_mark(foe, ME, "Bite"):
            break
    assert bears_mark(foe, ME, "Bite")


def test_hewing_strike_bite_deals_the_axe_s_own_damage():
    bundle = _bundle("tianxia.sphere.axes", ["TAL_AXES_HEWING_STRIKE"], AXE_KIT)
    row = next(row for row in bundle["action_catalog"] if row["display_name"] == BITE)
    on_hit = row["parameters"]["typed"]["effects"][0]["on_hit"]
    damage = next(e for e in on_hit if e["type"] == "damage" and e.get("weapon_damage"))
    assert damage["weapon_damage"] is True  # the axe's real dice, not a bare rider


def test_deep_bite_extends_the_bite_mark_past_the_default_expiry():
    bundle = _bundle("tianxia.sphere.axes", ["TAL_AXES_HEWING_STRIKE", "TAL_AXES_DEEP_BITE"], AXE_KIT)
    engine = _engine(bundle)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    variant = f"{BITE} + Deep Bite"
    assert any(row["display_name"] == variant for row in bundle["action_catalog"])
    for _attempt in range(10):
        _ready(engine)
        me.resources["resource:core.stamina"] = 5
        me.resources["resource:core.martial_focus"] = 1  # Deep Bite spends it; refresh so every attempt can afford the variant
        _use(engine, variant)
        if bears_mark(foe, ME, "Bite"):
            break
    assert bears_mark(foe, ME, "Bite")
    condition = next(c for c in foe.conditions.values() if c.condition_id == mark_condition_id("Bite", ME))
    from combat.ext import effect_durations

    # extended past the plain option's until_start_of_next_turn: "1 minute" is ten rounds on the round clock
    assert effect_durations.parse_round(condition.expires_on) == (engine.state.round_number + 10, engine.state.current_slot_index)


def test_close_haft_strike_does_not_double_the_axe_s_weapon_damage():
    """The talent's own flat 1d4+mod bludgeoning replaces normal weapon damage; the shared _deliver_with_weapons
    fix must drop the axe's own weapon_damage hit rather than stacking both (the free-power bug this fixed)."""
    bundle = _bundle("tianxia.sphere.axes", ["TAL_AXES_HEWING_STRIKE", "TAL_AXES_CLOSE_HAFT_STRIKE"], AXE_KIT)
    row = next(row for row in bundle["action_catalog"] if row["display_name"] == "Close Haft Strike: Push (loses Bite)")
    on_hit = row["parameters"]["typed"]["effects"][0]["on_hit"]
    damage_hits = [e for e in on_hit if e["type"] == "damage"]
    assert len(damage_hits) == 1  # not the axe's weapon_damage hit AND the talent's own 1d4 both landing
    assert damage_hits[0].get("dice", {}).get("sides") == 4 and not damage_hits[0].get("weapon_damage")


def test_headsmans_calm_regains_martial_focus_on_an_axe_kill():
    from combat.factory_compiler import RESOURCE_IDS

    bundle = _bundle("tianxia.sphere.axes", ["TAL_AXES_HEWING_STRIKE", "TAL_AXES_HEADSMAN_S_CALM"], AXE_KIT)
    assert any(row["block"] == "axes_headsmans_calm" for row in bundle["typed_passives"])
    engine = _engine(bundle)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    focus = RESOURCE_IDS["martial_focus"]
    me.resources[focus] = 0
    foe.current_hp = 1
    killed = False
    for _attempt in range(10):
        _ready(engine)
        _use(engine, HAMPER)
        if not foe.active:
            killed = True
            break
    assert killed
    assert me.resources[focus] == 1  # regained on the kill


# ------------------------------------------------------------------------------------------------ Spear weapon delivery


def test_spear_thrust_deals_the_qiang_s_own_damage_not_nothing():
    """Spear Thrust, Dragon-Spear Charge, Flowers in the Storm and Intercepting Thrust all read 'make an attack
    with an approved Spear weapon', which never matched the compiler's weapon-delivery auto-detect (economy
    action/bonus_action/reaction all excluded reactions, and the phrasing itself didn't match either); before the
    attach_spear_weapon fix, every option here dealt zero weapon damage."""
    bundle = _bundle("tianxia.sphere.spear", ["SPEAR_BASE_SPEAR_THRUST"], SPEAR_KIT)
    row = next(row for row in bundle["action_catalog"] if row["display_name"] == "Spear Thrust: Push Target")
    effects = row["parameters"]["typed"]["effects"]
    assert effects[0]["type"] == "attach_spear_weapon"  # runs before the attack resolves ctx.typed["weapon"]
    on_hit = effects[1]["on_hit"]
    damage = next(e for e in on_hit if e["type"] == "damage")
    assert damage.get("weapon_damage") is True


def test_spear_thrust_apply_spear_intent_option_marks_the_target():
    bundle = _bundle("tianxia.sphere.spear", ["SPEAR_BASE_SPEAR_THRUST"], SPEAR_KIT)
    engine = _engine(bundle)
    foe = engine.state.actors[AN]
    for _attempt in range(10):
        _ready(engine)
        _use(engine, "Spear Thrust: Apply Spear Intent")
        if bears_mark(foe, ME, "Spear Intent"):
            break
    assert bears_mark(foe, ME, "Spear Intent")


def test_intercepting_thrust_now_costs_a_resource():
    """'1 Spear Resource' never resolved to a real cost (the whole reaction was free); confirms it now spends
    the character's own primary pool."""
    bundle = _bundle("tianxia.sphere.spear", ["TAL_SPEAR_INTERCEPTING_THRUST"], SPEAR_KIT)
    reaction = next(r for r in bundle["typed_reactions"] if r.get("name") == "Intercepting Thrust")
    assert reaction["costs"] == [{"resource_id": "resource:core.stamina", "amount": 1}]  # it used to be []


# ------------------------------------------------------------------------------------------- Dual Wielding / Paired Strike


def test_dancing_display_and_dizzying_combination_register_their_marker_blocks():
    """A live two-weapon Qualifying Pair fight needs a specific dual-wield loadout this test file does not set
    up; confirms instead that owning the talent produces the compile_block marker
    combat/ext/martial_dual_wielding.py's attack_resolved hook keys off (exercised end-to-end via char_fight.py
    against the live roster during this work, not reproduced here)."""
    bundle = _bundle("tianxia.sphere.dual_wielding", ["TAL_DUAL_WIELDING_DANCING_DISPLAY"], DAGGER_PAIR_KIT)
    assert any(row["block"] == "dw_dancing_display" for row in bundle["typed_passives"])
    bundle2 = _bundle("tianxia.sphere.dual_wielding", ["TAL_DUAL_WIELDING_DIZZYING_COMBINATION"], DAGGER_PAIR_KIT)
    assert any(row["block"] == "dw_dizzying_combination" for row in bundle2["typed_passives"])
