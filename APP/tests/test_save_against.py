"""Advantage/Disadvantage on saves against named effects (typed_executor.block_advantage -> combat/ext/save_against.py):
Weight Shift's Body Heavying, Consecrated Boundary, Gather Charge's "next Dexterity saving throw" were GM lines."""

import pytest

from factory_authoring.roll_targets import _names_a_save, seal_roll_targets
from combat import typed_executor
from combat.ext.save_against import CONDITION, save_against
from combat.gate2_runtime_content import AN
from tests.test_auto_wenxue import ME, _bundle, _engine


def _ctx(engine, actor_id, target_id):
    action = next(iter(engine.action_catalog.values()))
    actor, target = engine.state.actors[actor_id], engine.state.actors[target_id]
    return typed_executor.Context(engine, actor, action, None, {"numbers": {"pb": 4, "save_dc": 15}}, [target], target, {})


def _held(actor):
    return [c for c in actor.conditions.values() if c.condition_id == CONDITION]


def test_resisting_shove_grapple_and_prone_is_advantage_on_those_saves_only():
    engine = _engine(_bundle())
    me = engine.state.actors[ME]
    typed_executor.block_advantage(_ctx(engine, ME, ME), {"roll_target": {'kind': 'save', 'next': False, 'against': ['forced_movement', 'grappled', 'prone'], 'abilities': [], 'preview': {'kind': 'save', 'group': 'resisting shove, grapple, forced movement, and effects that would knock you prone'}},
        "type": "advantage", "applies_to": "self", "expires_on": "UNTIL_REMOVED",
        "on": "resisting Shove, Grapple, forced movement, and effects that would knock you Prone"})
    assert [c.data["rule"]["save_against"]["against"] for c in _held(me)] == [["forced_movement", "grappled", "prone"]]
    foe_ctx = _ctx(engine, AN, ME)
    assert save_against(foe_ctx, me, "STR", {"prone"}) == {"bonus": 0, "modes": ["ADVANTAGE"]}
    assert save_against(foe_ctx, me, "STR", {"forced_movement"}) == {"bonus": 0, "modes": ["ADVANTAGE"]}
    assert save_against(foe_ctx, me, "WIS", {"frightened"}) is None
    assert len(_held(me)) == 1  # a lasting one is not used up


def test_the_next_dexterity_save_is_used_up():
    engine = _engine(_bundle())
    me = engine.state.actors[ME]
    typed_executor.block_advantage(_ctx(engine, ME, ME), {"roll_target": {'kind': 'save', 'next': True, 'against': ['forced_movement', 'paralyzed', 'prone'], 'abilities': ['DEX'], 'preview': {'kind': 'save', 'group': 'the next dexterity saving throw you make before the charge ends against lightning, thunder, paralysis, forced movement, or being knocked prone'}, 'inside': {'saves': ['DEX']}},
        "type": "advantage", "applies_to": "self",
        "on": "Display text deliberately names an attack roll, not a save"})
    foe_ctx = _ctx(engine, AN, ME)
    assert save_against(foe_ctx, me, "CON", {"prone"}) is None  # not a Dexterity save
    assert save_against(foe_ctx, me, "DEX", {"prone"}) == {"bonus": 0, "modes": ["ADVANTAGE"]}
    assert not _held(me)
    assert engine.events[-1].event_type == "CONDITION_REMOVED"


def test_a_typed_save_rolls_with_it():
    engine = _engine(_bundle())
    typed_executor.block_advantage(_ctx(engine, ME, ME), {"roll_target": {'kind': 'save', 'next': False, 'against': ['charmed', 'frightened'], 'abilities': [], 'preview': {'kind': 'save', 'group': 'saving throws against charmed and frightened'}},
        "type": "advantage", "applies_to": "self", "expires_on": "UNTIL_REMOVED", "on": "saving throws against Charmed and Frightened"})
    typed_executor.block_save(_ctx(engine, AN, ME), {"type": "save", "ability": "wis", "on_fail": [
        {"type": "condition", "condition": "frightened", "applies_to": "target"}], "on_success": []})
    rolled = next(e for e in reversed(engine.events) if e.event_type == "SAVE_ROLLED")
    assert rolled.payload["mode"] == "ADVANTAGE"


def test_an_ability_check_or_a_bare_line_stays_a_gm_line():
    assert not _names_a_save("checks made to hold a door, brace a barrier, resist a charging creature")
    assert not _names_a_save("its next Concentration saving throw")
    assert _names_a_save("dexterity saving throws")


def test_roll_target_is_required_and_explicit_values_are_not_rederived():
    engine = _engine(_bundle())
    ctx = _ctx(engine, ME, ME)
    effect = {"type": "advantage", "applies_to": "self", "on": "the next Dexterity saving throw"}
    with pytest.raises(ValueError, match=f"advantage effect from {ctx.source} requires roll_target"):
        typed_executor.block_advantage(ctx, effect)
    effect["roll_target"] = None
    seal_roll_targets(effect)
    assert effect["roll_target"] is None
    typed_executor.block_advantage(ctx, effect)
    assert not _held(engine.state.actors[ME])
    effect["roll_target"] = {"kind": "check", "checks": ["Stealth"]}
    seal_roll_targets(effect)
    assert effect["roll_target"] == {"kind": "check", "checks": ["Stealth"]}
    typed_executor.block_advantage(ctx, effect)
    held = engine.state.actors[ME].conditions.values()
    assert any(c.data.get("rule", {}).get("check_mode") == {"Stealth": "ADVANTAGE"} for c in held)


def test_attacks_against_the_target_means_attack_rolls():
    engine = _engine(_bundle())
    foe = engine.state.actors[AN]
    typed_executor.block_advantage(_ctx(engine, ME, AN), {"roll_target": {'kind': 'incoming_attack', 'preview': {'kind': 'attack', 'group': 'attack'}}, "type": "advantage", "applies_to": "target", "on": "attacks against the target"})
    assert any(m.target_field == "incoming_attack_mode" and m.value == "ADVANTAGE" for m in foe.modifiers.values())
    assert not any("Advantage on" in str((e.payload or {}).get("rider")) for e in engine.events if e.event_type == "GM_RIDER")
