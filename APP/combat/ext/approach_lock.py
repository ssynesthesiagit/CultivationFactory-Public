"""Held at distance: a typed effect that stops a creature walking toward or away from the creature who placed it
(worker AUTO56, Spear sphere, 2026-10-05; owner: "automate everything").

Several printed abilities say, in effect, "this creature cannot willingly move closer to me" or "... closer to or
farther from me" until the start of the speaker's next turn.  Before this file the table could not express that: the
typed effect ``rider`` said so out loud and left it to the GM ("no engine rule blocks a specific direction of
movement").  The engine has no notion of a direction of travel, so the honest general seam is a **per-step stop** at
the documented strict ``movement_attempt`` point: the step that would cross the boundary is refused before it is paid,
so the creature keeps its position and its step cost, exactly as the strict hook contract promises (see
``combat/ext/__init__.py``, "Per-step movement").

Spear uses, from the printed text alone (authority/typed_mechanics/rules_text.json):

  Pinning Strike          "prevent the target from willingly moving closer to you until the start of your next turn"
  Meteor-Net Spear Art    "A creature that fails also cannot willingly move closer to you until the start of your next turn"
  World-Transfixing Point "cannot willingly move closer to or farther from you"
  The Point That Pinned    "Held at Distance ... the target cannot willingly move closer to or farther from you"
  Heaven to Earth

Typed row::

  {"type": "held_at_distance", "applies_to": "target", "mode": "closer" | "farther" | "both",
   "duration": "until_start_of_next_turn", "evidence": "<the printed sentence>"}

``applies_to`` is the ordinary subject key (``target``, ``creatures_in_area``, ...). By default the anchor is
the user. With ``anchor: "attack_vessel"``, it is the vessel selected as the attack origin; the record stores its
zone id, and each step checks the vessel's current position and active state. The same anchor requirement can
guard an enclosing effect group when the other rows depend on the hold. With ``save: "str"`` (or another ability),
the first restricted step each turn rolls against the user's Cultivation Save DC; that result governs the rest of
the turn. The saved record uses strings and integers only, including the optional printed ``label``.

This module is inert for a creature holding no such record: the ``movement_attempt`` hook returns ``None`` before it
looks at any zone, mark or ability, and the effect never runs unless an ability that printed this sentence typed it.
Forced displacement and teleports do not go through ``movement_attempt`` and are deliberately not restricted, because the
printed words say *willingly*.  Granted movement does go through the same checkpoint (see "Per-step movement" in
``combat/ext/__init__.py``), so a step bought with this talent's own "move without provoking" feet is stopped too.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook
from .turn_words import until_words

CONDITION = "condition:typed.held_at_distance"
MODES = ("closer", "farther", "both")

#: One plain clause per mode, reused by the condition pill and the refusal line so a newcomer reads the same words
#: in both places.  ``{who}`` is the creature that placed the lock, ``{name}`` the creature it holds.
_CLAUSE = {
    "closer": "{who} holds {name} at arm's length: it cannot willingly walk closer to {who}",
    "farther": "{who} keeps {name} at arm's length: it cannot willingly walk farther away from {who}",
    "both": "{who} pins {name} in place: it cannot willingly move closer to or farther from {who}",
}
_STEP = {
    "closer": "{name} stops: it cannot willingly move closer to {who}.",
    "farther": "{name} stops: it cannot willingly move farther from {who}.",
    "both": "{name} stops: it cannot willingly move closer to or farther from {who}.",
}


_ABILITIES = dict(STR="Strength", DEX="Dexterity", CON="Constitution",
                  INT="Intelligence", WIS="Wisdom", CHA="Charisma")


def _sentence(mode: str, who: str, name: str, until: str = "", *, save: str = "", dc: int = 10) -> str:
    """The lock's own words: what it does, to whom, and the printed turn it ends on."""
    clause = _CLAUSE.get(mode, _CLAUSE["closer"]).format(who=who, name=name)
    if until:
        clause += f" {until}"
    if save:
        clause += f" unless it passes a {_ABILITIES.get(save, save)} saving throw (DC {dc}) on its first such step that turn"
    return f"{clause}."


def records(engine: Any, actor: Any) -> list[dict[str, Any]]:
    """The held-at-distance records on ``actor``, newest last.  Empty for every other creature.

    Public so a shared helper (or a test) can read the lock without touching a private function.
    """
    if actor is None:
        return []
    return [{"instance_id": key, **(condition.data or {})} for key, condition in actor.conditions.items()
            if condition.condition_id == CONDITION]


def _active_vessel(engine: Any, vessel_id: str) -> Any | None:
    from .placed import data

    zone = engine.state.zones.get(vessel_id)
    if zone is not None and zone.active:
        placement = data(zone)
        if placement.get("tag") == "vessel" and placement.get("state") == "active":
            return zone
    return None


def _attack_vessel(ctx: Any) -> Any | None:
    from ..action_geometry import record_for

    origin = record_for(ctx.engine, ctx.actor, ctx.action.source_definition_id)
    origin_id = (origin or {}).get("id", "")
    if origin_id.startswith("vessel:"):
        return _active_vessel(ctx.engine, origin_id.removeprefix("vessel:"))
    return None


@hook("effect_allowed")
def vessel_anchor_allowed(ctx: Any, row: dict[str, Any]) -> bool | None:
    if row.get("anchor") == "attack_vessel" and _attack_vessel(ctx) is None:
        return False
    return None


def _locked(record: dict[str, Any], engine: Any, mover: Any, previous: Any, nxt: Any) -> bool:
    """True when the step ``previous`` -> ``nxt`` would cross ``record``'s boundary."""
    if vessel_id := record.get("vessel_id"):
        vessel = _active_vessel(engine, vessel_id)
        point = vessel.center if vessel is not None else None
    else:
        anchor = engine.state.actors.get(str(record.get("anchor_id") or ""))
        point = anchor.position if anchor is not None and mover.entity_id != anchor.entity_id else None
    if point is None or previous is None or nxt is None:
        return False
    was = engine.grid.distance_ft(previous, point)
    now = engine.grid.distance_ft(nxt, point)
    if now == was:
        return False
    mode = str(record.get("mode") or "closer")
    if mode not in MODES:
        mode = "closer"
    return (mode in {"closer", "both"} and now < was) or (mode in {"farther", "both"} and now > was)


def _anchor_name(record: dict[str, Any], engine: Any) -> str:
    actors = getattr(getattr(engine, "state", None), "actors", None)
    anchor = actors.get(str(record.get("anchor_id") or "")) if isinstance(actors, dict) else None
    who = anchor.display_name if anchor is not None else "the creature who placed it"
    return f"{who}'s puppet vessel" if record.get("vessel_id") else who


@effect("held_at_distance")
def held_at_distance(ctx: Any, effect_row: dict[str, Any]) -> None:
    """Put the printed hold on every declared subject.  No subject, no condition and no rider."""
    from ..typed_executor import effect_subjects, stated_expiry

    mode = str(effect_row.get("mode") or "closer").lower()
    if mode not in MODES:
        mode = "closer"
    anchor_data = {"anchor_id": ctx.actor.entity_id}
    if effect_row.get("anchor") == "attack_vessel":
        vessel = _attack_vessel(ctx)
        if vessel is None:
            return
        anchor_data["vessel_id"] = vessel.zone_id
    who = _anchor_name(anchor_data, ctx.engine)
    label = str(effect_row.get("label") or "Held at distance")
    save = str(effect_row.get("save") or "").upper()
    dc = int(ctx.numbers.get("save_dc") or 10) if save else 10
    for subject in effect_subjects(ctx, effect_row, harmful=True):
        expires = stated_expiry(ctx, effect_row, subject, condition=True) or ctx.expires_on()
        until = until_words(ctx.engine, expires, actor=ctx.actor, holder=subject)
        data = {**anchor_data, "mode": mode, "label": label, "until": until,
                "reading": _sentence(mode, who, subject.display_name, until, save=save, dc=dc)}
        if save:
            data.update(save=save, dc=dc)
        ctx.engine._apply_condition(subject, CONDITION, ctx.source, ctx.actor.entity_id, expires_on=expires, data=data)


@hook("movement_attempt")
def stop_at_the_line(engine: Any, mover: Any, previous: Any, nxt: Any, intent: Any) -> dict[str, Any] | None:
    """Refuse the step that would cross a held-at-distance boundary, before it is paid.

    None (inert) whenever the mover holds no such record.  The reply leaves position, step cost and movement budget
    untouched, as the strict ``movement_attempt`` contract requires.
    """
    for record in records(engine, mover):
        if not _locked(record, engine, mover, previous, nxt):
            continue
        condition = mover.conditions.get(record["instance_id"])
        if condition is None:
            continue
        if save := record.get("save"):
            from ..turn_uses import current_turn_key

            turn = current_turn_key(engine)
            if record.get("save_turn") != turn:
                dc = record["dc"]
                roll = engine._roll_save(mover, save, dc, condition.source_definition_id,
                                         roll_context={"source_actor_id": condition.source_actor_id})
                if condition.instance_id not in mover.conditions:
                    continue
                passed = int(roll is None or roll.total >= dc)
                engine._update_condition_data(mover, condition, {**condition.data, "save_turn": turn, "passed": passed},
                                              condition.source_definition_id)
            if condition.data["passed"]:
                continue
        mode = str(record.get("mode") or "closer")
        line = _STEP.get(mode, _STEP["closer"]).format(name=mover.display_name, who=_anchor_name(record, engine))
        label = record.get("label") or "Held at distance"
        if label != "Held at distance":
            line = f"{label}: {line}"
        return {"stop": True, "source_id": CONDITION, "label": line}
    return None


@hook("status_description")
def held_at_distance_text(engine: Any, holder: Any, row: dict[str, Any], data: dict[str, Any]) -> dict[str, str] | None:
    """Say on the condition pill what the lock does, when it ends, and in the same words the refusal uses."""
    if str(row.get("condition_id") or "") != CONDITION:
        return None
    record = {**(data or {}), "label": (data or {}).get("label") or "Held at distance"}
    mode = str(record.get("mode") or "closer")
    reading = str(record.get("reading") or _sentence(mode, _anchor_name(record, engine), record["label"],
                                                     str(record.get("until") or "")))
    handling = "The table stops the step that would cross the line; forced movement and teleports are unaffected."
    if record.get("save"):
        handling = ("The same save applies for the rest of the turn. On a failure, only steps in the restricted direction "
                    "are stopped. Forced movement and teleports are unaffected.")
    if record.get("vessel_id") and _active_vessel(engine, record["vessel_id"]) is None:
        reading = "The puppet vessel is no longer active, so this hold does not stop movement."
        handling = "You can still use an Action to break free if the hold allows it."
    return {"text": reading, "handling": handling}
