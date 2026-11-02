"""Regressions for the three LUNA74r2 findings on the generic ``replace_*`` presentation hook.

1. A *paid* replacement must print its real resource cost. ``ActionDefinition.costs`` is a tuple
   of ``(resource_id, amount)`` pairs and the table passes the serialized list, so reading a cost
   as if it were an object made every charge print as "0".
2. A rider that only lands on every hit -- a Mark, a check penalty -- is utility, not damage. It
   must not inflate ``expected_damage``, which the controller also uses as its enemy-HP finishing
   threshold.
3. A ``replace_healing`` variant removes ordinary healing. No failed save ever granted it, so
   the button must not offer a "failed save" explanation for it.

These are the levels the bugs showed: the real button description the table serves, and the real
controller score the AI chooses from.
"""
import importlib.util
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "review_sw_monkey", APP / "tests/test_review_sw-monkey_style.py")
_SW = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SW)

from tests.test_auto_support import ME  # noqa: E402

BITTER_TRACE = "tianxia.talent.poison.bitter_trace"
GREATER_MEND = "tianxia.talent.life.greater_mend"
FOUNT_OF_LIFE = "tianxia.talent.life.fount_of_life"
LATENT_HEALING = "tianxia.talent.life.latent_healing"
REVITALIZING_THREAD = "tianxia.talent.life.revitalizing_thread"


def _variant_row(engine, contains):
    """The serialized action row the table hands the description hook, for the replacement button."""
    from combat.tabletop import engine_button_description

    row = next(a.model_dump(mode="json") for a in engine.action_catalog.values()
               if contains in a.display_name and "+" in a.display_name)
    return row, engine_button_description(row)


# ---------------------------------------------------------------- finding 1: paid costs


def test_a_paid_replacement_button_prints_its_real_resource_cost():
    """Greater Mend costs 2 Qi, so its button must say 2 Qi rather than a silent zero.

    The costs really do arrive serialized as ``[resource_id, amount]`` pairs here; that is the
    shape that used to be read as if each entry were an object with attributes.
    """
    _, engine, _, _ = _SW.fight(GREATER_MEND)
    row, text = _variant_row(engine, "Mend the Pulse")
    assert row["costs"] == [["resource:core.qi", 2]]
    cost_line = next(line for line in text.splitlines() if line.startswith("Cost:"))
    assert cost_line == "Cost: one Action and 2 Qi."


def test_a_free_replacement_still_reads_as_free_rather_than_inventing_a_price():
    """Bitter Trace charges nothing, so its cost line keeps saying so (finding 1, other side)."""
    _, engine, _, _ = _SW.fight(BITTER_TRACE)
    row, text = _variant_row(engine, "Deliver the Dose")
    assert row["costs"] == []
    assert "Cost: one Action." in text


# ------------------------------------------------- finding 2: rider utility is not damage


def _score(engine, target_hp):
    """The controller's own components for the two Deliver the Dose candidates, at a fixed HP."""
    from combat.gate4_context import build_decision_context
    from combat.gate4_controller import LocalDeterministicController
    from combat.gate4_policy import PolicyLibrary
    from combat.gate2_runtime_content import AN

    engine.state.actors[AN].current_hp = target_hp
    context = build_decision_context(engine, PolicyLibrary(APP).for_actor(ME)[0], for_ai=True)
    controller = LocalDeterministicController()
    out = {}
    for candidate in context.legal_candidates:
        if "Deliver the Dose" in candidate.display_name:
            scored = controller._score_candidate(context, candidate, candidate.option_ids)
            out[candidate.display_name] = {
                component.component: component.value for component in scored.components}
    return context, out


def test_a_mark_rider_is_not_scored_as_damage_the_ai_could_finish_a_wounded_creature_with():
    """The mark deals no damage, so it must not earn the +20 finish bonus for a wounded enemy.

    Deliver the Dose estimates 20 damage. A guaranteed mark used to add eight to that estimate,
    which put it at 28 and let the controller treat a 24 HP enemy as already finished -- a blow
    it never deals (finding 2).
    """
    _, engine, _, _ = _SW.fight(BITTER_TRACE)
    context, scores = _score(engine, target_hp=24)
    base, variant = scores["Deliver the Dose"], scores["Deliver the Dose + Bitter Trace"]
    assert base["defeat_prevention_or_finish"] == 0
    assert variant["defeat_prevention_or_finish"] == 0


def test_both_deliver_the_dose_modes_carry_the_same_damage_estimate():
    """The choice is between two ways to apply a Mark, not between two amounts of damage."""
    _, engine, _, _ = _SW.fight(BITTER_TRACE)
    context, _ = _score(engine, target_hp=200)
    rows = {c.display_name: c for c in context.legal_candidates if "Deliver the Dose" in c.display_name}
    assert (rows["Deliver the Dose + Bitter Trace"].metadata["expected_damage"]
            == rows["Deliver the Dose"].metadata["expected_damage"])


# ------------------------------------------------ finding 3: healing trades are not saves


@pytest.mark.parametrize("talent", [GREATER_MEND, FOUNT_OF_LIFE, LATENT_HEALING, REVITALIZING_THREAD])
def test_a_healing_replacement_is_not_explained_as_a_lost_failed_save(talent):
    """Mend the Pulse + Greater Mend replaces ordinary healing, which no failed save ever gave.

    Before this round every ``replace_*`` trade was described as "what a failed save would have
    given it", which wrapped four real healing abilities in a false explanation (finding 3).
    """
    _, engine, _, _ = _SW.fight(talent)
    _, text = _variant_row(engine, "Mend the Pulse")
    assert "failed save" not in text.lower()
    # It must still say what is given up and what the choice does instead.
    assert "You give up the effect it normally has:" in text
    assert "Instead," in text or "What this choice does instead:" in text
    # And the printed rules for the augment still travel with the button.
    assert "Mend" in text


# ------------------------------------- an already-saved fight keeps the wording it was saved with


def test_a_replacement_record_saved_before_this_change_keeps_its_original_wording():
    """A fight saved by an earlier build has a record with no ``save_gated`` / ``added`` keys.

    ``Gate2Engine`` loads its action catalog straight out of the saved bundle, so those fights
    still carry the old record. They must read exactly as they did before this change rather
    than silently re-worded (checklist: no change to old saved fights).
    """
    from combat.ext.replacement_variants import replacement_choice_help

    record = {"when": "replace_save", "base_name": "Deliver the Dose",
              "removed": [{"type": "disadvantage", "on": "ability_check",
                           "evidence": "Disadvantage on its next ability check."}],
              "reliable": []}
    text = replacement_choice_help({"economy": "ACTION", "costs": [],
                                    "parameters": {"typed": {"replacement": record,
                                                             "effects": []}}})
    # The pre-existing rendering: a removed rider with no save-gating information is described
    # the way it always was, and no "what this does instead" line is invented for it.
    assert "The target loses what a failed save would have given it: Disadvantage on its next ability check." in text
    assert "You give up the effect it normally has:" not in text
    assert "Instead," not in text and "What this choice does instead:" not in text
