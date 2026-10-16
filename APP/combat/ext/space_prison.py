"""Fold Prison's isolation, carried by its existing source-owned Incapacitated instance.

The printed loop gives total cover from outside and cannot affect outside creatures.
Recipient legality protects manual/AI menus and attack revalidation; subject legality
also protects ordinary typed effects (including unsaved area/zone packets) and
area saves. No object is created: the text supplies no shell, AC or HP.
Zone eligibility keeps map ownership explicit and excludes outside ground packets,
including a trapped owner's zones. Continuous zone conditions/modifiers reconcile
when the prison begins or ends; existing victim-carried effects are untouched.
The existing victim-turn expiry/repeat save ends the same instance, so no second
timer or independent cover condition can outlive it. Concentration loss releases it.
Fresh spatial_absence rows use the shared disappearance/occupancy/return provider;
these source-owned readers also preserve the earlier Incapacitated representation.
"""
from typing import Any

from . import hook

SOURCE = "tianxia.talent.space.fold_prison"
INCAPACITATED = "condition:typed.incapacitated"


def _is_prison(engine: Any, source: str) -> bool:
    action = engine.action_catalog.get(source)
    return ((getattr(action, "parameters", None) or {}).get("typed") or {}).get("source") == SOURCE


def _held(engine: Any, actor: Any) -> list[Any]:
    return [c for c in actor.conditions.values()
            if c.condition_id == INCAPACITATED and _is_prison(engine, c.source_definition_id)]


@hook("condition_state")
def prison_label(ctx: Any, subject: Any, row: dict) -> dict | None:
    if ctx.typed.get("source") != SOURCE or row.get("condition") != "incapacitated":
        return None
    return {"data": {"label": "Fold Prison: cannot act or affect outside creatures; total cover from outside until the end of its next turn or concentration ends"}}


@hook("recipient_allowed")
def isolated_recipient(engine: Any, actor: Any, target: Any, action: Any) -> bool | None:
    if actor.entity_id != target.entity_id and (_held(engine, actor) or _held(engine, target)):
        return False
    return None


@hook("effect_subject_allowed")
def isolated_area_subject(ctx: Any, row: dict, subject: Any) -> bool | None:
    if ctx.actor.entity_id != subject.entity_id and (_held(ctx.engine, ctx.actor) or _held(ctx.engine, subject)):
        return False
    return None


@hook("zone_subject_allowed")
def isolated_zone_subject(engine: Any, zone: Any, subject: Any) -> bool | None:
    owner = engine.state.actors.get(zone.owner_id)
    if _held(engine, subject) or (owner is not None and _held(engine, owner)):
        return False
    return None


@hook("event", nested=True)
def prison_inside_lifecycle(engine: Any, event_type: str, kwargs: dict) -> None:
    """Reconcile only an owned prison's application/removal, including expiry.

    Removal events can name the expiration system or a dispeller rather than the
    original technique. Resolve that instance's recorded application, without a
    new persisted marker or treating unrelated Incapacitated as a prison.
    """
    event = kwargs.get("originating_event")
    if event is None or event_type not in ("CONDITION_APPLIED", "CONDITION_REMOVED"):
        return
    payload = event.payload or {}
    if payload.get("condition_id") != INCAPACITATED:
        return
    source = event.source_definition_id
    if event_type == "CONDITION_REMOVED":
        iid = payload.get("instance_id")
        if not iid:
            return
        applied = next((e for e in reversed(engine.events)
                        if e.event_type == "CONDITION_APPLIED" and e.payload.get("instance_id") == iid), None)
        if applied is None:
            return
        source = applied.source_definition_id
    if not _is_prison(engine, source):
        return
    from ..zones import sync_inside

    sync_inside(engine, event.source_definition_id)


@hook("event", nested=True)
def concentration_releases(engine: Any, event_type: str, kwargs: dict) -> None:
    event = kwargs.get("originating_event")
    if event_type != "CONCENTRATION_ENDED" or event is None:
        return
    source = event.source_definition_id
    if not _is_prison(engine, source):
        return
    from ..concentration import copies, owner_copy
    owner_id = kwargs.get("actor_id")
    owner = engine.state.actors.get(owner_id)
    started = (kwargs.get("payload") or {}).get("started_sequence")
    starts = copies(owner, source, started) if owner is not None else []
    for actor in engine.state.actors.values():
        for condition in _held(engine, actor):
            if condition.source_actor_id != owner_id or condition.source_definition_id != source:
                continue
            if len(starts) > 1 and owner_copy(condition.applied_sequence, starts) != started:
                continue
            actor.conditions.pop(condition.instance_id)
            engine._append_event("CONDITION_REMOVED", source, actor_id=owner_id, target_ids=(actor.entity_id,),
                                 payload={"instance_id": condition.instance_id, "condition_id": condition.condition_id,
                                          "reason": "CONCENTRATION_ENDED"})
