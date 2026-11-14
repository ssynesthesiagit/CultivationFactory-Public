"""Flight diversity for choices and compact seats, using only their legal menu.

No capability is inferred from an ability name: expand_menu copies the engine's
movement mode and price. Both packers use these same representative keys.
"""


def representatives(view, legal, ranked=()):
    """Return one legal route per flight purpose, best scored routes first.

    Reserve ascent, landing/descent, and travel through the air. A ground-to-
    ground flight route can cross an obstacle even when its endpoint has z=0.
    Small budgets retain the first representative; larger frames retain more.
    """
    own = next((a for a in view.get("actors", []) if a["entity_id"] == view["fighter"]), {})
    start = own.get("position") or {}
    height = start.get("z", 0)
    order = {k: i for i, k in enumerate(ranked)}
    groups = {}
    from .tactics import observed_grid
    from combat.gate2_runtime_models import Position
    grid = observed_grid(view)
    ground_start = Position(x=start.get("x", 0), y=start.get("y", 0))
    for key, row in legal.items():
        end = row.get("destination")
        if row.get("action") != "Move" or row.get("movement_mode") != "fly" or not end:
            continue
        z = end.get("z", 0)
        purpose = ("ascend" if z > height else "land" if height and z == 0 else
                   "descend" if z < height else "travel")
        # Scored moves lead; otherwise prefer cheap routes, with actual altitude
        # changes before same-height travel. All ties are deterministic.
        priority = (order.get(key, len(order)), row.get("movement_cost_ft", 0), key)
        if purpose not in groups or priority < groups[purpose][0]:
            groups[purpose] = (priority, key)
        # Crossing a perceived obstruction deserves a separate travel option;
        # the offered engine route, not this sight heuristic, grants legality.
        if ((end["x"], end["y"]) not in grid.blocked | grid.opaque
                and not grid.line_of_sight(ground_start, Position(x=end["x"], y=end["y"]))):
            if "cross" not in groups or priority < groups["cross"][0]:
                groups["cross"] = (priority, key)
    return list(dict.fromkeys(key for _, key in sorted(groups.values(), key=lambda item: (
        legal[item[1]]["destination"].get("z", 0) == height, item[0][0],
        item[0][1], item[1]))))


def movement_label(start, destination, cost):
    """Plain, complete flight direction and price; does not grant permission."""
    height, end = start.get("z", 0), destination.get("z", 0)
    if height and not end:
        direction = "Land"
    elif end > height:
        direction = f"Fly up to {end * 5} ft above ground"
    elif end < height:
        direction = f"Fly down to {end * 5} ft above ground"
    else:
        direction = "Fly"
    return f"{direction} to ({destination['x']},{destination['y']}); spend {cost} ft of movement"
