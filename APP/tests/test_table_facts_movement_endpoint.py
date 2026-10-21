"""Read the Thread's Mark the Branch endpoint rule at the matching layer.

action_matches must fulfil a predicted voluntary MOVE only through an actual
committed displacement to the predicted cell: a one-cell non-displacement
commit and a committed loop that ends at its start never qualify.

Synthetic checks only: events and actors built in the test. No fixtures,
no history reads, no live model calls.
"""
import types

from combat.gate2_runtime_models import Position
from combat.table_facts import PredictedAction, action_matches

FOE = 'actor:factory.thread-subject'


def _prediction():
    return PredictedAction.model_validate({'actor_id': FOE, 'kind': 'MOVE',
        'source_definition_id': 'system:combat.movement', 'target_ids': [], 'destination': {'x': 5, 'y': 6},
        'aware_actor_ids': [FOE], 'description': 'Move to the exposed approach'})


def _engine(*moves):
    actor = types.SimpleNamespace(entity_id=FOE, position=Position.model_validate({'x': 5, 'y': 6}))
    return types.SimpleNamespace(
        events=[types.SimpleNamespace(sequence=1 + index, event_type='MOVEMENT_COMMITTED', actor_id=FOE,
                                      payload={'path': list(path)}) for index, path in enumerate(moves)],
        state=types.SimpleNamespace(round_number=1), actors={FOE: actor})


def _match(moves):
    actor = types.SimpleNamespace(entity_id=FOE, position=Position.model_validate({'x': 5, 'y': 6}))
    intent = types.SimpleNamespace(option_ids=())
    candidate = types.SimpleNamespace(kind=types.SimpleNamespace(value='MOVE'),
                                      source_definition_id='system:combat.movement', target_ids=())
    return action_matches(_engine(*moves), _prediction(), actor, candidate, intent, 0)


def test_non_displacement_commit_never_fulfils():
    # A one-cell commit displaces nobody; it is not the predicted voluntary move.
    assert not _match(({'x': 5, 'y': 6},))


def test_committed_loop_that_ends_at_its_start_never_fulfils():
    # Returning to the start cell leaves the creature where it was.
    assert not _match(({'x': 4, 'y': 6}, {'x': 4, 'y': 6}))


def test_actual_documented_displacement_fulfils():
    # Positive control: moving to the predicted committed endpoint matches.
    assert _match(({'x': 4, 'y': 6}, {'x': 5, 'y': 6}))
