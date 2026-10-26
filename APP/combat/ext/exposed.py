""""Cannot benefit from being Hidden or Invisible against you" (riders lane 2, 2026-09-29: Yang's Overexpose, Overbright Trail, Radiant
Overpressure, Sovereign Yang Incarnation, Court of Unfinished Noon, Noon Reveals the Hidden Work; the Stars talents that print the same
words), and the moment a creature "becomes Hidden or Invisible" that those reactions answer.

    {"type": "exposed", "applies_to": "target", "duration": "until_start_of_next_turn", "benefits": "hidden_or_invisible" | "hidden" |
     "invisible", "against": "you" | "anyone", "range_ft": 60, "requires_visible_light": false, "light": <mechanic id>}

puts ``condition:typed.exposed`` on the creature, filed under its user (its ``data`` holds what it may not benefit from, against whom, and
within what range of the user).  While it stands, ``masked_conditions`` (combat/senses.py, read by the engine's attack-mode rule) tells the
engine that the creature's Hidden or Invisible condition gives no Advantage or Disadvantage in an attack between it and the user (or anyone,
for ``against: anyone``): an attacker it hides from no longer has Disadvantage, and it gets no Advantage from being unseen.  It ends at the
printed deadline like any condition, and a second one from the same user replaces the first.

``light`` is optional: the mechanic id of a printed light (combat/rules/light_sources.json, docs/specs/LIGHTING_SPEC.md §8.2)
that this exposure makes the creature shed, because the ability that pays for the exposure is the one that prints it
(Radiant Overpressure: "The marked creature emits bright light in a 10-foot radius...").  The light is the model's own
``condition:typed.light`` on the same clock, so it lasts exactly as long as the exposure and carries the curated radii.
Absent, an exposure sheds no light.

Also: when a creature gains the Hidden or Invisible condition, the reactions whose trigger is "becomes Hidden or Invisible" (kind
``became_hidden``, combat/typed_reactions.on_creature_event) are offered to the fighters in range; an enemy's only.

Deterministic and evented: the condition is applied with the engine's own method; the hooks change no state of their own.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

EXPOSED = "condition:typed.exposed"  # the id of every exposure starts with this; one per kind (what it takes away, against whom), per user
HIDDEN, INVISIBLE = "condition:typed.hidden", "condition:typed.invisible"


@effect("exposed")
def apply(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import _default_subject, effect_expiry

    for target in _default_subject(ctx, row, harmful=True):
        if not target.active:
            continue
        benefits, against = str(row.get("benefits") or "hidden_or_invisible"), str(row.get("against") or "you")
        kind = f"{EXPOSED}.{benefits}.{against}"
        expiry = effect_expiry(ctx, row, target, condition=True)
        for iid, held in list(target.conditions.items()):
            if held.condition_id == kind and held.source_actor_id == ctx.actor.entity_id:  # the same exposure by the same user does not stack
                del target.conditions[iid]
                ctx.engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=held.source_actor_id, target_ids=(target.entity_id,),
                                         payload={"condition_id": kind, "instance_id": iid})
        ctx.engine._apply_condition(target, kind, ctx.source, ctx.actor.entity_id, expires_on=expiry,
                                    data={"benefits": benefits, "against": against, "range_ft": int(row.get("range_ft") or 0),
                                          "requires_visible_light": bool(row.get("requires_visible_light")),
                                          "label": f"Cannot benefit from being {benefits.replace('_or_', ' or ').title()} against "
                                                   f"{'anyone' if against == 'anyone' else ctx.actor.display_name}"})
        printed = str(row.get("light") or "")
        if printed:  # "the marked creature emits bright light ..." (Radiant Overpressure): the curated printed light
            from .. import light_sources
            from ..lighting import LIGHT
            light, named = light_sources.light(printed), light_sources.row(printed)
            if light and named:
                for iid, held in list(target.conditions.items()):  # a re-paid exposure replaces its own light, never stacks one
                    if held.condition_id == LIGHT and held.source_actor_id == ctx.actor.entity_id and held.source_definition_id == ctx.source:
                        del target.conditions[iid]
                ctx.engine._apply_condition(target, LIGHT, ctx.source, ctx.actor.entity_id, expires_on=expiry,
                                            data={"name": named["name"], "source_id": printed, "magical": light["magical"],
                                                  "bright_ft": light["bright_ft"], "dim_ft": light["dim_ft"]})


@hook("masked_conditions")
def masked(engine: Any, attacker: Any, target: Any) -> dict[str, set[str]] | None:
    """The target's Hidden / Invisible do not count when an exposure names this attacker (or anyone) and it is within the printed range."""
    out: dict[str, set[str]] = {}
    for who, other in ((target, attacker), (attacker, target)):
        for held in who.conditions.values():
            if not held.condition_id.startswith(EXPOSED):
                continue
            data = held.data or {}
            if data.get("against") != "anyone" and held.source_actor_id != other.entity_id:
                continue
            if data.get("requires_visible_light"):
                from ..typed_executor import condition_rules

                if any(c.condition_id == "condition:typed.blinded" for c in other.conditions.values()) or \
                        any(rule.get("cant_see") for rule in condition_rules(other)) or not engine._line_of_sight_actor_to_actor(other, who):
                    continue
            reach = int(data.get("range_ft") or 0)
            if reach and engine._distance_actor_to_actor(who, other) > reach:
                continue
            kinds = {"hidden": {HIDDEN}, "invisible": {INVISIBLE}}.get(str(data.get("benefits")), {HIDDEN, INVISIBLE})
            ids = {iid for iid, condition in who.conditions.items() if condition.condition_id in kinds}
            if ids:
                out.setdefault(who.entity_id, set()).update(ids)
    return out or None


@hook("event")
def became_hidden(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "CONDITION_APPLIED" or (kwargs.get("payload") or {}).get("condition_id") not in (HIDDEN, INVISIBLE):
        return
    if not getattr(engine, "typed_actor_ids", None):
        return
    from .. import typed_reactions

    for target_id in kwargs.get("target_ids") or ():
        subject = engine.state.actors.get(target_id)
        if subject is not None and subject.active:
            typed_reactions.on_creature_event(engine, subject, "became_hidden")
