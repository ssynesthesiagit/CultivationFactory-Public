"""Charged Countermeasure (Lightning talent; AI fight hunt item 5, /var/tmp/auto-audit/hunt1/REPORT.md).

Printed (authority/typed_mechanics/rules_text.json TAL_LIGHTNING_CHARGED_COUNTERMEASURE):

    The triggering creature must be Charged, Conductive, or using a visible qi circuit.
    Failed Save: The triggering reaction or counter has Disadvantage if it uses a roll. If it does not use a roll, its
    damage reduction, AC bonus, shield value, or movement prevention is reduced by your Proficiency Bonus.

The failed save handed the GM both branches at once as riders and never reached the roll; the requirement was not checked.
It gives the answered reaction ONE branch now (combat/ext/charged_countermeasure.py), lands the Disadvantage on that
reaction's own roll and on nothing later, and answers only a Charged or Conductive creature (AI and Auto reactors)."""

import json
from pathlib import Path

import pytest

from combat import typed_executor, typed_reactions
from combat.ext import charged_countermeasure
from combat.factory_compiler import TYPED_AUTHORITY, compile_character
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from tests.test_generic_reactions import REACTOR_SHEET, _mechanic

ROOT = Path(__file__).resolve().parents[1]
MECH = json.loads(TYPED_AUTHORITY.read_bytes())["mechanics"]
CM = "TAL_LIGHTNING_CHARGED_COUNTERMEASURE"
WATCHER, FOE = "actor:factory.cm_watcher", "actor:factory.cm_foe"
STRIKE = {"type": "attack", "attack_kind": "cultivation_melee", "count": 1,
          "on_hit": [{"type": "damage", "dice": {"count": 1, "sides": 6}, "damage_types": ["force"]}]}
RIPOSTE = {"type": "damage", "dice": {"count": 1, "sides": 6}, "damage_types": ["force"], "applies_to": "attacker"}


def _engine(foe_effects: list, seed: str = "CM-BRANCH"):
    """WATCHER carries the real Countermeasure record; FOE has a reaction of its own ("Counter": answers a melee miss)."""
    authority = {"mechanics": {"COUNTER": _mechanic("COUNTER", "Counter", "reaction", foe_effects,
                                                    trigger="A creature misses you with a melee attack")}}
    watcher = compile_character({**REACTOR_SHEET, "spheres_and_talents": {"learned_talent_record_ids": [CM]}},
                                actor_id=WATCHER, typed_authority={"mechanics": {CM: MECH[CM]}})
    foe = compile_character({**REACTOR_SHEET, "spheres_and_talents": {"learned_talent_record_ids": ["COUNTER"]}},
                            actor_id=FOE, typed_authority=authority)
    engine = Gate2Engine(ROOT, match_seed=seed, typed_bundles=(watcher, foe),
                         roster_setup={"primary_actor_ids": [WATCHER, FOE], "team_by_actor": {WATCHER: "team:a", FOE: "team:b"},
                                       "starting_positions": {WATCHER: {"x": 1, "y": 1}, FOE: {"x": 2, "y": 1}}})
    return engine, engine.state.actors[WATCHER], engine.state.actors[FOE]


def _ctx(engine, actor, target, source: str, **typed) -> typed_executor.Context:
    action = ActionDefinition(source_definition_id=source, display_name=source, owner_id=actor.entity_id, economy=EconomyKind.ACTION,
                              resolution_kind="TYPED", target_kind="HOSTILE_ENTITY")
    numbers = {"pb": 4, "save_dc": 15, "attack_bonus": 7}
    return typed_executor.Context(engine, actor, action, None, {"numbers": numbers, "effects": [], **typed}, [target], target)


def _mark(engine, watcher, foe, name: str = "Charged") -> None:
    typed_executor.run_effects(_ctx(engine, watcher, foe, "action:test.mark"), [{"type": "mark", "mark": name, "applies_to": "target"}])
    assert typed_executor.bears_mark(foe, WATCHER, name)


def _miss(engine, watcher, foe) -> None:
    """The watcher misses the foe with a melee attack: the foe's Counter opens, and "a creature uses a reaction" answers it."""
    typed_reactions.on_attack_missed(engine, watcher, foe, {"range_ft": None}, None)


def _events(engine, event_type: str, source: str) -> list:
    return [e for e in engine.events if e.event_type == event_type and e.source_definition_id == source]


def _riders(engine, source: str) -> list[str]:
    return [e.payload["rider"] for e in _events(engine, "GM_RIDER", source)]


def _modes(engine, source: str) -> list[str]:
    return [e.payload["mode"] for e in _events(engine, "ATTACK_ROLLED", source)]


def _answered(engine) -> bool:
    return bool(_events(engine, "REACTION_RESOLVED", CM))


def test_the_failed_save_is_one_effect_not_two_unconditional_riders():
    record = MECH[CM]
    (save,) = record["effects"]
    assert save["type"] == "save" and [effect["type"] for effect in save["on_fail"]] == ["countermeasure_penalty"]
    # the two printed branches were a "disadvantage" and a "damage_modifier" applied together; neither is left in the record
    assert not [n for n in json.dumps(record["effects"]).split('"type": "') if n.startswith(("disadvantage", "damage_modifier"))]
    assert [effect["type"] for effect in save["on_success"]] == ["spend_mark"]  # "the creature loses its Charge if it had one"


def test_a_reaction_that_rolls_gets_disadvantage_on_its_own_roll_and_no_second_branch():
    engine, watcher, foe = _engine([STRIKE])
    _mark(engine, watcher, foe)
    foe.saving_throws["CON"] = -50  # the save fails
    _miss(engine, watcher, foe)
    assert _answered(engine)
    assert _modes(engine, "COUNTER") == ["DISADVANTAGE"]  # the answered reaction's own attack roll
    (rider,) = _riders(engine, CM)  # one branch, one line: not the reduction as well
    assert "uses a roll" in rider and "Disadvantage" in rider and "reduced by" not in rider


def test_the_disadvantage_is_not_left_for_a_later_attack():
    engine, watcher, foe = _engine([STRIKE])
    _mark(engine, watcher, foe)
    foe.saving_throws["CON"] = -50
    _miss(engine, watcher, foe)
    assert _modes(engine, "COUNTER") == ["DISADVANTAGE"]
    # an ordinary attack the same creature makes afterwards is its own roll
    typed_executor.run_effects(_ctx(engine, foe, watcher, "action:test.strike"), [STRIKE])
    assert _modes(engine, "action:test.strike") == ["NORMAL"]
    # and so is the same reaction the next time it fires, with nobody left to answer it
    foe.reaction_available, watcher.reaction_available = True, False
    _miss(engine, watcher, foe)
    assert _modes(engine, "COUNTER") == ["DISADVANTAGE", "NORMAL"]


def test_a_reaction_with_no_roll_gets_only_the_reduction_rider_and_no_disadvantage():
    engine, watcher, foe = _engine([RIPOSTE])
    _mark(engine, watcher, foe)
    foe.saving_throws["CON"] = -50
    _miss(engine, watcher, foe)
    assert _answered(engine)
    (rider,) = _riders(engine, CM)  # the one branch that applies: Proficiency Bonus (4) off the reaction's numbers, by hand
    assert "uses no roll" in rider and "reduced by 4" in rider and "Disadvantage" not in rider
    assert typed_reactions.reaction_penalty(engine, FOE, "COUNTER") is None  # nothing waits to hit a later roll
    assert not _events(engine, "ATTACK_ROLLED", "COUNTER")


def test_a_successful_save_leaves_the_reaction_alone_and_spends_the_charge():
    engine, watcher, foe = _engine([STRIKE])
    _mark(engine, watcher, foe)
    foe.saving_throws["CON"] = 50  # the save succeeds
    _miss(engine, watcher, foe)
    assert _answered(engine)
    assert _modes(engine, "COUNTER") == ["NORMAL"] and not _riders(engine, CM)
    assert not typed_executor.bears_mark(foe, WATCHER, "Charged")  # "the creature loses its Charge if it had one"


def test_the_effect_without_a_reaction_to_answer_gives_one_rider_with_both_printed_branches():
    engine, watcher, foe = _engine([STRIKE])
    typed_executor.run_effects(_ctx(engine, watcher, foe, "action:test.cm"), [{"type": "countermeasure_penalty", "applies_to": "target"}])
    (rider,) = _riders(engine, "action:test.cm")
    assert "has Disadvantage if it uses a roll" in rider and "reduced by 4" in rider
    assert typed_reactions.reaction_penalty(engine, FOE, "COUNTER") is None


def test_it_answers_only_a_charged_or_conductive_creature():
    engine, watcher, foe = _engine([STRIKE], "CM-UNMARKED")
    _miss(engine, watcher, foe)  # the foe is neither Charged nor Conductive
    assert _events(engine, "REACTION_RESOLVED", "COUNTER") and not _answered(engine)
    assert watcher.reaction_available and not _events(engine, "SAVE_ROLLED", CM)  # the Reaction is kept, no Save was forced

    for name in ("Charged", "Conductive"):
        engine, watcher, foe = _engine([STRIKE], f"CM-{name.upper()}")
        _mark(engine, watcher, foe, name)
        _miss(engine, watcher, foe)
        assert _answered(engine) and not watcher.reaction_available, name


def test_a_player_who_is_asked_decides_the_visible_qi_circuit_themself():
    engine, watcher, foe = _engine([STRIKE])
    row = next(r for r in engine.typed_reaction_rows[WATCHER] if r["feature_id"] == CM)
    assert charged_countermeasure.eligible(engine, watcher, foe, row) is False  # an unmarked creature, AI or Auto
    row["ask"] = True
    engine.typed_ask_reactors = (WATCHER,)
    assert charged_countermeasure.eligible(engine, watcher, foe, row) is None  # offered: the player judges it
    other = next(r for r in engine.typed_reaction_rows[FOE] if r["feature_id"] == "COUNTER")
    assert charged_countermeasure.eligible(engine, foe, watcher, other) is None  # other reactions are not touched


def test_which_reactions_use_a_roll():
    rolling = [{"type": "attack", "attack_kind": "cultivation_melee"}, {"type": "counter_technique"},
               {"type": "negate_attack", "chance_d20": 11}, {"type": "negate_attack", "contest": True},
               {"type": "save", "on_fail": [{"type": "attack", "attack_kind": "cultivation_ranged"}]}]
    not_rolling = [{"type": "ac_bonus", "amount": 2}, {"type": "damage", "dice": {"count": 1, "sides": 6}},
                   {"type": "negate_attack", "if_out_of_reach": True}, {"type": "resistance", "damage_types": ["all"]},
                   {"type": "move", "distance_ft": 10}]
    for effect in rolling:
        assert charged_countermeasure.uses_roll({"effects": [effect]}), effect
    for effect in not_rolling:
        assert not charged_countermeasure.uses_roll({"effects": [effect]}), effect
    assert not charged_countermeasure.uses_roll({"block": "save_rescue", "amount": 2})


@pytest.mark.parametrize("actor_id, expected", [(FOE, "DISADVANTAGE"), (WATCHER, "NORMAL")])
def test_a_contest_or_chance_roll_has_disadvantage_only_for_the_answered_reactor(actor_id, expected):
    engine, watcher, foe = _engine([STRIKE])
    engine._typed_reaction_frames = {
        (FOE, "COUNTER"): {"penalty": {"actor_id": FOE, "feature_id": "COUNTER"}},
    }
    actor = foe if actor_id == FOE else watcher
    ctx = _ctx(engine, actor, watcher, "COUNTER", reaction_attack=True)
    assert typed_executor._reaction_roll_mode(ctx) == expected
    assert typed_executor._reaction_roll_mode(_ctx(engine, actor, watcher, "COUNTER")) == "NORMAL"  # not a reaction's own roll
    assert typed_executor._reaction_roll_mode(_ctx(engine, actor, watcher, "OTHER", reaction_attack=True)) == "NORMAL"
