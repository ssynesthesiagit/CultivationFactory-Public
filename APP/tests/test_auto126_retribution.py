"""Liver Shot's printed Speed and its printed duration, at the table (AUTO126).

"After your Counterstrike hits, reduce all of the target's Speeds to 5 feet until
the end of its next turn."  Two things are checked at table level: the 5 feet is a
SET (the old flat:5 typing was added to the target's Speed, so it sped the victim
up instead of rooting it), and it lasts until the END OF THE TARGET'S NEXT TURN
(the old typing fell back to the ability's own duration and silently ended at the
START OF MY NEXT TURN, one whole round early).  Tight Guard's printed AC bonus and
its printed "until the start of your next turn" are pinned the same way, and
Haymaker's printed anatomy immunity is checked against what a creature record
actually says (AUTO126r1f1).
"""
import json

from combat.creature_types import from_record
from combat.physiology import trait
from tests.auto_worker1_support import LEFT, RIGHT, fight, act, reload
from tests.h1_support import ROOT
from tests.hunt15_support import turn

BASE = "RETRIBUTION_BASE_COUNTERSTRIKE"
LIVER = "TAL_RETRIBUTION_LIVER_SHOT"
REFLEXIVE = "TAL_RETRIBUTION_REFLEXIVE_PREPARATION"
SOURCE_FILE = "review_sw-qiweaving.json"
DAO = {"items": [{"item_id": "tianxia.mortal.weapon.dao", "name": "Dao", "quantity": 1}]}


def settle(send, select=None):
    answers, prompts = [], []
    for _ in range(24):
        result = send(answers)
        if result["status"] != "REACTION_REQUIRED":
            assert result["status"] == "COMMITTED", result
            return result, prompts
        p = result["reaction"]
        prompts.append(p)
        ids = [o["id"] for o in (p.get("choice") or {}).get("options", [])]
        if p["context"]["reaction_source_id"] == "choice:needle.counterstrike":
            chosen = [next(o["id"] for o in p["choice"]["options"]
                           if o["label"].startswith(select) and "Dao" in o["label"]
                           and "a foe starts an action that targets you" in o["label"])]
        else:
            chosen = ids[:1]
        answers.append({**p["context"], "selection": "USE" if chosen or not p.get("choice") else "DECLINE",
                        "option_ids": chosen})
    raise AssertionError("too many choices")


def _seal(bundle):
    for action in bundle["action_catalog"]:
        typed = action.get("parameters", {}).get("typed", {})
        if action["display_name"] == "Cause":
            action["economy"] = "ACTION"
        if typed.get("weapon"):
            typed.setdefault("numbers", {})["attack_bonus"] = 100


def fight_liver_shot(tmp_path):
    combat, table, mid = fight(
        tmp_path, [BASE, LIVER, REFLEXIVE], left_kit=DAO,
        cause=[{"type": "damage", "flat": 9, "damage_types": ["slashing"], "applies_to": "target"}],
        bundle_edit=_seal)
    settle(lambda a: act(table, mid, "Reflexive Preparation", a), "Counterstrike + Liver Shot")
    turn(table, mid, RIGHT)
    settle(lambda a: act(table, mid, "Cause", a))
    return combat, table, mid


def test_liver_shot_sets_the_targets_speeds_to_five_and_keeps_them_until_the_end_of_its_next_turn(tmp_path):
    combat, table, mid = fight_liver_shot(tmp_path)
    engine = reload(combat, mid)
    foe = engine.state.actors[RIGHT]

    # The printed 5 feet is a set, not a bonus: a flat 5 would leave the foe at 35.
    assert engine._effective_speed(foe) == 5, engine._effective_speed(foe)
    assert any(m.target_field == "speed_ft" and m.operation == "ADD" and int(m.value) < 0
               for m in foe.modifiers.values()), dict(foe.modifiers)

    # It must still be in force at the start of my next turn (the old duration ended it there).
    turn(table, mid, LEFT)
    engine = reload(combat, mid)
    assert engine._effective_speed(engine.state.actors[RIGHT]) == 5

    # It lasts through the target's own next turn ...
    turn(table, mid, RIGHT)
    engine = reload(combat, mid)
    assert engine._effective_speed(engine.state.actors[RIGHT]) == 5

    # ... and lifts only at the end of it.
    turn(table, mid, LEFT)
    engine = reload(combat, mid)
    assert engine._effective_speed(engine.state.actors[RIGHT]) == 30
    assert not [m for m in engine.state.actors[RIGHT].modifiers.values() if m.target_field == "speed_ft"]


def test_liver_shot_does_not_touch_the_shooter(tmp_path):
    combat, table, mid = fight_liver_shot(tmp_path)
    engine = reload(combat, mid)
    assert engine._effective_speed(engine.state.actors[LEFT]) == 30


GUARD = "TAL_RETRIBUTION_TIGHT_GUARD"


def _ac(combat, table, mid, who):
    return reload(combat, mid)._ac_modifier(reload(combat, mid).state.actors[who])


def test_tight_guard_raises_ac_while_preparing_a_counterstrike_and_lifts_next_turn(tmp_path):
    """At CL 15 the printed bonus is +2, from the start of the preparation to the start of my next turn."""
    combat, table, mid = fight(
        tmp_path, [BASE, GUARD, REFLEXIVE], left_kit=DAO, cl=15,
        cause=[{"type": "damage", "flat": 9, "damage_types": ["slashing"], "applies_to": "target"}],
        bundle_edit=_seal)
    engine = reload(combat, mid)
    before = engine._ac_modifier(engine.state.actors[LEFT])

    settle(lambda a: act(table, mid, "Reflexive Preparation", a), "Counterstrike")
    engine = reload(combat, mid)
    me = engine.state.actors[LEFT]
    # "At CL 11, this bonus increases to +2": one +1 effect plus the min_cl 11 one, not two +1s doubled.
    assert engine._ac_modifier(me) == before + 2, (before, engine._ac_modifier(me))

    # "until the start of your next turn": it survives the foe's whole turn ...
    turn(table, mid, RIGHT)
    engine = reload(combat, mid)
    assert engine._ac_modifier(engine.state.actors[LEFT]) == before + 2

    # ... and is gone at the start of my next turn, not lasting the rest of the fight.
    turn(table, mid, LEFT)
    engine = reload(combat, mid)
    assert engine._ac_modifier(engine.state.actors[LEFT]) == before, (before, engine._ac_modifier(engine.state.actors[LEFT]))
    assert not [m for m in engine.state.actors[LEFT].modifiers.values() if m.target_field == "armor_class"]


def test_liver_shots_own_effect_row_sets_the_speed_instead_of_adding_to_it():
    """The talent's own effect row, not only the Counter modifier's, must carry the printed 5.

    A Counter talent is compiled through its modifier (``combat/factory_compiler.py`` apply_modifiers reads
    ``mechanics[key]["modifier"]``), so the record's own ``effects`` row is on no compiled path: the table
    test above can only ever exercise the modifier's copy of it. This data-level check is the only
    executable form of coverage for that row. ``flat: 5`` is what ``typed_executor.block_speed`` ADDs to
    ``speed_ft``, so a revert there speeds the victim up instead of rooting it.
    """
    generated = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())
    rows = [row for row in generated["mechanics"][LIVER]["effects"] if row.get("type") == "speed"]
    assert len(rows) == 1, generated["mechanics"][LIVER]["effects"]
    assert rows[0]["becomes"] == 5 and not int(rows[0].get("flat") or 0), rows[0]
    # The reviewed record the builder merges into it agrees.
    reviewed = json.loads((ROOT / f"authority/typed_mechanics/reviewed_final.d/{SOURCE_FILE}").read_text())
    assert [row for row in reviewed["mechanics"][LIVER]["effects"] if row.get("type") == "speed"] == rows


HAYMAKER = "TAL_RETRIBUTION_HAYMAKER"


def _anatomy(kind=None, stated=None):
    """Give the foe printed creature labels, exactly as combat.creature_types.from_record encodes them."""
    def edit(bundle):
        _seal(bundle)
        if bundle["actor_template"]["entity_id"] != RIGHT:
            return
        record = {"creature_type": kind} if kind else {}
        if stated is not None:
            record["physiology"] = {"voice_and_breath_channel": stated}
        bundle["actor_template"]["creature_types"] = list(from_record(record))
    return edit


def _countered(tmp_path, talent, label, seal=_seal):
    combat, table, mid = fight(
        tmp_path, [BASE, talent, REFLEXIVE], left_kit=DAO, cl=15,
        cause=[{"type": "damage", "flat": 9, "damage_types": ["slashing"], "applies_to": "target"}],
        bundle_edit=seal)
    settle(lambda a: act(table, mid, "Reflexive Preparation", a), label)
    turn(table, mid, RIGHT)
    settle(lambda a: act(table, mid, "Cause", a))
    return combat, table, mid


def _damaged(engine):
    return [c for c in engine.state.actors[RIGHT].conditions.values() if c.condition_id.endswith("speech_damaged")]


def _immune_note(engine):
    return [e.payload.get("log", "") for e in engine.events if e.event_type == "PASSIVE_TRIGGERED"]


def test_haymaker_damages_the_throat_of_a_creature_that_has_one(tmp_path):
    combat, table, mid = _countered(tmp_path, HAYMAKER, "Counterstrike + Haymaker")
    assert _damaged(reload(combat, mid))


def test_haymaker_does_not_read_not_breathing_as_having_no_mouth(tmp_path):
    """An undead needs no breath, so it has no mouth is not what its record says.

    combat/rules/creature_physiology.json marks undead as not breath-dependent, but nothing states it has
    no mouth, throat or breath channel, so the printed immunity is not established and the hit lands.
    """
    combat, table, mid = _countered(tmp_path, HAYMAKER, "Counterstrike + Haymaker", seal=_anatomy("undead"))
    engine = reload(combat, mid)
    assert trait(engine.state.actors[RIGHT], "breath_dependent") is False
    assert trait(engine.state.actors[RIGHT], "voice_and_breath_channel") is None
    assert _damaged(engine), engine.state.actors[RIGHT].conditions


def test_haymaker_damages_a_non_breathing_creature_whose_record_states_a_mouth(tmp_path):
    combat, table, mid = _countered(tmp_path, HAYMAKER, "Counterstrike + Haymaker", seal=_anatomy("undead", stated=True))
    engine = reload(combat, mid)
    assert trait(engine.state.actors[RIGHT], "breath_dependent") is False
    assert trait(engine.state.actors[RIGHT], "voice_and_breath_channel") is True
    assert _damaged(engine)


def test_haymaker_leaves_a_creature_whose_record_says_it_has_no_mouth_alone(tmp_path):
    """"A creature without a meaningful mouth, throat, breath channel, or equivalent anatomy is immune."

    The creature's own printed record states the absence, so the engine applies the printed immunity without
    a GM ruling and says so in plain language.
    """
    combat, table, mid = _countered(tmp_path, HAYMAKER, "Counterstrike + Haymaker", seal=_anatomy("Humanoid", stated=False))
    engine = reload(combat, mid)
    assert trait(engine.state.actors[RIGHT], "voice_and_breath_channel") is False
    assert not _damaged(engine)
    lines = _immune_note(engine)
    assert any("no mouth, throat or breath channel" in line for line in lines), lines
    assert any("creature record says it has no mouth" in line for line in lines), lines
