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


def test_perception_subject_identity_and_vertical_position_are_not_collapsed():
    first = SimpleNamespace(entity_id="effect:one", position=SimpleNamespace(x=2, y=3, z=0),
                            active=True, conditions={}, summon=None)
    second = SimpleNamespace(entity_id="effect:one", position=SimpleNamespace(x=2, y=3, z=4),
                             active=True, conditions={}, summon=None)
    assert first.entity_id == second.entity_id
    assert (first.position.x, first.position.y, first.position.z) != (
        second.position.x, second.position.y, second.position.z)


def test_public_perceives_query_keeps_action_specific_sight_routes_distinct(monkeypatch):
    from combat import read_queries

    class Actor:
        entity_id = "actor"
        position = SimpleNamespace(x=1, y=1, z=0)
        active = True
        conditions = {}

    class Action:
        def __init__(self, source):
            self.source_definition_id = source

    class Engine:
        def __init__(self):
            self._shot_geometry = {"actor_id": "actor", "action": Action("action:a")}
        def _actor_cells(self, _actor):
            return ((1, 1),)

    engine, viewer, seen = Engine(), Actor(), Actor()
    seen.entity_id = "target"
    keys = []
    monkeypatch.setattr(read_queries, "invariant_query",
                        lambda _engine, key, fn, refs=(): (keys.append(key), fn())[1])
    monkeypatch.setattr(senses, "_perceives", lambda *_a, **_kw: True)
    assert senses.perceives(engine, viewer, seen)
    engine._shot_geometry = {"actor_id": "actor", "action": Action("action:b")}
    assert senses.perceives(engine, viewer, seen)
    assert keys[0][-1] == "action:a"
    assert keys[1][-1] == "action:b"
    assert keys[0] != keys[1]
