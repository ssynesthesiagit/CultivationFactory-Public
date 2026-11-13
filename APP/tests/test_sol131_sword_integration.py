"""Sword-core passive ownership and AUTO54 rolls/payment share one implementation."""
import copy
import importlib

import pytest

from combat.ext import sword_sphere

S = importlib.import_module("tests.test_review_sw-sword")


@pytest.mark.parametrize("representation", ["passive", "legacy_modifier"])
def test_iron_body_rolls_once_and_quotes_stamina_in_both_saved_representations(representation):
    engine, actor, _ = S._fight([S.IRON_BODY, "SWORD_BASE_SWORD_BEYOND_HAND"], con=18, str_score=10)
    # The support compiler caches bundles. Keep the historical representation local to this engine.
    engine.typed_bundle_documents = tuple(copy.deepcopy(b) for b in engine.typed_bundle_documents)
    bundle = next(b for b in engine.typed_bundle_documents if b["actor_id"] == actor.entity_id)
    assert not any(row.get("id") == S.IRON_BODY for row in bundle["modifiers"])
    assert any(row.get("feature_id") == S.IRON_BODY for row in engine.typed_passive_rows[actor.entity_id])
    if representation == "legacy_modifier":
        # Historical saved bundles record this ownership in modifiers, before Sword-core's block existed.
        engine.typed_passive_rows[actor.entity_id] = [row for row in engine.typed_passive_rows[actor.entity_id]
                                                     if row.get("feature_id") != S.IRON_BODY]
        bundle["modifiers"].append({"id": S.IRON_BODY})
    action = S._sword_qi_attack(engine)
    numbers = action.parameters["typed"]["numbers"]
    ctx = S._ctx(engine, actor, action.parameters["typed"])
    ctx.action = action
    assert sword_sphere.iron_sword_body_attack(ctx, actor) == numbers["con_mod"] - numbers["key_mod"]
    attack, damage = S._strike(engine, "Sword Beyond Hand")
    assert attack["modified_total"] - attack["natural_result"] == numbers["attack_bonus"] + numbers["con_mod"] - numbers["key_mod"]
    assert damage["modifier"] == numbers["con_mod"]
    actor.resources["resource:core.stamina"] = 40
    plan = sword_sphere.iron_sword_body_payment(engine, actor, action.source_definition_id,
                                              {"resource:core.qi": 3}, {"resource:core.qi"})
    assert plan is not None and plan.costs == (("resource:core.stamina", 3),)
