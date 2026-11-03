"""Published Markdown labels preserve action identity and ambiguity checks."""
import pytest

from factory_authoring.command4_actions import _parse_explicit_fields
from factory_authoring.command4_provider import _candidate_action_type


@pytest.mark.parametrize("label", ["Action Type: Action", "**Action Type**: Action", "**Action Type:** Action"])
def test_colon_inside_or_outside_bold_label(label):
    source = label + "\n**Cost:** 1 Resonance\n**Range:** 60 feet\n\nPrinted effect."
    fields = _parse_explicit_fields(source)
    assert fields["action_type"] == "Action"
    assert fields["cost"] == "1 Resonance"
    assert fields["range"] == "60 feet"
    assert _candidate_action_type({"full_description": source}) == "action"


@pytest.mark.parametrize("second", ["Action", "Reaction"])
def test_multiple_bold_action_labels_remain_ambiguous(second):
    source = "**Action Type:** Action\n\nFirst operation.\n\n**Action Type:** " + second
    assert _candidate_action_type({"full_description": source}) is None


def test_bold_procedure_routing_does_not_authorize_combat():
    source = "**Action Type:** Ritual Procedure\n**Factory Routing:** procedure_ledger_not_combat_action"
    assert _candidate_action_type({"full_description": source}) == "procedure"
    assert _candidate_action_type({"full_description": source.replace("procedure_ledger_not_combat_action", "combat_action_row")}) is None


def test_bold_label_cannot_override_conflicting_sealed_type():
    assert _candidate_action_type({"action_type": "reaction", "full_description": "**Action Type:** Action"}) is None
