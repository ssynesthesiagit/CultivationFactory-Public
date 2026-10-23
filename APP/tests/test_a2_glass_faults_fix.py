"""GLASSMMX: the four P1 Faultline blockers, proved at table level.

Each test drives the printed line through ``TabletopService`` and asserts a *committed* consequence after a cold
reload -- not a label, not a prompt, not "some condition exists":

  P1-1  a Spell-Line answer changes play: a saved creature really cannot take Reactions.
  P1-2  a fracture is the fractured creature's own condition and is paid by its own next attack roll.
  P1-3  Break the Proud Weapon's Successful Save reduces *the triggering blow*, by the printed Proficiency Bonus.
  P1-4  Flaw's damage answer rolls the printed 4d8 and takes it off the interrupted effect, bound to that effect.

Saving throws are forced through the engine's own ``_roll_save`` so each printed branch is the one under test.
"""
from tests.cw2_service_support import add_action as add, seal
from tests.worker2_support import ALLY, FOE, OWNER, candidate, reload, settle, turn
from tests.h1_support import script
from tests.test_auto2_glass import (BASES, FLAW, FRACTURED, PRIDE, REACTION_DENIED, SPELL_LINE, T, conditions,
                                    foe_turn, glass, marked, owner_setup)

TALENTS = [T + name for name in ("BREAK_THE_PROUD_WEAPON", "SPELL_LINE_CRACK", "FLAW_WITHIN_THE_GOLDEN_TECHNIQUE")]


def forced_save(monkeypatch, wanted):
    """Force chosen saving throws through the engine's own roll: ``{"WIS": 20}`` makes that save succeed, ``{"STR": 1}`` fail."""
    from combat.gate4_engine import Gate4ControllerEngine

    original = Gate4ControllerEngine._roll_save

    def roll_save(engine, actor, ability, dc, *args, **kwargs):
        die = wanted.get(str(ability).upper())
        if die is not None:
            script(engine, [die])
        return original(engine, actor, ability, dc, *args, **kwargs)

    monkeypatch.setattr(Gate4ControllerEngine, "_roll_save", roll_save)


def spent_pct(engine, who):
    actor = engine.state.actors[who]
    return actor.maximum_hp - actor.current_hp


# ------------------------------------------------------------------------------ P1-1: an offered outcome changes play
def test_spell_line_successful_save_actually_denies_reactions(tmp_path, monkeypatch):
    """The Successful Save's "cannot take Reactions" must be the engine's real no_reactions rule, not a label.

    Before the fix the condition carried a label alone: the creature could still take Reactions, so the fighter spent a
    mark and a Reaction for nothing.  ``typed_reactions._can_react`` is the gate every reaction in the engine passes, so
    it is the honest proof that the printed outcome changed play.
    """
    from combat import typed_reactions

    forced_save(monkeypatch, {"WIS": 20})
    combat, table, mid = glass(tmp_path, ["SPELL_LINE_CRACK"], ask=False)
    owner_setup(combat, table, mid)
    foe_turn(table, mid)
    settle(table, mid, candidate(combat, mid, "Foe Technique", target=OWNER).candidate_id,
           {"choice:needle.glass_spell_line": "use"})
    engine = reload(tmp_path, mid)
    held = conditions(engine, FOE, REACTION_DENIED)
    assert held, "a saved creature takes Spell-Line Crack's Successful Save"
    assert (held[0].data or {}).get("rule", {}).get("no_reactions") is True, \
        "the condition must carry the engine's no_reactions rule the executor reads"
    assert not typed_reactions._can_react(engine, engine.state.actors[FOE]), \
        "the printed outcome must actually cost the creature its Reactions"


# ------------------------------------------------------------------------------ P1-2: the fracture is the creature's own
def test_fracture_is_paid_by_the_fractured_creatures_own_attack(tmp_path, monkeypatch):
    """The fracture lands on the marked attacker and is answered by that creature's own next attack roll.

    Before the fix ``attack_mode`` read the *defender's* conditions, so an ally attacking the fractured enemy was
    penalised and consumed the condition while the fractured creature's own attacks were untouched.
    """
    forced_save(monkeypatch, {"STR": 1})   # a failed Strength save fractures the weapon or limb
    combat, table, mid = glass(tmp_path, ["BREAK_THE_PROUD_WEAPON"], ask=False)
    owner_setup(combat, table, mid, temper=False)
    foe_turn(table, mid)
    settle(table, mid, candidate(combat, mid, "Foe Blade", target=OWNER).candidate_id,
           {"choice:needle.glass_pride_weapon": "use"})
    engine = reload(tmp_path, mid)
    fractured = conditions(engine, FOE, FRACTURED)
    assert fractured, "the marked creature's weapon or limb is the thing that fractures"
    assert not conditions(engine, OWNER, FRACTURED), "the victim of the hit is not the fractured creature"
    assert (fractured[0].data or {}).get("weapon") or (fractured[0].data or {}).get("limb"), \
        "the fracture must record which weapon or limb it broke"
    # the mark is spent, so this next blow opens no new question; it must still pay the fracture it carries
    foe_turn(table, mid)
    settle(table, mid, candidate(combat, mid, "Foe Blade", target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    assert not conditions(engine, FOE, FRACTURED), \
        "the fractured creature's own next attack roll is the one that answers the fracture"


# ------------------------------------------------------------------------------ P1-3: the reduction hits this blow
def test_pride_successful_save_cuts_the_triggering_blow(tmp_path, monkeypatch):
    """The Successful Save reduces the damage of the hit that earned it, by exactly the printed Proficiency Bonus.

    Before the fix the question was asked from ``after_hit``, after that damage had already landed, so the blow was
    full damage and the reduction waited for some later packet.
    """
    from combat.ext import glass_faults

    forced_save(monkeypatch, {"STR": 20})   # a successful Strength save reduces the triggering damage
    combat, table, mid = glass(tmp_path, ["BREAK_THE_PROUD_WEAPON"], ask=False)
    owner_setup(combat, table, mid, temper=False)
    foe_turn(table, mid)
    settle(table, mid, candidate(combat, mid, "Foe Blade", target=OWNER).candidate_id,
           {"choice:needle.glass_pride_weapon": "use"})
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    pb = int((glass_faults.rows(engine, owner, "pride") or [{}])[0].get("pb") or 0)
    assert pb > 0, "the caster's printed Proficiency Bonus is what the Successful Save reduces by"
    assert spent_pct(engine, OWNER) == max(0, 3 - pb), \
        f"the printed blow deals 3 and this save must cut it by {pb}, on this hit"


# ------------------------------------------------------------------------------ P1-4: the printed dice, on the interrupted effect
def test_flaw_damage_answer_rolls_printed_dice_on_the_triggering_effect(tmp_path, monkeypatch):
    """Flaw's "reduce the triggering effect's damage against all targets by 4d8" rolls 4d8 and takes it off that effect.

    Before the fix the answer halved whatever positive packet arrived first, which is neither the printed amount nor
    the printed scope.
    """
    from tests.test_auto2_glass import BASES as GLASS_BASES, prepare as base_prepare
    from tests.worker2_support import fixture

    def prepare(bundles):
        base_prepare(bundles)
        # a heavy high-cost technique, so a 4d8 reduction is visible as damage rather than saturating at zero
        add(bundles[2], "Foe Heavy Technique", [{"type": "damage", "applies_to": "target", "flat": 20,
                                                 "damage_types": ["slashing"], "duration": "instant"}],
            typed={"costs": [["resource:core.cp", 1]]})
        for bundle in bundles:
            seal(bundle)

    forced_save(monkeypatch, {"WIS": 1})   # a failed Wisdom save reaches the Failed Save answers
    combat, table, mid = fixture(tmp_path, list(GLASS_BASES) + [T + "FLAW_WITHIN_THE_GOLDEN_TECHNIQUE"], cl=15,
                                 ask=False, bundle_transform=prepare, foe_position={"x": 4, "y": 5})
    owner_setup(combat, table, mid)
    foe_turn(table, mid)
    settle(table, mid, candidate(combat, mid, "Foe Heavy Technique", target=OWNER).candidate_id,
           {"choice:needle.glass_flaw": "use", "choice:needle.glass_flaw_outcome": "reduce"})
    engine = reload(tmp_path, mid)
    rolled = [r for r in engine.rolls if str(getattr(r, "reason", "") or "").startswith(f"DAMAGE_REDUCTION:{FLAW}")]
    assert rolled, "the printed 4d8 must be rolled as a real roll and recorded"
    amount = int(rolled[-1].total)
    assert 4 <= amount <= 32, f"4d8 is between 4 and 32, not {amount}"
    assert spent_pct(engine, OWNER) == max(0, 20 - amount), \
        "the interrupted effect must deal its printed 20 less the rolled 4d8"
    assert not engine.__dict__.get("_a2glass_crack"), "the answer must not outlive its own activation"


def test_flaw_damage_answer_reaches_every_target_of_one_area_effect(tmp_path, monkeypatch):
    """Flaw's "reduce the triggering effect's damage against all targets by 4d8" reduces every target's own packet.

    A single real area effect hits OWNER and ALLY in the same activation; both committed damage totals must be cut
    by the same rolled amount.  Before the GLASSMMXR fix the bound answer was consumed (removed) by whichever
    packet matched first, so only the first target in roll order was ever actually discounted -- a regression this
    test's two independent assertions would catch (one alone could pass by accident if the order happened to put
    the discounted target first).
    """
    from tests.test_a2_glass_r6_fix import _area_action
    from tests.test_auto2_glass import BASES as GLASS_BASES, prepare as base_prepare
    from tests.worker2_support import fixture

    def prepare(bundles):
        base_prepare(bundles)
        _area_action(bundles[2], "Foe Area Heavy Technique",
                     [{"type": "damage", "applies_to": "creatures_in_area", "flat": 20, "damage_types": ["slashing"],
                       "duration": "instant"}],
                     size_ft=10, typed={"costs": [["resource:core.cp", 1]]})
        for bundle in bundles:
            seal(bundle)

    forced_save(monkeypatch, {"WIS": 1})   # a failed Wisdom save reaches the Failed Save answers
    combat, table, mid = fixture(tmp_path, list(GLASS_BASES) + [T + "FLAW_WITHIN_THE_GOLDEN_TECHNIQUE"], cl=15,
                                 ask=False, bundle_transform=prepare, foe_position={"x": 4, "y": 5})
    owner_setup(combat, table, mid)
    foe_turn(table, mid)
    # OWNER (3,6) and ALLY (4,6) by fixture default: a 10-foot sphere aimed at OWNER's own cell reaches both.
    cand = candidate(combat, mid, "Foe Area Heavy Technique", at=(3, 6))
    settle(table, mid, cand.candidate_id, {"choice:needle.glass_flaw": "use", "choice:needle.glass_flaw_outcome": "reduce"})
    engine = reload(tmp_path, mid)
    rolled = [r for r in engine.rolls if str(getattr(r, "reason", "") or "").startswith(f"DAMAGE_REDUCTION:{FLAW}")]
    assert rolled, "the printed 4d8 must be rolled as a real roll and recorded"
    amount = int(rolled[-1].total)
    assert 4 <= amount <= 32, f"4d8 is between 4 and 32, not {amount}"
    expected = max(0, 20 - amount)
    assert spent_pct(engine, OWNER) == expected, f"OWNER's packet must be cut by the rolled {amount}, every target"
    assert spent_pct(engine, ALLY) == expected, f"ALLY's packet must also be cut by the same rolled {amount}, every target"
    assert not engine.__dict__.get("_a2glass_crack"), "the answer must not outlive its own activation"