"""Sphere, Path and Foundation resources are generated, placed and tracked (owner 2026-09-26: "we need the
different resources to be generated and placed on characters, like does yin work?").

Combat tracked only Qi, Resonance, Stamina, Martial Focus and each Foundation's pool; Devoured Essence, Edge
Momentum and the rest were rules text, costs in them were dropped (the ability ran free), and marks typed as
resources were never placed. tools/type_resources.py names each owner's resources; the builder records them;
the compiler gives a character a combat resource for each pool of a Sphere/Foundation/Path it has; own-act
triggers (typed_reactions.on_own_event) run the generators.
"""

from pathlib import Path

from combat import typed_executor, typed_reactions
from combat.factory_compiler import compile_character
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_content import AN
from combat.typed_executor import Context
from factory_authoring.typed_structure import resources_as_marks

ROOT = Path(__file__).resolve().parents[1]
ESSENCE = "resource:named.devoured_essence"


def _mechanic(key, name, economy, effects, *, trigger=None, cost=None):
    return {"mechanic_id": key, "name": name, "sphere_id": "tianxia.sphere.daemonic", "kind": "talent",
            "activation": {"economy": economy, "trigger": trigger}, "effects": effects, "riders": [],
            "range": {"kind": "feet", "feet": 60}, "area": None, "duration": {"kind": "minutes", "amount": 1}, "cost": cost or []}


AUTHORITY = {
    "sphere_names": {"tianxia.sphere.daemonic": "Daemonic Cultivation"},
    "resources": {
        "devoured essence": {"name": "Devoured Essence", "kind": "pool", "max": 5, "start": 0, "owners": ["Sphere: Daemonic Cultivation"]},
        "edge momentum": {"name": "Edge Momentum", "kind": "pool", "max": "pb", "start": 0, "owners": ["Sphere: Blades"]},
    },
    "mechanics": {
        # A generator: free, own hit, once per round.
        "HUNGER": _mechanic("HUNGER", "Hunger", "no_action",
                            [{"type": "gain_resource", "applies_to": "self", "flat": 1, "evidence": "gain 1 Devoured Essence"}],
                            trigger="Once per round, after you hit a hostile creature"),
        # A cost in the named pool is paid, not dropped.
        "FEAST": _mechanic("FEAST", "Feast", "bonus_action", [{"type": "temp_hp", "applies_to": "self", "flat": 5, "evidence": "gain 5 temporary HP"}],
                           cost=[[{"resource": "text", "text": "Spend 2 Devoured Essence"}]]),
        # A later gain: "when it drops to 0 HP, gain 1 Devoured Essence" (Demon Mark).
        "MARK": _mechanic("MARK", "Demon Mark", "bonus_action",
                          [{"type": "gain_resource", "applies_to": "self", "flat": 1, "deferred": True,
                            "evidence": "when it drops to 0 HP, gain 1 Devoured Essence"}]),
    },
}
ACTOR = "actor:factory.named_resources"
SHEET = {
    "identity": {"proficiency_bonus": 4, "cultivation_level": 10, "path": "Qi Cultivation"},
    "ability_scores_and_statistics": {
        "abilities": [{"ability": a, "score": 14, "modifier": 2} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
        "primary_resource": {"name": "Qi", "maximum": 20}, "armor_class": {"base_value": 14}, "hit_points": {"maximum": 60},
        "speed": {"walking_ft": 30}, "technique_save_dc": 15, "technique_attack_bonus": 7,
    },
    "spheres_and_talents": {"learned_talent_record_ids": ["HUNGER", "FEAST", "MARK"]},
}


def _engine():
    bundle = compile_character(SHEET, actor_id=ACTOR, typed_authority=AUTHORITY)
    engine = Gate2Engine(ROOT, match_seed="NAMED-RESOURCES", typed_bundles=(bundle,),
                         roster_setup={"primary_actor_ids": [ACTOR, AN], "team_by_actor": {ACTOR: "team:a", AN: "team:b"}})
    return bundle, engine


def test_a_characters_named_pool_is_a_combat_resource_and_its_cost_is_paid():
    bundle, _engine_ = _engine()
    resources = {row["resource_id"]: row for row in bundle["actor_template"]["resources"]}
    assert resources[ESSENCE]["maximum"] == 5 and resources[ESSENCE]["initial"] == 0
    assert "resource:named.edge_momentum" not in resources  # a Blades pool: this character has no Blades talent
    feast = next(row for row in bundle["action_catalog"] if row["display_name"] == "Feast")
    assert [ESSENCE, 2] in [list(cost) for cost in feast["costs"]]


def test_a_generator_fires_on_your_own_hit_once_per_round():
    _bundle, engine = _engine()
    actor, foe = engine.state.actors[ACTOR], engine.state.actors[AN]
    typed_reactions.on_own_event(engine, actor, foe, "own_hit", ranged=False)
    typed_reactions.on_own_event(engine, actor, foe, "own_hit", ranged=False)
    assert actor.resources[ESSENCE] == 1  # once per round
    assert actor.reaction_available  # a free generator never spends the Reaction


def test_a_later_gain_fires_when_that_target_drops():
    bundle, engine = _engine()
    actor, foe = engine.state.actors[ACTOR], engine.state.actors[AN]
    action = engine.action_catalog[next(row["source_definition_id"] for row in bundle["action_catalog"] if row["display_name"] == "Demon Mark")]
    typed = action.parameters["typed"]
    typed_executor.run_effects(Context(engine, actor, action, None, typed, [foe], foe), typed["effects"])
    assert actor.resources[ESSENCE] == 0 and any(m.target_field == "typed_watch" for m in actor.modifiers.values())
    # Brought down by real damage (Astra's audit: the watch fires whoever lands the blow), with a second enemy so
    # the fight goes on (after the last enemy falls nothing more runs).
    second = foe.model_copy(deep=True, update={"entity_id": "actor:second_foe", "modifiers": {}, "conditions": {}})
    engine.state.actors[second.entity_id] = second
    typed_executor.block_damage(Context(engine, actor, action, None, typed, [foe], foe), {"type": "damage", "flat": 500, "damage_types": ["force"]})
    assert not foe.active and actor.resources[ESSENCE] == 1
    assert not any(m.target_field == "typed_watch" for m in actor.modifiers.values())  # used up


def test_marks_typed_as_resources_are_placed():
    """"The target gains 1 Dose Mark" is a mark on the target; "you gain 1 Thunder Charge" is your own pool, and
    the mark "Charge" is not the pool "Charge Momentum"."""
    effects = [{"type": "gain_resource", "applies_to": "self", "flat": 1, "evidence": "The target gains 1 Dose Mark"},
               {"type": "gain_resource", "applies_to": "self", "flat": 1, "evidence": "gain 1 Thunder Charge"},
               {"type": "gain_resource", "applies_to": "self", "flat": 1, "evidence": "Gain 1 Charge Momentum after you move toward a creature"},
               {"type": "spend_resource", "applies_to": "self", "flat": 2, "evidence": "You spend 2 Dose Marks on the target"}]
    out = resources_as_marks(effects, ["Dose Mark", "Charge"], ["Charge Momentum"])
    assert [(row["type"], row.get("mark")) for row in out] == [("mark", "Dose Mark"), ("gain_resource", None), ("gain_resource", None),
                                                               ("spend_mark", "Dose Mark")]
    assert out[0]["applies_to"] == "target"


def _yin_yang_engine():
    """A CL10 character with the Yin and Yang base abilities from the real authority (split records)."""
    import json

    authority = json.loads((ROOT / "authority" / "Tianxia_Typed_Mechanics_Authority_R1.json").read_bytes())
    mechanics = authority["mechanics"]
    base = [key for key in ("TAL_YIN_BASE_SPHERE_ABILITIES", "TAL_YIN_MARKING_A_CREATURE", "TAL_YIN_SPENDING_A_WANING_MARK",
                            "TAL_YANG_APPLYING_A_RISING_MARK", "TAL_YANG_KINDLED_RESPONSES", "TAL_YANG_OVERKINDLED_RESPONSES") if key in mechanics]
    sheet = {**SHEET, "spheres_and_talents": {"learned_talent_record_ids": [], "automatic_sphere_component_record_ids": base}}
    bundle = compile_character(sheet, actor_id=ACTOR)
    engine = Gate2Engine(ROOT, match_seed="YIN-YANG", typed_bundles=(bundle,),
                         roster_setup={"primary_actor_ids": [ACTOR, AN], "team_by_actor": {ACTOR: "team:a", AN: "team:b"}})
    return bundle, engine


def _use(engine, bundle, name, target):
    action = engine.action_catalog[next(row["source_definition_id"] for row in bundle["action_catalog"] if row["display_name"] == name)]
    typed = action.parameters["typed"]
    actor = engine.state.actors[ACTOR]
    typed_executor.run_effects(Context(engine, actor, action, None, typed, [target], target), typed["effects"])


def test_yin_places_waning_marks_and_spends_one_to_diminish_force():
    """Owner 2026-09-26: "like does yin work?" -- Mark the Waning marks; the marked creature's damage is reduced
    by Diminish Force (1d6..4d6 by CL + key modifier), which spends the mark, once per round, no Reaction."""
    from combat.typed_executor import bears_mark

    bundle, engine = _yin_yang_engine()
    names = {row["display_name"] for row in bundle["action_catalog"]}
    assert {"Mark the Waning", "Withdrawing Thread", "Kindle the Rising", "Rising Thread"} <= names
    actor, foe = engine.state.actors[ACTOR], engine.state.actors[AN]
    _use(engine, bundle, "Mark the Waning", foe)
    assert bears_mark(foe, ACTOR, "Waning Mark")
    left = typed_reactions.on_damage(engine, actor, 30, 0, source_actor_id=AN)
    assert left < 30 and not bears_mark(foe, ACTOR, "Waning Mark") and actor.reaction_available
    assert typed_reactions.on_damage(engine, actor, 30, 0, source_actor_id=AN) == 30  # the mark is spent


def test_yang_kindled_mark_completes_your_force_and_overkindled_mark_overheats_an_attacker():
    from combat.typed_executor import bears_mark

    bundle, engine = _yin_yang_engine()
    actor, foe = engine.state.actors[ACTOR], engine.state.actors[AN]
    _use(engine, bundle, "Kindle the Rising", actor)
    assert bears_mark(actor, ACTOR, "Kindled Mark")
    hp = foe.current_hp
    typed_reactions.on_own_event(engine, actor, foe, "own_hit", ranged=False)
    assert foe.current_hp < hp and not bears_mark(actor, ACTOR, "Kindled Mark")  # Complete Force: extra damage, mark spent
    # Overheat Force shares the once-per-round spend, so it waits for the next round.
    engine.state.round_number += 1
    typed_executor.block_mark(Context(engine, actor, engine.action_catalog[next(iter(engine.action_catalog))], None, {}, [foe], foe),
                              {"type": "mark", "mark": "Overkindled Mark", "applies_to": "target"})
    hp = foe.current_hp
    typed_reactions.on_attacked(engine, foe, actor, {"attack_bonus": 5, "range_ft": None}, None)
    assert foe.current_hp == hp and bears_mark(foe, ACTOR, "Overkindled Mark")  # not before the attack roll (Astra's audit)
    typed_reactions.on_attack_resolved(engine, foe, actor, {"attack_bonus": 5, "range_ft": None}, None)
    assert foe.current_hp < hp and not bears_mark(foe, ACTOR, "Overkindled Mark")  # after the attack resolves


def test_a_mark_on_a_token_reads_as_its_name():
    """A mark's condition id ends in its owner's id; the table showed "96d51dc3 A04c ..." (owner 2026-09-26)."""
    from combat.presentation import _condition_label

    assert _condition_label("condition:typed.mark.waning_mark.actor:factory.96d51dc3-a04c-424c-8c41-a52dcdcebff8") == "Waning Mark"
    assert _condition_label("condition:typed.prone") == "Prone"
