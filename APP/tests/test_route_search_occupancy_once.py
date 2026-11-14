"""Route search prices a mover's occupancy and passage once, not once per step.

Why this exists: candidate generation cost was O(route steps) in occupancy
rebuilds. Both climbing and roof walking re-ran volume_geometry per edge.
An elevated flying climber generates actual legal candidates at two speeds;
the test counts reads and explored edges within both route searches.
"""
from pathlib import Path

from combat import creature_passage, flight, roof_movement
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_models import Position
from combat.tabletop import normalize_map, to_battlefield

ROOT = Path(__file__).resolve().parents[1]


def engine_at_wall(*, wall_x=4, climb_speed=0, height_ft=10):
    document = normalize_map({
        'display_name': 'Route search occupancy yard', 'width_squares': 18, 'height_squares': 12,
        'background': {'style': 'wood'},
        'walls': [{'shape': 'rect', 'points': [[wall_x, 3], [wall_x + 5, 8]], 'filled': False}],
        'roofs': {'height_ft': height_ft, 'climb_check': 'none'},
    })
    engine = Gate2Engine(ROOT, match_seed='route-search-occupancy', battlefield=to_battlefield(document))
    actor = engine.state.actors[engine.state.current_actor_id]
    for index, other in enumerate(engine.state.actors.values()):
        other.position = Position(x=index, y=11)
    actor.position = Position(x=wall_x - 1, y=5)
    actor.speed_ft = actor.movement_remaining_ft = 30
    actor.climb_speed_ft = climb_speed
    actor.fly_speed_ft = 0
    actor.turn_flags = {}
    return engine, actor


def test_climb_search_reads_occupancy_and_passage_once_however_many_steps(monkeypatch):
    engine, actor = engine_at_wall(climb_speed=30)
    # Start supported on the roof: a flying actor offers both roof walking and climbing.
    actor.position = Position(x=5, y=5, z=2)
    actor.fly_speed_ft = 30
    reads, edges, searches = [], {'walk': 0, 'climb': 0}, {'walk': [], 'climb': []}
    real_geometry = creature_passage.volume_geometry

    def counting(*args, **kwargs):
        reads.append(1)
        return real_geometry(*args, **kwargs)

    monkeypatch.setattr(creature_passage, 'volume_geometry', counting)
    for name, module, search_name in (('walk', flight, '_roof_walking'), ('climb', roof_movement, 'routes')):
        real_search = getattr(module, search_name)
        real_step = module.step_allowed

        def search(*args, _name=name, _real=real_search, **kwargs):
            before_reads, before_edges = len(reads), edges[_name]
            result = _real(*args, **kwargs)
            searches[_name].append((len(reads) - before_reads, edges[_name] - before_edges))
            return result

        def step(*args, _name=name, _real=real_step, **kwargs):
            edges[_name] += 1
            return _real(*args, **kwargs)

        monkeypatch.setattr(module, search_name, search)
        monkeypatch.setattr(module, 'step_allowed', step)

    for speed in (10, 30):
        actor.speed_ft = actor.movement_remaining_ft = speed
        actor.fly_speed_ft = actor.climb_speed_ft = speed
        assert engine.legal_candidates(), 'candidate generation must produce legal options'

    for name, runs in searches.items():
        assert len(runs) == 2, f'{name} search must run once per candidate generation: {runs}'
        assert runs[0][1] > 0 and runs[1][1] > runs[0][1], f'{name} must explore more edges at higher speed: {runs}'
        assert all(count <= 2 for count, _ in runs), f'{name} occupancy reads grew with explored edges: {runs}'
