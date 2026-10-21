"""Prediction matching in combat.table_facts (review F1 on learning-proficiency-2).

FactAnswer.predictions are consumed only by action_matches and reaction_matches.
No caller exists yet, so these tests drive the matchers directly with a minimal
engine. They pin: a witnessed prediction needs the exact actor, kind, source,
targets and explicit option ids; a declined or offered reaction never matches;
a MOVE only matches a committed, non-forced walk that ends at the predicted cell;
and a non-empty answer with predictions validates as a recorded fact.
"""
from types import SimpleNamespace

import pytest

from combat import table_facts as tf
from combat.table_facts import FactAnswer, PredictedAction, TableFact


def _fact(record_id='fact:warded-step', witnesses=('ally',), round_number=5, answers=None):
    return TableFact(record_id=record_id, subject_id='foe', subject_name='Foe', subject_kind='creature',
                     position={'x': 1, 'y': 1}, source_reference='table observation', witness_ids=witnesses,
                     valid_through_round=round_number, answers=answers or {})


def _engine(events=(), facts=()):
    recorded = [SimpleNamespace(sequence=i, event_type='TABLE_FACT_RECORDED', actor_id=None,
                                payload={'fact': fact.model_dump(mode='json')})
                for i, fact in enumerate(facts)]
    return SimpleNamespace(state=SimpleNamespace(actors={}, round_number=5), events=[*recorded, *events])


def _reaction_prediction(**overrides):
    values = dict(actor_id='foe', kind='REACTION', source_definition_id='ACTION:opportunity_strike',
                  target_ids=('ally',), option_ids=('option:sweep',), aware_actor_ids=('ally', 'foe'),
                  description='Opportunity strike when the ally moves')
    values.update(overrides)
    return PredictedAction(**values)


def _reaction_event(**overrides):
    event = {'actor_id': 'foe', 'source_definition_id': 'ACTION:opportunity_strike', 'target_ids': ('ally',),
             'payload': {'option_ids': ('option:sweep',)}}
    event.update(overrides)
    return event


def test_non_empty_answer_with_prediction_validates_as_recorded_fact():
    prediction = _reaction_prediction()
    answer = FactAnswer(fact='Foe is ready to strike', category='combat', visible_sign='tense stance',
                        source_cl=1, predictions=(prediction,))
    fact = _fact(answers={'ally': answer})
    assert fact.answers['ally'].predictions == (prediction,)
    assert fact.model_dump(mode='json')['answers']['ally']['predictions'][0]['kind'] == 'REACTION'


def test_reaction_matches_committed_reaction_with_exact_option_ids():
    prediction = _reaction_prediction()
    assert tf.reaction_matches(_engine(), prediction, 'REACTION_RESOLVED', _reaction_event())


@pytest.mark.parametrize('event_type, overrides', [
    ('REACTION_OFFERED', {}),
    ('REACTION_DECLINED', {}),
    ('REACTION_RESOLVED', {'actor_id': 'ally'}),
    ('REACTION_RESOLVED', {'source_definition_id': 'ACTION:other'}),
    ('REACTION_RESOLVED', {'target_ids': ('someone-else',)}),
    ('REACTION_RESOLVED', {'payload': {'option_ids': ('option:other',)}}),
    ('REACTION_RESOLVED', {'payload': {}}),
])
def test_reaction_does_not_match_offered_declined_or_different_variant(event_type, overrides):
    assert not tf.reaction_matches(_engine(), _reaction_prediction(), event_type, _reaction_event(**overrides))


def test_reaction_match_requires_the_predicted_fact_to_be_recorded():
    prediction = _reaction_prediction(requires_facts=('fact:warded-step',))
    assert not tf.reaction_matches(_engine(), prediction, 'REACTION_RESOLVED', _reaction_event())
    engine = _engine(facts=[_fact()])
    assert tf.reaction_matches(engine, prediction, 'REACTION_RESOLVED', _reaction_event())


def test_reaction_match_ignores_creatures_outside_the_awareness_list():
    prediction = _reaction_prediction(aware_actor_ids=('ally',))
    assert not tf.reaction_matches(_engine(), prediction, 'REACTION_RESOLVED', _reaction_event())


def _move_prediction(destination):
    return PredictedAction(actor_id='foe', kind='MOVE', source_definition_id='MOVE:walk', target_ids=(),
                           option_ids=(), destination=destination, aware_actor_ids=('foe', 'ally'),
                           description='Walks to the doorway')


class _Position(SimpleNamespace):
    def model_dump(self, mode='python'):
        return {'x': self.x, 'y': self.y}


def _move_candidate():
    return SimpleNamespace(kind=SimpleNamespace(value='MOVE'), source_definition_id='MOVE:walk', target_ids=())


def _move_event(sequence, path, **payload):
    body = {'path': path, **payload}
    return SimpleNamespace(sequence=sequence, event_type='MOVEMENT_COMMITTED', actor_id='foe', payload=body)


def test_move_matches_committed_walk_that_ends_at_predicted_cell():
    actor = SimpleNamespace(entity_id='foe', position=_Position(x=4, y=2))
    engine = _engine(events=[_move_event(3, [{'x': 2, 'y': 2}, {'x': 3, 'y': 2}, {'x': 4, 'y': 2}])])
    intent = SimpleNamespace(option_ids=())
    prediction = _move_prediction({'x': 4, 'y': 2})
    assert tf.action_matches(engine, prediction, actor, _move_candidate(), intent, start_sequence=2)


@pytest.mark.parametrize('position, payload, path', [
    # Actor stopped short of the predicted endpoint.
    ((3, 2), {}, [{'x': 2, 'y': 2}, {'x': 3, 'y': 2}]),
    # Forced or teleported movement is not a voluntary walk.
    ((4, 2), {'forced': True}, [{'x': 2, 'y': 2}, {'x': 4, 'y': 2}]),
    ((4, 2), {'teleport': True}, [{'x': 2, 'y': 2}, {'x': 4, 'y': 2}]),
    # A walk committed before the prediction window does not count.
    ((4, 2), {}, None),
])
def test_move_does_not_match_short_forced_or_pre_window_walks(position, payload, path):
    actor = SimpleNamespace(entity_id='foe', position=_Position(x=position[0], y=position[1]))
    if path is None:
        event = _move_event(1, [{'x': 2, 'y': 2}, {'x': 4, 'y': 2}])
    else:
        event = _move_event(3, path, **payload)
    engine = _engine(events=[event])
    intent = SimpleNamespace(option_ids=())
    assert not tf.action_matches(engine, _move_prediction({'x': 4, 'y': 2}), actor, _move_candidate(), intent,
                                 start_sequence=2)


def test_action_match_requires_the_predicted_actor_and_awareness():
    actor = SimpleNamespace(entity_id='ally', position=_Position(x=4, y=2))
    intent = SimpleNamespace(option_ids=())
    assert not tf.action_matches(_engine(), _move_prediction({'x': 4, 'y': 2}), actor, _move_candidate(),
                                 intent, start_sequence=0)
