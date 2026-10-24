"""Execute use-timed bonuses through the real action candidate/commit path.

Mixed recipient damage and caster self-costs model the reviewed authority shapes. Sequential
attack/save shapes are authoring controls, not claims about a currently shipped character.
"""
import copy

import pytest

from combat.factory_compiler import _attach
from tests.test_typed_executor import _engine_with, _intent


def damage(amount, applies_to="target"):
    return {"type": "damage", "flat": amount, "applies_to": applies_to}


def save(failure=20, success=None):
    return {"type": "save", "ability": "dex", "on_fail": [damage(failure)],
            "on_success": [] if success is None else [damage(success)]}


def execute(effects, *, outcome="success", hit=None, kind="extra_damage", bonus=True):
    rider = {"type": kind, "applies_to": "target", "formula": "pb", "damage_label": "Test bonus"}
    tree = _attach(copy.deepcopy(effects), [rider], "use") if bonus else copy.deepcopy(effects)
    engine, actor_id = _engine_with({"effects": tree, "numbers": {"pb": 6, "save_dc": 15,
                                                                  "attack_bonus": 100 if hit else -100}}, "SOLFMMX97R2")
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == "action:typed.test")
    target = engine.state.actors[candidate.target_ids[0]]
    target.maximum_hp = 1000
    target.current_hp = 1000
    target.temporary_hp = 0
    engine._typed_roll_outcome = {target.entity_id: outcome}
    if hit is not None:
        engine._typed_roll_outcome[actor_id] = "success" if hit else "failure"
    before = len(engine.events)
    engine.execute_intent(_intent(candidate))
    events = engine.events[before:]
    return engine, actor_id, target.entity_id, events


def dealt(events, target):
    return sum(e.payload["hp_damage"] for e in events if e.event_type == "DAMAGE_COMMITTED"
               and target in e.target_ids)


def test_unconditional_recipient_damage_keeps_bonus_when_every_nearby_creature_saves():
    engine, _, target, events = execute([damage(30), save()])
    assert any(e.event_type == "SAVE_ROLLED" for e in events)
    assert dealt(events, target) == 36


def test_authority_compiled_burn_through_keeps_bloodline_bonus_on_successful_saves():
    """Execute the shipped broad modifier, using Burn Through's current compiled target schema.

    Object targeting/breach gating in its unchecked authority are inherited, outside this fix.
    Every creature's save is forced successful; the unconditional roll must still get the bonus.
    """
    from combat.factory_compiler import compile_character
    from tests.test_riders_c7 import ME, answers, fight, sheet, use

    character = compile_character(sheet([
        "FIRE_TAL_BURN_THROUGH",
        "tianxia.subpath.qi.bloodline_cultivator.feature.ancestral_bloodline_awakening",
    ], spheres={"sphere_record_ids": ["tianxia.sphere.fire"]}), actor_id=ME)
    engine = fight(character)
    answers(engine)
    engine._typed_roll_outcome = {actor_id: "success" for actor_id in engine.state.actors}
    events = use(engine, "Burn Through")
    assert any(e.event_type == "SAVE_ROLLED" for e in events)
    rolled = [e for e in events if e.event_type == "DAMAGE_ROLLED"]
    assert any(e.payload.get("damage_label") == "Ancestral Bloodline Awakening" for e in rolled)
    assert len([e for e in events if e.event_type == "DAMAGE_COMMITTED"]) == 2


@pytest.mark.parametrize("outcome,expected", [("success", 0), ("failure", 26)])
def test_caster_self_cost_cannot_claim_the_recipient_bonus(outcome, expected):
    _, actor, target, events = execute([damage(10, "self"), save()], outcome=outcome)
    assert dealt(events, actor) == 10
    assert dealt(events, target) == expected


@pytest.mark.parametrize("kind", ["damage", "extra_damage"])
@pytest.mark.parametrize("hit,outcome", [(True, "failure"), (True, "success"), (False, "failure")])
def test_sequential_attack_and_save_spend_one_bonus(kind, hit, outcome):
    attack = {"type": "attack", "attack_kind": "cultivation_melee",
              "on_hit": [damage(10), save()], "on_miss": []}
    _, _, target, events = execute([attack], hit=hit, outcome=outcome, kind=kind)
    _, _, control_target, control = execute([attack], hit=hit, outcome=outcome, kind=kind, bonus=False)
    assert dealt(events, target) - dealt(control, control_target) == (6 if hit else 0)
    assert sum(e.event_type == "SAVE_ROLLED" for e in events) == int(hit)


@pytest.mark.parametrize("outcome,expected", [("failure", 26), ("success", 16)])
def test_alternative_save_outcomes_keep_one_bonus(outcome, expected):
    _, _, target, events = execute([save(success=10)], outcome=outcome)
    assert dealt(events, target) == expected


@pytest.mark.parametrize("kind", ["damage", "extra_damage"])
def test_successful_half_save_after_an_attack_does_not_reuse_its_bonus(kind):
    half = save()
    half["on_success"] = [{"type": "half_damage"}]
    attack = {"type": "attack", "attack_kind": "cultivation_melee",
              "on_hit": [damage(10), half], "on_miss": []}
    _, _, target, events = execute([attack], hit=True, kind=kind)
    _, _, other, control = execute([attack], hit=True, kind=kind, bonus=False)
    assert dealt(events, target) - dealt(control, other) == 6


def test_two_sequential_saves_spend_the_bonus_only_in_the_first_damaging_stage():
    _, _, target, events = execute([save(), save()], outcome="failure")
    _, _, other, control = execute([save(), save()], outcome="failure", bonus=False)
    assert dealt(events, target) - dealt(control, other) == 6


def test_two_sequential_attacks_share_the_activation_slot():
    attack = {"type": "attack", "attack_kind": "cultivation_melee",
              "on_hit": [damage(10)], "on_miss": []}
    _, _, target, events = execute([attack, copy.deepcopy(attack)], hit=True)
    _, _, other, control = execute([attack, copy.deepcopy(attack)], hit=True, bonus=False)
    assert dealt(events, target) - dealt(control, other) == 6
