"""Cancellation choices stop discovery; other optional reactions keep grouping."""
from types import SimpleNamespace
import pytest
from combat.gate4_models import ExtensionChoice
from combat.reaction_menu import ReactionMenuProbe,MenuBoundary


def context(spec):
    return SimpleNamespace(checkpoint='PAYMENT',reactor_id='actor:payer',reaction_source_id='choice:payment',extension_choice=spec)


def test_canceling_payment_preserves_the_original_choice_boundary():
    spec=ExtensionChoice(option_ids=('ordinary','alternative'),decline_cancels_activation=True)
    first=context(spec)
    probe=ReactionMenuProbe(first)
    with pytest.raises(MenuBoundary):probe.answer(first)
    assert probe.contexts==[] and probe.first is first
    assert ExtensionChoice.model_validate(spec.model_dump()).decline_cancels_activation


def test_default_optional_reaction_keeps_legacy_decline_and_discovery():
    spec=ExtensionChoice(option_ids=('benefit',))
    assert 'decline_cancels_activation' not in spec.model_dump()
    first=context(spec);probe=ReactionMenuProbe(first)
    decision=probe.answer(first)
    assert decision.selection=='DECLINE' and probe.contexts==[first]


def test_mandatory_choice_remains_a_boundary_without_new_metadata():
    first=context(ExtensionChoice(option_ids=('required',),allow_decline=False))
    with pytest.raises(MenuBoundary):ReactionMenuProbe(first).answer(first)
