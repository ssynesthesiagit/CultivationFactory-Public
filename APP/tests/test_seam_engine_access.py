"""Regression: Iron Oath / Fate Reader / project-check plug-ins reach the engine only through combat/engine_seam.py.

Synthetic checks only: source text of the plug-in files plus fake engine objects. No fixtures, no history reads.
"""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from combat import engine_seam as seam
from combat.ext import iron_oath

ROOT = Path(__file__).resolve().parents[1] / 'combat'
FILES = ['ext/iron_oath.py', 'ext/foundation_iron_oath_2.py', 'ext/fate_reader.py', 'project_checks.py']
PRIVATE = {'_active_intent', '_active_candidate', '_record_roll', '_append_event'}


@pytest.mark.parametrize('name', FILES)
def test_no_engine_private_access_or_getattr_fallback(name):
    tree = ast.parse((ROOT / name).read_text(encoding='utf-8'))
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in PRIVATE:
            offenders.append(f'{name}:{node.lineno}.{node.attr}')
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'getattr'
                and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) and node.args[1].value in PRIVATE):
            offenders.append(f'{name}:{node.lineno} getattr {node.args[1].value}')
    assert offenders == []


def test_seam_forwards_to_engine():
    calls = []
    engine = SimpleNamespace(_active_intent='intent', _active_candidate='candidate',
                             _record_roll=lambda roll: calls.append(('roll', roll)),
                             _append_event=lambda kind, *a, **k: calls.append(('event', kind, a, k)))
    assert seam.active_intent(engine) == 'intent'
    assert seam.active_candidate(engine) == 'candidate'
    seam.record_roll(engine, 'die')
    assert seam.append_event(engine, 'REACTION_RESOLVED', 'Nudge', actor_id='a', payload={'x': 1}) is None
    assert calls == [('roll', 'die'), ('event', 'REACTION_RESOLVED', ('Nudge',), {'actor_id': 'a', 'payload': {'x': 1}})]


def test_missing_intent_fails_loudly_instead_of_silently_skipping():
    # Old code used getattr(engine, '_active_intent', None) and returned quietly; a missing context must now raise.
    engine = SimpleNamespace(state=SimpleNamespace(actors={}), action_catalog={})
    event = SimpleNamespace(event_type='INTENT_ACCEPTED')
    with pytest.raises(AttributeError):
        iron_oath.off_turn_declaration(engine, event)
