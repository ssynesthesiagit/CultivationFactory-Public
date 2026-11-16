"""A chosen creature's own Resistance, set aside against one source's abilities for a stated turn.

Several printed abilities end a line with a rider of the form "Choose one creature that failed. Until the start of your
next turn: ordinary Resistance to Piercing and Force damage does not apply to your Spear talents against it".  Three
things in that sentence are creature-specific -- which creature was chosen, who is doing the ignoring, and whose
abilities may ignore it -- and the engine's own ``ignore_resistance`` effect row cannot say any of them: it is a
property of one damage packet, read before a recipient is known, so an ability that used it at the top level had its
bypass applied to every creature in the line.

The general seam is the documented ``resistance_ignored`` hook, which answers while the engine weighs one creature's
defences against one incoming packet.  AUTO56f2 added the packet's ``target`` argument to that hook (a core change, one
argument, every existing handler ignores it) so a bypass can be scoped to a chosen creature and a source.  This module
is the only subscriber that uses ``target``; the ten handlers that ignore it behave exactly as before.

Spear uses, from the printed text alone (authority/typed_mechanics/rules_text.json):

  Heaven-Piercing Spear Light   "ordinary Resistance to Piercing and Force damage does not apply to your Spear
                                talents against it"
  World-Transfixing Point       "ordinary Resistance to Piercing and Force damage does not apply"

Typed row::

  {"type": "target_resistance_ignored", "applies_to": <the ordinary subject key>,
   "damage_types": ["piercing", "force"],
   "by_sphere": "tianxia.sphere.spear",       # optional: only the named sphere's abilities ignore it
   "attacker_scope": "chooser" | "anyone",   # optional: whose damage may ignore it (see below)
   "duration": <the printed turn>, "evidence": <the printed sentence>}

Whose damage may ignore it is printed, not inferred, so it is data.  ``attacker_scope: "chooser"`` (the default) is
a sentence that names the chooser, "does not apply to *your* Spear talents against it": only the creature that placed
the bypass, and only its own sphere's abilities if ``by_sphere`` is given, benefit.  ``"anyone"`` is a sentence that
names no source at all -- "ordinary Resistance to Piercing and Force damage does not apply" -- so ANY creature's damage
of a named type is ignored against that one creature, which is what World-Transfixing Point says.  Both together
express a sentence that names a sphere but no chooser.

The record sits on the creature that was chosen, so a saved fight needs nothing new: strings only (``anchor_id``,
``damage_types``, ``by_sphere``, ``attacker_scope``, ``label``, ``until``, ``reading``), and the engine removes it on
the printed turn's own expiry name.  A creature with no record, a damage type it does not name, a source outside the
printed scope and an ability from another sphere all keep its Resistance.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook
from .turn_words import until_words

CONDITION = "condition:typed.resistance_bypass"

#: Whose damage may ignore the bypass.  Both are printed sentences; neither is the default by accident.
SCOPE_CHOOSER = "chooser"     # "does not apply to your Spear talents against it"
SCOPE_ANYONE = "anyone"       # "does not apply", with no source named
SCOPES = (SCOPE_CHOOSER, SCOPE_ANYONE)


def scope_of(row: dict[str, Any]) -> str:
    """The printed attacker scope of one row or saved record: ``chooser`` unless it says ``anyone``."""
    value = str(row.get("attacker_scope") or "").strip().lower()
    if value not in SCOPES:
        return SCOPE_CHOOSER
    return value


def records(engine: Any, actor: Any) -> list[dict[str, Any]]:
    """The ignored-Resistance records on ``actor``, newest last.  Empty for every other creature.

    Public so a shared helper (or a test) can read a bypass without touching a private function.
    """
    if actor is None:
        return []
    return [{"instance_id": key, **(condition.data or {})} for key, condition in actor.conditions.items()
            if condition.condition_id == CONDITION]


def _names(kinds: Any) -> str:
    """``["piercing", "force"]`` or ``"PIERCING|FORCE"`` -> "Piercing and Force"."""
    if isinstance(kinds, (list, tuple, set)):
        parts = [str(kind) for kind in kinds]
    else:
        parts = [part for part in str(kinds or "").replace("|", ",").split(",") if part.strip()]
    return " and ".join(part.strip().title() for part in parts)


def _reading(who: str, name: str, kinds: Any, until: str, sphere: str, scope: str = SCOPE_CHOOSER) -> str:
    """One plain sentence: whose Resistance is set aside, to what, and until when."""
    named = _names(kinds)
    if not sphere:
        clause = f"Resistance to {named} damage does not apply against {name}"
    elif scope == SCOPE_ANYONE:
        clause = (f"Any {_sphere_word(sphere)} technique's {named} damage ignores {name}'s Resistance")
    else:
        clause = f"{who}'s {_sphere_word(sphere)} techniques ignore {name}'s Resistance to {named} damage"
    return f"{clause} {until}." if until else f"{clause}."


def _handling(who: str, name: str, kinds: Any, sphere: str, scope: str, until: str) -> str:
    """The pill's second line: exactly whose damage may ignore it, in the same plain words as the first line.

    The first line names the creature whose Resistance is set aside; this one names the creature that *benefits*
    and must not promise more than execution does.  ``ignores_chosen_creature_resistance`` ignores a packet only
    when its attacker is the chooser (unless the sentence named no source), its ability is in the named sphere when
    the row names one, and its damage is one of the named types -- so a sphere-limited ``anyone`` sentence promises
    every creature's Spear techniques, not every creature's damage, and a sphere-less ``chooser`` sentence promises
    the chooser's own techniques of those types, not only the technique that placed it.
    """
    named = _names(kinds)
    when = f" {until}" if until else ""
    only = (f"Only {name}'s Resistance to {named} damage is set aside{when}; nothing else about "
            f"{name}'s defences changes")
    if scope == SCOPE_ANYONE:
        if sphere:
            return f"{only}. Every creature's {_sphere_word(sphere).lower()} techniques deal their {named} damage " \
                   f"through that Resistance"
        return f"{only}. Any creature's {named} damage goes through that Resistance"
    if sphere:
        return f"{only}. Only the {_sphere_word(sphere).lower()} techniques of {who} deal their {named} damage " \
               f"through that Resistance, never {name}'s own"
    return f"{only}. Only the techniques of {who} deal their {named} damage through that Resistance, " \
           f"never {name}'s own"


def _sphere_word(sphere: str) -> str:
    """The printed sphere's own name for a source's abilities ("Spear techniques")."""
    tail = str(sphere or "").rsplit(".", 1)[-1].replace("_", " ")
    return tail.title() if tail else ""


@effect("target_resistance_ignored")
def target_resistance_ignored(ctx: Any, effect_row: dict[str, Any]) -> None:
    """Put the printed bypass on every declared subject.  No subject, no condition and no rider."""
    from ..typed_executor import effect_subjects, stated_expiry

    # the printed order, not an alphabetical one: the sentence a player reads names them as written
    kinds = list(dict.fromkeys(str(kind).upper() for kind in effect_row.get("damage_types") or []))
    if not kinds:
        return
    sphere = str(effect_row.get("by_sphere") or "")
    scope = scope_of(effect_row)
    for subject in effect_subjects(ctx, effect_row, harmful=True):
        who = ctx.actor.display_name
        expires = stated_expiry(ctx, effect_row, subject, condition=True) or ctx.expires_on()
        until = until_words(ctx.engine, expires, actor=ctx.actor, holder=subject)
        reading = _reading(who, subject.display_name, kinds, until, sphere, scope)
        data = {"anchor_id": ctx.actor.entity_id, "damage_types": "|".join(kinds), "by_sphere": sphere,
                "attacker_scope": scope, "label": "Resistance ignored", "until": until, "reading": reading}
        ctx.engine._apply_condition(subject, CONDITION, ctx.source, ctx.actor.entity_id,
                                    expires_on=expires, data=data)


@hook("resistance_ignored")
def ignores_chosen_creature_resistance(engine: Any, kind: str, typed: dict[str, Any],
                                       source_actor_id: str | None, target: Any = None) -> bool | None:
    """True only for the creature that was chosen, a source inside the printed scope and a named damage type.

    ``kind`` is upper case, ``typed`` is the incoming packet's own ability.  The printed attacker scope is read
    from the record: ``chooser`` (the sentence named "your" talents) needs the creature that chose it, ``anyone``
    (the sentence named no source) does not, which is what World-Transfixing Point says.  A named ``by_sphere``
    still limits the packet's own sphere either way.
    """
    if target is None or not source_actor_id:
        return None
    for record in records(engine, target):
        if str(record.get("anchor_id") or "") != source_actor_id \
                and scope_of(record) != SCOPE_ANYONE:
            continue
        if kind not in str(record.get("damage_types") or "").split("|"):
            continue
        sphere = str(record.get("by_sphere") or "")
        if sphere and str((typed or {}).get("sphere") or "") != sphere:
            continue
        return True
    return None


@hook("status_description")
def ignored_resistance_text(engine: Any, holder: Any, row: dict[str, Any],
                            data: dict[str, Any]) -> dict[str, str] | None:
    """Say on the condition pill whose Resistance is set aside, to what, and until when."""
    if str(row.get("condition_id") or "") != CONDITION:
        return None
    record = {**(data or {})}
    anchor = engine.state.actors.get(str(record.get("anchor_id") or "")) if engine is not None else None
    who = anchor.display_name if anchor is not None else "the creature that chose it"
    sphere, scope = str(record.get("by_sphere") or ""), scope_of(record)
    reading = str(record.get("reading") or _reading(who, getattr(holder, "display_name", "it"),
                                                   record.get("damage_types"), str(record.get("until") or ""),
                                                   sphere, scope))
    return {"text": reading, "handling": _handling(who, getattr(holder, "display_name", "it"), record.get("damage_types"),
                                                   sphere, scope, str(record.get("until") or ""))}