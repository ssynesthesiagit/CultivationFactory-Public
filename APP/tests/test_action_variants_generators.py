"""VARIANTS26: generator families that emit real variants of one action carry structured identity.

Each migrated generator keeps its action id, effects and costs; the variant names only the choice that
was made and its signed cost delta. No renderer or client parses display names.
"""
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat.ext import karma_riders, kensei, kukishin

STAMINA = "resource:core.stamina"
QI = "resource:core.qi"


def _action(sid, name, costs=(), typed=None, economy=EconomyKind.ACTION, target="HOSTILE_ENTITY"):
    return ActionDefinition(source_definition_id=sid, display_name=name, owner_id="owner", economy=economy,
                            resolution_kind="TYPED", target_kind=target, costs=tuple(costs),
                            parameters={"typed": typed or {"effects": [], "numbers": {}, "riders": [], "source": sid}})


def test_kukishin_empty_world_is_one_cost_variant_of_hollow_step():
    base = _action(kukishin.PREFIX + kukishin.HOLLOW_STEP, "Hollow Step", ((STAMINA, 1), (QI, 1)), target="SELF")
    info = {"owned_ids": [kukishin.PREFIX + "hollow_immortal"], "actions": [base]}
    (made,) = kukishin.empty_world_step(info)
    assert made.source_definition_id == base.source_definition_id + "#empty_world"
    assert made.costs == ((QI, 1),)
    assert made.variant.base_key == base.source_definition_id
    assert made.variant.base_label == "Hollow Step"
    (choice,) = made.variant.choices
    assert (choice.axis, choice.key) == ("cost", "empty_world")
    assert choice.costs == ((STAMINA, -1),)


def test_kensei_dexterity_fist_is_an_ability_variant_with_no_cost_delta():
    typed = {"effects": [], "numbers": {"attack_bonus": 5}, "riders": [], "source": "x",
             "weapon": {"ability_modifier": 2, "damage": {"modifier": 2}}}
    base = _action(kensei.PREFIX + "natural.fist", "Unarmed Strike (Iron Fist)", (), typed=typed, target="HOSTILE_ENTITY")
    (made,) = kensei._dexterity_fist({"mods": {"DEX": 4}, "actions": [base]})
    assert made.display_name == "Unarmed Strike (Iron Fist) (Dexterity)"
    assert made.variant.base_key == base.source_definition_id
    assert [(c.axis, c.key, c.costs) for c in made.variant.choices] == [("ability", "dexterity", ())]


def test_karma_burden_ally_variant_changes_target_only():
    base = _action("action:typed.k.burden", "Burden of Deeds", ((QI, 1),),
                   typed={"effects": [], "numbers": {}, "riders": [], "source": karma_riders.BURDEN_ID})
    (made,) = karma_riders.burden_marked_allies({"actions": [base]})
    assert made.target_kind == "ALLY_OR_SELF"
    assert made.costs == base.costs
    assert made.variant.base_key == base.source_definition_id
    assert [(c.axis, c.key) for c in made.variant.choices] == [("target", "ally_or_self")]
