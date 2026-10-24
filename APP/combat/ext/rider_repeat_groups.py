"""A successful repeat save ends the complete declared effect group.

``rider_repeat_group`` wraps conditions/modifiers applied by one failed-save
branch, recording only newly created instance IDs and the repeat-save anchor.
At the turn-end boundary after the engine resolves repeat saves, losing the
anchor removes the recorded companions and modifiers. It preserves effects
from other casts and casters and emits ordinary removal events. The original
repeat-save condition remains responsible for rolling and expiring.

Concentration anchor-removal events also remove companion conditions with an
earlier, independent deadline before concentration cleanup removes the ledger. The
engine still owns concentration-expiring rows; removing those inside its
condition sweep would invalidate that sweep's captured instance list.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from . import effect, hook

PREFIX = "condition:typed.rider_repeat_group."


@effect("rider_repeat_group")
def group(ctx: Any, spec: dict[str, Any]) -> None:
    from .. import typed_executor as te

    for subject in ctx.targets or ([ctx.target] if ctx.target else []):
        before_c, before_m = set(subject.conditions), set(subject.modifiers)
        te.run_effects(replace(ctx, targets=[subject], target=subject), spec.get("effects") or [])
        conditions = sorted(set(subject.conditions) - before_c)
        anchors = [iid for iid in conditions if subject.conditions[iid].data.get("repeat_save")]
        if anchors:
            conc = ctx.actor.concentration
            ctx.engine._apply_condition(subject, PREFIX + te._mark_slug(spec["name"]), ctx.source, ctx.actor.entity_id,
                                        expires_on=te.effect_expiry(ctx, spec, subject, condition=True),
                                        data={"conditions": conditions, "anchors": anchors,
                                              "modifiers": sorted(set(subject.modifiers) - before_m), "label": spec["name"],
                                              "concentration_sequence": conc.started_sequence if spec.get("ends_concentration")
                                              and conc and conc.source_definition_id == ctx.source else None})


@hook("event", nested=True)
def anchor_removed(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """End independently timed conditions when concentration loses its last anchor.

    The ledger is created after its anchors, so concentration's ordered sweep
    delivers their removal while it still exists, including in old saved
    groups. Only recorded instance IDs are removed, preserving other casts.
    Nested delivery covers held concentration and loss inside another hook.
    """
    if event_type != "CONDITION_REMOVED":
        return
    event = kwargs.get("originating_event")
    if event is None:
        return
    payload = event.payload or {}
    # Concentration removal supplies a reason, whereas ordinary turn expiry
    # and repeat saves supply a checkpoint and keep the turn-end cleanup path.
    if not payload.get("reason"):
        return
    removed = payload.get("instance_id")
    for target_id in event.target_ids:
        holder = engine.state.actors.get(target_id)
        if holder is None:
            continue
        for ledger in list(holder.conditions.values()):
            if (not ledger.condition_id.startswith(PREFIX) or ledger.expires_on != "CONCENTRATION_END"
                    or removed not in ledger.data["anchors"]
                    or any(iid in holder.conditions for iid in ledger.data["anchors"])):
                continue
            for iid in ledger.data["conditions"]:
                companion = holder.conditions.get(iid)
                if companion is None or companion.expires_on == "CONCENTRATION_END":
                    continue
                del holder.conditions[iid]
                engine._append_event("CONDITION_REMOVED", ledger.source_definition_id,
                                     actor_id=ledger.source_actor_id, target_ids=(holder.entity_id,),
                                     payload={"condition_id": companion.condition_id, "instance_id": iid})


@hook("turn_end")
def repeat_ended(engine: Any, actor: Any) -> None:
    for holder in engine.state.actors.values():
        for ledger in list(holder.conditions.values()):
            if not ledger.condition_id.startswith(PREFIX) or any(iid in holder.conditions for iid in ledger.data["anchors"]):
                continue
            source, owner = ledger.source_definition_id, ledger.source_actor_id
            for iid in [*ledger.data["conditions"], ledger.instance_id]:
                condition = holder.conditions.pop(iid, None)
                if condition:
                    engine._append_event("CONDITION_REMOVED", source, actor_id=owner, target_ids=(holder.entity_id,),
                                         payload={"condition_id": condition.condition_id, "instance_id": iid})
            for mid in ledger.data["modifiers"]:
                if holder.modifiers.pop(mid, None):
                    engine._append_event("MODIFIER_REMOVED", source, actor_id=holder.entity_id, target_ids=(holder.entity_id,),
                                         payload={"modifier_id": mid})
            sequence = ledger.data.get("concentration_sequence")
            remaining = any(c.condition_id.startswith(PREFIX) and c.source_actor_id == owner
                            and c.source_definition_id == source and c.data.get("concentration_sequence") == sequence
                            for target in engine.state.actors.values() for c in target.conditions.values())
            caster = engine.state.actors.get(owner)
            if sequence is not None and not remaining and caster is not None:
                conc = caster.concentration
                if conc and conc.source_definition_id == source and conc.started_sequence == sequence:
                    engine._end_concentration(caster, "REPEAT_EFFECT_ENDED")
                else:
                    from .. import concentration

                    for iid, held in concentration.held(caster):
                        if held.source_definition_id == source and held.started_sequence == sequence:
                            concentration.end_held(engine, caster, iid, "REPEAT_EFFECT_ENDED")
