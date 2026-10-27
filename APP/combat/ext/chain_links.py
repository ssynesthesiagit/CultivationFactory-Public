"""Lightning Chains' link (rider lane 1, 2026-09-29: "i want everything we can automated").

"When you hit a Charged creature with Lightning Lash, you may spend 1 CP to create a short-lived lightning link between it and one
creature or object within 15 feet.  The second target makes a Dexterity saving throw.  Failed Save: It takes lightning damage
equal to 1d8 + your Lightning key ability modifier, and both targets are linked until the start of your next turn.  Successful Save:
It takes half damage and no link forms.  While linked, if either target willingly moves more than 10 feet away from the other, it
takes lightning damage equal to your Proficiency Bonus and the link ends."

The second target is an ``arc`` (combat/ext/arcs.py); its failed save runs

    {"type": "lightning_link"}     -- puts one "condition:typed.link.lightning" on each of the two creatures (the arc's first
                                      target and the arc target), each naming the other and the damage (the caster's Proficiency
                                      Bonus); it ends at the start of the caster's next turn like any condition it applied.

and the ``event`` hook below watches MOVEMENT_COMMITTED: a creature's own willing move (not a push, a pull or being dragged along)
that ends more than 10 feet from its partner and farther than it began takes the damage, and both links end.  A creature that
starts the move already more than 10 feet away (the two may be 15 feet apart when the link forms) is not punished for a step that
does not carry it further from the other.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

LINK = "condition:typed.link.lightning"


@effect("lightning_link")
def lightning_link(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import typed_executor as te
    from . import arcs

    engine, actor = ctx.engine, ctx.actor
    subject = ctx.target if ctx.target is not None else (ctx.targets[0] if len(ctx.targets) == 1 else None)
    partner = engine.state.actors.get(str(arcs.arc_state(ctx).get("primary") or ""))
    if subject is None or partner is None or partner.entity_id == subject.entity_id or not (subject.active and partner.active):
        return
    damage = int(ctx.numbers.get("pb") or 0)
    # Each application is independent, including pairs sharing either endpoint.
    # The ordinary event sequence is persisted and unique within this fight.
    pair_id = f"lightning-pair:{engine.state.event_sequence + 1}"
    for holder, other in ((subject, partner), (partner, subject)):
        engine._apply_condition(holder, LINK, ctx.source, actor.entity_id,
                                expires_on=te.effect_expiry(ctx, {"duration": "until_start_of_your_next_turn"}, holder, condition=True)
                                or "START_OF_SOURCE_NEXT_TURN",
                                data={"with": other.entity_id, "pair_id": pair_id,
                                      "damage": damage, "label": f"Lightning link with {other.display_name}",
                                      "reading": f"Until the start of {actor.display_name}'s next turn: if you willingly move "
                                      f"farther from {other.display_name} and end more than 10 feet away, you take {damage} "
                                      "lightning damage and this link ends."})


@hook("event", nested=True)
def link_snaps(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "MOVEMENT_COMMITTED":
        return
    payload = kwargs.get("payload") or {}
    mover = engine.state.actors.get(kwargs.get("actor_id") or "")
    if mover is None or payload.get("forced") or payload.get("dragged_by") or not mover.active or not payload.get("path"):
        return
    for link in [c for c in mover.conditions.values() if c.condition_id == LINK]:
        _snap_link(engine, mover, payload, link)


def _snap_link(engine: Any, mover: Any, payload: dict[str, Any], link: Any) -> None:
    partner = engine.state.actors.get(str((link.data or {}).get("with") or "")) if link is not None else None
    if partner is None or not partner.active:
        return
    from ..gate2_runtime_models import Position

    start = Position(**payload["path"][0])
    distance = engine._distance_actor_to_actor(mover, partner)
    if distance <= 10 or distance <= engine._distance_actor_to_actor(mover, partner, actor_position=start):
        return
    amount = int((link.data or {}).get("damage") or 0)
    source, owner = link.source_definition_id, link.source_actor_id
    pair_id = (link.data or {}).get("pair_id")
    for holder, other in ((mover, partner), (partner, mover)):
        for iid, condition in list(holder.conditions.items()):
            if condition.condition_id != LINK or condition.source_definition_id != source or condition.source_actor_id != owner:
                continue
            data = condition.data or {}
            # Legacy saves have no pair ID: match reciprocal endpoints, never
            # another partner's link even when its caster/source is identical.
            if data.get("with") != other.entity_id or data.get("pair_id") != pair_id:
                continue
            holder.conditions.pop(iid)
            engine._append_event("CONDITION_REMOVED", source, actor_id=owner,
                                 target_ids=(holder.entity_id,),
                                 payload={"condition_id": LINK, "instance_id": iid, "reason": "LINK_SNAPPED"})
    engine._append_event("PASSIVE_TRIGGERED", source, actor_id=owner, target_ids=(mover.entity_id,),
                         payload={"log": f"The lightning link snaps as {mover.display_name} moves away from {partner.display_name}."})
    if amount > 0:
        from ..typed_executor import Context, run_effects
        caster, action = engine.state.actors.get(owner), engine.action_catalog.get(source)
        if caster is not None and action is not None:
            run_effects(Context(engine, caster, action, getattr(engine, '_active_intent', None),
                action.parameters.get('typed') or {}, [mover], mover, {'_potency_used': True}),
                [{'type': 'damage', 'flat': amount, 'damage_types': ['lightning']}])
