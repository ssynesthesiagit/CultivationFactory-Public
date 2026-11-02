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


def test_perception_subject_identity_and_vertical_position_are_not_collapsed(monkeypatch):
    """Drive the real perceives() answer cache: one candidate pass, one subject, two states.

    The same subject object is first on the ground and then 4 feet up (same entity_id, same
    square, z differs); a second pass re-keys its entity_id only. Each change must reach the
    underlying _perceives decision, not a stale cached answer from the earlier state.
    """
    from combat import read_queries

    class Engine:
        def __init__(self):
            self.state = SimpleNamespace(state_version=1, event_sequence=1, actors={})
            self.action_catalog = object()
        def _actor_cells(self, _actor):
            return ((2, 3),)

    engine = Engine()
    viewer = SimpleNamespace(entity_id="viewer", position=SimpleNamespace(x=0, y=0, z=0),
                             active=True, conditions={})
    subject = SimpleNamespace(entity_id="effect:one", position=SimpleNamespace(x=2, y=3, z=0),
                              active=True, conditions={}, summon=None)
    calls = []
    # Visible only at ground level: the answer depends on z, so a z-blind key returns a stale True.
    monkeypatch.setattr(senses, "_perceives",
                        lambda _e, _v, seen, **_kw: calls.append(
                            (seen.entity_id, seen.position.z)) or seen.position.z == 0)
    with read_queries.candidate_pass(engine):
        assert senses.perceives(engine, viewer, subject) is True
        subject.position = SimpleNamespace(x=2, y=3, z=4)
        assert senses.perceives(engine, viewer, subject) is False
        subject.entity_id = "effect:two"
        subject.position = SimpleNamespace(x=2, y=3, z=0)
        assert senses.perceives(engine, viewer, subject) is True
    assert calls == [("effect:one", 0), ("effect:one", 4), ("effect:two", 0)]


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
