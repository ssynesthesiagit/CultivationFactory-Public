"""Keep the journey/admission lifecycle contracts centrally discoverable."""
import ast
from pathlib import Path

import pytest


@pytest.mark.parametrize("signature, required", [
    ("journey_resource_spent(session, actor_id, resource_id, before, after, source)",
     ("strict observer", "RESOURCE_SPENT", "transaction", "not charge", "default-inert")),
    ("journey_initialize(session, actor_id)",
     ("strict observer", "registry", "roster order", "before save", "default-inert")),
    ("journey_scene_end(session, previous_scene, next_scene)",
     ("strict", "table owner", "once", "SCENE_ENDED", "default-inert")),
    ("journey_snapshot_actor(actor, session, actor_id, engine)",
     ("ActorState | None", "pure transform", "registration order", "None retains",
      "copy before editing", "unrelated effects", "Exceptions abort", "default-inert")),
    ("journey_encounter_settled(session, actor_id, engine, creature)",
     ("strict observer", "original", "TRAVEL_RESUMED", "twice", "immutable", "default-inert")),
    ("fact_admission_schema(session, source, subject, kind)",
     ("dict | None", "pure", "Exactly one", "zero or multiple", "authority",
      "errors", "default-inert", "rejects")),
    ("fact_admission_validate(session, payload, world)",
     ("strict validator", "before", "All validators", "exception", "not False", "default-inert")),
    ("fact_declared(session, record)",
     ("strict observer", "after", "deep copy", "commitment", "transaction", "default-inert")),
])
def test_central_journey_admission_contract(signature, required):
    registry = Path(__file__).resolve().parents[1] / "combat/ext/__init__.py"
    documentation = ast.get_docstring(ast.parse(registry.read_text()))
    assert signature in documentation, f"Missing central API contract: {signature}"
    section = documentation.split(signature, 1)[1].split("\n\n", 1)[0]
    for term in required:
        assert term in section, f"{signature} does not document {term}"
