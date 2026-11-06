"""Draw the Line's Guide benefit, using existing native attack/mark seams.

Only a hit by the owned, compiled Guide option creates the grant. The ordinary
marker clock expires it at the end of the source's next turn. Cover queries are
pure; the next actual attack roll against this target consumes it even on a
miss or when there was no half cover. Other attackers and targets are inert.
This does not supply stock, anchor, object or line-handling scene facts.
"""
from . import hook
from .condition_ownership import refresh_owned, remove_instance
from .thread_common import mark_condition_id

DRAW = "THREAD_BASE_DRAW_THE_LINE"
GUIDE = "Thread Guide"


def grants(target, owner_id):
    """Source-owned Guide instances; shared by cover and roll consumption."""
    cid = mark_condition_id(owner_id, GUIDE)
    return [(iid, c) for iid, c in target.conditions.items()
            if c.condition_id == cid and c.source_actor_id == owner_id]


@hook("after_hit")
def guide_hit(ctx, target, kind):
    if ctx.typed.get("option_of") != DRAW or ctx.typed.get("option_label") != "Guide":
        return
    if not target.active:
        return
    cid = mark_condition_id(ctx.actor.entity_id, GUIDE)
    refresh_owned(ctx.engine, target, cid, ctx.actor.entity_id, ctx.source)
    ctx.engine._apply_condition(target, cid, ctx.source, ctx.actor.entity_id,
        expires_on="END_OF_MARKER_NEXT_TURN",
        data={"marker_turn": int(ctx.actor.turns_started),
              "label": f"Draw the Line — Guide: {ctx.actor.display_name}'s next attack against "
                       f"{target.display_name} ignores half cover until the end of their next turn (no extra cost)."})


@hook("cover_reduction")
def guide_cover(engine, attacker, target, cover):
    # Three-quarters and total cover are outside the printed benefit.
    return 1 if cover == 2 and grants(target, attacker.entity_id) else None


@hook("event", nested=True)
def consume_guide(engine, event_type, kwargs):
    if event_type != "ATTACK_ROLLED":
        return
    owner_id = kwargs.get("actor_id")
    for target_id in kwargs.get("target_ids") or ():
        target = engine.state.actors.get(target_id)
        if target is not None:
            for iid, _condition in grants(target, owner_id):
                remove_instance(engine, target, iid, kwargs.get("source_definition_id") or DRAW)
