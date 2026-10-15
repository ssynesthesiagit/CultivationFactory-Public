"""Read-only text seams preserve provenance and the selected rule's context."""
import pytest

from combat.decision_text import trigger_text


@pytest.mark.parametrize("explicit", [None, "action:other"])
def test_null_trigger_source_recovers_action_but_concrete_source_wins(explicit):
    context = {"checkpoint": "TYPED:TECHNIQUE_DECLARED@1",
               "choice_trigger": {"actor_id": "attacker", "target_id": "target",
                                  "source_definition_id": explicit, "roll_kind": None},
               "recent_events": [{"event_type": "INTENT_ACCEPTED", "actor_id": "attacker",
                                  "source_definition_id": "action:strike", "target_ids": ["target"]}]}
    result = trigger_text(context, {"reactor": "Target"},
                          {"attacker": "Attacker", "target": "Target"},
                          {"action:strike": "Lightning Lash", "action:other": "Other ability"})
    assert result == f"Attacker uses {'Other ability' if explicit else 'Lightning Lash'} on Target."


def test_reminder_keeps_conditional_application_without_addressing_player_as_gm():
    from combat.history_text import rider_text
    text = rider_text({"rider": "Choose one learned characteristic."}, "Reader", "Read the Vessel", "Target")
    assert "Resolve only effects that the recorded outcomes have not already applied." in text
    assert "Rule reminder: Choose one learned characteristic." in text
    assert "GM" not in text


def test_native_variant_description_names_modifier_cost_and_its_override():
    from tests.test_mmx38_replacement_help_and_scoring import _SW, BITTER_TRACE, _variant_row
    _, engine, _, _ = _SW.fight(BITTER_TRACE)
    _, text = _variant_row(engine, "Deliver the Dose")
    assert "Bitter Trace" in text and "Cost: one Action." in text
    assert "1 Dose Mark automatically on a hit" in text
    assert "subtle" in text
    assert "additional saving throw effect" in text


@pytest.mark.parametrize("modifier", ["TAL_DARK_OBFUSCATION", "unknown:modifier"])
def test_native_replacement_help_is_inert_for_additive_or_unknown_modifiers(modifier):
    from combat.ext.replacement_variants import replacement_choice_help
    row = {"parameters": {"typed": {"variant_of": "action:base",
                                    "modifier": {"id": modifier}}}}
    assert replacement_choice_help(row) is None


@pytest.mark.parametrize("pool,wording", [("", "cultivation points (your Path resource)"),
                                          ("resource:core.qi", "Qi")])
def test_choice_moment_and_trigger_explain_cp_in_the_same_paying_pool(pool, wording):
    from combat.decision_text import build_decision_text
    context = {"reactor_id": "reader", "reaction_source_id": "choice:example",
               "extension_choice": {"option_ids": ["use"]},
               "choice_trigger": {"cost": "2 CP", "paying_pool": pool}}
    prompt = {"reactor": "Reader", "reaction": "Example",
              "moment": "Example hits Target; pay 2 CP.",
              "choice": {"options": [{"id": "use", "label": "Use"}], "allow_decline": True}}
    result = build_decision_text(None, context, prompt, {}, {}, {})
    assert result["moment"] == result["trigger"] == f"Example hits Target; pay 2 {wording}."
    assert prompt["moment"] == "Example hits Target; pay 2 CP."
