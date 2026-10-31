"""Keep the journey/admission lifecycle contracts centrally discoverable."""
import ast
from pathlib import Path
import re

import pytest

APP = Path(__file__).resolve().parents[1]


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
    ("fact_admission_validate(session, source, subject, kind, value)",
     ("strict validator", "before", "All validators", "exception", "not False", "default-inert")),
    ("fact_admitted(session, record)",
     ("strict observer", "after", "deep copy", "commitment", "transaction", "default-inert")),
])
def test_central_journey_admission_contract(signature, required):
    registry = APP / "combat/ext/__init__.py"
    documentation = ast.get_docstring(ast.parse(registry.read_text()))
    assert signature in documentation, f"Missing central API contract: {signature}"
    section = documentation.split(signature, 1)[1].split("\n\n", 1)[0]
    for term in required:
        assert term in section, f"{signature} does not document {term}"


ADMISSION_HOOKS = (
    "fact_admission_schema",
    "fact_admission_validate",
    "fact_admitted",
    "combat_fact_admission_allowed",
)


def _documented_parameters(documentation, hook):
    """The parameter count of a documented hook signature."""
    match = re.search(r"\b" + hook + r"\(([^()]*)\)", documentation)
    assert match, f"the central document must describe {hook}"
    return len([part for part in match.group(1).split(",") if part.strip()])


def _call_arguments(path, hook):
    """The argument count of the owning call of a hook, if it calls it."""
    for node in ast.walk(ast.parse(path.read_text())):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in ("run_strict", "query") and node.args):
            continue
        point = node.args[0]
        if isinstance(point, ast.Constant) and point.value == hook:
            return len(node.args) - 1
    return None


def _subscriber_parameters(hook):
    """The parameter count of every registered subscriber of a hook."""
    counts = []
    for path in sorted((APP / "combat/ext").glob("*.py")):
        for node in ast.parse(path.read_text()).body:
            if not isinstance(node, ast.FunctionDef):
                continue
            for decorator in node.decorator_list:
                if (isinstance(decorator, ast.Call) and decorator.args
                        and isinstance(decorator.args[0], ast.Constant)
                        and decorator.args[0].value == hook):
                    counts.append((path.name, node.name, len(node.args.args)))
    return counts


def test_the_documented_admission_contracts_match_the_running_code():
    """The central document, the owning call and every subscriber agree."""
    documentation = ast.get_docstring(ast.parse((APP / "combat/ext/__init__.py").read_text()))
    owner = APP / "combat/fact_consent_admission.py"
    for hook in ADMISSION_HOOKS:
        documented = _documented_parameters(documentation, hook)
        called = _call_arguments(owner, hook)
        assert called == documented, (f"{hook} is called with {called} arguments "
                                     f"but the central document describes {documented}")
        for name, function, count in _subscriber_parameters(hook):
            assert count == documented, (f"{name}.{function} takes {count} parameters, "
                                         f"but {hook} is documented with {documented}")
