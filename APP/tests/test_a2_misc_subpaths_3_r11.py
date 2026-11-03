"""Witnessing describes the intersecting route edge after table commit/reload."""
from tests.test_a2_misc_subpaths_3 import setup, mark, move, cold, ME, FOE, MARK, DOOR
from tests.worker2_support import turn


def test_witnessing_detour_uses_crossing_edge_after_cold_reload(tmp_path):
    # The sealed wall prevents the direct northern route and its diagonals.
    # The mover starts north, goes around the west end of the aperture, then
    # crosses the door from south to north in one native movement candidate.
    service, table, mid = setup(tmp_path, [MARK], owner=(5, 6), foe=(2, 5), walls=[{
        'id': 'detour', 'shape': 'rect', 'points': [[3, 3], [4, 6]],
        'filled': True, 'blocks': 'sight_and_movement'}])
    mark(service, table, mid, 'witnessing')
    turn(table, mid, FOE)
    prior = cold(tmp_path, service, mid)
    candidate = next(c for c in prior.legal_candidates() if c.kind == 'MOVE'
                     and c.destination and (c.destination.x, c.destination.y) == (4, 5))
    route = [(p.x, p.y) for p in candidate.canonical_path]
    assert route == [(2, 5), (2, 6), (3, 6), (4, 6), (4, 5)]
    assert candidate.movement_cost_ft == 20
    start = len(prior.events)
    move(service, table, mid, (4, 5))
    engine = cold(tmp_path, service, mid)
    assert (engine.state.actors[FOE].position.x, engine.state.actors[FOE].position.y) == (4, 5)
    receipt = next(e for e in engine.events[start:] if e.event_type == 'MOVEMENT_COMMITTED'
                   and e.actor_id == FOE)
    assert [(p['x'], p['y']) for p in receipt.payload['path']] == route
    assert receipt.payload['cost_ft'] == 20 and receipt.payload['forced'] is False
    notices = [e for e in engine.events[start:] if e.event_type == 'PASSIVE_TRIGGERED'
               and e.actor_id == ME and 'threshold_crossing' in e.payload]
    assert len(notices) == 1
    assert notices[0].payload['threshold_crossing'] == {
        'threshold_id': DOOR, 'creature_id': FOE, 'direction': 'south to north', 'willing': True}
    assert notices[0].payload['log'] == (
        f'{engine.state.actors[FOE].display_name} crosses Wooden gate (south to north; willingly).')
