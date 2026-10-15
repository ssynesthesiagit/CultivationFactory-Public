"""Receipt-aware queries shared by native, flight and granted movement.

Identical receipts are counted, never permuted. A search state is a placement,
remaining counts and the receipts bound to ongoing crossings. Exiting consumes
the binding; re-entry requires another receipt. This is call-local planning,
never execution authority or persisted fight state.
"""
from collections import defaultdict
from itertools import product
import heapq
from types import MappingProxyType

from .creature_passage import grants, limited_grants, planning_scope
from .gate2_runtime_models import Position
from .read_queries import pure


class Reachability(dict):
    """Endpoint quotes, walking run-ups and distinct native-mode alternatives.

    Merged spatial queries keep alternate (destination, route) entries here so
    native candidate binding can expose every mode at a shared destination.
    """
    runups = ()
    alternatives = ()


class Resources:
    def __init__(self, engine, actor):
        from .target_knowledge import actors_for, knowledge
        self.engine, self.actor = engine, actor
        self.occupants = {}
        options = defaultdict(list)
        for other in actors_for(engine, actor):
            if (not other.active or other.entity_id == actor.entity_id
                    or engine._shared_occupancy_pair(actor.entity_id, other.entity_id)):
                continue
            known = knowledge(engine, actor, engine.state.actors[other.entity_id])
            if known is None or known.mode != 'DIRECT':
                continue
            self.occupants[other.entity_id] = other
            for cost, scope, resource in limited_grants(engine, actor, other):
                options[resource].append((other.entity_id, cost, None if scope is None else tuple(sorted(scope))))
        groups = defaultdict(list)
        for resource, rows in sorted(options.items()):
            groups[tuple(sorted(rows, key=repr))].append(resource)
        self.groups = tuple(groups.items())
        self.initial = (tuple(len(ids) for _, ids in self.groups), ())
        self.volume = {who: set(engine._actor_volume(other)) for who, other in self.occupants.items()}
        # Independent/unlimited and prospective grants must not spend receipts.
        with planning_scope(engine, {}):
            self.unlimited = {who: grants(engine, actor, other, preview=True)
                              for who, other in self.occupants.items()}
        self.work = 0

    def overlaps(self, position):
        cells = set(self.engine._actor_volume(self.actor, position))
        return {who: cells & volume for who, volume in self.volume.items() if cells & volume}

    def assignment(self, counts, bindings):
        assignment = {}
        for index, (rows, ids) in enumerate(self.groups):
            bound = [who for who, groups in bindings for group in groups if group == index]
            for resource, who in zip(ids, bound):
                assignment[resource] = who
            # Diagonal clearance can touch a side placement without entering
            # its occupant. Unspent receipts still permit that clearance;
            # actual footprint entry is allocated separately by advance().
            for resource in ids[len(bound):len(bound)+counts[index]]:
                assignment[resource] = tuple(sorted({who for who, _, _ in rows} - {who for who, _ in bindings}))
        return assignment

    @staticmethod
    def covered(rows, cells):
        return set().union(*(cells if scope is None else cells & set(scope) for _, scope in rows)) if rows else set()

    def advance(self, state, previous, destination):
        """Yield distinct legal inventories/bindings and their per-edge geometry.

        Scoped grants can compose. Identical inventory units branch once. The
        old binding remains available for the exit edge but not for re-entry.
        """
        self.work += 1
        counts, bindings = state
        before, after = self.overlaps(previous), self.overlaps(destination)
        current = dict(bindings)
        def bound_rows(who):
            return [(cost, scope) for group in current.get(who, ())
                    for target, cost, scope in self.groups[group][0] if target == who]
        pending = [(who, cells) for who, cells in sorted({**before, **after}.items())
                   if who not in current or not cells <= self.covered(self.unlimited[who] + bound_rows(who), cells)]

        def allocate(index, remaining, bound):
            if index == len(pending):
                edge = tuple(sorted(bound.items()))
                following = tuple((who, groups) for who, groups in edge if who in after)
                yield (remaining, following), self.assignment(remaining, edge)
                return
            who, cells = pending[index]
            base = self.covered(self.unlimited[who] + bound_rows(who), cells)
            choices = []
            for group, (rows, _) in enumerate(self.groups):
                if remaining[group]:
                    covered = self.covered([(cost, scope) for target, cost, scope in rows if target == who], cells)
                    if covered:
                        choices.append((group, covered))

            def cover(start, covered, selected):
                if cells <= covered:
                    # Actual entry binds a held receipt even when another
                    # provider already permits passage. Do not quote saving it
                    # for a later, more expensive footprint.
                    if selected or not choices or who in current:
                        updated = list(remaining)
                        for group in selected:
                            updated[group] -= 1
                        yield from allocate(index + 1, tuple(updated), {**bound, who: tuple(current.get(who, ())) + tuple(selected)})
                        return
                for offset in range(start, len(choices)):
                    group, extra = choices[offset]
                    if extra - covered or not selected:
                        yield from cover(offset + 1, covered | extra, selected + [group])
            yield from cover(0, base, [])

        yield from allocate(0, counts, current)


def path_cost(engine, actor, path, mode):
    """Price adjacent steps with one receipt per transit episode, or reject."""
    from . import flight
    from .creature_passage import geometry
    resources = Resources(engine, actor)
    states = {resources.initial: 0}
    for previous, destination in zip(path, path[1:]):
        following = {}
        for state, spent in states.items():
            for next_state, assignment in resources.advance(state, previous, destination):
                with planning_scope(engine, assignment):
                    if not flight.step_allowed(engine, actor, previous, destination, mode=mode, observed=True):
                        continue
                    difficult = engine._hostile_difficult_cells(actor) | geometry(engine, actor, observed=True)[2]
                    cost = spent + flight.step_cost(engine, actor, previous, destination, mode, difficult)
                    if mode == 'climb':
                        from .roof_movement import step_mode
                        if cost > flight.remaining(engine, actor, step_mode(engine, actor, previous, destination)):
                            continue
                following[next_state] = min(cost, following.get(next_state, cost))
        if not following:
            raise ValueError('Granted movement requires a legal path of adjacent spaces')
        states = following
    return min(states.values())


@pure
def reachable(engine, actor, feet, mode='walk', *, path_selector=None):
    """All feasible free endpoints, including detours; no option count cap.

    Ordinary movement keeps its existing search and tie selector. This search
    is used only for current limited receipts and retains inventories at each
    placement so a cheap spent-receipt path cannot displace a feasible detour.
    """
    from . import flight
    from .creature_passage import geometry
    from .voluntary_movement import edge_predicate
    from .falling import supported
    resources = Resources(engine, actor)
    if not resources.groups:
        return None
    if not actor.active or engine._effective_speed(actor) <= 0:
        return {}
    restriction = edge_predicate(engine, actor)
    start = actor.position
    # The last heading and up to two consecutive steps distinguish running
    # approaches without retaining every complete route to a placement.
    initial = (start.x, start.y, start.z, resources.initial, bool(actor.climbing) if mode == 'climb' else False, (0, 0, 0))
    costs, paths = {initial: 0}, {initial: (start,)}
    predecessors = {}
    queue = [(0, 0, initial)]
    serial = 0
    frontier = defaultdict(set)
    frontier[(start.x, start.y, start.z, (), initial[4], initial[5])].add(initial)
    edge_costs = {}
    advances = {}
    results = Reachability()
    occupied = engine._occupied_volumes_except(actor.entity_id, observed=True)
    offsets = tuple(d for d in product((-1, 0, 1), repeat=3) if d != (0, 0, 0) and (mode == 'fly' or not d[2]))
    if mode == 'climb':
        offsets += ((0,0,-1),(0,0,1))
    while queue:
        spent, _, key = heapq.heappop(queue)
        if spent != costs.get(key) or spent >= feet:
            continue
        previous = Position(x=key[0], y=key[1], z=key[2])
        if mode == 'walk' and previous.z and not supported(engine, actor, previous):
            continue
        for dx, dy, dz in offsets:
            if not (0 <= previous.x+dx < engine.grid.width and 0 <= previous.y+dy < engine.grid.height and previous.z+dz >= 0):
                continue
            destination = Position(x=previous.x+dx, y=previous.y+dy, z=previous.z+dz)
            if restriction is not None and not restriction(previous, destination):
                continue
            # Different run-up histories reuse the exact same inventory edge.
            advance_key = (key[:4], destination.x, destination.y, destination.z)
            if advance_key not in advances:
                advances[advance_key] = tuple(resources.advance(key[3], previous, destination))
            for state, assignment in advances[advance_key]:
                edge = (previous.x,previous.y,previous.z,destination.x,destination.y,destination.z,tuple(sorted(assignment.items())))
                if edge not in edge_costs:
                    with planning_scope(engine, assignment):
                        if not flight.step_allowed(engine, actor, previous, destination, mode=mode, observed=True):
                            edge_costs[edge] = None
                        else:
                            difficult = engine._hostile_difficult_cells(actor) | geometry(engine, actor, observed=True)[2]
                            edge_costs[edge] = flight.step_cost(engine, actor, previous, destination, mode, difficult)
                if edge_costs[edge] is None:
                    continue
                total = spent + edge_costs[edge]
                climbed = key[4]
                if mode == 'climb':
                    from .roof_movement import step_mode
                    step = step_mode(engine, actor, previous, destination)
                    if total > flight.remaining(engine, actor, step):
                        continue
                    climbed |= step == 'climb'
                heading = (dx, dy, min(2, key[5][2] + 1) if key[5][:2] == (dx, dy) else 1) if mode == 'walk' else (0, 0, 0)
                next_key = (destination.x, destination.y, destination.z, state, climbed, heading)
                if total > feet or total > costs.get(next_key, feet+1):
                    continue
                if total == costs.get(next_key):
                    predecessors[next_key].add(key)
                    continue
                bucket = frontier[(destination.x,destination.y,destination.z,state[1],climbed,heading)]
                # A strictly cheaper state with more equivalent receipts can
                # perform every future crossing. Equal costs retain safety ties.
                if any(costs[old] < total and all(a >= b for a,b in zip(old[3][0],state[0])) for old in bucket):
                    continue
                for old in tuple(bucket):
                    if total < costs[old] and all(a >= b for a,b in zip(state[0],old[3][0])):
                        bucket.remove(old)
                        costs.pop(old)
                        predecessors.pop(old, None)
                bucket.add(next_key)
                serial += 1
                costs[next_key] = total
                paths[next_key] = paths[key] + (destination,)
                predecessors[next_key] = {key}
                heapq.heappush(queue, (total, serial, next_key))
    selected = path_selector(initial, MappingProxyType({key: frozenset(rows) for key, rows in predecessors.items()}),
                             MappingProxyType(costs)) if path_selector else {}
    ranks = getattr(selected, 'ranks', {})
    best = {}
    for key, total in costs.items():
        if key in selected:
            paths[key] = tuple(Position(x=p[0], y=p[1], z=p[2]) for p in selected[key])
        destination = paths[key][-1]
        if (destination != start and (mode != 'climb' or key[4])
                and engine.grid.volume_legal(destination, footprint=engine._footprint(actor), occupied_cells=occupied)):
            rank = (total, ranks.get(key, (0, 0)))
            if destination not in best or rank < best[destination]:
                best[destination] = rank
                results[destination] = (paths[key], total, mode)
    if mode == 'walk':
        results.runups = tuple((paths[key],cost,'walk') for key,cost in costs.items()
            if engine.grid.volume_legal(paths[key][-1],footprint=engine._footprint(actor),occupied_cells=occupied))
    return results
