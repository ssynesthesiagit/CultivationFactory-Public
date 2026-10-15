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

``applies_to`` is the ordinary subject key (``target``, ``creatures_in_area``, ...); the anchor is always the
creature using the ability, because that is who every printed version names ("closer to **you**").  The saved record
is strings only: ``anchor_id``, ``mode``, ``label``, ``until``, ``reading`` -- no objects, so a table commit and
reload round-trips.

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


def _sentence(mode: str, who: str, name: str, until: str = "") -> str:
    """The lock's own words: what it does, to whom, and the printed turn it ends on."""
    clause = _CLAUSE.get(mode, _CLAUSE["closer"]).format(who=who, name=name)
    return f"{clause} {until}." if until else f"{clause}."


def records(engine: Any, actor: Any) -> list[dict[str, Any]]:
    """The held-at-distance records on ``actor``, newest last.  Empty for every other creature.

    Public so a shared helper (or a test) can read the lock without touching a private function.
    """
    if actor is None:
        return []
    return [{"instance_id": key, **(condition.data or {})} for key, condition in actor.conditions.items()
            if condition.condition_id == CONDITION]


def _locked(record: dict[str, Any], engine: Any, mover: Any, previous: Any, nxt: Any) -> bool:
    """True when the step ``previous`` -> ``nxt`` would cross ``record``'s boundary."""
    anchor = engine.state.actors.get(str(record.get("anchor_id") or ""))
    if anchor is None or mover is None or mover.entity_id == anchor.entity_id or previous is None or nxt is None:
        return False
    was = engine.grid.distance_ft(previous, anchor.position)
    now = engine.grid.distance_ft(nxt, anchor.position)
    if now == was:
        return False
    mode = str(record.get("mode") or "closer")
    if mode not in MODES:
        mode = "closer"
    return (mode in {"closer", "both"} and now < was) or (mode in {"farther", "both"} and now > was)


def _names(record: dict[str, Any], engine: Any, mover: Any) -> tuple[str, str]:
    actors = getattr(getattr(engine, "state", None), "actors", None)
    anchor = actors.get(str(record.get("anchor_id") or "")) if isinstance(actors, dict) else None
    who = anchor.display_name if anchor is not None else "the creature who placed it"
    return str(record.get("label") or "Held at distance"), who


@effect("held_at_distance")
def held_at_distance(ctx: Any, effect_row: dict[str, Any]) -> None:
    """Put the printed hold on every declared subject.  No subject, no condition and no rider."""
    from ..typed_executor import effect_subjects, stated_expiry

    mode = str(effect_row.get("mode") or "closer").lower()
    if mode not in MODES:
        mode = "closer"
    for subject in effect_subjects(ctx, effect_row, harmful=True):
        label = "Held at distance"
        who = ctx.actor.display_name
        expires = stated_expiry(ctx, effect_row, subject, condition=True) or ctx.expires_on()
        until = until_words(ctx.engine, expires, actor=ctx.actor, holder=subject)
        data = {"anchor_id": ctx.actor.entity_id, "mode": mode, "label": label, "until": until,
                "reading": _sentence(mode, who, subject.display_name, until)}
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
        name, who = _names(record, engine, mover)
        mode = str(record.get("mode") or "closer")
        # the strict checkpoint accepts exactly stop/source_id/label and prints the label itself
        return {"stop": True, "source_id": CONDITION,
                "label": _STEP.get(mode, _STEP["closer"]).format(name=mover.display_name, who=who)}
    return None


@hook("status_description")
def held_at_distance_text(engine: Any, holder: Any, row: dict[str, Any], data: dict[str, Any]) -> dict[str, str] | None:
    """Say on the condition pill what the lock does, when it ends, and in the same words the refusal uses."""
    if str(row.get("condition_id") or "") != CONDITION:
        return None
    record = {**(data or {}), "label": (data or {}).get("label") or "Held at distance"}
    name, who = _names(record, engine, holder)
    mode = str(record.get("mode") or "closer")
    reading = str(record.get("reading") or _sentence(mode, who, name, str(record.get("until") or "")))
    return {"text": reading, "handling": "The table stops the step that would cross the line; forced movement and teleports are unaffected."}
