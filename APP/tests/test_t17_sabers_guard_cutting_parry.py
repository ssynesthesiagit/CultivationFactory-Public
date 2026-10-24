"""MGR-T17: Guard-Cutting Parry's base reduction (clause (a)) on the real table.

The card's first clause is "Reduce the incoming weapon damage by 1d8 + your Proficiency Bonus." It is
data, not code: combat/rules/feature_blocks.json owns the damage_reduction row for the talent and
combat/typed_reactions.py runs it (before any soak). These tests pin the row, the compiled reaction and
what the table does with it -- the exact reduction, the single roll, the cause named in the fight log,
the sources the melee-weapon trigger rejects, and the spent Reaction.

Still manual, and untouched here: the printed 5-foot move ("you may move 5 feet without provoking
Opportunity Attacks from the attacker") and the owner's pending ruling on the CL5+ CP/Stamina "Guard
Pressured" upgrade. The free parry itself must never charge for either.
"""
import json
from pathlib import Path

from combat import typed_reactions
from combat.factory_compiler import compile_character
from tests import hunt15_support
from tests.h1_support import ROOT, sheet
from tests.hunt15_support import ALLY, LEFT, RIGHT, act, fight, reload, turn

PARRY = "tianxia.talent.sabers.guard_cutting_parry"
MAUL = {"items": [{"item_id": "tianxia.mortal.weapon.da_chui", "name": "Da Chui (Maul)", "quantity": 1}]}
BOW = {"items": [{"item_id": "tianxia.mortal.weapon.gong_jian", "name": "Gong Jian (Bow and Arrow)", "quantity": 1}]}
# The row's own threshold ("Reactions fire only when affordable and big enough to matter",
# combat/rules/feature_blocks.json). It is owner-editable and not a printed number.
MINIMUM_DAMAGE = 5


def _attacks(table, mid):
    return [group["label"] for group in table.state(mid)["menu"]["actions"]
            if group["label"].endswith(" attack")]


def _swing(table, mid, label=None, target=RIGHT):
    """Declare one attack and decline every reaction prompt, taking the free printed outcome."""
    label = label or _attacks(table, mid)[0]
    result = act(table, mid, label, (), target_id=target)
    answers = []
    for _ in range(6):
        if result["status"] != "REACTION_REQUIRED":
            break
        prompt = result["reaction"]
        options = [option["id"] for option in (prompt.get("choice") or {}).get("options") or []]
        answers.append({**prompt["context"], "selection": "USE",
                        "option_ids": ["skip" if "skip" in options else options[0]]})
        result = act(table, mid, label, answers, target_id=target)
    return result


def _reductions(engine, after=0):
    return [event for event in engine.events
            if event.event_type == "REACTION_RESOLVED" and event.sequence > after]


def _reduction_rolls(engine):
    return [roll for roll in engine.rolls if str(roll.reason).startswith("DAMAGE_REDUCTION:")]


def _weapon(engine):
    return next(key for key in engine.action_catalog if str(key).endswith("weapon.da_chui"))


def test_the_printed_reduction_is_one_data_row():
    blocks = json.loads((Path(ROOT) / "combat/rules/feature_blocks.json").read_text(encoding="utf-8"))
    row = blocks["features"][PARRY]
    assert {key: row[key] for key in ("block", "trigger", "dice", "bonus", "cost")} == {
        "block": "damage_reduction", "trigger": "melee_weapon_hit", "dice": "1d8", "bonus": "pb", "cost": 0}
    assert row["minimum_damage"] == MINIMUM_DAMAGE


def test_the_row_compiles_to_a_free_reaction_that_uses_proficiency_bonus():
    bundle = compile_character(sheet([PARRY], cl=15), actor_id="actor:factory.t17")
    row = next(row for row in bundle["typed_reactions"] if row["feature_id"] == PARRY)
    assert (row["block"], row["trigger"], row["dice"], row["cost"], row["resource_id"]) == (
        "damage_reduction", "melee_weapon_hit", "1d8", 0, "")
    assert row["bonus"] == 4  # the Proficiency Bonus of a CL15 sheet, read from the feature's "pb"


def test_a_melee_weapon_hit_is_reduced_by_one_d8_plus_proficiency_bonus(tmp_path, monkeypatch):
    monkeypatch.setattr(hunt15_support, "KIT", MAUL)
    combat, table, mid = fight(tmp_path / "hit", right=[PARRY], seed="T01")
    turn(table, mid, LEFT)
    assert _swing(table, mid)["status"] == "COMMITTED"
    engine = reload(combat, mid)
    rolls, reactions = _reduction_rolls(engine), _reductions(engine)
    committed = [event for event in engine.events if event.event_type == "DAMAGE_COMMITTED"][-1]
    assert len(rolls) == 1 and len(reactions) == 1  # one roll, applied once
    assert rolls[0].expression == "1d8+4" and len(rolls[0].dice) == 1
    assert reactions[0].source_definition_id == PARRY
    payload = reactions[0].payload
    assert payload["reduction"] == rolls[0].total
    assert payload["pending_after"] == payload["pending_before"] - rolls[0].total
    assert committed.payload["hp_damage"] == payload["pending_after"]
    assert engine.state.actors[RIGHT].reaction_available is False
    # The fight log names the cause of the gap and the amount the parry removed, and the free
    # parry charges nothing for the CL5+ upgrade it was not asked to buy.
    lines = [row["summary"] for row in table.events(mid, 0)["events"]]
    assert any("Guard-Cutting Parry" in line and "reduced from" in line for line in lines), lines
    assert any(f"Damage reduced by {rolls[0].total}" in line for line in lines), lines
    assert not [event for event in engine.events
                if event.event_type == "RESOURCE_SPENT" and event.source_definition_id == PARRY]


def test_a_ranged_weapon_attack_is_not_reduced(tmp_path, monkeypatch):
    monkeypatch.setattr(hunt15_support, "KIT", BOW)
    combat, table, mid = fight(tmp_path / "ranged", right=[PARRY], seed="R1",
                               positions={LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 7, "y": 6}})
    turn(table, mid, LEFT)
    assert _swing(table, mid)["status"] == "COMMITTED"
    engine = reload(combat, mid)
    committed = [event for event in engine.events if event.event_type == "DAMAGE_COMMITTED"][-1]
    assert not _reductions(engine) and not _reduction_rolls(engine)
    assert committed.payload["hp_damage"] == committed.payload["rolled_or_pending_damage"] > 0
    assert engine.state.actors[RIGHT].reaction_available is True


def test_technique_damage_is_not_reduced(tmp_path, monkeypatch):
    monkeypatch.setattr(hunt15_support, "KIT", MAUL)
    effects = [{"type": "save", "ability": "dex", "dc": 100, "applies_to": "target",
                "on_fail": [{"type": "damage", "flat": 10, "damage_types": ["SLASHING"]}], "on_success": []}]
    combat, table, mid = fight(tmp_path / "technique", right=[PARRY], effects=effects,
                               target="HOSTILE_ENTITY", seed="Q1")
    turn(table, mid, LEFT)
    assert _swing(table, mid, "Test setup")["status"] == "COMMITTED"
    engine = reload(combat, mid)
    committed = [event for event in engine.events if event.event_type == "DAMAGE_COMMITTED"][-1]
    assert not _reductions(engine)
    assert committed.payload["hp_damage"] == committed.payload["rolled_or_pending_damage"] == 10


def test_the_reaction_is_spent_so_a_second_hit_this_round_is_not_reduced(tmp_path, monkeypatch):
    monkeypatch.setattr(hunt15_support, "KIT", MAUL)
    combat, table, mid = fight(tmp_path / "spent", right=[PARRY], ally=[], seed="B4",
                               positions={LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 4, "y": 6}, ALLY: {"x": 5, "y": 6}})
    turn(table, mid, LEFT)
    assert _swing(table, mid)["status"] == "COMMITTED"
    engine = reload(combat, mid)
    assert len(_reductions(engine)) == 1
    assert engine.state.actors[RIGHT].reaction_available is False
    marker = max(event.sequence for event in engine.events)
    act(table, mid, "end")
    turn(table, mid, ALLY)
    # The parry owner has not started a turn, so the Reaction has not come back yet.
    assert not [event for event in reload(combat, mid).events
                if event.event_type == "TURN_STARTED" and event.sequence > marker and event.actor_id == RIGHT]
    assert _swing(table, mid)["status"] == "COMMITTED"
    engine = reload(combat, mid)
    committed = [event for event in engine.events
                 if event.event_type == "DAMAGE_COMMITTED" and event.sequence > marker][-1]
    assert not _reductions(engine, marker) and len(_reduction_rolls(engine)) == 1
    assert committed.payload["hp_damage"] == committed.payload["rolled_or_pending_damage"] > 0
    assert engine.state.actors[RIGHT].reaction_available is False


def test_with_no_reaction_left_nothing_is_reduced_or_charged(tmp_path, monkeypatch):
    monkeypatch.setattr(hunt15_support, "KIT", MAUL)
    combat, table, mid = fight(tmp_path / "no-reaction", right=[PARRY], seed="S1")
    engine = reload(combat, mid)
    target = engine.state.actors[RIGHT]
    target.reaction_available = False
    before, resources = len(engine.events), dict(target.resources)
    assert typed_reactions.on_damage(engine, target, 12, 0, _weapon(engine), LEFT) == 12
    assert len(engine.events) == before and not _reduction_rolls(engine)
    assert dict(target.resources) == resources


def test_the_threshold_and_the_zero_floor_hold(tmp_path, monkeypatch):
    monkeypatch.setattr(hunt15_support, "KIT", MAUL)
    combat, table, mid = fight(tmp_path / "floor", right=[PARRY], seed="S1")
    engine = reload(combat, mid)
    target = engine.state.actors[RIGHT]
    weapon = _weapon(engine)
    before = len(engine.events)
    # Below the row's own minimum the parry is not even asked for.
    below = MINIMUM_DAMAGE - 1
    assert typed_reactions.on_damage(engine, target, below, 0, weapon, LEFT) == below
    assert len(engine.events) == before
    # A reduction larger than the damage stops at 0 instead of healing the target.
    assert typed_reactions.on_damage(engine, target, MINIMUM_DAMAGE, 0, weapon, LEFT) == 0
    event = _reductions(engine)[0]
    assert event.payload["reduction"] >= MINIMUM_DAMAGE
    assert event.payload["pending_after"] == 0
