"""Public, opt-in Asset/Anchor runtime for the abilities that place one.

"create(engine, owner, source, profile, position, *, component, lifetime=None)"
validates a source-scoped physical profile, checks the whole occupied volume and
its support, and commits exactly one ordinary object event (OBJECT_UPDATED).
"members(engine, owner_id=None, group=None, live=True)" queries the works a
source placed, read from committed objects only. "legal_placement" is the same
volume check for candidate enumeration, and "stable" answers whether one cell
has support. "retire(engine, obj, source)" ends exactly that object without
repairing damage or changing its statistics.

No caller means no object, no event and no change to existing saves; nothing is
inferred from a name, a team or narration. Profiles and declarations belong to
the calling source, never to ability ids here.
"""
from .gate2_runtime_models import Position, RuntimeObjectState
from .object_geometry import target_cells

KEY = "asset_anchor_runtime"


def members(engine, owner_id=None, group=None, *, live=True):
    """The works this runtime placed, newest state only."""
    return [obj for obj in engine.state.objects.values() if (obj.component or {}).get(KEY)
            and (owner_id is None or obj.owner_id == owner_id)
            and (group is None or obj.component[KEY].get("group") == group)
            and (not live or not obj.destroyed)]


def stable(engine, position, *, ignore=()):
    """Whether one cell of a work has support: ground, roof, terrain or a structure below.

    A ground-level cell needs legal open volume. Higher cells stand on a roof, on blocked
    terrain directly below, or on a structure object whose top meets them.
    """
    if position.z == 0:
        return engine.grid.volume_legal(position)
    if engine.grid.roof_supported(position, None):
        return True
    if engine.grid.terrain_at((position.x, position.y, position.z - 1), "BLOCKED"):
        return True
    return any(not obj.destroyed and obj.object_id not in ignore
               and (obj.component or {}).get("structure") and obj.height_ft is not None
               and obj.position.z + (obj.height_ft + 4) // 5 == position.z
               and any((cell.x, cell.y) == (position.x, position.y) for cell in target_cells(engine, obj))
               for obj in engine.state.objects.values())


def legal_placement(engine, cells, height_ft, *, ignore=(), require_support=True,
                    preview=False, viewer=None):
    """Whether a work of this footprint and height may stand on these cells.

    Every cell of the full volume must be in bounds and open, no active creature and no
    other work may share it, and at least one of the work's own cells needs support unless
    the caller is moving a work that already stands. Candidate previews may pass a viewer;
    only directly known creatures then block the offer, while execution checks all bodies.
    """
    if type(height_ft) is not int or height_ft < 1 or not cells:
        return False
    if any(oid in engine.state.objects and (engine.state.objects[oid].component or {}).get("blocks") for oid in ignore):
        return legal_placement(_without_works(engine, ignore), cells, height_ft,
                               require_support=require_support, preview=preview, viewer=viewer)
    volume = {(cell.x, cell.y, z) for cell in cells for z in range(cell.z, cell.z + (height_ft + 4) // 5)}
    if len({(cell.x, cell.y, cell.z) for cell in cells}) != len(cells):
        return False
    if any(not engine.grid.volume_legal(Position(x=x, y=y, z=z)) for x, y, z in volume):
        return False
    if preview:
        if viewer is None:
            raise ValueError("Preview placement requires its observing actor.")
        from .target_knowledge import actors_for, knowledge
        actors = [actor for actor in actors_for(engine, viewer)
                  if (known := knowledge(engine, viewer, engine.state.actors[actor.entity_id])) is not None
                  and known.mode == "DIRECT"]
    else:
        actors = engine.state.actors.values()
    if any(volume & set(engine._actor_volume(actor)) for actor in actors if actor.active):
        return False
    for obj in engine.state.objects.values():
        if obj.destroyed or obj.object_id in ignore:
            continue
        occupied = {(cell.x, cell.y, z) for cell in target_cells(engine, obj)
                    for z in range(cell.z, cell.z + max(1, ((obj.height_ft or 5) + 4) // 5))}
        if volume & occupied:
            return False
    return not require_support or any(stable(engine, cell, ignore=ignore) for cell in cells)


def _without_works(engine, ignore):
    """Query-local copy without these works, with derived walls and roof rebuilt.

    Only used when a relocated work is a wall (blocks): its old wall must never block its
    own new cells. Nothing here is committed; the real engine is untouched.
    """
    from copy import copy, deepcopy
    shadow = copy(engine)
    if hasattr(engine, "session"):
        from .journey_assets import grid_for
        shadow.grid = grid_for(engine.session, ignore=ignore)
        shadow.state = copy(engine.state)
        shadow.state.objects = {k: o for k, o in engine.state.objects.items() if k not in ignore}
    else:
        shadow.grid = deepcopy(engine.grid)
        shadow.state = engine.state.model_copy(update={"objects": {k: o for k, o in engine.state.objects.items() if k not in ignore}})
        from . import zones
        zones.sync_walls(shadow)
    return shadow


def create(engine, owner, source, profile, position, *, component, lifetime=None):
    """Commit one work at "position"; return the object, never a transient record.

    The profile is the printed stat block (name, kind, AC, HP, Source CL, height, group)
    plus any explicit saving-throw bonus, immunities or resistances the source states.
    Placement is re-checked here so a work is never committed inside a body or through
    terrain, even when no menu produced the position.
    """
    required = ("name", "kind", "ac", "hp", "source_cl", "height_ft", "group")
    if any(key not in profile for key in required):
        raise ValueError("Asset profile requires name, kind, AC, HP, Source CL, height and group.")
    if any(type(profile[key]) is not int or profile[key] < 1 for key in ("ac", "hp", "source_cl", "height_ft")):
        raise ValueError("Asset statistics must be positive integers.")
    if "saving_throw_bonus" in profile and type(profile["saving_throw_bonus"]) is not int:
        raise ValueError("An explicit Asset saving-throw bonus must be an integer.")
    if not isinstance(source, str) or not source or not owner.entity_id or engine.state.actors.get(owner.entity_id) is not owner:
        raise ValueError("Asset creation requires its native owner and source.")
    sequence = max([engine.state.event_sequence, *[int(obj.component[KEY]["sequence"])
                    for obj in members(engine, owner.entity_id, live=False)]]) + 1
    obj = RuntimeObjectState(object_id=f"object:asset:{owner.entity_id}:{sequence}",
        object_kind=profile["kind"], owner_id=owner.entity_id, position=position,
        unattended=True, flammable=False, ac=profile["ac"], current_hp=profile["hp"], maximum_hp=profile["hp"],
        damage_threshold=int(profile.get("threshold", 0)),
        damage_immunities=tuple(profile.get("immune", ("POISON", "PSYCHIC"))),
        height_ft=profile["height_ft"], destroyed=False,
        component={**component, "name": profile["name"], "source_cl": profile["source_cl"],
            **({"saving_throw_bonus": profile["saving_throw_bonus"]} if "saving_throw_bonus" in profile else {}),
            "created_by": source, "resist": list(profile.get("resist", ())),
            KEY: {"owner": owner.entity_id, "source": source, "group": profile["group"],
                  "sequence": sequence, "lifetime": lifetime or ""}})
    cells = target_cells(engine, obj)
    if not legal_placement(engine, cells, obj.height_ft):
        raise ValueError("The work needs unoccupied spaces connected to stable support.")
    if component.get("blocks") and seals_airspace(engine, cells, obj.height_ft):
        raise ValueError("A structure cannot seal a creature inside an airtight space.")
    engine._update_object(obj, source, owner.entity_id)
    refresh(engine)
    return obj


def retire(engine, obj, source):
    """Mark exactly this work ended; its statistics and damage stay as recorded."""
    component = obj.component or {}
    if KEY in component:
        component = {**component, KEY: {**component[KEY], "ended": True}}
    engine._update_object(obj.model_copy(update={"destroyed": True, "current_hp": 0, "component": component}),
                          source, obj.owner_id)
    refresh(engine)


def refresh(engine):
    """Re-sync the derived grid after a work appears or ends (native combat or a journey grid)."""
    if hasattr(engine, "asset_runtime_refresh"):
        engine.asset_runtime_refresh()
    else:
        from . import zones
        zones.sync_walls(engine)


def repair_allowed(obj, source_cl, *, material=False):
    c=obj.component or {}
    if obj.current_hp is None or obj.maximum_hp is None or c.get('specialist_reconstruction'):
        return False
    if c.get('artifact') and obj.destroyed:
        return False
    if obj.destroyed and not material:
        return False
    if c.get('repair_allowed') is False or c.get('absolute_repair_protection'):
        return False
    return True


def seals_airspace(engine,cells,height_ft):
    """Whether this solid addition closes the last native air route of a creature.

    Uses committed terrain/roof/object volumes. An existing sealed space is not
    attributed to the new work. Open sky remains an outlet; support never implies
    a ceiling. Called at actual creation, not while enumerating hidden choices.
    """
    from collections import deque
    ceilings=[*(getattr(engine.grid.roof_geometry,'heights',()) or ()),height_ft]
    ceilings += [int(o.position.z*5+(o.height_ft or 5)) for o in engine.state.objects.values() if not o.destroyed]
    top=max(ceilings,default=10)//5+2
    existing={(c.x,c.y,z) for obj in engine.state.objects.values() if not obj.destroyed
        and not ((obj.component or {}).get('air_passage') or (obj.component or {}).get('mechanism',{}).get('open'))
        for c in target_cells(engine,obj) for z in range(c.z,c.z+max(1,((obj.height_ft or 5)+4)//5))}
    addition={(c.x,c.y,z) for c in cells for z in range(c.z,c.z+(height_ft+4)//5)}
    def reaches_air(start,blocked):
        seen={start};queue=deque([start])
        while queue:
            x,y,z=queue.popleft()
            if z>=top or x in (0,engine.grid.width-1) or y in (0,engine.grid.height-1):return True
            for dx,dy,dz in ((1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)):
                key=(x+dx,y+dy,z+dz)
                if key in seen or key in blocked or key[2]<0:continue
                if not engine.grid.volume_legal(Position(x=key[0],y=key[1],z=key[2])):continue
                seen.add(key);queue.append(key)
        return False
    for actor in engine.state.actors.values():
        if not actor.active:continue
        start=(actor.position.x,actor.position.y,actor.position.z)
        if reaches_air(start,existing) and not reaches_air(start,existing|addition):return True
    return False
