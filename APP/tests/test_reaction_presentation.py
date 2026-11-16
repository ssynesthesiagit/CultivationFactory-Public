"""Pure menu hints: no engine execution, dice, hidden actors or model server."""
from types import SimpleNamespace

import pytest

from combat.reaction_presentation import annotate_reactions


def context(source, *, moment="DAMAGE_APPLICATION", target="left", pending=17):
    return {"checkpoint": "TYPED:" + moment + "@8", "reactor_id": "left",
            "reaction_source_id": "reaction:typed." + source,
            "choice_trigger": {"target_id": target, "damage_amount": pending}}


def prompt(ctx):
    return {"context": ctx, "reaction": "A defense", "summary": "The printed effect.",
            "choice": {"options": [{"id": str(n)} for n in range(1, 5)]}}


@pytest.mark.parametrize("moment,pending", [("ATTACK_MISSED", None), ("DAMAGE_APPLICATION", 0)])
def test_no_damage_reductions_move_to_other_without_removal(moment, pending):
    ctx = context("soak", moment=moment, pending=pending)
    engine = SimpleNamespace(typed_reaction_rows={"left": [{"feature_id": "soak", "block": "damage_soak",
        "die": 10, "resource_id": "resource:stamina"}]})
    rows = annotate_reactions([prompt(ctx)], [ctx], engine)
    assert len(rows) == 1 and rows[0]["context"] is ctx
    assert rows[0]["useful_now"] is False
    assert rows[0]["menu_priority"] == 0
    assert rows[0]["expected_effect"] == "No damage to reduce for this trigger."


def test_unknown_effect_stays_relevant_and_another_targets_packet_is_not_borrowed():
    contexts = [context("flat", moment="ATTACK_HIT_BEFORE_DAMAGE", pending=None),
                context("unknown", target="other", pending=99)]
    engine = SimpleNamespace(typed_reaction_rows={"left": [{"feature_id": "flat", "block": "generic",
        "effects": [{"type": "damage_modifier", "flat": 7}]}]})
    result = annotate_reactions([prompt(ctx) for ctx in contexts], contexts, engine)
    assert "99" not in result[0]["expected_effect"]
    assert "this hit’s damage by 7" in result[0]["expected_effect"]
    assert result[1]["useful_now"] is True
    assert result[1]["expected_effect"] == "The printed effect."


def test_modes_use_their_own_effects_and_keep_additional_effects_relevant_on_a_miss():
    contexts = [context("ward:mode:3", moment="ATTACK_MISSED", pending=None),
                context("ward:mode:7", moment="ATTACK_MISSED", pending=None)]
    engine = SimpleNamespace(typed_reaction_rows={"left": [{"feature_id": "ward", "block": "generic",
        "reaction_modes": [{"index": 3, "effects": [{"type": "damage_modifier", "flat": 7}]},
                           {"index": 7, "effects": [{"type": "damage_modifier", "flat": 7},
                                                    {"type": "healing", "flat": 3}]}]}]})
    result = annotate_reactions([prompt(ctx) for ctx in contexts], contexts, engine)
    assert result[0]["useful_now"] is False
    assert result[1]["useful_now"] is True


@pytest.mark.parametrize("conditional", [{"half": True}, {"protected_if": {"bloodied": True}}, {"only_damage_types": ["fire"]}])
def test_unquantified_conditional_reductions_are_never_declared_useless(conditional):
    ctx = context("conditional")
    engine = SimpleNamespace(typed_reaction_rows={"left": [{"feature_id": "conditional", "block": "generic",
        "effects": [{"type": "damage_modifier", "flat": 0},
                    {"type": "damage_modifier", **conditional}]}]})
    result = annotate_reactions([prompt(ctx)], [ctx], engine)
    assert result[0]["useful_now"] is True


@pytest.mark.parametrize("damage_type,expected", [("rAdIaNt", 12), ("NECROTIC", 12), ("BLUDGEONING", 8), (None, 8)])
def test_damage_type_bonus_only_counts_when_known_to_match(damage_type, expected):
    ctx = context("ward")
    if damage_type:
        ctx["choice_trigger"]["damage_type"] = damage_type
    engine = SimpleNamespace(typed_reaction_rows={"left": [{"feature_id": "ward", "block": "generic",
        "effects": [{"type": "damage_modifier", "flat": 8},
                    {"type": "damage_modifier", "flat": 4, "only_damage_types": ["necrotic", "radiant"]}]}]})
    printed = "Reduce damage by 8; add 4 against Necrotic or Radiant damage."
    result = annotate_reactions([{**prompt(ctx), "summary": printed}], [ctx], engine)[0]
    assert result["expected_effect"] == f"Reduce 17 damage by {expected} (base average)."
    assert result["menu_priority"] == 2 * expected
    assert result["summary"] == printed
    assert result["useful_now"] is True


def test_type_restricted_only_reduction_stays_reachable_when_useless():
    ctx = context("ward")
    ctx["choice_trigger"]["damage_type"] = "BLUDGEONING"
    engine = SimpleNamespace(typed_reaction_rows={"left": [{"feature_id": "ward", "block": "generic",
        "effects": [{"type": "damage_modifier", "flat": 4, "only_damage_types": ["radiant"]}]}]})
    rows = annotate_reactions([prompt(ctx)], [ctx], engine)
    assert len(rows) == 1 and rows[0]["context"] is ctx
    assert rows[0]["useful_now"] is False and rows[0]["menu_priority"] == 0
    assert rows[0]["expected_effect"] == "Reduce 17 damage by 0 (base average)."
