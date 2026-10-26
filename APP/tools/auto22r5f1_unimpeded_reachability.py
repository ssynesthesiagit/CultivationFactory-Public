"""AUTO22r5f1: exactly where can commit 9aa59948's changed line in combat/motion.py unimpeded() differ from the line
it replaced?  Both expressions are evaluated verbatim, over every price combination the SHIPPED content can produce.

The reviewed head 7a941f91:
    return {cell: kept.get(cell, 1 if cell in cells else cost) for cell, cost in costs.items()}
Head 9aa59948:
    return {cell: (kept[cell] if cell in kept else 1) if cell in cells else cost for cell, cost in costs.items()}

costs[cell] is what combat/zones.py sync_walls built: max(region ground cost, wall move_cost) (zones.py:200-201).
So the two lines can only disagree on a square that is NOT covered by the exemption AND carries a wall price > 1,
and only when costs[cell] (the map's price) != that wall price -- i.e. when the wall is CHEAPER than the ground under it.
"""
OLD = lambda costs, cells, kept: {c: kept.get(c, 1 if c in cells else cost) for c, cost in costs.items()}
NEW = lambda costs, cells, kept: {c: (kept[c] if c in kept else 1) if c in cells else cost for c, cost in costs.items()}

# every move_cost any shipped wall can publish (APP/combat/rules/terrain.json walls.*)
SHIPPED_WALL = {2, 4}
# every movement_cost any shipped map / built-in arena region publishes
SHIPPED_GROUND = {1, 2}   # live maps use normal ground or double-cost rubble/streams
# ground prices a FUTURE map could publish (gate2_grid.py:150 takes any integer)
ALL_GROUND = {1, 2, 3, 4, 5, 6, 8}

print("Price sets below are a snapshot, not a guard against future content changes.")
print(f"{'wall':>5} {'ground':>7} {'map price':>10} | {'case':>9} | {'old':>3} / {'new':>3} | differ?")
print("-" * 78)
shipped_diffs, any_diffs = [], []
for wall in sorted(SHIPPED_WALL):
    for ground in sorted(ALL_GROUND):
        cell = (0, 0)
        map_price = max(ground, wall)          # zones.py:200-201
        costs = {cell: map_price}
        kept = {cell: wall}                    # motion.wall_traversal_cost, kept only when > 1
        for cells in ({cell}, frozenset()):     # covered square, and an uncovered one
            old = OLD(costs, cells, kept)[cell]
            new = NEW(costs, cells, kept)[cell]
            differ = old != new
            tag = "SHIPPED" if ground in SHIPPED_GROUND else "future-map"
            if differ:
                (shipped_diffs if ground in SHIPPED_GROUND else any_diffs).append((wall, ground, cells, old, new))
            if ground in SHIPPED_GROUND or differ:
                case = "covered" if cells else "uncovered"
                print(f"{wall:>5} {ground:>7} {map_price:>10} | {case:>9} | {old:>3} / {new:>3} | "
                      f"{'YES' if differ else 'no'}"
                      + (f"   ({tag})" if differ else ""))

print()
print(f"combinations where old != new AND the ground is shipped: {len(shipped_diffs)}")
print(f"combinations where old != new with a future/custom map:    {len(any_diffs)} -> {any_diffs}")
print()
print("Reading: the two lines differ ONLY on an uncovered square where the wall is cheaper than the ground")
print("beneath it.  No shipped wall (x2, x4) is cheaper than any shipped ground (x1, x2), so with the content")
print("that ships today the changed line is unreachable -- which is exactly why baseline and head are byte-identical")
print("in the replays above, and why the difference is demonstrated by the engine regressions instead.")
