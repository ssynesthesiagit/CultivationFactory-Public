from types import SimpleNamespace

from combat import senses


def test_condition_query_key_includes_data_and_source():
    first = SimpleNamespace(condition_id='hidden', source_definition_id='feature:a', data={'cause': 'smoke'})
    second = SimpleNamespace(condition_id='hidden', source_definition_id='feature:b', data={'cause': 'smoke'})
    actor_a = SimpleNamespace(conditions={'row': first})
    actor_b = SimpleNamespace(conditions={'row': second})
    actor_c = SimpleNamespace(conditions={'row': SimpleNamespace(
        condition_id='hidden', source_definition_id='feature:a', data={'cause': 'shadow'})})
    assert senses._condition_query_key(actor_a) != senses._condition_query_key(actor_b)
    assert senses._condition_query_key(actor_a) != senses._condition_query_key(actor_c)
    assert senses._condition_query_key(actor_a) == senses._condition_query_key(actor_a)


def test_query_footprint_key_tracks_projected_actor_cells():
    actor = SimpleNamespace()
    class Engine:
        cells = ((1, 2), (1, 3))
        def _actor_cells(self, _actor):
            return self.cells
    engine = Engine()
    before = senses._footprint_query_key(engine, actor)
    engine.cells = ((1, 2), (2, 2))
    assert before != senses._footprint_query_key(engine, actor)
