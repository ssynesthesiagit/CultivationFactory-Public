"""Owner playtest 2026-09-29 (the opening move on the bamboo map): Counter Palm, Hammer Rebuke and a counterattack answered
from across the map, Counter Palm answered an ally's miss, Bulwark fired with no Persistent Aegis and shielded the reactor,
and Hammer Rebuke applied all three of its choose-one results."""

import json
from pathlib import Path

from combat import reaction_triggers, typed_executor, typed_reactions
from combat.ext import blacksmith_rebuke
from combat.factory_compiler import TYPED_AUTHORITY, compile_character
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_content import AN
from tests.test_generic_reactions import REACTOR_SHEET, _mechanic

ROOT = Path(__file__).resolve().parents[1]
MECH = json.loads(TYPED_AUTHORITY.read_bytes())["mechanics"]
ME, FRIEND = "actor:factory.reach_reactor", "actor:factory.reach_friend"

COUNTER = {"type": "attack", "attack_kind": "cultivation_melee", "count": 1,
           "on_hit": [{"type": "damage", "dice": {"count": 1, "sides": 6}, "damage_types": ["force"]}]}
AUTHORITY = {"mechanics": {
    "COUNTER": _mechanic("COUNTER", "Counter", "reaction", [COUNTER], trigger="A creature misses you with a melee attack"),
    "GUARD_COUNTER": _mechanic("GUARD_COUNTER", "Guard Counter", "reaction", [COUNTER],
                               trigger="A creature misses an ally within 30 feet of you with an attack"),
    "SHIELD_FRIEND": _mechanic("SHIELD_FRIEND", "Shield Friend", "reaction",
                               [{"type": "resistance", "applies_to": "ally", "damage_types": ["all"], "duration": "this_attack"}],
                               trigger="An ally within 30 feet of you is targeted by an attack roll"),
}}


def _engine(me_at: dict, foe_at: dict, friend_at: dict | None = None) -> Gate2Engine:
    sheet = {**REACTOR_SHEET, "spheres_and_talents": {"learned_talent_record_ids": list(AUTHORITY["mechanics"])}}
    bundles = [compile_character(sheet, actor_id=ME, typed_authority=AUTHORITY)]
    ids, teams, spots = [ME, AN], {ME: "team:a", AN: "team:b"}, {ME: me_at, AN: foe_at}
    if friend_at is not None:
        bundles.append(compile_character({**REACTOR_SHEET, "spheres_and_talents": {"learned_talent_record_ids": []}},
                                         actor_id=FRIEND, typed_authority=AUTHORITY))
        ids, teams, spots = [ME, FRIEND, AN], {**teams, FRIEND: "team:a"}, {**spots, FRIEND: friend_at}
    engine = Gate2Engine(ROOT, match_seed="REACTION-REACH", typed_bundles=tuple(bundles),
                         roster_setup={"primary_actor_ids": ids, "team_by_actor": teams, "starting_positions": spots})
    engine.state.actors[ME].reaction_available = True
    return engine


def _fired(engine, feature_id: str) -> bool:
    return any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id == feature_id for e in engine.events)


def test_a_counterattack_does_not_answer_a_miss_from_across_the_map():
    engine = _engine({"x": 1, "y": 1}, {"x": 12, "y": 1})
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    typed_reactions.on_attack_missed(engine, foe, me, {"range_ft": 60}, None)
    assert not _fired(engine, "COUNTER") and me.reaction_available  # the Reaction is kept


def test_a_counterattack_answers_a_miss_in_reach():
    engine = _engine({"x": 1, "y": 1}, {"x": 2, "y": 1})
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    typed_reactions.on_attack_missed(engine, foe, me, {"range_ft": None}, None)
    assert _fired(engine, "COUNTER") and not me.reaction_available


def test_a_bystander_counterattack_needs_the_attacker_in_its_reach():
    engine = _engine({"x": 1, "y": 1}, {"x": 5, "y": 1}, friend_at={"x": 4, "y": 1})
    foe, friend = engine.state.actors[AN], engine.state.actors[FRIEND]
    typed_reactions.on_attack_missed(engine, foe, friend, {"range_ft": None}, None)
    assert not _fired(engine, "GUARD_COUNTER")
    engine = _engine({"x": 1, "y": 1}, {"x": 2, "y": 1}, friend_at={"x": 3, "y": 1})  # the attacker next to the reactor
    typed_reactions.on_attack_missed(engine, engine.state.actors[AN], engine.state.actors[FRIEND], {"range_ft": None}, None)
    assert _fired(engine, "GUARD_COUNTER")


def test_a_protecting_reaction_shields_the_ally_not_the_reactor():
    engine = _engine({"x": 1, "y": 1}, {"x": 5, "y": 1}, friend_at={"x": 4, "y": 1})
    foe, friend, me = engine.state.actors[AN], engine.state.actors[FRIEND], engine.state.actors[ME]
    typed_reactions.on_attacked(engine, foe, friend, {"range_ft": None}, None)
    assert _fired(engine, "SHIELD_FRIEND")
    assert any(m.source_definition_id == "SHIELD_FRIEND" and m.target_field == "damage_resistance" for m in friend.modifiers.values())
    assert not any(m.source_definition_id == "SHIELD_FRIEND" for m in me.modifiers.values())


def test_counter_palm_and_hammer_rebuke_answer_misses_against_you_within_reach():
    for key in ("TAL_IRON_FIST_COUNTER_PALM", "tianxia.talent.blacksmith.hammer_rebuke"):
        match = reaction_triggers.classify_mechanic(MECH[key])
        assert match.kind == "missed" and match.source_within_reach, key  # not ally_missed from the model overlay
    assert not reaction_triggers.classify_trigger("An ally within your reach is attacked").source_within_reach


def test_bulwark_needs_a_persistent_aegis_on_the_ally():
    match = reaction_triggers.classify_mechanic(MECH["tianxia.talent.protection.bulwark"])
    assert match.kind == "ally_attacked" and match.requires_mark == "Persistent Aegis" and match.mark_on == "subject"


def _ctx(engine, actor, target):
    action = next(iter(engine.action_catalog.values()))
    return typed_executor.Context(engine, actor, action, None, {"numbers": {"pb": 4, "save_dc": 15}}, [target], target, {})


def test_hammer_rebuke_applies_one_chosen_result():
    engine = _engine({"x": 1, "y": 1}, {"x": 2, "y": 1})
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    speed_before = [m for m in foe.modifiers.values() if m.target_field == "speed"]
    typed_executor.run_effects(_ctx(engine, me, foe), [{"type": "hammer_rebuke_choice"}])  # AI default: Disadvantage
    assert any(m.target_field == "attack_mode" and m.value == "DISADVANTAGE" for m in foe.modifiers.values())
    assert [m for m in foe.modifiers.values() if m.target_field == "speed"] == speed_before
    assert not any(c.condition_id == blacksmith_rebuke.NO_OPPORTUNITY for c in foe.conditions.values())
    typed_executor.run_effects(_ctx(engine, me, me), [{"type": "hammer_rebuke_pick", "choice": "no_oa"}])
    typed_executor.run_effects(_ctx(engine, me, foe), [{"type": "hammer_rebuke_choice"}])
    assert any(c.condition_id == blacksmith_rebuke.NO_OPPORTUNITY for c in foe.conditions.values())
    assert foe.reaction_available  # no opportunity attacks is not "no Reactions"


def test_hammer_rebukes_successful_save_only_spares_the_blacksmith():
    engine = _engine({"x": 1, "y": 1}, {"x": 2, "y": 1})
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    typed_executor.run_effects(_ctx(engine, me, foe), [{"type": "hammer_rebuke_no_oa", "against_you": True}])
    held = next(c for c in foe.conditions.values() if c.condition_id == blacksmith_rebuke.NO_OPPORTUNITY)
    assert held.data["against"] == ME
    hammer = MECH["tianxia.talent.blacksmith.hammer_rebuke"]["effects"][0]
    assert [e["type"] for e in hammer["on_fail"]] == ["hammer_rebuke_choice"] and hammer["on_success"][0]["against_you"]


def test_a_reaction_move_at_the_map_edge_does_not_step_off_it():
    """Fight audit 2026-09-29: Unbroken Pursuit 'could not run' -- a square at x=-1 failed validation."""
    engine = _engine({"x": 0, "y": 0}, {"x": 3, "y": 0})
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    typed_executor.run_effects(_ctx(engine, me, foe), [{"type": "reaction_move", "distance_ft": 15, "direction": "away"}])
    assert me.position.x >= 0 and me.position.y >= 0
    assert not any(e.event_type == "GM_RIDER" and "could not run" in str(e.payload) for e in engine.events)


def test_a_reaction_is_spent_before_anything_can_answer_it(monkeypatch):
    """Fight audit 2026-09-29: "a creature uses a reaction" answered Jia's Seal of Final Authority before her Reaction was
    marked spent, forcing a save that Nascent Soul answered with the same Reaction."""
    engine = _engine({"x": 1, "y": 1}, {"x": 2, "y": 1})
    me = engine.state.actors[ME]
    seen = []
    monkeypatch.setattr(typed_reactions, "on_creature_event", lambda engine_, actor, kind, **kw: seen.append((kind, actor.reaction_available)))
    me.reaction_available = True
    typed_reactions._open(engine, {"feature_id": "X", "block": "generic"}, me, (), "TEST")
    assert seen == [("reaction_used", False)]
    me.reaction_available = True
    typed_reactions._open(engine, {"feature_id": "Y", "block": "save_rescue", "reaction": False}, me, (), "TEST")
    assert me.reaction_available and len(seen) == 1  # a once-per-round rescue that is no Reaction


def test_nascent_soul_rescues_only_a_concentration_save():
    """Fight audit 2026-09-29: Independent Concentration answered any failed Constitution save."""
    blocks = json.loads((ROOT / "combat/rules/feature_blocks.json").read_text())["features"]
    assert blocks["tianxia.path.qi_cultivation.feature.nascent_soul"]["sources"] == ["system:combat.concentration"]
    engine = _engine({"x": 1, "y": 1}, {"x": 2, "y": 1})
    me = engine.state.actors[ME]
    row = {"feature_id": "NASCENT", "block": "save_rescue", "abilities": ["CON"], "resource_id": "resource:core.qi", "cost": 1,
           "bonus": 4, "reaction": True, "sources": ["system:combat.concentration"]}
    engine.typed_reaction_rows = {**(getattr(engine, "typed_reaction_rows", {}) or {}), ME: [row]}
    roll = engine.roller.d20(modifier=0, actor_id=ME, reason="TEST")
    low = roll.model_copy(update={"total": 12})
    assert typed_reactions.on_save(engine, me, "CON", 15, low, "action:someone.technique").total == 12
    me.reaction_available = True
    assert typed_reactions.on_save(engine, me, "CON", 15, low, "system:combat.concentration").total == 16


def test_an_attack_is_not_rolled_at_a_target_that_left_its_reach():
    """Fight audit 2026-09-29: after a push, a Cha's second attack (reach 10) was rolled at 15 feet."""
    from combat.gate2_runtime_models import ActionDefinition, EconomyKind

    engine = _engine({"x": 1, "y": 1}, {"x": 5, "y": 1})
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    strike = ActionDefinition(source_definition_id="action:test.strike", display_name="Strike", owner_id=ME, economy=EconomyKind.ACTION,
                              resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=10)
    ctx = typed_executor.Context(engine, me, strike, None, {"numbers": {"attack_bonus": 5}, "effects": []}, [foe], foe, {})
    typed_executor.run_effects(ctx, [{"type": "attack", "attack_kind": "melee", "count": 2, "on_hit": []}])
    assert not any(e.event_type == "ATTACK_ROLLED" for e in engine.events)
    assert any(e.event_type == "GM_RIDER" and "out of reach" in str(e.payload) for e in engine.events)
    foe.position = foe.position.model_copy(update={"x": 3})  # 10 feet: in reach
    typed_executor.run_effects(ctx, [{"type": "attack", "attack_kind": "melee", "count": 1, "on_hit": []}])
    assert any(e.event_type == "ATTACK_ROLLED" for e in engine.events)


def test_a_self_cast_allys_line_reaches_the_ally_not_the_caster():
    """Fight audit 2026-09-29 (Battle Cadence): "one ally within 15 feet gains +5 feet Speed" landed on the caster."""
    from combat.gate2_runtime_models import ActionDefinition, EconomyKind

    engine = _engine({"x": 1, "y": 1}, {"x": 9, "y": 1}, friend_at={"x": 3, "y": 1})
    me, friend = engine.state.actors[ME], engine.state.actors[FRIEND]
    cadence = ActionDefinition(source_definition_id="action:test.cadence", display_name="Cadence", owner_id=ME, economy=EconomyKind.BONUS_ACTION,
                               resolution_kind="TYPED", target_kind="SELF")
    ctx = typed_executor.Context(engine, me, cadence, None, {"numbers": {}, "effects": []}, [me], me, {})
    line = {"type": "speed", "applies_to": "ally", "flat": 5, "evidence": "one ally within 15 feet who can perceive your cadence gains +5 feet Speed"}
    assert typed_executor._default_subject(ctx, line, harmful=False) == [friend]
    far = {**line, "evidence": "one ally within 5 feet gains +5 feet Speed"}
    assert typed_executor._default_subject(ctx, far, harmful=False) == []
    assert typed_executor._default_subject(ctx, {**far, "evidence": "you or an ally within 5 feet gains +5 feet Speed"}, harmful=False) == [me]


def test_a_later_on_hit_bonus_does_not_aim_a_self_form_at_an_enemy():
    """Fight audit 2026-09-29: Obsidian Skin, Asura's Rage, Weapon Hymn ... needed an enemy within 5 feet to be used."""
    from combat.factory_compiler import _target_kind

    form = {"effects": [{"type": "ac_bonus", "applies_to": "self", "flat": 2},
                        {"type": "extra_damage", "applies_to": "target", "deferred": True, "evidence": "once per turn when you hit, add 1d6"}],
            "range": {"kind": "self"}, "area": None}
    assert _target_kind(form)[0] == "SELF"
