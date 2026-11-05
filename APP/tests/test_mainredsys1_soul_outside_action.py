"""CHARACTERIZATION (no code change in this branch): General's Soul-Standard for a drop with no action behind it.

A zone trigger or hazard takes a Warleader to 0 Hit Points with no active intent, so no question can be put. A player in
Ask-me mode is not asked there (typed_reactions._consent returns False on its no-intent branch), so the Soul-Standard is
not set and the Martial Focus is not charged; the leader falls Unconscious, and its Momentum Marks end then by the printed
"until you are Incapacitated" rule. An AI-controlled leader takes its printed survival. These pass on main as well; they
pin that current behaviour so a later change to the no-intent consent path is noticed. Synthetic fixtures only (public CI).
"""
from combat.factory_compiler import compile_character
from tests.test_auto_lane1 import ME, FOE, _engine, _held, _payloads, _sheet, _ready

UNCONSCIOUS = "condition:typed.life_unconscious"

WL = "tianxia.talent.warleader."
SOUL = "condition:typed.warleader_soul_standard"
MOMENTUM = "resource:named.momentum_mark"
FOCUS = "resource:core.martial_focus"


def _leader_engine(marks=3):
    sheet = _sheet("WARLEADER_BASE_SET_THE_STANDARD", cl=10)
    sheet["spheres_and_talents"]["learned_talent_record_ids"] = [WL + "general_s_soul_standard"]
    sheet["equipment"] = [{"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.dao", "name": "Dao", "quantity": 1}]}}]
    engine = _engine(compile_character(sheet, actor_id=ME))
    me = engine.state.actors[ME]
    me.current_hp = me.maximum_hp = 6
    me.resources[FOCUS] = 1
    engine._gain_resource(me, MOMENTUM, marks, "test")
    engine.state.rules["zero_hp"] = "dying_2024"
    return engine


def _hit(engine, amount=6):
    me = engine.state.actors[ME]
    engine._commit_damage(me, amount, "FORCE", "action:test.foe_hit", FOE, None, reaction_depth=0)
    return me


def _plug_in_failures(engine):
    return [p["rider"] for p in _payloads(engine.events, "GM_RIDER") if "failed:" in str(p.get("rider"))]


def test_a_player_leader_dropped_outside_an_action_is_not_kept_up_or_charged_unasked():
    engine = _leader_engine(marks=3)
    engine.typed_control_modes = {ME: "MANUAL"}
    engine.typed_ask_reactors = {ME}  # a player controls the leader in this fight
    assert getattr(engine, "_active_intent", None) is None  # no action behind the drop
    me = _hit(engine)
    assert me.current_hp == 0 and me.life_state != "CONSCIOUS"
    assert me.resources[FOCUS] == 1  # the Focus is not charged unasked
    assert not _held(me, SOUL)  # the Standard is not set without a question
    assert _held(me, UNCONSCIOUS)  # the leader falls Unconscious at 0 Hit Points
    assert me.resources[MOMENTUM] == 0  # Incapacitated: "Momentum Marks last ... until you are Incapacitated"
    assert not _plug_in_failures(engine)


def test_an_ai_leader_dropped_outside_an_action_takes_its_printed_survival():
    engine = _leader_engine(marks=3)
    assert getattr(engine, "_active_intent", None) is None
    me = _hit(engine)
    assert me.current_hp == 0 and me.active and me.life_state == "CONSCIOUS"
    assert me.resources[FOCUS] == 0 and me.resources[MOMENTUM] == 0 and len(_held(me, SOUL)) == 1
    assert not _plug_in_failures(engine)
