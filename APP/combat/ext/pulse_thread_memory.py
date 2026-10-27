"""Pulse-Thread Memory: owned seal capacity and private settled-damage readings.

One implementation uses the documented mark_cap, pulse_read, compile_block and
presentation hooks. Ordinary uncapped seals remain uncapped; without a recorded
previous owner turn the reading stays unknown. Only the reader learns the result.
"""
from typing import Any

from . import hook
from .needle import ask, checkpoint_id
from .passive_rows import row_of

FEATURE = "insight.pulse-thread-memory"
BLOCK = "pulse_thread_memory"
CHOICE = "choice:needle.pulse_memory"


@hook("mark_cap")
def seal_capacity(ctx, name):
    if name.lower() == "pulse seal" and row_of(ctx.engine, ctx.actor.entity_id, BLOCK, FEATURE):
        return {"add": 1}
    return None


@hook("compile_block")
def compile_pulse_memory(block: str, spec: dict, row: dict, numbers: dict) -> Any:
    if block == BLOCK:
        return [{**row, "kind": FEATURE}]
    return None


@hook("presentation_hidden_conditions")
def private_pulse_memory(engine: Any, target: Any) -> set[str]:
    """Keep only this Insight's private reading records out of public history/status."""
    from .mind_hidden_eye import LEARNED

    return {iid for iid, held in target.conditions.items()
            if held.condition_id == LEARNED and held.source_definition_id == FEATURE}


@hook("pulse_read")
def pulse_memory(ctx: Any, target: Any) -> None:
    """Read settled damage, recording only the reader's private yes/no snapshot.

    Uses the native TURN_STARTED/DAMAGE_COMMITTED journal producers and the
    shared learned-characteristic ledger (Analyze and Spirit-Trace Pursuit).
    As in Pact-Brother Battle Rhythm, 'last turn' excludes the ongoing turn.
    No recorded earlier turn means unknown, never an invented negative.
    """
    from .mind_hidden_eye import record_characteristic

    if (not row_of(ctx.engine, ctx.actor.entity_id, BLOCK, FEATURE)
            or not sealed_before_activation(ctx, target)):
        return
    starts = [event.sequence for event in ctx.engine.events
              if event.event_type == "TURN_STARTED" and event.actor_id == ctx.actor.entity_id]
    if ctx.engine.state.current_actor_id == ctx.actor.entity_id:
        starts = starts[:-1]
    if not starts:
        return
    since = starts[-1]
    if not ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "pulse_memory", target.entity_id),
               ctx.actor, "choice:needle.pulse_memory", ["learn"], name="Pulse-Thread Memory",
               feature_id=FEATURE, target_id=target.entity_id, allow_decline=True, default="first",
               labels={"learn": "Learn whether this creature took damage since your last turn began"},
               prompt=f"Pulse-Thread Memory: Read the Pulse is reading {target.display_name}, who bears your Pulse Seal. "
                      "Learn whether they took damage since the start of your last turn? No extra action or resource cost; "
                      "this is a snapshot at the time of this reading."):
        return
    damaged = any(event.event_type == "DAMAGE_COMMITTED" and event.sequence >= since
                  and target.entity_id in event.target_ids
                  and int((event.payload or {}).get("hp_damage") or 0)
                      + int((event.payload or {}).get("temporary_hp_absorbed") or 0) > 0
                  for event in ctx.engine.events)
    # Choice checkpoints are addressed to the reader, unlike public history.
    # This acknowledgement delivers the learned fact to a manual reader too.
    ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "pulse_memory_result", target.entity_id),
        ctx.actor, "choice:needle.pulse_memory_result", ["continue"], name="Pulse-Thread Memory",
        feature_id=FEATURE, target_id=target.entity_id, labels={"continue": "Continue"},
        prompt=f"Pulse-Thread Memory — Read the Pulse: {target.display_name} "
               + ("has taken damage" if damaged else "has taken no damage")
               + " since the start of your last turn. This reading is a snapshot; it costs no extra action or resource.")
    # Distinct readings retain their time window; a later negative must never
    # reuse an earlier positive. The ledger hides the fact and learner from
    # the subject's status presentation. No private damage details enter prose.
    reading = ctx.engine.events[-1].sequence
    record_characteristic(ctx.engine, ctx.actor, target,
                          f"Pulse-Thread Memory reading {reading}, since turn {since}", FEATURE,
                          newly_learned=False, value="Took damage" if damaged else "Took no damage")
def sealed_before_activation(ctx, target):
    """Reconstruct the reader-owned seal before this activation refreshes it."""
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
