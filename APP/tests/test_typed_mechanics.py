"""Typed combat mechanics: the parser's reads and the text-fingerprint rules for model typing."""

from factory_authoring.typed_mechanics import type_mechanic
from factory_authoring.typed_mechanics_merge import merge

PALM = """#### Mountain-Moving Palm
Prerequisite: CL 15+
Action Type: Action
Area: 60-foot cone
Cost: Expend Martial Focus
Use Limit: Once per long rest
Release a palm strike of overwhelming physical pressure.
Creatures and unattended objects inside make Strength saving throws.
Failed Save:
take 8d8 Force damage;
move 30 feet away from you;
fall Prone.
Successful Save:
take half damage;
move 10 feet away;
remain standing.
Temporary Barriers take double damage."""


def test_parser_types_the_save_core_and_keeps_riders():
    mechanic = type_mechanic("X", "Mountain-Moving Palm", PALM, kind="talent", sphere_id="s", source={"text_sha256": "h"})
    assert mechanic["activation"]["economy"] == "action" and mechanic["use_limit"] == "once_per_long_rest"
    assert mechanic["cost"] == [[{"resource": "martial_focus", "amount": 1}]]
    assert mechanic["area"] == {"shape": "cone", "size_ft": 60, "centered_on_self": False}
    save = mechanic["effects"][0]
    assert save["type"] == "save" and save["ability"] == "str"
    assert [effect["type"] for effect in save["on_fail"]] == ["damage", "forced_movement", "condition"]
    assert save["on_fail"][0]["dice"]["count"] == 8 and save["on_fail"][0]["damage_types"] == ["force"]
    assert save["on_success"][0]["type"] == "half_damage"
    assert mechanic["riders"] == ["Temporary Barriers take double damage."]
    assert mechanic["coverage"] == "CORE_WITH_RIDERS"


def test_model_typing_counts_only_for_the_text_it_read():
    base = type_mechanic("X", "Brutal Strike", "When making Batter, take: -5 to the attack roll.", kind="talent",
                         sphere_id="s", source={"text_sha256": "current"})
    proposal = {"accepted": [{"type": "attack_modifier", "flat": -5, "evidence": "-5"}], "still_untyped": [],
                "economy": "passive", "trigger": "When making Batter", "modifies": "Batter"}
    merged = merge(base, proposal, None, stale=False)
    assert merged["typing_status"] == "model_unchecked" and merged["activation"]["modifies"] == "Batter"
    assert merged["coverage"] == "FULL" and merged["effects"][-1]["origin"] == "model"
    # The talent was edited after the model read it: its proposal no longer applies.
    assert merge(base, None, None, stale=True)["typing_status"] == "stale_model"
    reviewed = merge(base, proposal, {"effects": [{"type": "attack_modifier", "flat": -5, "evidence": "-5"}], "riders": []}, stale=False)
    assert reviewed["typing_status"] == "checked" and reviewed["effects"][-1]["origin"] == "reviewed"
