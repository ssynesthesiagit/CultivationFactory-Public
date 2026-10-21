"""Regression: Iron Oath / Fate Reader / project-check plug-ins reach the engine
only through combat/engine_seam.py, which forwards to the public, documented
Gate2Engine accessors ("Public engine seam" block in combat/gate2_engine.py).
No subscriber may read engine privates, use a getattr/hasattr fallback, or touch
the engine's __dict__ directly; the seam forwards loudly instead.

Synthetic checks only: source text of the subscriber files plus fake engine
objects. No fixtures, no history reads.
"""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from combat import engine_seam as seam
from combat.ext import iron_oath

ROOT = Path(__file__).resolve().parents[1] / 'combat'
FILES = ['engine_seam.py', 'ext/iron_oath.py', 'ext/foundation_iron_oath_2.py',
         'ext/fate_reader.py', 'ext/project_checks.py', 'project_checks.py',
         'protected_subjects.py']


def _engine_receiver(node):
    """True for an expression that names the live engine: ``engine`` or ``x.engine``."""
    if isinstance(node, ast.Name):
        return node.id == 'engine'
    if isinstance(node, ast.Attribute) and node.attr == 'engine':
        return isinstance(node.value, ast.Name)
    return False


@pytest.mark.parametrize('name', FILES)
def test_no_engine_private_access_or_getattr_fallback(name):
    tree = ast.parse((ROOT / name).read_text(encoding='utf-8'))
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr.startswith('_') and _engine_receiver(node.value):
            offenders.append(f'{name}:{node.lineno}.{node.attr}')
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in ('getattr', 'hasattr') and node.args
                and _engine_receiver(node.args[0])
                and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str)
                and node.args[1].value.startswith('_')):
            offenders.append(f'{name}:{node.lineno} {node.func.id} {node.args[1].value}')
    assert offenders == []


def test_seam_forwards_to_public_accessors():
    calls = []
    engine = SimpleNamespace(active_intent=lambda: 'intent', active_candidate=lambda: 'candidate',
                             active_intent_id=lambda: 'intent-id',
                             record_roll=lambda roll: calls.append(('roll', roll)),
                             append_event=lambda kind, *a, **k: calls.append(('event', kind, a, k))
                             )
    assert seam.active_intent(engine) == 'intent'
    assert seam.active_candidate(engine) == 'candidate'
    assert seam.active_intent_id(engine) == 'intent-id'
    seam.record_roll(engine, 'die')
    assert seam.append_event(engine, 'REACTION_RESOLVED', 'Nudge', actor_id='a', payload={'x': 1}) == (
        'event', 'REACTION_RESOLVED', ('Nudge',), {'actor_id': 'a', 'payload': {'x': 1}})
    assert calls == [('roll', 'die')]


def test_missing_intent_fails_loudly_instead_of_silently_skipping():
    # Old code used getattr(engine, '_active_intent', None) and returned quietly; a missing context must now raise.
    engine = SimpleNamespace(state=SimpleNamespace(actors={}), action_catalog={})
    event = SimpleNamespace(event_type='INTENT_ACCEPTED')
    with pytest.raises(AttributeError):
        iron_oath.off_turn_declaration(engine, event)
