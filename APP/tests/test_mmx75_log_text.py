"""MMX75 (hunt86 findings 1 and 4): the fight log names what happened, not how it is stored.

The log used to print a condition's storage key as if it were rules text
("No Temp Hp", and "Unnamed effect" once the key ended in a number), and it named
the wrong creature as the source of two kinds of effect: an attack's own roll mode
was credited to the ability that made the attack, and a d20 rewrite was credited
to the creature whose roll was rewritten rather than to the one who used the
ability.

Every assertion here is about the printed line, because that is the level the
defect was reported at: these are the strings a player reads in the fight log.
"""
import pytest

from combat.condition_names import condition_key, condition_label
from combat.history_feed import format_history_feed

ACTORS = {"a": "Wolf", "b": "Tabik Damu", "hao": "Hao Bing", "cai": "Cai Xiao"}
# Real definition ids are namespaced, which is what lets the feed resolve a printed
# name for them; a bare word is echoed back unchanged.
DEFINITIONS = {"action:typed.0a11.bite": "Bite", "action:typed.0a22.field": "Void Field",
               "action:typed.0a33.talisman": "Qi Storage Talisman",
               "action:typed.0a44.wdr": "Waking Dream Revision", "action:typed.0a55.hex": "Hex"}
BITE, FIELD, WDR, HEX = ("action:typed.0a11.bite", "action:typed.0a22.field",
                         "action:typed.0a44.wdr", "action:typed.0a55.hex")


def feed(*events):
    return [row["summary"] for row in format_history_feed(
        list(events), [], pre_state=None, post_state={},
        actor_names=dict(ACTORS), definition_names=dict(DEFINITIONS))]


def applied(condition_id, *, target="cai", actor="hao", source=FIELD, data=None):
    record = {"condition_id": condition_id, "data": data or {}}
    return {"event_type": "CONDITION_APPLIED", "actor_id": actor, "target_ids": [target],
            "source_definition_id": source,
            "payload": {"condition_id": condition_id, "expires_on": "UNTIL_REMOVED",
                        "gate3_condition_after": record}}


def removed(condition_id, *, target="cai", actor="hao", source=FIELD):
    record = {"condition_id": condition_id, "data": {}}
    return {"event_type": "CONDITION_REMOVED", "actor_id": actor, "target_ids": [target],
            "source_definition_id": source,
            "payload": {"condition_id": condition_id,
                        "gate3_condition_before": record}}


# --------------------------------------------------------------------------- finding 1

@pytest.mark.parametrize("condition_id, expected", [
    # hunt86: "No Temp Hp", "No Invisible" -- the slug printed as rules text.
    ("condition:typed.no_temp_hp", "No Temporary Hit Points"),
    ("condition:typed.no_invisible", "Cannot Become Invisible"),
    # hunt86 H86-B01: 58 lines of "Unnamed effect" for ...:prepared:N.
    ("condition:typed.qi_storage_talisman:prepared:1", "Qi Storage Talisman"),
    ("condition:typed.qi_storage_talisman:prepared:11", "Qi Storage Talisman"),
    # hunt86: a scope prefix and a generated option tail are not part of the name.
    ("condition:typed.state.court_of_charged_paths", "Court of Charged Paths"),
    ("condition:typed.wenxue.hard_draw_ready", "Hard Draw Ready"),
    ("condition:typed.unmaking_crack.action_typed_dec5e0a651_weapon_bi_shou", "Unmaking Crack"),
    ("condition:core.dodge", "Dodge"),
    ("condition:typed.poisoned", "Poisoned"),
])
def test_applied_line_names_the_condition_readably(condition_id, expected):
    """The applied line carries the condition's name, never its storage key."""
    (line,) = feed(applied(condition_id))
    assert expected in line, line
    assert "Unnamed effect" not in line, line
    for leaked in (condition_id, condition_id.removeprefix("condition:typed."), "condition:"):
        assert leaked not in line, f"{condition_id!r} leaked into {line!r}"


def test_removed_line_names_the_condition_readably():
    """The removed line is named by the same formatter, so a condition has one name."""
    (line,) = feed(removed("condition:typed.qi_storage_talisman:prepared:4"))
    assert "Qi Storage Talisman was removed from Cai Xiao" in line, line
    assert "Unnamed effect" not in line and "condition:typed" not in line, line


def test_applied_line_names_a_companion_effect_in_plain_words():
    """The companion wording a pinned test expects still reads as plain words."""
    (line,) = feed(applied("condition:typed.no_temp_hp", source=FIELD,
                           data={"companion_of": "hollowed"}))
    assert "Hollowed: cannot gain temporary hit points" in line, line
    assert "No Temp Hp" not in line, line


@pytest.mark.parametrize("condition_id, key", [
    ("condition:typed.qi_storage_talisman:prepared:3", "qi_storage_talisman"),
    ("condition:typed.state.court_of_charged_paths", "state.court_of_charged_paths"),
    ("condition:typed.wenxue.hard_draw_ready", "wenxue.hard_draw_ready"),
    ("condition:core.dodge", "dodge"),
    ("condition:typed.mark.resonance.actor:factory.a911a1d4-d261-4fd3-9199-97f468ad10dc",
     "mark.resonance"),
])
def test_the_name_segment_of_an_id_is_itself_readable(condition_id, key):
    """Owner, instance and option tails are dropped; the printed name never shows a scope."""
    assert condition_key(condition_id) == key
    assert "." not in condition_label(condition_id) and ":" not in condition_label(condition_id)


def test_an_id_that_names_nothing_says_so_rather_than_printing_a_hash():
    assert condition_label("") == "Unnamed effect"
    assert condition_label(None) == "Unnamed effect"
    assert condition_label("condition:typed.4f3a9c21-dead-beef") == "Unnamed effect"


# --------------------------------------------------------------------------- finding 4a

STRIKE = {"modifier_id": "m1", "target_field": "attack_mode", "operation": "SET",
          "value": "DISADVANTAGE", "applies_to": "NEXT_ATTACK", "expires_on": "CONSUMED"}


def modifier(*, target="a", owner="a", source=BITE, **changes):
    record = {**STRIKE, "target_id": target, "source_actor_id": owner,
              "source_definition_id": source, **changes}
    return {"event_type": "MODIFIER_APPLIED", "actor_id": owner, "target_ids": [target],
            "source_definition_id": source,
            "payload": {**record, "gate3_modifier_after": record}}


def test_an_attack_own_roll_mode_is_not_blamed_on_the_attack_that_made_it():
    """hunt86 H86-N1: "Wolf: disadvantage on attack rolls from Bite" read as Bite
    penalising its own wolf. The roll mode belongs to the attack."""
    (line,) = feed(modifier())
    assert line == "Wolf's Bite is made with Disadvantage on the attack roll; until used."
    assert "from Bite" not in line, line


@pytest.mark.parametrize("changes", [
    {"value": "ADVANTAGE", "source": "hex"},
    {"value": "DISADVANTAGE:blinded"},
])
def test_every_shape_of_an_own_roll_mode_is_worded_the_same_way(changes):
    source = changes.pop("source", "bite")
    (line,) = feed(modifier(source=source, **changes))
    assert line.startswith("Wolf's ") and " is made with " in line and " on the attack roll" in line, line
    assert "from " not in line, line


def test_a_roll_mode_on_another_creature_keeps_the_ability_that_caused_it():
    """The fix is about an effect on its own user; a real effect still names its source."""
    (line,) = feed(modifier(target="b", owner="a", source=HEX))
    assert line == "Tabik Damu: disadvantage on their next attack roll from Hex; until used."


def test_a_modifier_with_no_recorded_owner_keeps_the_existing_wording():
    """Older saved fights record no source_actor_id; they must still read as before."""
    event = modifier()
    del event["payload"]["source_actor_id"]
    del event["payload"]["gate3_modifier_after"]["source_actor_id"]
    (line,) = feed(event)
    assert line == "Wolf: disadvantage on their next attack roll from Bite; until used."


# --------------------------------------------------------------------------- finding 4b

BEFORE = {"natural_result": 10, "modifier": -1, "total": 9, "reason": "SAVE:STR"}
AFTER = {"natural_result": 9, "modifier": -1, "total": 8, "reason": "SAVE:STR"}


def rewritten(*, user_id=None, actor="cai", operation="reroll"):
    payload = {"operation": operation, "original": dict(BEFORE), "result": dict(AFTER)}
    if user_id is not None:
        payload["user_id"] = user_id
    return {"event_type": "D20_REWRITTEN", "actor_id": actor, "target_ids": [],
            "source_definition_id": WDR, "payload": payload}


def test_a_rewrite_names_the_creature_that_used_the_ability():
    """hunt86 H86-11: "Cai Xiao's Waking Dream Revision rerolled the saving throw" made
    the target look like the owner. Hao Bing used the ability on Cai Xiao."""
    (line,) = feed(rewritten(user_id="hao"))
    assert line.startswith("Hao Bing's Waking Dream Revision rerolled Cai Xiao's saving throw: "), line
    assert not line.startswith("Cai Xiao's"), line


def test_a_rewrite_of_your_own_roll_keeps_its_existing_wording():
    (line,) = feed(rewritten(user_id="cai"))
    assert line.startswith("Cai Xiao's Waking Dream Revision rerolled the saving throw: "), line


def test_a_rewrite_with_no_recorded_user_keeps_its_existing_wording():
    """A fight saved before user_id was recorded must read exactly as it did."""
    (line,) = feed(rewritten())
    assert line.startswith("Cai Xiao's Waking Dream Revision rerolled the saving throw: "), line


def test_a_bonus_from_another_creature_is_attributed_to_its_user():
    (line,) = feed(rewritten(user_id="hao", operation="bonus"))
    assert line.startswith("Hao Bing's Waking Dream Revision added a bonus to Cai Xiao's saving throw"), line
