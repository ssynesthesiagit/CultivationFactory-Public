"""Source-owned, single-jump receipts for typed benefits (Wind Lash Lift).

Consent belongs to the recipient. Quotes and preparation are pure; settlement
removes only the prepared instances after actual jump travel, never a cancelled
route or a run-up that stopped before takeoff. Native source-turn expiry handles
unused receipts, including after a cold reload.
"""

from . import effect

RECEIPT = "condition:typed.next_jump_receipt"


@effect("prepare_next_jump")
def grant(ctx, row):
    """Opt-in typed effect: feet, consent, label; source owns the expiry clock."""
    from .willing_targets import asks_consent

    subject = ctx.target
    feet = int(row.get("feet") or 0)
    if subject is None or feet <= 0:
        return
    label = str(row.get("label") or ctx.action.display_name)
    if row.get("consent") and not asks_consent(
            ctx.engine, ctx.intent, subject, label,
            f"{ctx.actor.display_name}'s {label} hit {subject.display_name}: accept a "
            f"{feet}-foot increase to your next jump before the start of "
            f"{ctx.actor.display_name}'s next turn? This costs no Reaction.",
            prefer_accept=subject.team_id == ctx.actor.team_id, asker=ctx.actor):
        return
    ctx.engine._apply_condition(
        subject, RECEIPT, ctx.source, ctx.actor.entity_id,
        expires_on="START_OF_SOURCE_NEXT_TURN",
        data={"feet": feet, "label": f"{label}: next jump increases {feet} feet; "
              f"ends at the start of {ctx.actor.display_name}'s next turn"})


def bonus(engine, actor):
    """Pure flat-feet quote. Repeated copies of one source do not stack."""
    sources = {}
    for held in actor.conditions.values():
        if held.condition_id == RECEIPT:
            key = held.source_definition_id
            sources[key] = max(sources.get(key, 0), int(held.data.get("feet") or 0))
    return sum(sources.values())


def prepare(engine, actor, mode, path):
    """Pure accepted-route snapshot; no receipt is reserved or spent yet."""
    if mode not in ("jump", "jump_down"):
        return ()
    return tuple(held.instance_id for held in actor.conditions.values()
                 if held.condition_id == RECEIPT)


def commit(engine, actor, mode, prepared, traversed):
    """Settle exact prepared instances only after a real takeoff/edge step.

    An interrupted jump that already took off still is that next jump. An
    interrupted run-up, zero-step route, or failed validation is not.
    """
    if not prepared:
        return
    from ..falling import supported

    success = (mode == "jump" and any(b.z > a.z for a, b in zip(traversed, traversed[1:])))
    success = success or (mode == "jump_down" and any(
        supported(engine, actor, a) and not supported(engine, actor, b)
        for a, b in zip(traversed, traversed[1:])))
    if not success:
        return
    for instance_id in prepared:
        held = actor.conditions.get(instance_id)
        if held is None or held.condition_id != RECEIPT:
            continue
        del actor.conditions[instance_id]
        engine._append_event("CONDITION_REMOVED", held.source_definition_id,
            actor_id=actor.entity_id, target_ids=(actor.entity_id,),
            payload={"condition_id": RECEIPT, "instance_id": instance_id,
                     "reason": "NEXT_JUMP_COMMITTED"})
