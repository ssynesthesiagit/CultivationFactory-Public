"""Movement enumeration owns a short-lived pass even during a reaction."""
from pathlib import Path

from combat import ext, read_queries, senses
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_models import Position
from combat.tabletop import normalize_map, to_battlefield


# Without a shared pass, every material-route edge repeats expensive perception.
def test_bare_movement_enumeration_shares_perception_and_preserves_scope(monkeypatch):
    document = normalize_map({
        'display_name': 'Synthetic movement yard', 'width_squares': 8, 'height_squares': 8,
        'background': {'style': 'wood'},
    })
    engine = Gate2Engine(Path(__file__).resolve().parents[1], match_seed='movement-pass',
                         battlefield=to_battlefield(document))
    actor = engine.state.actors[engine.state.current_actor_id]
    for index, other in enumerate(engine.state.actors.values()):
        other.position = Position(x=index + 1, y=5)
    actor.position = Position(x=2, y=2)
    actor.speed_ft = actor.movement_remaining_ft = 20

    ext.effects()
    providers = ext._HOOKS.get('material_traversal', ())
    monkeypatch.setitem(ext._HOOKS, 'material_traversal', [
        *providers, lambda e, a: {'mode': 'test_swim', 'materials': ('wood',)}
        if a is actor else None,
    ])
    calls = []
    original = senses.perceives

    def counted(*args, **kwargs):
        calls.append(read_queries.enumeration_cache(engine))
        return original(*args, **kwargs)

    monkeypatch.setattr(senses, 'perceives', counted)
    before = engine.state.model_dump(mode='json')
    assert read_queries.enumeration_cache(engine) is None
    bare = engine._movement_candidates(actor)
    bare_calls = list(calls)
    assert read_queries.enumeration_cache(engine) is None
    calls.clear()
    with read_queries.candidate_pass(engine):
        caller_cache = read_queries.enumeration_cache(engine)
        nested = engine._movement_candidates(actor)
        assert read_queries.enumeration_cache(engine) is caller_cache
        assert calls and all(cache is caller_cache for cache in calls)
    assert read_queries.enumeration_cache(engine) is None
    assert bare_calls and len(bare_calls) == len(calls)
    assert all(cache is bare_calls[0] and cache is not None for cache in bare_calls)
    assert [(c.candidate_id, c.destination) for c in bare] == [
        (c.candidate_id, c.destination) for c in nested]
    assert bare
    assert engine.state.model_dump(mode='json') == before
