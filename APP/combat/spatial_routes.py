"""Pure spatial route ties shared by flight and movement_routes.safe_selector.

Only cost-optimal predecessor edges are considered. These queries change no
geometry, movement pricing, destination admission or ability safety priority.
"""


def horizontal_steps(start, predecessors, costs):
    """Minimum horizontal edge count over a strictly increasing-cost DAG."""
    steps = {start: 0}
    for cell in sorted(predecessors, key=lambda c: (costs[c], c)):
        steps[cell] = min(steps[p] + int(p[:2] != cell[:2]) for p in predecessors[cell])
    return steps


def projected_path(start, goal, predecessors, horizontal):
    """Reverse cost-optimal path with the shortest horizontal projection.

    Among equally short projections, prefer parents nearest the start-goal
    line, continuing the horizontal heading, then stable coordinates. Integer
    cross products make ties deterministic. Vertical-only steps do not turn
    the projection. Explicit native route providers retain their priority.
    """
    dx, dy = goal[0] - start[0], goal[1] - start[1]
    chain, heading = [goal], None
    while chain[-1] != start:
        cell = chain[-1]
        def rank(parent):
            direction = (cell[0] - parent[0], cell[1] - parent[1])
            cross = abs(dx * (parent[1] - start[1]) - dy * (parent[0] - start[0]))
            turn = bool(heading and direction != (0, 0) and direction != heading)
            return cross, turn, parent[1], parent[0], parent[2]
        parent = min((p for p in predecessors[cell]
                      if horizontal[p] + int(p[:2] != cell[:2]) == horizontal[cell]), key=rank)
        direction = (cell[0] - parent[0], cell[1] - parent[1])
        if direction != (0, 0):
            heading = direction
        chain.append(parent)
    return chain
