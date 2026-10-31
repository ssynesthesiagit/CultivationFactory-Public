"""Documentation contract for the shared journey hooks (architecture-guard regression).

Journey hooks are documented in the combat/ext/__init__.py module docstring (the guard reads only
that docstring), and a helper module imported by other plug-ins must say it is shared.
"""
import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1]


def _doc(rel):
    return ast.get_docstring(ast.parse((APP / rel).read_text(encoding="utf-8"))) or ""


def test_journey_hook_contracts_are_in_ext_docstring():
    doc = _doc("combat/ext/__init__.py")
    assert "journey_before_command(session, actor_id, kind, payload) -> None" in doc
    assert "activity_validate(session, actor_id, activity)" in doc
    assert "activity_interrupted(session, actor_id, activity)" in doc
    assert "journey_check_rolled(session, actor_id, spec)" in doc
    assert "journey_resource_spent(session, actor_id, resource_id, before, after, source)" in doc


def test_journey_activities_helper_is_documented_as_shared():
    doc = _doc("combat/ext/journey_activities.py")
    assert "shared" in doc.lower()
    assert "journey_institutions" in doc and "restful_dream_journey" in doc
