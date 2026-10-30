"""MMX97: damage and cost reporting (round 24, live 42e43e14; HUNT99 findings 1/2/4, HUNT101 finding 3).

Each test drives a real engine through the table's own candidate list and fails on the behaviour the
audit found, not on a unit call:

* ``test_demon_mark_augment_does_not_damage_a_creature_that_saves`` -- HUNT99 #2. Demon Mark prints
  "The creature makes a Charisma saving throw. Failed Save: It bears your Demon Mark." and has no
  Successful Save clause, so a creature that saves must take nothing. Composed with Daemonic Augment's
  "add Proficiency Bonus to one damage roll" (typed ``when: "use"``), the augment's row used to land
  on top of the ability's effects, beside the save rather than inside its failure branch, and invented
  a damage packet the printed rules never grant.
* ``test_demon_mark_failed_save_registers_a_later_bonus_without_damage`` -- a failure marks the
  target; "when you damage it" does not itself deal damage (HUNT211 #1).
* ``test_damage_commit_explains_temporary_hit_point_absorption`` -- HUNT99 #1. The commit payload has
  always carried the whole chain (rolled, reduced, absorbed by temporary Hit Points), but the history
  feed showed only the last number, so a packet that lost 34 points to a temporary Hit Point read as
  "8d8 ... total 38" then "dealt 4" with no printed basis.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.test_riders_c7 import ME, answers, fight, legal, payloads, sheet, use  # noqa: E402

DEMON_MARK = "TAL_DAEMONIC_CULTIVATION_DEMON_MARK"
DAEMONIC = {"sphere_record_ids": ["tianxia.sphere.daemonic_cultivation"],
            "automatic_sphere_component_record_ids": ["TAL_DAEMONIC_CULTIVATION_DAEMONIC_AUGMENT"]}
AUGMENTED = "Demon Mark + Daemonic Augment: Bonus Damage"


def _foe(engine):
    return next(a for a in engine.state.actors.values() if a.entity_id != ME)


def _mark_fight():
    from combat.factory_compiler import compile_character

    engine = fight(compile_character(sheet([DEMON_MARK], spheres=DAEMONIC, cl=18, dc=15), actor_id=ME))
    answers(engine)
    assert AUGMENTED in legal(engine), "the table must still offer the composed augment button"
    return engine, _foe(engine)


# ------------------------------------------------------------------------------- HUNT99 #2: a save is not a hit
def test_demon_mark_augment_does_not_damage_a_creature_that_saves():
    engine, foe = _mark_fight()
    # A forced save outcome decides which branch runs. The SAVE_ROLLED payload keeps the raw d20, so
    # the branch itself is read back off what the ability then did.
    engine._typed_roll_outcome = {foe.entity_id: "success"}
    events = use(engine, AUGMENTED, target=foe.entity_id)
    assert payloads(events, "SAVE_ROLLED"), "the Charisma save must have been rolled"
    assert payloads(events, "DAMAGE_COMMITTED") == [], "a successful Demon Mark save must deal no damage"
    assert payloads(events, "CONDITION_APPLIED") == [], "no Demon Mark may be borne after a successful save"


def test_demon_mark_failed_save_registers_a_later_bonus_without_damage():
    """A failed save registers the printed later rider, without inventing a roll.

    Demon Mark: "once per turn when you damage it, add Proficiency Bonus to the damage", and the
    Augment's own "add Proficiency Bonus to one damage roll" both require damage
    from another source. "Failed Save: It bears your Demon Mark" grants none.
    """
    engine, foe = _mark_fight()
    engine._typed_roll_outcome = {foe.entity_id: "failure"}
    events = use(engine, AUGMENTED, target=foe.entity_id)
    assert payloads(events, "SAVE_ROLLED"), "the Charisma save must have been rolled"
    dealt = payloads(events, "DAMAGE_COMMITTED")
    assert dealt == []
    assert payloads(events, "CONDITION_APPLIED"), "a failed save must bear the Demon Mark"


# ------------------------------------------------------------------------------- HUNT99 #1: say what happened to the damage
def _commit_payload(**over):
    payload = {"rolled_or_pending_damage": 38, "reduced_to": 38, "temporary_hp_absorbed": 34,
               "hp_damage": 4, "damage_type": "PIERCING", "remaining_hp": 171}
    payload.update(over)
    return payload


def _summary(payload):
    from combat.history_feed import format_history_feed

    events = [{"event_type": "DAMAGE_COMMITTED", "actor_id": "a1", "target_ids": ["t2"],
               "source_definition_id": "TAL_METAL_HEAVEN_PIERCING_NAIL", "payload": payload}]
    return " ".join(row["summary"] for row in format_history_feed(events, [], pre_state=None, post_state={},
                                                                actor_names={"a1": "Zheng Jingxu", "t2": "Zou Chenzhen"},
                                                                definition_names={"TAL_METAL_HEAVEN_PIERCING_NAIL": "Heaven-Piercing Nail"}))


def test_damage_commit_explains_temporary_hit_point_absorption():
    """The exact H99-07 packet: 38 rolled, 4 taken, with 34 swallowed by temporary Hit Points."""
    line = _summary(_commit_payload())
    assert "4 piercing" in line and "171 HP remained" in line
    assert "38 rolled" in line, f"the rolled number must be stated, got: {line}"
    assert "34" in line and "temporary Hit Points" in line, f"the absorbed amount must be stated, got: {line}"


def test_ordinary_damage_reads_exactly_as_before():
    """No gap, no new words: a packet that dealt everything it rolled is unchanged."""
    line = _summary(_commit_payload(rolled_or_pending_damage=28, reduced_to=28, temporary_hp_absorbed=0, hp_damage=28,
                                    remaining_hp=143))
    assert line.endswith("Heaven-Piercing Nail dealt 28 piercing to Zou Chenzhen; 143 HP remained."), line


def test_a_record_without_the_chain_still_reads():
    """Fights saved before these keys existed, and rolled-out records, must not gain stray words."""
    line = _summary({"hp_damage": 4, "damage_type": "PIERCING", "remaining_hp": 171})
    assert line.endswith("Heaven-Piercing Nail dealt 4 piercing to Zou Chenzhen; 171 HP remained."), line


def test_a_reduction_is_named_too():
    line = _summary(_commit_payload(rolled_or_pending_damage=30, reduced_to=15, temporary_hp_absorbed=0, hp_damage=15,
                                    remaining_hp=160))
    assert "reduced from 30 to 15" in line, line


# ------------------------------------------------------------------------------- HUNT99 #4: show the cost you pay
def _augmented_action(engine=None):
    """The composed button as the table serves it: the engine's own action definition, dumped."""
    if engine is None:
        engine, _ = _mark_fight()
    action = next(a for a in engine.action_catalog.values() if a.display_name == AUGMENTED)
    return action.model_dump()


def test_a_plus_modifier_button_states_the_total_it_charges():
    """HUNT99 #4: the button used to print the BASE cost and charge base + rider ("reads 1, pays 2")."""
    from combat.tabletop import engine_button_description

    action = _augmented_action()
    line = engine_button_description(action)
    paid = {}
    for resource, amount in action["costs"]:
        paid[resource] = paid.get(resource, 0) + int(amount)
    for resource, amount in paid.items():
        word = str(resource).split(".")[-1].replace("_", " ").title()
        assert f"{amount} {word}" in line, f"the charged {amount} {word} must be printed; button said: {line}"
    assert "in total" in line, line


def test_the_printed_total_matches_what_the_table_actually_charges():
    """The button and the ledger must agree: read the printed amounts, then spend the button.

    Every resource the press actually charges must appear on the button at the amount charged --
    HUNT99's "the player reads 1 and pays 2", the base's cost printed and the rider's kept secret.
    """
    import re

    from combat.tabletop import engine_button_description

    engine, foe = _mark_fight()
    line = engine_button_description(_augmented_action(engine))
    printed = {word.strip(): int(number) for number, word in
               re.findall(r"(\d+)\s+([A-Za-z][A-Za-z ]*?)(?=\s|,|\.| in total)", line)}
    events = use(engine, AUGMENTED, target=foe.entity_id)
    charged = payloads(events, "RESOURCE_SPENT")
    assert charged, "the press must charge something"
    for spent in charged:
        word = str(spent["resource_id"]).split(".")[-1].replace("_", " ").title()
        assert printed.get(word) == spent["amount"], (
            f"the button printed {printed.get(word)} {word} but the table charged {spent['amount']}; said: {line}")


def test_an_ordinary_button_gains_no_cost_sentence():
    """Only composed variants carry the sentence; a plain ability reads exactly as before."""
    from combat.tabletop import engine_button_description

    engine, _ = _mark_fight()
    plain = next(a for a in engine.action_catalog.values() if a.display_name == "Demon Mark")
    assert "in total" not in engine_button_description(plain.model_dump())
