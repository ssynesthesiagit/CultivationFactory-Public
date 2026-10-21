"""Regression checks for Chain Body guidance after its triggers became automated."""
import json
from pathlib import Path

from combat.factory_compiler import compile_character
from tests.test_riders_c7 import sheet


CHAIN = "tianxia.subpath.body.heaven_binding_chain_body.feature."


def test_printed_tether_removal_and_release_are_both_present_and_automated():
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
    # The printed removal clause stays; the table offers the free release action that carries it out.
    assert "a tether also ends when you willingly end it" in guidance
    assert "free end one meridian tether action" in guidance
    # Severance and the prison's own effects are automated, not left to the GM.
    assert "severs cultivation bindings" in guidance
    assert "the gm must" not in guidance
    assert "spatial movement out of the prison requires" not in guidance
    assert "refined iron fist and heavenly fist" in guidance
    assert "temporary barriers" in guidance
    assert "central anchor" in guidance

    # The release mechanic itself exists in this fight's compiled options (not only in the wording).
    bundle = compile_character(sheet([CHAIN + "chain_body_integration"]), actor_id="actor:factory.c7guidance")
    assert any(action["source_definition_id"].endswith(".release_meridian_tether")
               for action in bundle["action_catalog"])
