"""Fixes for Astra's audit of the 2026-09-26 combat work (owner: "I'll have astra do an audit of the whole thing").

1. The compiler read reactions with the phrase classifier alone, while the reaction report
   (reaction_triggers.distribution) counts the normalized-trigger rewrites and "you or an ally": 10 reactions
   the rewrites make runnable were never compiled and 8 "you or an ally" ones covered only the reactor.
2. A choose-one option was aimed by the ability's shared effects: an attacking option of a menu whose shared part
   is empty compiled as an ally-only action.
3. "Remove Poisoned" (Purify the Pulse) and "end the Poisoned condition" were typed as applying the condition.
"""

import json
from pathlib import Path

from combat import typed_executor
from combat.factory_compiler import compile_character
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_content import AN
from combat.typed_executor import Context
from factory_authoring.typed_structure import removals_as_removals

ROOT = Path(__file__).resolve().parents[1]
ACTOR = "actor:factory.audit_fixes"
SHEET = {
    "identity": {"proficiency_bonus": 4, "cultivation_level": 10, "path": "Qi Cultivation"},
    "ability_scores_and_statistics": {
        "abilities": [{"ability": a, "score": 14, "modifier": 2} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
        "primary_resource": {"name": "Qi", "maximum": 20}, "armor_class": {"base_value": 14}, "hit_points": {"maximum": 60},
        "speed": {"walking_ft": 30}, "technique_save_dc": 15, "technique_attack_bonus": 7,
    },
}


def _sheet(ids):
    return {**SHEET, "spheres_and_talents": {"learned_talent_record_ids": list(ids)}}


def test_the_compiler_reads_reactions_as_the_report_counts_them():
    authority = json.loads((ROOT / "authority" / "Tianxia_Typed_Mechanics_Authority_R1.json").read_bytes())
    qi_mirror = "tianxia.subpath.qi.mirror_cultivator.feature.qi_mirror"  # runnable only through the rewrites
    bell = "TAL_METAL_BELL_METAL_COUNTER"  # "you or an ally"
    bundle = compile_character(_sheet([qi_mirror, bell]), actor_id=ACTOR, typed_authority=authority)
    rows = {row["feature_id"]: row for row in bundle["typed_reactions"]}
    assert qi_mirror in rows and rows[qi_mirror]["kind"] == "attacked"
    assert rows[bell]["kind"] == "ally_hit" and rows[bell]["includes_self"]


def test_each_option_is_aimed_by_its_own_effects():
    menu = {"mechanic_id": "MENU", "name": "Menu", "sphere_id": "tianxia.sphere.test", "kind": "talent",
            "activation": {"economy": "action"}, "effects": [], "riders": [], "range": {"kind": "feet", "feet": 30},
            "area": None, "duration": {"kind": "instant"}, "cost": [],
            "options": [{"label": "Strike", "effects": [{"type": "damage", "applies_to": "target", "dice": {"count": 2, "sides": 6}}]},
                        {"label": "Mend", "effects": [{"type": "healing", "applies_to": "target", "flat": 5}]}]}
    bundle = compile_character(_sheet(["MENU"]), actor_id=ACTOR, typed_authority={"mechanics": {"MENU": menu}})
    kinds = {row["display_name"]: row["target_kind"] for row in bundle["action_catalog"] if row["display_name"].startswith("Menu:")}
    assert kinds == {"Menu: Strike": "HOSTILE_ENTITY", "Menu: Mend": "ALLY_OR_SELF"}


def test_a_removed_condition_is_removed_not_applied():
    effects = [{"type": "condition", "condition": "poisoned", "applies_to": "target", "evidence": "Poisoned"},
               {"type": "condition", "condition": "restrained", "applies_to": "target", "evidence": "The target is Restrained"}]
    by_label = removals_as_removals(effects, "Remove Poisoned")
    assert [row["type"] for row in by_label] == ["remove_condition", "condition"]  # the label names only Poisoned
    by_text = removals_as_removals([{"type": "condition", "condition": "frightened", "evidence": "End the Frightened condition on the target"},
                                    {"type": "condition", "condition": "blinded", "evidence": "Blinded until the end of your next turn"}])
    assert [row["type"] for row in by_text] == ["remove_condition", "condition"]  # "until the end of" is not a removal

    bundle = compile_character(_sheet([]), actor_id=ACTOR, typed_authority={"mechanics": {}})
    engine = Gate2Engine(ROOT, match_seed="AUDIT-REMOVE", typed_bundles=(bundle,),
                         roster_setup={"primary_actor_ids": [ACTOR, AN], "team_by_actor": {ACTOR: "team:a", AN: "team:b"}})
    actor = engine.state.actors[ACTOR]
    action = next(iter(engine.action_catalog.values()))
    ctx = Context(engine, actor, action, None, {}, [actor], actor)
    typed_executor.block_condition(ctx, {"type": "condition", "condition": "poisoned", "applies_to": "self"})
    assert any(c.condition_id == "condition:typed.poisoned" for c in actor.conditions.values())
    typed_executor.block_remove_condition(ctx, {"type": "remove_condition", "condition": "poisoned", "applies_to": "self"})
    assert not any(c.condition_id == "condition:typed.poisoned" for c in actor.conditions.values())
