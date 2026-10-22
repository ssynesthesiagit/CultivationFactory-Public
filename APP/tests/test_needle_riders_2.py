"""Needle riders round 2 (NEEDLE1F2): regressions for the Object branch die and the Arm Strike limb.

Each test fails without its fix:

  The One Opening Beneath Heaven, Object branch  "If the attack form has no normal damage die, treat its normal
                                                  damage die as d1 when calculating this inheritance's additional
                                                  damage." (was d4)
  Arm Strike, limb scope                          the -2 lands only on attacks made with the limb Arm Strike recorded
                                                  when it landed; an attack with the target's other limb takes none.

Vacuum Slice (the shared-d20 attack seam) is not covered here: it is still a GM rider, see the review record.
"""

from types import SimpleNamespace

from combat.ext import needle as N
from combat.ext import needle_opening as O
from combat.gate2_runtime_models import DiceSpec


# ------------------------------------------------------------------------------------------------ Object branch die
def test_object_branch_without_a_damage_die_uses_d1():
    dice = O.object_damage_die({})
    assert (dice.count, dice.sides, dice.modifier) == (1, 1, 0)


def test_object_branch_keeps_the_attack_form_damage_die():
    dice = O.object_damage_die({"damage": {"count": 1, "sides": 8, "modifier": 2}})
    assert (dice.count, dice.sides, dice.modifier) == (1, 8, 2)
    assert isinstance(dice, DiceSpec)


def test_object_branch_extra_dice_match_the_attack_die_when_missing():
    # Eighteen rolls of the normal damage die: with no die the rolls are d1, so the extra damage is 18 (not 18d4).
    assert O.object_damage_die({}).sides == 1


# ------------------------------------------------------------------------------------------------ Arm Strike limb
def _actor(limb=None, shadow=False):
    conditions = {}
    if limb is not None:
        conditions["arm"] = SimpleNamespace(condition_id=N.PENALTY + "arm_strike", data={"limb": limb})
    if shadow:
        conditions["shadow"] = SimpleNamespace(condition_id=N.PENALTY + "shadow_strike", data={})
    return SimpleNamespace(conditions=conditions)


def _attack(weapon_limb=None, weapon=True):
    typed = {"weapon": {"damage": {"count": 1, "sides": 8, "modifier": 0}, **({"limb": weapon_limb} if weapon_limb else {})}} if weapon else {}
    return SimpleNamespace(typed=typed)


def test_arm_strike_penalises_an_attack_made_with_the_recorded_limb():
    assert N._attack_penalty(_attack(weapon_limb="primary"), _actor(limb="primary")) == -2


def test_arm_strike_penalises_an_attack_with_no_named_limb_when_the_primary_was_struck():
    assert N._attack_penalty(_attack(), _actor(limb="primary")) == -2


def test_arm_strike_spares_an_attack_made_with_the_other_limb():
    assert N._attack_penalty(_attack(weapon_limb="secondary"), _actor(limb="primary")) is None


def test_arm_strike_on_the_secondary_limb_penalises_only_that_limb():
    assert N._attack_penalty(_attack(weapon_limb="secondary"), _actor(limb="secondary")) == -2
    assert N._attack_penalty(_attack(), _actor(limb="secondary")) is None


def test_arm_strike_keeps_its_penalty_separate_from_shadow_strike():
    assert N._attack_penalty(_attack(weapon_limb="secondary"), _actor(limb="primary", shadow=True)) == -2
