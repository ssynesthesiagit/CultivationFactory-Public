"""Sealed Unmaking Insights; no current authority reads in a retained fight."""
from . import hook
from .passive_rows import row_of
from .needle import CHOICE, ask, checkpoint_id, say

BLOCK = "unmaking_insights"
INITIATE = "insight.black-vein-initiate"
GRIP = "insight.ruin-safe-grip"
USED = "condition:typed.black_vein_initiate_used"


@hook("compile_block")
def compile_rows(block, spec, row, numbers):
    if block != BLOCK:
        return None
    outcomes = {
        INITIATE: "Once per fight, when you would gain Black Vein Strain while you have none, you may take Ruin damage equal to your Proficiency Bonus instead",
        GRIP: "When your External Channel would gain its first Crack, roll a d6: prevent that Crack on 5–6, or 4–6 at Cultivation Level 10",
    }
    return [{**row, "kind": row["feature_id"], "pb": int(numbers["pb"]),
             "cl": int(numbers["cl"]), "choice_owner": 1,
             "player_outcome": outcomes[row["feature_id"]]}]


def owned(engine, actor, feature):
    return row_of(engine, actor.entity_id, BLOCK, feature)


@hook("resource_gain_allowed")
def first_strain(engine, actor, resource_id, amount, source):
    from .. import unmaking
    row = owned(engine, actor, INITIATE)
    if (not row or resource_id != unmaking.STRAIN or amount <= 0
            or str(source).endswith(unmaking.BLACK_STAR_REMAIN)
            or actor.resources.get(resource_id, 0) != 0
            or any(c.condition_id == USED for c in actor.conditions.values())):
        return None
    from .choice_prompt import resource_gain_context

    pb = int(row["pb"])
    picked = ask(engine, getattr(engine, "_active_intent", None),
                 checkpoint_id(engine, "BLACK_VEIN_INITIATE", source, actor.entity_id),
                 actor, CHOICE + "black_vein_initiate", ["damage"], allow_decline=True,
                 name="Black-Vein Initiate", feature_id=INITIATE,
                 target_id=actor.entity_id,
                 prompt_context=resource_gain_context(engine, str(source), actor),
                 labels={"damage": f"Take {pb} Ruin damage instead of {amount} Black Vein Strain"},
                 prompt=f"You have no Black Vein Strain. Take {pb} Ruin damage instead? Once per fight.")
    if not picked:
        return None
    engine._apply_condition(actor, USED, INITIATE, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"used": 1, "label": "Black-Vein Initiate used this fight"})
    unmaking.self_damage(engine, actor, pb, INITIATE)
    say(engine, INITIATE, actor, f"Black-Vein Initiate: {pb} Ruin damage replaces {amount} Black Vein Strain.")
    return False


@hook("channel_crack_amount")
def safe_grip(amount, ctx, weapon_id):
    from . import unmaking_channels as channels
    from ..gate2_runtime_models import DiceSpec
    row = owned(ctx.engine, ctx.actor, GRIP)
    if not row or amount <= 0 or channels.cracks(ctx.actor, weapon_id) != 0:
        return None
    pending = channels.delayed_crack(ctx.actor)
    if pending is not None and pending.data.get("weapon") == weapon_id and int(pending.data.get("count") or 0) > 0:
        return None
    roll = ctx.engine.roller.roll(DiceSpec(count=1, sides=6, modifier=0),
                                  actor_id=ctx.actor.entity_id, reason=f"RUIN_SAFE_GRIP:{ctx.source}:{weapon_id}")
    ctx.engine._record_roll(roll)
    threshold = 4 if int(row["cl"]) >= 10 else 5
    prevented = int(roll.total) >= threshold
    say(ctx.engine, GRIP, ctx.actor,
        f"Ruin-Safe Grip: rolled {roll.total}; {channels.channel_name(ctx.engine, weapon_id)} "
        + ("avoids its first Crack." if prevented else "gains Crack normally."))
    return amount - 1 if prevented else amount
