"""RW191F1 modularity regression (checklist item 5).

Plug-ins in combat/ext must not import another plug-in's private (underscore) names.
Light-Body Recovery in foundations4 used foundation_resources._plus; the helper is now the
public plus_selected. This test reads the source tree only (no history, no private data).
"""
import ast
from pathlib import Path

EXT = Path(__file__).resolve().parents[1] / "combat" / "ext"


def _private_imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
            found += [(node.module, a.name) for a in node.names if a.name.startswith("_")]
    return found


def test_ext_plugins_do_not_import_private_names_from_each_other():
    offenders = {p.name: _private_imports(p) for p in sorted(EXT.glob("*.py"))}
    offenders = {k: v for k, v in offenders.items() if v}
    assert offenders == {}


def test_light_body_uses_public_plus_selected_helper():
    source = (EXT / "foundations4.py").read_text(encoding="utf-8")
    assert "from .foundation_resources import plus_selected" in source
    resources = (EXT / "foundation_resources.py").read_text(encoding="utf-8")
    assert "def plus_selected(" in resources
    assert "def _plus(" not in resources


def test_plus_selected_is_inert_without_owned_row():
    from combat.ext.foundation_resources import plus_selected

    class Actor:
        entity_id = "actor:nobody"

    class Engine:
        typed_passive_rows = {}

    assert plus_selected(Engine(), Actor(), "wings_remember_ground") is False
