"""Why a hold ended: the shared "escaped" seam (rider lane C15, 2026-09-30; BLOCKED_CENSUS.md row 31) -- shared helper.

Some printed lines answer the moment a creature gets out of a hold, and care how it got out: "When a creature escapes one of
your Chains talents, destroys one of your Chain Objects, teleports away from one of your Tethers ... you may immediately learn
the direction of its escape and whether it used physical movement, teleportation, spiritual escape, forced movement, or
outside assistance" (Prisoner's Bell). Holds end on many paths, so every path that frees a creature reports here:

  escaped(engine, holder, held, how, *, by=None, source="", way="", object_id="")
      holder   the creature that got free
      held     the hold instances that ended (ConditionInstance objects, taken before or after their removal)
      how      "physical"            its own Strength/Dexterity/Constitution check or save, or breaking the hold's object
               "spiritual"           its own Intelligence/Wisdom/Charisma check or save
               "teleportation"       it teleported out (a tether broke)
               "forced_movement"     something moved it out (a tether broke, a grip lost its reach)
               "outside_assistance"  another creature freed it (helped its check, destroyed the hold's object)
      by       the creature responsible (the holder itself, a helper, the one that destroyed the object)
      source   the ability or rule doing the freeing (event source for any listener's log line)
      way      the mechanism: "repeat_save" (the hold's own end-of-turn save), "save" (a save taken as an Action), "check"
               (an escape check), "object" (the hold's object was destroyed), "movement" (a move broke it)
      object_id  the destroyed object, for "object"

  how_for(ability, holder, by) -> the "how" for a check or save of that ability (another creature = outside assistance).
  movement_how(payload)        -> the "how" for a hold a MOVEMENT_COMMITTED broke (teleport / forced / its own move).

It runs the ``hold_escaped(engine, record)`` hook (documented in combat/ext/__init__.py) with one plain record:
  {"holder": id, "by": id, "how": str, "way": str, "object": id or "", "source": str, "at": {"x", "y"},
   "holds": [{"instance_id", "condition_id", "source", "owner"}, ...]}
The helper itself records nothing and changes nothing: a listener that acts records its own events. With no listener for
the fight's creatures nothing happens, so fights without such an ability replay exactly as before.

Reporting paths: the table's escape-a-grapple Action (typed_executor.block_escape_grapple), granted escape options
(escape_options.py: Break free, and an ally's help), bound objects destroyed (bound_objects.py), Chains tethers that break
(chains_sphere.py), grips that lose their reach because the held creature was moved (grapple_range.py), and the engine's
own end-of-turn repeat saves, read here from their CONDITION_REMOVED event (payload
``repeat_save``). Not reporting (yet): a hold that simply runs out, ends with Concentration, or is released by its owner --
those are not escapes.

Users: combat/ext/chains_sphere.py (Prisoner's Bell), combat/ext/repeat_saves.py (a hold row's ``on_repeat_success`` rows:
Chain Prison's "If the target succeeds, it remains Bound until the start of its next turn").
The spatial prison/seal marker is also a hold for reporting: destroying a prison still reports an escape after its
Restrained and temporary Bound portions end. This taxonomy only reports removals; it grants no escape actions.
"""

from __future__ import annotations

from typing import Any


def escape_stage(grips: list[tuple[str, Any]]) -> list[tuple[str, Any]]:
    """Return the current layer of holds an escape attempt can end.

    A pin sits on top of a grapple: an escape ends pins first, leaving the
    grapple for a later attempt. Shared by ordinary and feature-granted escapes.
    """
    pins = [(iid, condition) for iid, condition in grips
            if condition.condition_id.rsplit(".", 1)[-1] == "pinned"]
    return pins or grips

from . import has, hook, run

HOLDS = ("grappled", "restrained", "pinned", "bound", "chains_spatial_lock")
PHYSICAL, SPIRITUAL = {"STR", "DEX", "CON"}, {"INT", "WIS", "CHA"}
WORDS = {"physical": "by physical effort", "spiritual": "by spiritual escape", "teleportation": "by teleporting away",
         "forced_movement": "by being moved out of it", "outside_assistance": "with outside help"}


def is_hold(condition_id: str) -> bool:
    """A grip, restraint, pin, Chains Bound or spatial hold, for escape reporting only."""
    name = str(condition_id or "").rsplit(".", 1)[-1]
    return name in HOLDS


def how_for(ability: Any, holder: Any, by: Any = None) -> str:
    """The printed kind of escape for a check or save made with ``ability``: another creature doing it is outside help."""
    if by is not None and holder is not None and getattr(by, "entity_id", by) != getattr(holder, "entity_id", holder):
        return "outside_assistance"
    return "spiritual" if str(ability or "").upper()[:3] in SPIRITUAL else "physical"


def movement_how(payload: Any) -> str:
    """The kind of escape for a hold that a MOVEMENT_COMMITTED broke (its payload): teleport, forced, or its own move."""
    payload = payload or {}
    return "teleportation" if payload.get("teleport") else "forced_movement" if payload.get("forced") else "physical"


def _hold(condition: Any) -> dict[str, str]:
    return {"instance_id": str(condition.instance_id), "condition_id": str(condition.condition_id),
            "source": str(condition.source_definition_id or ""), "owner": str(condition.source_actor_id or "")}


def escaped(engine: Any, holder: Any, held: Any, how: str, *, by: Any = None, source: str = "", way: str = "",
            object_id: str = "") -> None:
    """Report that ``holder`` got out of ``held`` (hold instances only are reported; others are ignored)."""
    if holder is None or not has("hold_escaped"):
        return
    holds = [_hold(c) for c in held or () if c is not None and is_hold(c.condition_id)]
    if not holds:
        return
    record = {"holder": holder.entity_id, "by": str(getattr(by, "entity_id", by) or holder.entity_id), "how": str(how),
              "way": str(way), "object": str(object_id or ""), "source": str(source or holds[0]["source"]),
              "at": {"x": int(holder.position.x), "y": int(holder.position.y)}, "holds": holds}
    run("hold_escaped", engine, record)


# ---------------------------------------------------------------------- the engine's own end-of-turn repeat saves
def _applied(engine: Any, instance_id: str) -> Any | None:
    """The CONDITION_APPLIED event of a (now removed) instance: who applied it and with what."""
    for event in reversed(engine.events):
        if event.event_type == "CONDITION_APPLIED" and (event.payload or {}).get("instance_id") == instance_id:
            return event
    return None


def _save_ability(engine: Any, holder_id: str, sequence: int) -> str:
    for event in reversed(engine.events):
        if event.sequence >= sequence:
            continue
        if event.event_type == "SAVE_ROLLED" and event.actor_id == holder_id:
            payload = event.payload or {}  # the roll: reason "SAVE:<source>:<ABILITY>"
            return str(payload.get("ability") or str(payload.get("reason") or "").rsplit(":", 1)[-1])
        if event.event_type in ("TURN_STARTED", "INTENT_ACCEPTED"):
            break
    return ""


@hook("event")
def _repeat_save(engine: Any, event_type: str, kwargs: Any) -> None:
    """A hold ended by its end-of-turn repeat save (gate2 rolls it; its removal event says ``repeat_save``)."""
    if event_type != "CONDITION_REMOVED" or not has("hold_escaped"):
        return
    payload = kwargs.get("payload") or {}
    if not payload.get("repeat_save") or not is_hold(str(payload.get("condition_id") or "")):
        return
    targets = tuple(kwargs.get("target_ids") or ())
    holder = engine.state.actors.get(targets[0] if targets else "")
    applied = _applied(engine, str(payload.get("instance_id") or ""))
    if holder is None or applied is None:
        return
    from types import SimpleNamespace

    event = kwargs.get("originating_event")
    sequence = int(getattr(event, "sequence", 0) or engine.state.event_sequence)
    gone = SimpleNamespace(instance_id=str(payload.get("instance_id")), condition_id=str(payload.get("condition_id")),
                           source_definition_id=applied.source_definition_id, source_actor_id=applied.actor_id)
    escaped(engine, holder, [gone], how_for(_save_ability(engine, holder.entity_id, sequence + 1), holder),
            by=holder, source=applied.source_definition_id, way="repeat_save")
