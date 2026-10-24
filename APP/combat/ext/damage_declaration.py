"""General explicit damage declaration before a save or another consequence.

Typed actions place declare_damage_type before their save. The declaration is
activation-local, shared by full/half damage, and never consults hidden target
defenses. Manual/Ask owners use the normal transactional choice checkpoint;
automatic actors use the source's first legal type. Used by Last-Inch Palm.
"""
from . import effect, hook

KEY = "declared_damage_type"


@effect("declare_damage_type", harmful=False)
def declare(ctx, row):
    from . import needle
    kinds = list(dict.fromkeys(str(k).upper() for k in row["damage_types"]))
    if not kinds:
        raise ValueError("A damage declaration needs legal types")
    target = ctx.target or next(iter(ctx.targets or []), None)
    target_name = target.display_name if target is not None else "the declared targets"
    selected = needle.ask(ctx.engine, ctx.intent,
        needle.checkpoint_id(ctx.engine, "DAMAGE_DECLARATION", ctx.source), ctx.actor,
        "choice:needle.damage_declaration", kinds, labels={k: k.title() + " damage" for k in kinds},
        prompt=f"{ctx.action.display_name}: choose the damage type for {target_name} before its saving throw.",
        name=ctx.action.display_name, target_id=getattr(target, "entity_id", None))
    ctx.damage_cache[(KEY, ctx.source)] = selected[0] if selected else kinds[0]


@hook("damage_type_override")
def declared_type(ctx, kinds, targets):
    selected = ctx.damage_cache.get((KEY, ctx.source))
    return selected if selected in kinds else None
