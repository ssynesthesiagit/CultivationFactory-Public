"""Source-owned temporary growth; geometry and event persistence live in dynamic_size."""
from . import effect, hook
from .. import dynamic_size


@effect("size_change")
def grow(ctx, row):
    from ..typed_executor import effect_expiry
    base = dynamic_size.base_category(ctx.engine, ctx.actor)
    rank = dynamic_size.CATEGORIES.index(base)
    if row.get("size"):
        wanted = row["size"]
    else:
        steps = row.get("steps", 0)
        if type(steps) is not int or steps < 0:
            raise ValueError("Growth requires nonnegative whole size steps.")
        cap = dynamic_size.CATEGORIES.index(row.get("maximum_size", "Gargantuan"))
        wanted = dynamic_size.CATEGORIES[min(cap, rank + steps)]
    expiry = effect_expiry(ctx, row, ctx.actor, condition=True)
    if expiry is None:
        raise ValueError("A size change must have a recognized duration.")
    dynamic_size.apply_growth(ctx.engine, ctx.actor, wanted, ctx.source,
        source_actor_id=ctx.actor.entity_id, expires_on=expiry,
        functional_steps=row.get("functional_steps", 0))


@hook("size_steps")
def functional_size(engine, actor, role, purposes):
    # The actual transformation is already in _footprint; count only the printed
    # additional step for Grappling/Shoving/pushing, never reach or occupied space.
    if not purposes.intersection({"grapple", "shove", "forced"}):
        return None
    extra = max((int(c.data.get("functional_size_steps", 0)) for c in actor.conditions.values()
                 if c.condition_id == dynamic_size.CONDITION), default=0)
    return {"additional": extra} if extra else None
