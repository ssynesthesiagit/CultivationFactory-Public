"""Reaction limits honour the printed trigger (owner 2026-09-26, "make sure the mechanics aren't
damaged"): a reaction must not fire in a situation its trigger excludes. combat/reaction_triggers.py
parses a checkable limit -- save_abilities, damage_types, conditions, requires_resource -- out of the
ORIGINAL printed trigger alongside its kind; combat/factory_compiler.py resolves requires_resource to
a real resource id per character (or refuses to compile the row); combat/typed_reactions.py's hooks
enforce all four at runtime. Built like tests/test_generic_reactions.py and tests/test_reaction_hooks.py.
"""

from pathlib import Path

from combat import typed_reactions
from combat.factory_compiler import compile_character
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_content import AN
from combat.reaction_triggers import classify_trigger

ROOT = Path(__file__).resolve().parents[1]


def _mechanic(key: str, name: str, effects: list, *, trigger: str) -> dict:
    return {"mechanic_id": key, "name": name, "sphere_id": "tianxia.sphere.test", "kind": "talent",
            "activation": {"economy": "reaction", "trigger": trigger}, "effects": effects, "riders": [],
            "range": None, "area": None, "duration": {"kind": "instant"}, "cost": []}


AUTHORITY = {"mechanics": {
    "SAVE_GUARD": _mechanic(
        "SAVE_GUARD", "Save Guard",
        [{"type": "attack_modifier", "applies_to": "self", "flat": 4, "on": "the saving throw",
          "evidence": "Add 4 to the saving throw."}],
        trigger="You fail an Intelligence, Wisdom, or Charisma saving throw."),
    "FIRE_WARD": _mechanic(
        "FIRE_WARD", "Fire Ward",
        [{"type": "damage_modifier", "applies_to": "self", "flat": 10, "evidence": "reduce the damage by 10"}],
        trigger="You take Fire damage."),
    "CONDITION_WARD": _mechanic(
        "CONDITION_WARD", "Grapple Ward",
        [{"type": "prevent_condition"}],
        trigger="You gain the Grappled condition."),
    "RESOURCE_GUARD": _mechanic(
        "RESOURCE_GUARD", "Reed Guard",
        [{"type": "damage_modifier", "applies_to": "self", "flat": 10, "evidence": "reduce the damage by 10"}],
        trigger="When you take damage and already have Reed Flex."),
    "UNRESOLVED_GUARD": _mechanic(
        "UNRESOLVED_GUARD", "Unresolved Guard",
        [{"type": "ac_bonus", "amount": 2}],
        trigger="A creature misses you with a melee attack while Body Lightening is active"),
}}
REACTOR = "actor:factory.limits_reactor"
REACTOR_SHEET = {
    "identity": {"proficiency_bonus": 4, "cultivation_level": 10, "path": "Qi Cultivation"},
    "ability_scores_and_statistics": {
        "abilities": [{"ability": a, "score": 14, "modifier": 2} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
        "primary_resource": {"name": "Qi", "maximum": 20}, "armor_class": {"base_value": 14}, "hit_points": {"maximum": 60},
        "speed": {"walking_ft": 30}, "technique_save_dc": 15, "technique_attack_bonus": 7,
    },
    "spheres_and_talents": {"learned_talent_record_ids": [
        "SAVE_GUARD", "FIRE_WARD", "CONDITION_WARD", "RESOURCE_GUARD", "UNRESOLVED_GUARD"]},
    "foundation": {
        "foundation_id": "weak_reed_tendons_v0_2B", "stage": "Awakened",
        "resource": {"name": "Reed Flex", "resource_id": "foundation.resource.weak_reed_tendons_v0_2B",
                     "current": 0, "initial_current": 0, "maximum": 1},
    },
}
REED_FLEX = "resource:foundation.reed_flex"


# ------------------------------------------------------------------ classifier: parsed limits
def test_classifier_parses_save_abilities_damage_types_conditions_and_resource():
    match = classify_trigger("You fail an Intelligence, Wisdom, or Charisma saving throw.")
    assert match.kind == "save" and match.save_abilities == frozenset({"INT", "WIS", "CHA"})

    match = classify_trigger("You fail the selected saving throw")  # no named ability: unrestricted
    assert match.kind == "save" and match.save_abilities == frozenset()

    match = classify_trigger("You take Fire damage.")
    assert match.kind == "damaged" and match.damage_types == frozenset({"FIRE"})

    match = classify_trigger("You gain Grappled, Prone, or Restrained, or become the target of an Opportunity Attack")
    assert match.kind == "condition_gained" and match.conditions == frozenset({"grappled", "prone", "restrained"})

    match = classify_trigger("When you take damage and already have Reed Flex.")
    assert match.kind == "damaged" and match.requires_resource == "Reed Flex"


# ------------------------------------------------------------------ compiler: resource resolution
def test_compiler_resolves_a_held_resource_to_the_characters_own_foundation_resource():
    bundle = compile_character(REACTOR_SHEET, actor_id="actor:factory.limits_compile", typed_authority=AUTHORITY)
    reactions = {row["feature_id"]: row for row in bundle["typed_reactions"] if row.get("block") == "generic"}
    assert reactions["RESOURCE_GUARD"]["requires_resource"] == REED_FLEX
    assert reactions["SAVE_GUARD"]["save_abilities"] == ["CHA", "INT", "WIS"]
    assert reactions["FIRE_WARD"]["damage_types"] == ["FIRE"]
    assert reactions["CONDITION_WARD"]["conditions"] == ["grappled"]


def test_compiler_refuses_a_reaction_naming_a_resource_the_character_does_not_hold():
    # "Body Lightening" is a stance word, not a resource on this character's sheet: not compiled,
    # reported instead of silently firing unrestricted (owner 2026-09-26).
    bundle = compile_character(REACTOR_SHEET, actor_id="actor:factory.limits_unresolved", typed_authority=AUTHORITY)
    assert "Unresolved Guard" in bundle["diagnostics"]["skipped"]["reaction"]
    assert any("Unresolved Guard" in note and "Body Lightening" in note for note in bundle["diagnostics"]["notes"])
    reactions = {row["feature_id"] for row in bundle["typed_reactions"] if row.get("block") == "generic"}
    assert "UNRESOLVED_GUARD" not in reactions


# ------------------------------------------------------------------ engine hooks
def _engine() -> Gate2Engine:
    bundle = compile_character(REACTOR_SHEET, actor_id=REACTOR, typed_authority=AUTHORITY)
    return Gate2Engine(ROOT, match_seed="REACTION-LIMITS-ENGINE", typed_bundles=(bundle,),
                       roster_setup={"primary_actor_ids": [REACTOR, AN], "team_by_actor": {REACTOR: "team:a", AN: "team:b"}})


def test_a_save_ability_limited_reaction_ignores_a_dex_save_and_fires_on_a_wis_save():
    engine = _engine()
    reactor = engine.state.actors[REACTOR]
    reactor.reaction_available = True
    roll = engine.roller.d20(modifier=0, actor_id=REACTOR, reason="TEST_SAVE")
    roll = roll.model_copy(update={"total": 10})  # DC 13, fails by 3; Save Guard's +4 would cover it
    result = typed_reactions.on_save(engine, reactor, "DEX", 13, roll, "action:test.save")
    assert result.total == 10 and reactor.reaction_available  # DEX is not INT/WIS/CHA: never offered

    engine = _engine()
    reactor = engine.state.actors[REACTOR]
    reactor.reaction_available = True
    roll = engine.roller.d20(modifier=0, actor_id=REACTOR, reason="TEST_SAVE")
    roll = roll.model_copy(update={"total": 10})
    result = typed_reactions.on_save(engine, reactor, "WIS", 13, roll, "action:test.save")
    assert result.total == 14 and not reactor.reaction_available  # WIS is named: fires and rescues


def test_a_fire_only_reaction_fires_on_fire_and_not_on_slashing_or_unknown_damage():
    # Unknown type (no typed_executor call stashed one on the engine, e.g. an engine-internal source):
    # a type-limited row must not fire rather than risk firing on the wrong type.
    engine = _engine()
    reactor = engine.state.actors[REACTOR]
    reactor.reaction_available = True
    reduced = typed_reactions.on_damage(engine, reactor, 20, 0, source_definition_id="action:test.attack", source_actor_id=AN)
    assert reduced == 20 and reactor.reaction_available

    engine = _engine()
    reactor = engine.state.actors[REACTOR]
    reactor.reaction_available = True
    engine._typed_pending_damage_type = "SLASHING"
    reduced = typed_reactions.on_damage(engine, reactor, 20, 0, source_definition_id="action:test.attack", source_actor_id=AN)
    assert reduced == 20 and reactor.reaction_available  # named type is Fire, not Slashing

    engine = _engine()
    reactor = engine.state.actors[REACTOR]
    reactor.reaction_available = True
    engine._typed_pending_damage_type = "FIRE"
    reduced = typed_reactions.on_damage(engine, reactor, 20, 0, source_definition_id="action:test.attack", source_actor_id=AN)
    assert reduced == 10 and not reactor.reaction_available  # Fire Ward: flat 10 reduction


def test_a_while_you_have_x_reaction_fires_only_when_x_is_held():
    engine = _engine()
    reactor = engine.state.actors[REACTOR]
    reactor.reaction_available = True
    reactor.resources[REED_FLEX] = 0
    reduced = typed_reactions.on_damage(engine, reactor, 20, 0, source_definition_id="action:test.attack", source_actor_id=AN)
    assert reduced == 20 and reactor.reaction_available  # 0 Reed Flex: Reed Guard never offered

    reactor.resources[REED_FLEX] = 1
    reduced = typed_reactions.on_damage(engine, reactor, 20, 0, source_definition_id="action:test.attack", source_actor_id=AN)
    assert reduced == 10 and not reactor.reaction_available  # >=1 Reed Flex: Reed Guard fires


def test_a_condition_gained_reaction_for_grappled_ignores_prone():
    engine = _engine()
    reactor, actor = engine.state.actors[REACTOR], engine.state.actors[AN]
    reactor.reaction_available = True
    prevented = typed_reactions.offer_condition_gained(engine, reactor, actor, "prone")
    assert prevented is False and reactor.reaction_available  # Grapple Ward only answers Grappled

    prevented = typed_reactions.offer_condition_gained(engine, reactor, actor, "grappled")
    assert prevented is True and not reactor.reaction_available


def test_one_reaction_per_round_is_still_respected_with_a_limited_row():
    engine = _engine()
    reactor = engine.state.actors[REACTOR]
    reactor.reaction_available = True
    engine._typed_pending_damage_type = "FIRE"
    typed_reactions.on_damage(engine, reactor, 20, 0, source_definition_id="action:test.attack", source_actor_id=AN)
    assert not reactor.reaction_available  # Fire Ward spent the round's only Reaction
    reduced = typed_reactions.on_damage(engine, reactor, 20, 0, source_definition_id="action:test.attack", source_actor_id=AN)
    assert reduced == 20  # no reaction left this round, even though the type still matches
