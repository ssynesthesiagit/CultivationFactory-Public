"""Abilities combat runs nothing for stay off the AI's menu (owner 2026-09-26, step 11).

Talisman Recall compiles to a bare save with no result, and Qi Sensing to text only; the AI spent turns on them
(Talisman Recall x31 in one tournament). combat/factory_compiler.py marks such an action ``inert`` and
combat/gate4_context.build_decision_context(for_ai=True) leaves it out; a player's own menu keeps it.
"""

from pathlib import Path

from combat.factory_compiler import _does_something, compile_character
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_content import AN
from combat.gate4_context import build_decision_context
from combat.gate4_policy import PolicyLibrary

ROOT = Path(__file__).resolve().parents[1]
ACTOR = "actor:factory.inert_check"


def test_does_something_reads_through_deliveries_and_ignores_text():
    assert not _does_something([])
    assert not _does_something(["Qi Sensing is always active."])
    assert not _does_something([{"type": "save", "ability": "str", "on_fail": [], "on_success": []}])
    assert not _does_something([{"type": "zone", "evidence": "a 20-foot zone"}, {"type": "spend_resource", "flat": 1}])
    assert _does_something([{"type": "save", "on_fail": [{"type": "condition", "condition": "prone"}], "on_success": []}])
    assert _does_something([{"type": "attack", "on_hit": [{"type": "damage", "dice": {"count": 1, "sides": 6}}]}])
    assert _does_something([{"type": "temp_hp", "flat": 5}])
    # A later trigger counts only when combat registers it (a "when you hit" bonus, a resource or mark watch).
    assert _does_something([{"type": "extra_damage", "deferred": True, "evidence": "Once per turn when you hit a creature, deal 1d6 extra damage"}])
    assert not _does_something([{"type": "condition", "deferred": True, "evidence": "When it drops to 0 HP, it is frightened"}])


def _mechanic(key: str, name: str, effects: list) -> dict:
    return {"mechanic_id": key, "name": name, "sphere_id": "tianxia.sphere.test", "kind": "talent",
            "activation": {"economy": "bonus_action"}, "effects": effects, "riders": [],
            "range": {"kind": "feet", "feet": 60}, "area": None, "duration": {"kind": "instant"}, "cost": []}


AUTHORITY = {"mechanics": {
    "BARE_RECALL": _mechanic("BARE_RECALL", "Bare Recall", [{"type": "save", "ability": "str", "on_fail": [], "on_success": []}]),
    "REAL_BOLT": _mechanic("REAL_BOLT", "Real Bolt", [{"type": "save", "ability": "dex", "on_success": [],
                                                       "on_fail": [{"type": "damage", "dice": {"count": 2, "sides": 6}, "damage_types": ["fire"]}]}]),
}}
SHEET = {
    "identity": {"proficiency_bonus": 4, "cultivation_level": 10, "path": "Qi Cultivation"},
    "ability_scores_and_statistics": {
        "abilities": [{"ability": a, "score": 14, "modifier": 2} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
        "primary_resource": {"name": "Qi", "maximum": 20}, "armor_class": {"base_value": 14}, "hit_points": {"maximum": 60},
        "speed": {"walking_ft": 30}, "technique_save_dc": 15, "technique_attack_bonus": 7,
    },
    "spheres_and_talents": {"learned_talent_record_ids": ["BARE_RECALL", "REAL_BOLT"]},
}


def test_the_ai_menu_leaves_out_an_inert_ability_and_the_player_menu_keeps_it():
    bundle = compile_character(SHEET, actor_id=ACTOR, typed_authority=AUTHORITY)
    by_name = {row["display_name"]: row for row in bundle["action_catalog"]}
    assert by_name["Bare Recall"]["parameters"].get("inert") is True
    assert not by_name["Real Bolt"]["parameters"].get("inert")
    assert not any(row["parameters"].get("inert") for row in bundle["action_catalog"] if ".weapon." in row["source_definition_id"])

    engine = Gate2Engine(ROOT, match_seed="INERT-MENU", typed_bundles=(bundle,),
                         roster_setup={"primary_actor_ids": [ACTOR, AN], "team_by_actor": {ACTOR: "team:a", AN: "team:b"}})
    engine.state.current_actor_id = ACTOR
    policy, _ = PolicyLibrary(ROOT).for_actor(ACTOR)
    recall, bolt = by_name["Bare Recall"]["source_definition_id"], by_name["Real Bolt"]["source_definition_id"]
    player = {c.source_definition_id for c in build_decision_context(engine, policy).legal_candidates}
    ai = {c.source_definition_id for c in build_decision_context(engine, policy, for_ai=True).legal_candidates}
    assert {recall, bolt} <= player
    assert bolt in ai and recall not in ai
