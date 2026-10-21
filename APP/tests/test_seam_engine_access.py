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
# Every plug-in and producer module of the Iron Oath / Fate Reader / table-fact
# feature reads the engine only through the public seam (see engine_seam.py).
FILES = ['engine_seam.py', 'ext/iron_oath.py', 'ext/foundation_iron_oath_2.py',
         'ext/fate_reader.py', 'ext/foundation_combat.py', 'ext/project_checks.py',
         'project_checks.py', 'protected_subjects.py', 'table_facts.py',
         'feature_access.py', 'source_effects.py']

# The TabletopService private reads these producer modules inherit from the
# established table-service pattern (combat/tabletop_service.py, gate5_service.py,
# agent_seats/runner.py). Recorded so the scan is exact about what it lets through.
INHERITED_TABLE_RECEIVERS = {('project_checks.py', '_factory_owner_sheet'),
                             ('source_effects.py', '_load_session')}


def _engine_receiver(node):
    """True for an expression that names the live engine: ``engine`` or ``x.engine``."""
    if isinstance(node, ast.Name):
        return node.id == 'engine'
    if isinstance(node, ast.Attribute) and node.attr == 'engine':
        return isinstance(node.value, ast.Name)
    return False


def _table_receiver(node):
    """True for ``table.combat`` (a TabletopService's combat service)."""
    return (isinstance(node, ast.Attribute) and node.attr == 'combat'
            and isinstance(node.value, ast.Name) and node.value.id == 'table')


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


@pytest.mark.parametrize('name', FILES)
def test_no_table_service_private_access(name):
    tree = ast.parse((ROOT / name).read_text(encoding='utf-8'))
    offenders = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute) and node.attr.startswith('_') and _table_receiver(node.value)
                and (name, node.attr) not in INHERITED_TABLE_RECEIVERS):
            offenders.append(f'{name}:{node.lineno}.{node.attr}')
    assert offenders == []


def test_observable_uses_the_public_distance_seam(monkeypatch):
    # A recorded observation's range check must ask the seam, not read
    # Gate2Engine._distance_actor_to_actor. The fake engine has only the public
    # accessor, so the old private call raises AttributeError here.
    from combat import table_facts, target_knowledge
    from combat.gate2_runtime_models import Position
    monkeypatch.setattr(target_knowledge, 'can_see', lambda engine, viewer, target: True)
    calls = []
    viewer = SimpleNamespace(entity_id='a', position=Position(x=0, y=0))
    subject = SimpleNamespace(entity_id='b', position=Position(x=3, y=0))
    engine = SimpleNamespace(state=SimpleNamespace(actors={'b': subject}, objects={}),
                             distance_actor_to_actor=lambda s, t: calls.append((s.entity_id, t.entity_id)) or 30)
    fact = SimpleNamespace(subject_id='b', subject_kind='creature', position={'x': 3, 'y': 0})
    assert table_facts.observable(engine, viewer, fact, 60) is True
    assert calls == [('a', 'b')]
    assert table_facts.observable(engine, viewer, fact, 25) is False


def test_reaction_prediction_without_an_active_intent_stays_live():
    # A REACTION_RESOLVED can arrive with no in-flight intent (a turn-start or
    # passive-triggered reaction window). Fulfilling the prediction against that
    # null intent used to walk into the typed execution path with no action; the
    # prediction now stays live and expires with its own deadline.
    import json

    from combat import canonical
    from combat.ext import fate_reader
    from combat.table_facts import PredictedAction, TableFact
    prediction = PredictedAction(actor_id='b', kind='REACTION',
                                 source_definition_id='system:combat.opportunity_attack',
                                 target_ids=('a',), aware_actor_ids=('b',),
                                 description='Make an opportunity attack against the reader')
    fact = TableFact(record_id='r', subject_id='b', subject_name='Subject', subject_kind='creature',
                     position={'x': 1, 'y': 1}, source_reference='campaign:test',
                     witness_ids=('a',), valid_through_round=5, answers={})
    held = SimpleNamespace(condition_id=fate_reader.BRANCH, source_definition_id=fate_reader.READ,
                           source_actor_id='a', expires_on='UNTIL_REMOVED',
                           data={'record_id': 'r', 'prediction': json.dumps(prediction.model_dump(mode='json')),
                                 'record_hash': canonical.canonical_sha256(fact.model_dump(mode='json'))})
    target = SimpleNamespace(entity_id='b', active=True, conditions={'c1': held})
    owner = SimpleNamespace(entity_id='a', active=True)
    events = []
    engine = SimpleNamespace(
        events=[SimpleNamespace(event_type='TABLE_FACT_RECORDED', payload={'fact': fact.model_dump(mode='json')})],
        state=SimpleNamespace(round_number=1, actors={'a': owner, 'b': target}),
        active_intent=lambda: None, action_catalog={})
    engine._append_event = lambda *args, **kwargs: events.append((args, kwargs))
    fate_reader.thread_reaction_occurs(engine, 'REACTION_RESOLVED', {
        'actor_id': 'b', 'source_definition_id': 'system:combat.opportunity_attack',
        'target_ids': ('a',), 'payload': {}})
    assert 'c1' in target.conditions
    assert [call[1]['payload']['log'] for call in events] == [
        'Read the Thread: the predicted reaction happened outside a declared action, '
        'so the prediction still stands until it expires.']


def test_seam_forwards_to_public_accessors():
    calls = []
    def append_event(kind, *a, **k):
        call = ('event', kind, a, k)
        calls.append(call)
        return call
    engine = SimpleNamespace(active_intent=lambda: 'intent', active_candidate=lambda: 'candidate',
                             active_intent_id=lambda: 'intent-id',
                             record_roll=lambda roll: calls.append(('roll', roll)),
                             append_event=append_event)
    assert seam.active_intent(engine) == 'intent'
    assert seam.active_candidate(engine) == 'candidate'
    assert seam.active_intent_id(engine) == 'intent-id'
    seam.record_roll(engine, 'die')
    assert seam.append_event(engine, 'REACTION_RESOLVED', 'Nudge', actor_id='a', payload={'x': 1}) == (
        'event', 'REACTION_RESOLVED', ('Nudge',), {'actor_id': 'a', 'payload': {'x': 1}})
    assert calls == [('roll', 'die'), ('event', 'REACTION_RESOLVED', ('Nudge',), {'actor_id': 'a', 'payload': {'x': 1}})]


def test_missing_intent_fails_loudly_instead_of_silently_skipping():
    # The engine HAS the public accessor, but no intent is in flight. Old code returned quietly here;
    # a missing context must now raise (RuntimeError), not skip the duty offer.
    engine = SimpleNamespace(active_intent=lambda: None, active_candidate=lambda: None,
                             state=SimpleNamespace(actors={}), action_catalog={})
    event = SimpleNamespace(event_type='INTENT_ACCEPTED')
    with pytest.raises(RuntimeError, match='no active intent'):
        iron_oath.off_turn_declaration(engine, event)
