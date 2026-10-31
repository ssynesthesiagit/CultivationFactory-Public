"""Regression: back-to-back combat declarations get distinct fact sequences.

Before the fix, NativeFactSession.next_fact_sequence() returned
event_sequence + 1, so two declarations with no event between them shared a
sequence and the later read could not tell which one was latest.
"""
import json
from types import SimpleNamespace

from combat.fact_consent_admission import CONDITION, NativeFactSession


def _condition(record):
    return SimpleNamespace(condition_id=CONDITION, data={'record': json.dumps(record)},
                           model_dump_json=lambda **_: '{}')


def _engine(event_sequence, conditions):
    actor = SimpleNamespace(conditions={f'c{i}': c for i, c in enumerate(conditions)}, modifiers={})
    return SimpleNamespace(state=SimpleNamespace(actors={'actor:a': actor}, round_number=1,
                                                  event_sequence=event_sequence),
                           typed_bundle_documents=())


def test_back_to_back_declarations_get_distinct_sequences():
    first = NativeFactSession(_engine(5, []))
    assert first.next_fact_sequence() == 6
    # The first declaration commits as a condition without emitting an event.
    record = {'source': 's', 'subject': 'actor:a', 'kind': 'k', 'scope': 'x', 'sequence': 6}
    second = NativeFactSession(_engine(5, [_condition(record)]))
    assert second.next_fact_sequence() == 7


def test_event_sequence_still_raises_the_floor():
    assert NativeFactSession(_engine(40, [])).next_fact_sequence() == 41
