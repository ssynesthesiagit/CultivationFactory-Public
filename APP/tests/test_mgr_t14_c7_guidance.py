"""Regression checks for Chain Body guidance after its triggers became automated."""
import json
from pathlib import Path


def test_automated_chain_body_clauses_are_not_presented_as_manual_rules():
    source = Path(__file__).parents[1] / "authority/typed_mechanics/reviewed_final.d/riders_c7.json"
    mechanics = json.loads(source.read_text(encoding="utf-8"))["mechanics"]

    integration = mechanics[
        "tianxia.subpath.body.heaven_binding_chain_body.feature.chain_body_integration"
    ]["riders"]
    network = mechanics[
        "tianxia.subpath.body.heaven_binding_chain_body.feature.thousand_link_meridian_network"
    ]["riders"]
    prison = mechanics[
        "tianxia.subpath.body.heaven_binding_chain_body.feature.heaven_binding_prison"
    ]["riders"]

    guidance = " ".join(integration + network + prison).lower()
    assert "willingly end it" not in guidance
    assert "spatial movement out of the prison requires" not in guidance
    assert "only when a creature leaves your reach" not in guidance
    # Genuine GM adjudications remain available.
    assert "refined iron fist and heavenly fist" in guidance
    assert "temporary barriers" in guidance
    assert "central anchor" in guidance
