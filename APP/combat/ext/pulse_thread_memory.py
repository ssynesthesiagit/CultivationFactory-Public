"""Pulse Thread Memory: owned extra seal capacity and optional injury history.

Uses mark_cap and pulse_read, without inventing a base limit where authority
leaves seals uncapped. The reading discloses only a yes/no fact, not damage
amount, attacker, source or hidden creature details. Committed events survive
cold reload and contain actual damage (including absorption by Temporary HP).
"""
from . import hook, note
from .needle import ask, checkpoint_id, option_spec
from .passive_rows import row_of

FEATURE = "insight.pulse-thread-memory"
BLOCK = "pulse_thread_memory"
CHOICE = "choice:insights7.pulse_thread_memory"


@hook("choice_options")
def reading_options(engine, intent, checkpoint, reactor_id, choice_id, context):
    return option_spec(choice_id, context, CHOICE)


@hook("compile_block")
def compile_rows(block, spec, row, numbers):
    if block != BLOCK:
        return None
    return [{**row, "kind": BLOCK,
             "player_outcome": "Maintain one additional Pulse Seal; Read the Pulse can reveal whether a sealed creature took damage since the start of your last turn."}]


@hook("mark_cap")
def seal_capacity(ctx, name):
    if name.lower() == "pulse seal" and row_of(ctx.engine, ctx.actor.entity_id, BLOCK, BLOCK):
        return {"add": 1}
    return None


@hook("pulse_read")
def injury_history(ctx, target):
    if (row_of(ctx.engine, ctx.actor.entity_id, BLOCK, BLOCK) is None
            or not sealed_before_activation(ctx, target)):
        return
    chosen = ask(ctx.engine, ctx.intent,
        checkpoint_id(ctx.engine, "PULSE_THREAD_MEMORY", target.entity_id),
        ctx.actor, CHOICE, ["read"],
        labels={"read": "Learn whether this creature has taken damage"},
        preferred=["read"], allow_decline=True, target_id=target.entity_id,
        prompt=f"Pulse Thread Memory: {ctx.actor.display_name} uses {ctx.action.display_name} on {target.display_name}, "
               "who bears your Pulse Seal. Learn whether it has taken damage since the start of your last turn? "
               "This costs no extra action or CP and reveals no damage amount or cause.")
    if not chosen:
        return
    starts = [event.sequence for event in ctx.engine.events
              if event.event_type == "TURN_STARTED" and event.actor_id == ctx.actor.entity_id]
    # On your turn, 'last turn' is the preceding turn; on another turn it is
    # your most recent turn. Before a preceding turn exists, use scene start.
    previous = starts[:-1] if ctx.engine.state.current_actor_id == ctx.actor.entity_id else starts
    since = previous[-1] if previous else 0
    hurt = any(event.sequence >= since and event.event_type == "DAMAGE_COMMITTED"
               and target.entity_id in event.target_ids and int(event.payload.get("reduced_to") or 0) > 0
               for event in ctx.engine.events)
    note(ctx.engine, FEATURE, ctx.actor,
         f"Pulse Thread Memory: {target.display_name} has {'taken damage' if hurt else 'not taken damage'} "
         "since the start of your last turn.", targets=(target,), took_damage=int(hurt))


def sealed_before_activation(ctx, target):
    """Read the seal at activation start, before Read the Pulse refreshes it.

    The ordinary effect list places/refreshes a seal before its diagnosis.
    Reconstructing just this owned mark from committed receipts prevents a new
    seal in the same activation from qualifying its own optional history.
    No live sheet or unrepresented knowledge is consulted.
    """
    from ..typed_executor import mark_condition_id
    boundary = next((event.sequence for event in reversed(ctx.engine.events)
                     if event.event_type == "INTENT_ACCEPTED"), ctx.engine.state.event_sequence + 1)
    condition_id = mark_condition_id("Pulse Seal", ctx.actor.entity_id)
    instances = set()
    for event in ctx.engine.events:
        if event.sequence >= boundary:
            break
        if target.entity_id not in event.target_ids or event.payload.get("condition_id") != condition_id:
            continue
        if event.event_type == "CONDITION_APPLIED":
            instances.add(event.payload.get("instance_id"))
        elif event.event_type == "CONDITION_REMOVED":
            instances.discard(event.payload.get("instance_id"))
    return bool(instances)
